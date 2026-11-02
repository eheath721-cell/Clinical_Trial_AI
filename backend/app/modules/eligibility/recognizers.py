"""Deterministic recognizers: criterion text -> structured requirement.

A requirement is a JSON-serializable statement about the patient. Inclusion criteria require
the statement to be true; exclusion criteria exclude the patient if it is true.

Requirement shapes
  {"type": "all"|"any", "items": [...]}
  {"type": "age", "min": 18, "max": 65}
  {"type": "lab", "analyte": "lpa", "thresholds": [{"op": ">=", "value": 175, "unit": "nmol/L"}],
   "combine": "any"|"all", "at_screening": bool}
  {"type": "lab_relative", "analyte": "alt", "op": ">", "multiple": 3, "reference": "uln"}
  {"type": "lab_qualitative", "analyte": "lpa", "quality": "elevated"|"high"|"normal"}
  {"type": "lab_measured", "analyte": "lpa"}
  {"type": "condition", "concept": "ascvd_event", "negated": bool, "window_days": 90,
   "qualifiers": ["severe"], "screening_assessed": bool, "planned": bool}
  {"type": "medication", "concept": "statin", "mode": "current"|"within_window"|"ever"|"stable_if_current",
   "negated": bool, "window_days": int|None, "min_duration_days": int|None}
  {"type": "pregnancy"}
  {"type": "vague", "reason": "..."}

Anything that cannot be recognized reliably is returned as category "unparsed" and shown to
the patient as "needs review" - the engine never guesses.
"""

from __future__ import annotations

import re
from typing import Any

from app.clinical.vocab import (
    UNIT_REGEX,
    ancestors,
    concept_index,
    find_analytes,
    find_concepts,
    normalize_unit,
)

PARSER_VERSION = "rules-1.0"

_ADMIN_RE = re.compile(
    r"informed consent|\bicf\b|\bwilling\b|willingness|able to (understand|comply|complete|provide)|comply with|"
    r"compliance with|contracepti|suitable veins|venipuncture|cannulation|donate (sperm|ova)|\bsign(ed)? the\b|"
    r"cooperate|blood donation|standardized diet|dysphagia|live vaccine|needle or blood phobia|"
    r"continue to use a stable dose|do not start new|no planned (medication|addition|dose)|"
    r"ethnically (japanese|chinese)|both parents and 4 grandparents|negative pregnancy test|"
    r"non-childbearing potential|heterosexually active|plans for pregnancy|weigh at least|asian origin|"
    r"alcohol|cigarettes|smok|nicotine|drug abuse|urine drug screen|trauma|anesthesia|"
    r"unable to safely undergo|contrast allerg|abstain", re.I)
_ADMIN_HARD_RE = re.compile(r"continue to use a stable dose|do not start new|unable to safely undergo|"
                            r"^there should be no planned", re.I)
_INVESTIGATOR_HARD_RE = re.compile(r"^any clinically (significant|important)|in the investigator'?s judgment|"
                                   r"considered by the investigator|^history of any clinically", re.I)
_ALLERGY_RE = re.compile(r"\ballerg|hypersensitivity", re.I)
_MED_QUALIFIER_RE = re.compile(r"optimized and stable dose|moderate or high-intensity|high-intensity|maximally tolerated",
                               re.I)
_RISK_BEFORE_RE = re.compile(r"risk (for|of)\s+(a\s+|an\s+)?(first\s+)?$", re.I)
_PREGNANCY_RE = re.compile(r"\bpregnan|breastfeed|breast-feed|lactating", re.I)
_INVESTIGATOR_RE = re.compile(
    r"investigator'?s?\s+(judg|opinion|discretion)|judged by the investigator|considered by the investigator|"
    r"as determined by the investigator|clinically (important|significant)|any (other )?(condition|disease|factor|"
    r"medical condition) (that|which|known)|poor compliance|abnormal vital|physical examination|"
    r"electrocardiogram|\becg\b|abnormal laboratory values|unsuitable", re.I)
_VAGUE_RE = re.compile(
    r"combination(\(s\))? of (high[- ]?)?risk factors|high[- ]risk factors|multiple [\w\s]*risk factors|"
    r"additional risk factor|risk stratification|10-year [\w\s]*risk|moderate or high risk|at (a )?(high|increased) risk|"
    r"at risk (for|of) (a )?first|specified (in the protocol|timeframe)|prohibited timeframe|certain therapies|"
    r"as specified in the protocol|specified period|diseases that significantly affect|"
    r"optimized and stable dose|moderate or high-intensity", re.I)
