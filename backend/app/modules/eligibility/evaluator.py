"""Evaluate a structured requirement against PatientFacts.

Statements evaluate to one of:
  true | false | unknown (information missing) | review (cannot be decided reliably) |
  conflict (sources disagree) | na (does not apply) | confirm (study team confirms at screening)

Every result carries a patient-facing explanation, the patient facts used as evidence (with
provenance), the information that is missing, and suggested questions for the study team.
Nothing here guesses: missing information is never treated as a negative finding, thresholds
are only those printed in the criterion, and Lp(a) units are never converted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.clinical.vocab import analyte_index, convert, get_concept, normalize_unit
from app.modules.eligibility.patient import LabFact, PatientFacts

RESTRICTIVE_QUALIFIERS = {
    "severe", "moderate to severe", "uncontrolled", "poorly controlled", "inadequately treated", "untreated",
    "active", "class iii or iv", "class iv", "nyha class iii", "nyha class iv", "iii or iv", "recent",
    "unless controlled",
}
_OPS = {">=": "at least", ">": "above", "<=": "at most", "<": "below", "=": "equal to"}


@dataclass
class Eval:
    value: str
    patient_info: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


def _label(code: str) -> str:
    c = get_concept(code)
    return c.label if c else code.replace("_", " ")


def _fmt_date(d: date | None) -> str:
    return d.strftime("%b %d, %Y") if d else "an unrecorded date"


def _cmp(v: float, op: str, t: float) -> bool:
    return {">=": v >= t, ">": v > t, "<=": v <= t, "<": v < t, "=": v == t}[op]


def evaluate(req: dict | None, facts: PatientFacts, kind: str) -> Eval:
    if req is None:
        return Eval("review", explanation=["This criterion could not be interpreted automatically."])
    t = req.get("type")
    fn = _HANDLERS.get(t)
    if fn is None:
        return Eval("review", explanation=["This criterion type is not supported yet."])
    return fn(req, facts, kind)


# ----------------------------------------------------------------------------- combinators


def _merge(children: list[Eval], value: str) -> Eval:
    out = Eval(value)
    for c in children:
        for attr in ("patient_info", "explanation", "missing", "questions"):
            for item in getattr(c, attr):
                if item not in getattr(out, attr):
                    getattr(out, attr).append(item)
        for ev in c.evidence:
            if ev not in out.evidence:
                out.evidence.append(ev)
    return out


def combine_all(children: list[Eval]) -> str:
    vals = [c.value for c in children if c.value != "na"]
    if not vals:
        return "na"
    for v in ("false", "conflict", "review", "unknown", "confirm"):
        if v in vals:
            return v
    return "true"


def combine_any(children: list[Eval]) -> str:
    vals = [c.value for c in children]
    if "true" in vals:
        return "true"
    rest = [v for v in vals if v not in ("false", "na")]
    if not rest:
        return "false" if "false" in vals else "na"
    for v in ("conflict", "unknown", "review", "confirm"):
        if v in rest:
            return v
    return "unknown"


def _all(req, facts, kind):
    children = [evaluate(r, facts, kind) for r in req["items"]]
    return _merge(children, combine_all(children))


def _any(req, facts, kind):
    children = [evaluate(r, facts, kind) for r in req["items"]]
    value = combine_any(children)
    if value == "true":  # only show the branch(es) that satisfied it
        children = [c for c in children if c.value == "true"]
    return _merge(children, value)


# ----------------------------------------------------------------------------- demographics


def _age(req, facts, kind):
    lo, hi = req.get("min"), req.get("max")
    rng = f"{lo}–{hi}" if lo is not None and hi is not None else (f"{lo} or older" if lo is not None else f"up to {hi}")
    if facts.age_years is None:
        return Eval("unknown", ["Age not provided"], [f"The study enrolls people aged {rng}; your age isn't on file."],
                    missing=["Your date of birth or age"])
    age = facts.age_years
    ok = (lo is None or age >= lo) and (hi is None or age <= hi)
    basis = "from your date of birth" if facts.age_basis == "date_of_birth" else "as you reported it"
    ev = [facts.age_ref.as_evidence()] if facts.age_ref else []
    msg = f"The study enrolls people aged {rng}. You are {age:g} ({basis})" + (", which is in range." if ok else ", which is outside this range.")
    return Eval("true" if ok else "false", [f"Age {age:g}"], [msg], ev)


def _pregnancy(req, facts, kind):
    if facts.sex == "male":
        return Eval("na", ["Male"], ["Applies only to people who can become pregnant."])
    if facts.can_become_pregnant == "absent":
        return Eval("false" if kind == "exclusion" else "na", ["Not able to become pregnant (reported)"],
                    ["You reported that you cannot become pregnant, so this does not appear to apply."])
    return Eval("confirm", ["Pregnancy-related requirement"],
                ["Pregnancy, breastfeeding and contraception requirements are confirmed by the study team at screening."])


# ----------------------------------------------------------------------------- labs


def _lab_comparison(lab: LabFact, th: dict, analyte: str) -> tuple[bool | None, str | None, float | None]:
    """Returns (passes, problem, compared_value)."""
    if lab.value is None:
        return None, "the result is not numeric", None
    unit_p = normalize_unit(lab.unit)
    unit_t = th.get("unit")
    if unit_t is None:
        return None, "the criterion does not state a unit", None
    if unit_p is None:
        return None, "your result has no unit recorded", None
    if unit_p == unit_t:
        return _cmp(lab.value, th["op"], th["value"]), None, lab.value
    conv = convert(analyte, lab.value, unit_p, unit_t)
    if conv is None:
        a = analyte_index().get(analyte)
        reason = a.non_convertible_reason if a and not a.convertible else f"{unit_p} cannot be converted to {unit_t}"
        return None, reason, None
    return _cmp(conv, th["op"], th["value"]), None, conv


def _lab(req, facts, kind):
    analyte = req["analyte"]
    a = analyte_index().get(analyte)
    label = a.label if a else analyte
    ths = req["thresholds"]
    th_text = (" or " if req.get("combine") == "any" else " and ").join(
        f"{_OPS[t['op']]} {t['value']:g} {t.get('unit') or ''}".strip() for t in ths)
    labs = facts.labs_for(analyte)
    if not labs:
        return Eval("unknown", [f"No {label} result on file"],
                    [f"The study requires {label} {th_text}. No {label} result is on file."],
                    missing=[f"{label} result" + (f" (in {ths[0]['unit']})" if ths[0].get("unit") else "")])
    lab = labs[0]
    results = [_lab_comparison(lab, th, analyte) for th in ths]
    comparable = [r for r in results if r[0] is not None]
    problems = [r[1] for r in results if r[1]]
    if req.get("combine") == "any":
        if any(r[0] is True for r in comparable):
            value = "true"
        elif not problems:
            value = "false"
        else:
            value = "review"
    else:
        if any(r[0] is False for r in comparable):
            value = "false"
        elif problems:
            value = "review"
        else:
            value = "true"
    if value in ("true", "false"):
        problems = []  # an alternative was decisive; incomparable alternatives don't matter

    shown = f"{lab.value:g} {lab.unit or ''}".strip() if lab.value is not None else (lab.value_text or "?")
    conv_note = ""
    for (_ok, _p, v), th in zip(results, ths, strict=False):
        if v is not None and normalize_unit(lab.unit) != th.get("unit"):
            conv_note = f" (≈ {v:.0f} {th['unit']} after unit conversion)"
    when = f"collected {_fmt_date(lab.collected_on)}" if lab.collected_on else "collection date not recorded"
    expl = [f"The study requires {label} {th_text}. Your most recent result is {shown}{conv_note} ({when})."]
    if value == "true":
        expl.append("That meets the stated threshold.")
    elif value == "false":
        expl.append("That does not meet the stated threshold.")
    for p in dict.fromkeys(problems):
        expl.append(f"It can't be compared directly because {p}" if not p.startswith("Lp(a)") else p)
    # near-threshold
    for th, (_ok, _p, v) in zip(ths, results, strict=False):
        if v is not None and th["value"] and abs(v - th["value"]) / th["value"] < 0.10:
            expl.append("Your value is close to the threshold, so the study's own screening measurement will decide.")
            break
    # recency
    if a and a.recency_days:
        if lab.collected_on is None:
            expl.append("The collection date isn't recorded, so it's unclear whether this result is current.")
            if value in ("true", "false"):
                value = "review"
        elif (facts.as_of - lab.collected_on).days > a.recency_days:
            months = a.recency_days // 30
            expl.append(f"This result is more than {months} months old and may not reflect your current level.")
            if value in ("true", "false"):
                value = "review"
    if req.get("at_screening") or (a and a.stability_note):
        expl.append(a.stability_note if a and a.stability_note else "The study measures this itself at screening.")
    # older results on the other side of the threshold
    if len(labs) > 1 and value in ("true", "false"):
        for older in labs[1:]:
            res = [_lab_comparison(older, th, analyte)[0] for th in ths]
            older_ok = any(r for r in res if r is not None) if req.get("combine") == "any" else all(r for r in res if r is not None)
            if (older_ok and value == "false") or (not older_ok and value == "true" and any(r is not None for r in res)):
                expl.append(f"An earlier result ({older.value:g} {older.unit or ''} on {_fmt_date(older.collected_on)}) "
                            "was on the other side of the threshold.")
                break
    ev = [lab.ref.as_evidence()]
    missing = []
    if value == "review" and problems and analyte == "lpa":
        units = {t.get("unit") for t in ths if t.get("unit")}
        missing.append(f"Lp(a) result reported in {' or '.join(sorted(units))}")
    return Eval(value, [lab.ref.label], expl, ev, missing)


def _lab_relative(req, facts, kind):
    analyte = req["analyte"]
    a = analyte_index().get(analyte)
    label = a.label if a else analyte
    labs = facts.labs_for(analyte)
    desc = f"{label} {_OPS[req['op']]} {req['multiple']:g}× the upper limit of normal"
    if not labs:
        return Eval("unknown", [f"No {label} result on file"], [f"This refers to {desc}. No result is on file."],
                    missing=[f"{label} result with reference range"])
    lab = labs[0]
    if lab.value is None or lab.ref_high is None:
        return Eval("unknown", [lab.ref.label], [f"This refers to {desc}; the lab's reference range isn't recorded."],
                    [lab.ref.as_evidence()], missing=[f"{label} reference range"])
    passes = _cmp(lab.value, req["op"], req["multiple"] * lab.ref_high)
    return Eval("true" if passes else "false", [lab.ref.label],
                [f"This refers to {desc}. Your result is {lab.value:g} with an upper limit of normal of {lab.ref_high:g}."],
                [lab.ref.as_evidence()])


def _lab_qualitative(req, facts, kind):
    analyte = req["analyte"]
    a = analyte_index().get(analyte)
    label = a.label if a else analyte
    labs = facts.labs_for(analyte)
    quality = req.get("quality")
    if not labs:
        article = "an" if quality[0] in "aeiou" else "a"
        return Eval("unknown", [f"No {label} result on file"], [f"This requires {article} {quality} {label}. No result is on file."],
                    missing=[f"{label} result"])
    lab = labs[0]
    ev = [lab.ref.as_evidence()]
    if quality in ("elevated", "high"):
        extra = ""
        if lab.value is not None and lab.ref_high is not None and lab.value > lab.ref_high:
            extra = " It is above the reporting laboratory's reference range, but that range is not the study's threshold."
        return Eval("review", [lab.ref.label],
                    [f"The study requires {'a high' if quality == 'high' else 'an elevated'} {label} but does not publish a "
                     f"numeric threshold in the registry. Your result is {lab.ref.label}.{extra} Only the study team can say "
                     "whether it qualifies."], ev,
                    questions=[f"What {label} level does the study require?"])
    if lab.value is None or (lab.ref_low is None and lab.ref_high is None):
        return Eval("unknown", [lab.ref.label], [f"This depends on whether your {label} is within the normal range; "
                                                 "the reference range isn't recorded."], ev,
                    missing=[f"{label} reference range"])
    normal = (lab.ref_low is None or lab.value >= lab.ref_low) and (lab.ref_high is None or lab.value <= lab.ref_high)
    want_normal = quality == "normal"
    return Eval("true" if normal == want_normal else "false", [lab.ref.label],
                [f"Your {label} is {'within' if normal else 'outside'} the laboratory's reference range."], ev)


def _lab_measured(req, facts, kind):
    analyte = req["analyte"]
    labs = facts.labs_for(analyte)
    label = analyte_index()[analyte].label
    if labs:
        return Eval("true", [labs[0].ref.label], [f"You have a {label} measurement on file."], [labs[0].ref.as_evidence()])
    return Eval("unknown", [f"No {label} result on file"], [f"Requires a {label} measurement."], missing=[f"{label} result"])


# ----------------------------------------------------------------------------- conditions


def _condition(req, facts, kind):
    code = req["concept"]
    label = _label(code)
    concept = get_concept(code)
    question = concept.patient_question if concept and concept.patient_question else None
    if req.get("planned_only"):
        return Eval("unknown", [f"Planned {label.lower()}: not recorded"],
                    [f"This depends on whether you have a planned {label.lower()}, which isn't recorded in your profile."],
                    missing=[f"Whether you have a planned {label.lower()}"])
    st, fs = facts.concept_status(code)
    if req.get("negated"):
        inner = _condition({**req, "negated": False}, facts, kind)
        flip = {"true": "false", "false": "true"}
        out = Eval(flip.get(inner.value, inner.value), inner.patient_info, [], inner.evidence, inner.missing, inner.questions)
        out.explanation = [f"The study requires no history of {label.lower()}."] + inner.explanation[1:]
        if inner.value == "unknown":
            out.explanation.append("Whether you have this history is not fully recorded.")
        return out

    ev = [f.ref.as_evidence() for f in fs]
    info = [f.ref.label for f in fs] or [f"No information recorded about {label.lower()}"]
    head = f"This criterion refers to {label.lower()}"
    if req.get("window_days"):
        head += f" within the last {_window_text(req['window_days'])}"
    head += "."

    if st == "conflict":
        return Eval("conflict", info, [head, "Your records disagree about this (see sources). Please review and correct "
                                             "your profile."], ev, missing=[f"Clarify: {label}"])
    if st == "unknown":
        if req.get("screening_assessed") and kind == "inclusion":
            return Eval("unknown", info, [head, "The study assesses this during screening (for example with imaging), "
                                                "so it can't be determined in advance."], ev)
        out = Eval("unknown", info, [head, "Your profile doesn't say whether this applies to you."], ev,
                   missing=[question or label])
        if req.get("planned"):
            out.missing.append(f"Whether you have a planned {label.lower()}")
        return out
    if st == "absent":
        if req.get("screening_assessed") and kind == "inclusion":
            return Eval("unknown", info, [head, "You have no recorded diagnosis, but the study assesses this itself during "
                                                "screening (for example with imaging)."], ev)
        if req.get("planned"):
            return Eval("unknown", info, [head, "You reported no history of this; whether one is planned isn't recorded."],
                        ev, missing=[f"Whether you have a planned {label.lower()}"])
        return Eval("false", info, [head, "Your profile indicates you do not have this."], ev)

    # present
    expl = [head]
    value = "true"
    if req.get("window_days"):
        dated = [f for f in fs if f.onset]
        within = [f for f in dated if (facts.as_of - f.onset).days <= req["window_days"]]
        if within:
            expl.append("Your recorded date falls within this period.")
        elif dated and len(dated) == len(fs):
            value = "false"
            expl.append("Your recorded date is outside this period.")
        else:
            value = "unknown"
            expl.append("The date isn't recorded, so it's unclear whether it falls within this period.")
            return Eval(value, info, expl, ev, missing=[f"Date of {label.lower()}"])
    quals = [q for q in req.get("qualifiers", []) if q in RESTRICTIVE_QUALIFIERS]
    if quals and value == "true":
        verdict = _qualifier_verdict(quals, fs)
        if verdict is None:
            expl.append(f"You reported {label.lower()}. Whether it is {' / '.join(quals)} isn't recorded; the study team "
                        "will assess this.")
            return Eval("review", info, expl, ev, missing=[f"Whether your {label.lower()} is {' / '.join(quals)}"])
        value = "true" if verdict else "false"
        expl.append("Based on what you reported about severity/control." )
    if req.get("screening_assessed"):
        expl.append("The study will confirm this during screening.")
    if value == "true":
        expl.append("Your profile indicates this applies to you.")
    return Eval(value, info, expl, ev)


def _qualifier_verdict(quals: list[str], fs) -> bool | None:
    """True if the restrictive qualifier applies, False if it clearly does not, None if unknown."""
    for f in fs:
        q = f.qualifiers or {}
        for qual in quals:
            if qual in ("uncontrolled", "poorly controlled", "inadequately treated", "untreated") and "controlled" in q:
                return not bool(q["controlled"])
            if qual == "unless controlled" and "controlled" in q:
                return not bool(q["controlled"])
            if qual == "active" and "active" in q:
                return bool(q["active"])
            if qual in ("severe", "moderate to severe") and "severity" in q:
                sev = str(q["severity"]).lower()
                return sev == "severe" or (qual == "moderate to severe" and sev == "moderate")
    return None


def _window_text(days: int) -> str:
    if days % 365 == 0:
        n = days // 365
        return f"{n} year{'s' if n > 1 else ''}"
    if days % 30 == 0:
        n = days // 30
        return f"{n} month{'s' if n > 1 else ''}"
    return f"{days} days"


# ----------------------------------------------------------------------------- medications


def _medication(req, facts, kind):
    code = req["concept"]
    label = _label(code)
    st, fs = facts.med_status(code)
    ev = [f.ref.as_evidence() for f in fs]
    info = [f.ref.label for f in fs] or [f"No information recorded about {label.lower()}"]
    mode = req.get("mode", "ever")
    win = req.get("window_days")
    missing_q = f"Whether you take (or have taken) {label.lower()}"

    if st == "conflict":
        return Eval("conflict", info, [f"Your records disagree about {label.lower()} use."], ev, missing=[f"Clarify: {label}"])

    if mode == "stable_if_current":
        need = req.get("min_duration_days")
        if st in ("past", "not_current", "never"):
            return Eval("na", info, [f"Applies only if you take {label.lower()}; you reported you don't, so it doesn't apply."], ev)
        if st == "unknown":
            return Eval("unknown", info, [f"Applies if you take {label.lower()}; that isn't recorded."], ev, missing=[missing_q])
        started = [f.started_on for f in fs if f.started_on]
        if need and started and (facts.as_of - max(started)).days >= need:
            return Eval("true", info, [f"You've been taking {label.lower()} long enough to meet the stability requirement."], ev)
        return Eval("review", info, [f"You take {label.lower()}; the study requires a stable dose"
                                     + (f" for at least {_window_text(need)}" if need else "") + ", and the start date isn't recorded."],
                    ev, missing=[f"When you started your current {label.lower()} dose"])

    if mode == "current":
        if st == "current":
            need = req.get("min_duration_days")
            expl = [f"The study requires current {label.lower()} use"
                    + (f" for at least {_window_text(need)}" if need else "") + ". You reported taking it."]
            value = "true"
            if need:
                started = [f.started_on for f in fs if f.started_on]
                if not started:
                    value = "review"
                    expl.append("Your start date isn't recorded.")
                elif (facts.as_of - max(started)).days < need:
                    value = "false"
                    expl.append("You started it more recently than required.")
            if req.get("qualifier") and value == "true":
                value = "review"
                expl.append(f"The study also specifies an '{req['qualifier']}'; dose intensity isn't evaluated automatically.")
            out = Eval(value, info, expl, ev)
        elif st in ("past", "not_current", "never"):
            out = Eval("false", info, [f"The study requires participants to currently take {label.lower()}"
                                       + (f" ({req['qualifier']})" if req.get("qualifier") else "")
                                       + ". You reported that you are not currently taking it."], ev)
        else:
            out = Eval("unknown", info, [f"The study requires current {label.lower()} use; this isn't recorded."], ev,
                       missing=[missing_q])
        return _negate(out) if req.get("negated") else out

    if mode == "within_window":
        period = f"in the last {_window_text(win)}" if win else "within a period specified in the protocol"
        if st == "current":
            out = Eval("true", info, [f"This refers to {label.lower()} use {period}. You reported currently taking it."], ev)
        elif st == "never":
            out = Eval("false", info, [f"This refers to {label.lower()} use {period}. You reported never taking it."], ev)
        elif st == "past" and win:
            stops = [f.stopped_on for f in fs if f.stopped_on]
            if stops and (facts.as_of - max(stops)).days <= win:
                out = Eval("true", info, [f"This refers to {label.lower()} use {period}. You stopped within that period."], ev)
            elif stops:
                out = Eval("false", info, [f"This refers to {label.lower()} use {period}. You stopped before that period."], ev)
            else:
                out = Eval("unknown", info, [f"This refers to {label.lower()} use {period}. Your stop date isn't recorded."], ev,
                           missing=[f"When you stopped {label.lower()}"])
        elif st in ("past", "not_current"):
            out = Eval("unknown", info, [f"This refers to {label.lower()} use {period}. You reported you are not currently "
                                         "taking it, but whether you took it during that period isn't recorded."], ev,
                       missing=[f"Whether you took {label.lower()} {period}"])
        else:
            out = Eval("unknown", info, [f"This refers to {label.lower()} use {period}; it isn't recorded."], ev,
                       missing=[missing_q])
        if req.get("negated"):
            out = _negate(out)
            out.explanation[0] = out.explanation[0].replace("This refers to", "The study requires no")
        return out

    # mode == ever
    if st in ("current", "past"):
        out = Eval("true", info, [f"This refers to any prior use of {label.lower()}. Your profile shows you have taken it."], ev)
    elif st == "never":
        out = Eval("false", info, [f"This refers to any prior use of {label.lower()}. You reported never taking it."], ev)
    else:
        out = Eval("unknown", info, [f"This refers to any prior use of {label.lower()}; that isn't recorded."], ev,
                   missing=[missing_q])
    return _negate(out) if req.get("negated") else out


def _negate(e: Eval) -> Eval:
    e.value = {"true": "false", "false": "true"}.get(e.value, e.value)
    return e


def _vague(req, facts, kind):
    reason = req.get("reason", "")
    if "not collected" in reason:
        return Eval("review", [], ["This depends on information that isn't collected in your profile (for example "
                                   "allergies). The study team will ask about it."])
    return Eval("review", [], [f"Part of this criterion (“{reason}”) is defined in the full study protocol, which "
                               "isn't published in the registry. The study team determines this."],
                questions=[f"How does the study define “{reason}”?"])


_HANDLERS = {
    "all": _all, "any": _any, "age": _age, "pregnancy": _pregnancy, "lab": _lab, "lab_relative": _lab_relative,
    "lab_qualitative": _lab_qualitative, "lab_measured": _lab_measured, "condition": _condition,
    "medication": _medication, "vague": _vague,
}