_SCREENING_RE = re.compile(r"\b(at|during|on) (the )?screening\b|screening (visit|ccta)|at screening", re.I)
_PLANNED_RE = re.compile(r"\bplann(ed|ing)\b|expected to undergo|scheduled", re.I)
_NEG_BEFORE_RE = re.compile(r"(\bno\b|\bwithout\b|\bnot have\b|\babsence of\b|\bnever\b|free of)[^.;]{0,60}$", re.I)
_QUALIFIER_RE = re.compile(
    r"(moderate to severe|severe|uncontrolled|poorly controlled|inadequately treated|untreated|active|"
    r"class iii or iv|class iv|nyha class iii|nyha class iv|iii or iv|major|recent|acute|unstable)"
    r"[\w\s(),/-]{0,45}$", re.I)
_RISK_AFTER_RE = re.compile(r"^\s*\)?\s*(\(\w+\)\s*)?risk", re.I)

_COMPARATORS = [
    ("greater than or equal to", ">="), ("less than or equal to", "<="), ("at least", ">="), ("no more than", "<="),
    ("greater than", ">"), ("more than", ">"), ("less than", "<"), ("above", ">"), ("over", ">"),
    ("below", "<"), ("under", "<"), ("≥", ">="), (">=", ">="), ("≤", "<="), ("<=", "<="), (">", ">"), ("<", "<"),
    ("=", "="),
]
_COMP_ALT = "|".join(re.escape(c[0]) for c in _COMPARATORS)
_THRESH_RE = re.compile(rf"(?P<op>{_COMP_ALT})\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_REGEX})?", re.I)
_RANGE_RE = re.compile(rf"between\s*(?P<lo>\d+(?:\.\d+)?)\s*(?P<u1>{UNIT_REGEX})?\s*(?:and|to|-)\s*"
                       rf"(?P<hi>\d+(?:\.\d+)?)\s*(?P<u2>{UNIT_REGEX})?", re.I)
_ULN_RE = re.compile(r"(?P<op>>|≥|>=)\s*(?P<mult>\d+(?:\.\d+)?)\s*(?:x|×|times)\s*(?:the\s+)?(upper limit of normal|uln)",
                     re.I)
_WINDOW_RES = [
    re.compile(r"within\s+(?:the\s+)?(?:past\s+|last\s+)?(?P<n>\d+)\s+(?P<u>day|week|month|year)s?", re.I),
    re.compile(r"(?P<n>\d+)\s+(?P<u>day|week|month|year)s?\s+(?:prior to|before)", re.I),
    re.compile(r"in the (?:last|past)\s+(?P<n>\d+)\s+(?P<u>day|week|month|year)s?", re.I),
    re.compile(r"(?:less than|<)\s*(?P<n>\d+)\s+(?P<u>day|week|month|year)s?\s+before", re.I),
    re.compile(r"from\s+(?P<n>\d+)\s+(?P<u>day|week|month|year)s?\s+before", re.I),
]
_DURATION_RE = re.compile(r"for\s*(?:≥|>=|at least)?\s*(?P<n>\d+)\s+(?P<u>day|week|month|year)s?|"
                          r"stable for\s+(?P<n2>\d+)\s+(?P<u2>day|week|month|year)s?", re.I)
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

_AGE_RANGE_RE = re.compile(r"(?:aged?|age)\s*(?P<lo>\d{1,3})\s*(?:years?)?\s*(?:to|-|–|and)\s*(?:≤|<=)?\s*(?P<hi>\d{1,3})\s*years",
                           re.I)
_AGE_MIN_RES = [
    re.compile(r"(?:aged?|age)\s*(?:≥|>=|at least)\s*(?P<n>\d{1,3})", re.I),
    re.compile(r"(?:≥|>=)\s*(?P<n>\d{1,3})\s*years of age", re.I),
    re.compile(r"(?P<n>\d{1,3})\s*years of age or older", re.I),
    re.compile(r"(?P<n>\d{1,3})\s*years or older", re.I),
    re.compile(r"(?:adults?|individuals|participants)\s+(?:aged\s+)?(?:≥|>=)\s*(?P<n>\d{1,3})", re.I),
]

_MED_CURRENT_RE = re.compile(r"receiving|taking|treated with|on (a )?(stable )?(dose of )?|current(ly)? (use|treatment|"
                             r"therapy)|current treatment with|treatment with", re.I)
_MED_PRIOR_RE = re.compile(r"previous(ly)? (administration|received|use|treatment)|prior (treatment|use|exposure)|"
                           r"received|administration of|have used|history of (use|treatment)", re.I)
_MED_NOT_RECEIVED_RE = re.compile(r"(have|has) not (received|taken|used)|not received any|no (prior|previous) "
                                  r"(use|treatment)", re.I)
_IF_TAKING_RE = re.compile(r"^\s*if (taking|on|receiving|currently)", re.I)


def _window_days(text: str) -> int | None:
    for rx in _WINDOW_RES:
        m = rx.search(text)
        if m:
            return int(m.group("n")) * _UNIT_DAYS[m.group("u").lower()]
    return None


def _duration_days(text: str) -> int | None:
    m = _DURATION_RE.search(text)
    if not m:
        return None
    n = m.group("n") or m.group("n2")
    u = m.group("u") or m.group("u2")
    return int(n) * _UNIT_DAYS[u.lower()]


def _op(raw: str) -> str:
    raw = raw.lower()
    for k, v in _COMPARATORS:
        if raw == k:
            return v
    return raw


def recognize(text: str, kind: str) -> tuple[str, dict[str, Any] | None]:
    """Return (category, requirement). category: clinical | administrative | investigator | unparsed"""
    t = " ".join(text.split())
    low = t.lower()

    if _ADMIN_HARD_RE.search(low):
        return "administrative", None
    if _INVESTIGATOR_HARD_RE.search(low):
        return "investigator", None
    if _ALLERGY_RE.search(low):
        return "clinical", {"type": "vague", "reason": "allergy or hypersensitivity (not collected in the profile)"}
    if re.match(r"^for [\w\s,()]+participants", low) and low.endswith(":"):
        return "administrative", None  # conditional sub-population definition (e.g. ethnicity cohorts)
    if _PREGNANCY_RE.search(low) and not find_analytes(t):
        return "clinical", {"type": "pregnancy"}
    if re.search(r"\bmeasured lipoprotein\s*\(a\)", low):
        return "clinical", {"type": "lab_measured", "analyte": "lpa"}

    items: list[dict[str, Any]] = []
    lab_spans: list[tuple[int, int]] = []

    # --- labs ------------------------------------------------------------------
    analytes = []
    for am in find_analytes(t):  # drop parenthetical repeats: "alanine aminotransferase (ALT)"
        if analytes and am.code == analytes[-1].code and am.start - analytes[-1].end <= 3:
            continue
        analytes.append(am)
    lab_reqs: list[dict[str, Any] | None] = []
    for idx, m in enumerate(analytes):
        end = analytes[idx + 1].start if idx + 1 < len(analytes) else len(t)
        seg = t[m.end:min(end, m.end + 110)]
        lab_reqs.append(_lab_requirement(m.code, t[max(0, m.start - 40):m.start], seg))
        lab_spans.append((m.start, m.end + len(seg)))
    for idx in range(len(analytes) - 2, -1, -1):  # "AST or ALT > 3 x ULN": earlier analyte shares the threshold
        gap = t[analytes[idx].end:analytes[idx + 1].start]
        if lab_reqs[idx] is None and lab_reqs[idx + 1] is not None and len(gap) < 30 and re.search(r"\bor\b|\band\b", gap):
            lab_reqs[idx] = {**lab_reqs[idx + 1], "analyte": analytes[idx].code}
    with_thresholds = {r["analyte"] for r in lab_reqs if r and r["type"] in ("lab", "lab_relative")}
    shared = [r for r in lab_reqs if r]
    shared = [r for r in shared if not (r["type"] == "lab_qualitative" and r["analyte"] in with_thresholds)]
    if len(shared) > 1 and all(r["type"] == "lab_relative" for r in shared):
        items.append({"type": "any" if kind == "exclusion" else "all", "items": shared})
    else:
        items.extend(shared)

    # --- age -------------------------------------------------------------------
    age = _age_requirement(t)
    if age:
        items.append(age)

    # --- concepts: conditions, events, procedures, medications -------------------
    mentions = [mm for mm in find_concepts(t) if mm.code != "elevated_lpa"]
    mentions = [mm for mm in mentions if not any(s <= mm.start < e for s, e in lab_spans)]
    # "ASCVD risk factors" / "ASCVD risk" are about risk, not a diagnosis
    mentions = [mm for mm in mentions if not _RISK_AFTER_RE.match(t[mm.end:mm.end + 20])]
    mentions = [mm for mm in mentions if not _RISK_BEFORE_RE.search(t[max(0, mm.start - 30):mm.start])]
    deduped = []
    for mm in mentions:  # "homozygous familial hypercholesterolemia (FH)": the abbreviation adds nothing
        if deduped and t[max(0, mm.start - 2):mm.start].endswith("(") and mm.start - deduped[-1].end <= 3:
            continue
        deduped.append(mm)
    mentions = deduped
    # drop examples covered by an umbrella mentioned in the same text ("event (such as heart attack...)")
    codes = {mm.code for mm in mentions}
    mentions = [mm for mm in mentions if not (ancestors(mm.code) & codes)]
    seen: set[tuple[str, bool]] = set()
    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    window = _window_days(t)
    planned = bool(_PLANNED_RE.search(low))
    screening = bool(_SCREENING_RE.search(low))
    for mm in mentions:
        concept = concept_index()[mm.code]
        before = t[max(0, mm.start - 60):mm.start]
        negated = bool(_NEG_BEFORE_RE.search(before))
        key = (mm.code, negated)
        if key in seen:
            continue
        seen.add(key)
        if concept.kind in ("drug", "drug_class"):
            req = _medication_requirement(mm.code, t, before, negated)
        else:
            qual = _QUALIFIER_RE.search(before)
            qualifiers = [qual.group(1).lower()] if qual else []
            if re.search(r"\bcontrolled\b", t[mm.end:mm.end + 60], re.I) and "unless" in low:
                qualifiers.append("unless controlled")
            req = {"type": "condition", "concept": mm.code, "negated": negated}
            if window:
                req["window_days"] = window
            if qualifiers:
                req["qualifiers"] = qualifiers
            if planned and concept.kind == "procedure":
                req["planned"] = True
                if not re.search(r"\bprior\b|history|ha(ve|s) had|current|recent|undergone|within|previous", low):
                    req["planned_only"] = True
            if screening and concept.kind == "condition":
                req["screening_assessed"] = True
        (negatives if negated else positives).append(req)

    medq = _MED_QUALIFIER_RE.search(low)
    meds = [p for p in positives if p.get("type") == "medication"]
    if medq and meds:
        for p in meds:
            p["qualifier"] = medq.group(0)  # e.g. "moderate or high-intensity" statin: an AND, not an OR
    vague = _VAGUE_RE.search(low)
    already_vague = any(p.get("type") == "any" and any(i.get("type") == "vague" for i in p.get("items", [])) for p in positives)
    generic_protocol_ref = bool(vague and re.fullmatch(r"(as )?specified in the protocol|per protocol",
                                                       vague.group(0).lower()))
    if (vague and not (medq and meds and vague.group(0).lower() in medq.group(0).lower()) and not already_vague
            and not (generic_protocol_ref and (items or positives or negatives))):
        positives.append({"type": "vague", "reason": vague.group(0)})
    if re.search(r"\bhigh coronary artery calcium|\bhigh cac\b", low) and not any(
        i.get("analyte") == "cac_score" for i in items
    ):
        items.append({"type": "lab_qualitative", "analyte": "cac_score", "quality": "high"})

    if positives:
        if len(positives) == 1:
            items.append(positives[0])
        else:
            if re.search(r"\bor\b|and/or|either|one of", low):
                combine = "any"
            elif re.search(r"\bwith\b|\band\b", low):
                combine = "all"
            else:
                combine = "any" if kind == "exclusion" else "all"
            items.append({"type": combine, "items": positives})
    items.extend(negatives)

    if not items:
        if _INVESTIGATOR_RE.search(low):
            return "investigator", None
        if _ADMIN_RE.search(low):
            return "administrative", None
        return "unparsed", None
    # Clinical content wrapped in investigator/administrative language is still evaluated, but a
    # purely administrative line that happens to mention a concept is not.
    if _ADMIN_RE.search(low) and all(i["type"] in ("condition", "vague") for i in items) and not _strong(items):
        return "administrative", None

    if len(items) == 1:
        return "clinical", items[0]
    across = "any" if kind == "exclusion" else "all"
    return "clinical", {"type": across, "items": items}


def _strong(items: list[dict]) -> bool:
    return any(i["type"] == "condition" and not i.get("negated") for i in items)


def _lab_requirement(analyte: str, before: str, seg: str) -> dict[str, Any] | None:
    low_before = before.lower()
    rel = _ULN_RE.search(seg)
    if rel:
        return {"type": "lab_relative", "analyte": analyte, "op": _op(rel.group("op")),
                "multiple": float(rel.group("mult")), "reference": "uln"}
    rng = _RANGE_RE.search(seg)
    if rng and rng.start() < 25:
        unit = normalize_unit(rng.group("u2") or rng.group("u1"))
        return {"type": "lab", "analyte": analyte, "combine": "all",
                "thresholds": [{"op": ">=", "value": float(rng.group("lo")), "unit": unit},
                               {"op": "<=", "value": float(rng.group("hi")), "unit": unit}],
                "at_screening": bool(_SCREENING_RE.search(seg))}
    found = []
    last_end = 0
    joiners = []
    for m in _THRESH_RE.finditer(seg):
        if found and m.start() - last_end > 45:
            break
        if not found and m.start() > 30:
            break
        if found:
            joiners.append(seg[last_end:m.start()].lower())
        found.append({"op": _op(m.group("op")), "value": float(m.group("val")),
                      "unit": normalize_unit(m.group("unit")) if m.group("unit") else None})
        last_end = m.end()
    if found:
        # inherit a unit stated only once ("≥ 70 and < 190 mg/dL")
        units = [f["unit"] for f in found if f["unit"]]
        for f in found:
            if f["unit"] is None and units:
                f["unit"] = units[-1]
        combine = "any" if any(re.search(r"\bor\b", j) for j in joiners) else "all"
        return {"type": "lab", "analyte": analyte, "thresholds": found, "combine": combine,
                "at_screening": bool(_SCREENING_RE.search(seg))}
    if re.search(r"outside (the )?(reference|normal) range|\babnormal\b", seg + " " + low_before, re.I):
        return {"type": "lab_qualitative", "analyte": analyte, "quality": "abnormal"}
    if re.search(r"within normal range|normal range|within (the )?reference range", seg, re.I):
        return {"type": "lab_qualitative", "analyte": analyte, "quality": "normal"}
    if re.search(r"(elevated|high|increased)\s*$", low_before) or re.search(r"^\W*\s*(elevated|high)", seg, re.I):
        return {"type": "lab_qualitative", "analyte": analyte, "quality": "elevated"}
    return None


def _age_requirement(t: str) -> dict[str, Any] | None:
    m = _AGE_RANGE_RE.search(t)
    if m:
        lo, hi = int(m.group("lo")), int(m.group("hi"))
        if lo < hi <= 120:
            return {"type": "age", "min": lo, "max": hi}
    for rx in _AGE_MIN_RES:
        m = rx.search(t)
        if m:
            n = int(m.group("n"))
            if 0 < n <= 120:
                return {"type": "age", "min": n}
    return None


def _medication_requirement(code: str, t: str, before: str, negated: bool) -> dict[str, Any]:
    low = t.lower()
    req: dict[str, Any] = {"type": "medication", "concept": code, "negated": False}
    if _IF_TAKING_RE.search(low):
        req["mode"] = "stable_if_current"
        req["min_duration_days"] = _duration_days(t)
        return req
    if _MED_NOT_RECEIVED_RE.search(low):
        req["mode"] = "within_window"
        req["negated"] = True
        req["window_days"] = _window_days(t)
        return req
    win = _window_days(t)
    if re.search(r"current|receiving|taking|treated with|on (a )?stable", low) and not _MED_PRIOR_RE.search(before.lower()):
        req["mode"] = "current"
        req["min_duration_days"] = _duration_days(t)
        if re.search(r"or prior treatment|or previous", low):
            req = {"type": "any", "items": [req, {"type": "vague", "reason": "prior treatment within a timeframe "
                                                                            "specified in the protocol"}]}
        return req
    if win:
        req["mode"] = "within_window"
        req["window_days"] = win
        return req
    req["mode"] = "ever"
    req["negated"] = negated
    return req
