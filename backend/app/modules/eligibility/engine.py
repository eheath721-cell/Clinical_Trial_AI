"""Eligibility engine: parsed criteria + patient facts -> transparent assessment.

Classification rules (applied per cohort for multi-cohort studies; best cohort wins):
  POTENTIALLY INELIGIBLE  at least one clinical criterion appears to conflict with the
                          patient's information (inclusion not met, or exclusion applies).
  ELIGIBILITY UNCERTAIN   no conflicts, but at least one inclusion criterion cannot be
                          evaluated (missing / ambiguous / conflicting information).
  POTENTIALLY ELIGIBLE    no conflicts and every clinical inclusion criterion appears met.
                          Exclusions that cannot be checked are listed for the patient to
                          confirm with the study team; administrative and investigator-
                          judgment items are listed but never counted.

The engine never states that a patient IS eligible; final eligibility is determined by the
study investigator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import CriterionOutcome as O
from app.models.enums import EligibilityClass as EC
from app.modules.eligibility.criteria_parser import CriterionNode, ParsedCriteria, parse_criteria
from app.modules.eligibility.evaluator import Eval, combine_all, combine_any, evaluate
from app.modules.eligibility.patient import PatientFacts
from app.modules.eligibility.recognizers import PARSER_VERSION, recognize

ENGINE_VERSION = "1.0.0"


@dataclass
class CriterionResult:
    position: int
    depth: int
    kind: str
    text: str
    category: str
    outcome: O
    patient_information: str
    explanation: str
    evidence: list[dict[str, Any]]
    requirement: dict[str, Any] | None
    cohort: str | None = None
    missing: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    is_group: bool = False
    source: str = "registry_text"  # registry_text | registry_field


@dataclass
class AssessmentResult:
    classification: EC
    summary: str
    key_reasons: list[str]
    missing_information: list[str]
    potential_exclusions: list[str]
    questions: list[str]
    criteria: list[CriterionResult]
    counts: dict[str, int]
    best_cohort: str | None
    caveats: list[str]
    engine_version: str = ENGINE_VERSION


def _outcome(value: str, kind: str, category: str) -> O:
    if category in ("administrative", "investigator"):
        return O.confirm_with_team
    if value == "confirm":
        return O.confirm_with_team
    if value == "na":
        return O.not_applicable
    if value == "unknown":
        return O.unknown
    if value == "review":
        return O.needs_review
    if value == "conflict":
        return O.conflicting
    if kind == "inclusion":
        return O.satisfied if value == "true" else O.not_satisfied
    return O.not_satisfied if value == "true" else O.satisfied


def parse_age(text: str | None) -> float | None:
    if not text or text.upper() in ("N/A", "NA"):
        return None
    m = re.match(r"(\d+(?:\.\d+)?)\s*(year|month|week|day)", text, re.I)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower()
    return n / {"year": 1, "month": 12, "week": 52.143, "day": 365.25}[unit]


def recognize_tree(parsed: ParsedCriteria) -> dict[int, tuple[str, dict | None]]:
    out: dict[int, tuple[str, dict | None]] = {}
    for n in parsed.walk():
        if n.is_group:
            out[n.ordinal] = ("group", None)
        else:
            out[n.ordinal] = recognize(n.text, n.kind)
    return out


def assess(
    trial: Any,
    facts: PatientFacts,
    parsed: ParsedCriteria | None = None,
    recognized: dict[int, tuple[str, dict | None]] | None = None,
    llm_interpreter=None,
) -> AssessmentResult:
    """`trial` needs: eligibility_text, minimum_age, maximum_age, sex, source_url, nct_id."""
    parsed = parsed or parse_criteria(trial.eligibility_text)
    recognized = recognized or recognize_tree(parsed)
    if llm_interpreter is not None:
        for n in parsed.walk():
            cat, req = recognized.get(n.ordinal, ("unparsed", None))
            if cat == "unparsed":
                interpreted = llm_interpreter(n.text, n.kind)
                if interpreted is not None:
                    recognized[n.ordinal] = ("clinical", interpreted)

    rows: list[CriterionResult] = []
    criterion_ev = lambda text: {"kind": "trial_criterion", "nct_id": trial.nct_id, "text": text,  # noqa: E731
                                 "source_url": trial.source_url}

    # Registry structured fields: age and sex
    lo, hi = parse_age(trial.minimum_age), parse_age(trial.maximum_age)
    text_has_age = any(recognized.get(n.ordinal, ("", None))[1] and recognized[n.ordinal][1].get("type") == "age"
                       for n in parsed.inclusion)
    if (lo is not None or hi is not None) and not text_has_age:
        req = {"type": "age", **({"min": int(lo)} if lo is not None else {}), **({"max": int(hi)} if hi is not None else {})}
        e = evaluate(req, facts, "inclusion")
        label = f"Age {trial.minimum_age or 'no minimum'} to {trial.maximum_age or 'no maximum'}".replace(" Years", "")
        rows.append(_row(len(rows), 0, "inclusion", label + " (registry age limits)", "clinical", e, req, None,
                         criterion_ev(label), source="registry_field"))
    sex = (trial.sex or "ALL").upper()
    if sex in ("FEMALE", "MALE"):
        want = sex.lower()
        if facts.sex == "unknown":
            e = Eval("unknown", ["Sex not provided"], [f"The study enrolls {want} participants only."],
                     missing=["Your sex (used only for studies that restrict by sex)"])
        else:
            e = Eval("true" if facts.sex == want else "false", [facts.sex.title()],
                     [f"The study enrolls {want} participants only."])
        rows.append(_row(len(rows), 0, "inclusion", f"Sex: {want} only (registry)", "clinical", e, {"type": "sex", "value": want},
                         None, criterion_ev(f"Sex: {sex}"), source="registry_field"))

    node_values: dict[int, Eval] = {}

    def visit(node: CriterionNode, depth: int) -> Eval:
        cat, req = recognized.get(node.ordinal, ("unparsed", None))
        position = len(rows)
        rows.append(None)  # placeholder to keep parent before children
        if node.is_group or (node.children and cat in ("group", "unparsed")):
            child_evals = [visit(c, depth + 1) for c in node.children]
            relevant = [ce for ce, c in zip(child_evals, node.children, strict=False)
                        if recognized.get(c.ordinal, ("", None))[0] not in ("administrative", "investigator")]
            if not relevant:
                e = Eval("confirm", explanation=["Confirmed by the study team."])
                category = "administrative"
            else:
                val = combine_any(relevant) if node.logic == "any" else combine_all(relevant)
                e = Eval(val, explanation=[_group_expl(node.logic, val, node.kind)])
                category = "clinical"
            rows[position] = _row(position, depth, node.kind, node.text, category, e, {"type": node.logic, "group": True},
                                  node.cohort, criterion_ev(node.text), is_group=True)
        else:
            if cat == "unparsed":
                e = Eval("review", [], ["This criterion couldn't be interpreted automatically; the study team will review it."],
                         questions=[f"Can you clarify this requirement: “{_short(node.text, 120)}”?"])
            elif cat in ("administrative", "investigator"):
                e = Eval("confirm", [], ["Confirmed by the study team" + (
                    " based on the investigator's judgment." if cat == "investigator" else " (consent, logistics or "
                    "study procedures).")])
            else:
                e = evaluate(req, facts, node.kind)
            if node.children:  # a criterion with its own requirement plus refinements
                child_evals = [visit(c, depth + 1) for c in node.children]
                e = Eval(combine_all([e, *child_evals]), e.patient_info, e.explanation, e.evidence, e.missing, e.questions)
            rows[position] = _row(position, depth, node.kind, node.text, cat, e, req, node.cohort, criterion_ev(node.text))
        node_values[node.ordinal] = e
        return e

    top_nodes: list[tuple[CriterionNode, int]] = []
    for node in parsed.inclusion + parsed.exclusion:
        visit(node, 0)
    for r in rows:
        assert r is not None
    for i, r in enumerate(rows):
        r.position = i

    # Classification (per cohort)
    cohorts = parsed.cohorts or [None]
    best: tuple[int, EC, list[CriterionResult], str | None] | None = None
    rank = {EC.potentially_eligible: 0, EC.uncertain: 1, EC.potentially_ineligible: 2}
    for c in cohorts:
        applicable = [r for r in rows if r.depth == 0 and (r.cohort is None or r.cohort == c)]
        cls = _classify(applicable)
        if best is None or rank[cls] < best[0]:
            best = (rank[cls], cls, applicable, c)
    assert best is not None
    _, classification, applicable, best_cohort = best

    del top_nodes
    return _summarize(trial, classification, applicable, rows, parsed, best_cohort, facts)


def _row(position, depth, kind, text, category, e: Eval, req, cohort, crit_ev, is_group=False, source="registry_text"):
    return CriterionResult(
        position=position,
        depth=depth,
        kind=kind,
        text=text,
        category=category if category != "group" else "clinical",
        outcome=_outcome(e.value, kind, category),
        patient_information="; ".join(e.patient_info) if e.patient_info else "—",
        explanation=" ".join(e.explanation),
        evidence=[crit_ev, *e.evidence],
        requirement=req,
        cohort=cohort,
        missing=list(e.missing),
        questions=list(e.questions),
        is_group=is_group,
        source=source,
    )


def _group_expl(logic: str, value: str, kind: str) -> str:
    if logic == "any":
        return {"true": "At least one of the options below appears to apply.",
                "false": "None of the options below appear to apply."}.get(
            value, "At least one option below can't be evaluated yet, and none is confirmed.")
    return {"true": "All items below appear to apply.", "false": "At least one item below does not appear to apply."}.get(
        value, "Some items below can't be evaluated yet.")


def _classify(applicable: list[CriterionResult]) -> EC:
    clinical = [r for r in applicable if r.category in ("clinical", "unparsed")]
    if any(r.outcome == O.not_satisfied for r in clinical):
        return EC.potentially_ineligible
    if any(r.kind == "inclusion" and r.outcome in (O.unknown, O.needs_review, O.conflicting) for r in clinical):
        return EC.uncertain
    if any(r.kind == "exclusion" and r.outcome == O.conflicting for r in clinical):
        return EC.uncertain
    return EC.potentially_eligible


def _short(text: str, n: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _summarize(trial, cls: EC, applicable, rows, parsed: ParsedCriteria, best_cohort, facts: PatientFacts) -> AssessmentResult:
    conflicts = [r for r in applicable if r.category in ("clinical", "unparsed") and r.outcome == O.not_satisfied]
    open_inc = [r for r in applicable if r.kind == "inclusion" and r.category in ("clinical", "unparsed")
                and r.outcome in (O.unknown, O.needs_review, O.conflicting)]
    met_inc = [r for r in applicable if r.kind == "inclusion" and r.outcome == O.satisfied]
    open_exc = [r for r in applicable if r.kind == "exclusion" and r.category == "clinical"
                and r.outcome in (O.unknown, O.needs_review)]

    def reason(r: CriterionResult, verb: str) -> str:
        return f"{verb}: “{_short(r.text)}”"

    if cls == EC.potentially_ineligible:
        lead = ("At least one requirement appears to conflict with the information in your profile. "
                "If your information is incomplete or has changed, update your profile.")
        key = [reason(r, "Inclusion not met" if r.kind == "inclusion" else "Exclusion appears to apply") for r in conflicts]
    elif cls == EC.uncertain:
        lead = "Some key requirements can't be evaluated yet because information is missing or the criterion is ambiguous."
        key = [reason(r, "Can't evaluate yet") for r in open_inc]
    else:
        lead = ("Based on the information you've provided, you may meet the key requirements listed in the registry. "
                "This is not a determination of eligibility.")
        key = [reason(r, "Appears met") for r in met_inc if r.source == "registry_text"][:4]
    summary = lead + " Final eligibility is always decided by the study team."

    missing: list[str] = []
    for r in open_inc + [r for r in applicable if r.kind == "exclusion" and r.outcome in (O.unknown, O.conflicting)]:
        for m in r.missing:
            if m not in missing:
                missing.append(m)
    # child rows' missing info
    for r in rows:
        if r.depth > 0 and r.outcome in (O.unknown, O.conflicting) and (r.cohort is None or r.cohort == best_cohort):
            for m in r.missing:
                if m not in missing:
                    missing.append(m)
    questions: list[str] = []
    for r in rows:
        if r.cohort is None or r.cohort == best_cohort:
            for q in r.questions:
                if q not in questions:
                    questions.append(q)

    caveats = []
    if parsed.partial_list:
        caveats.append("The registry lists only the main criteria; the full protocol has additional requirements.")
    if parsed.cohorts:
        caveats.append(f"This study enrolls separate groups ({', '.join(parsed.cohorts)}). The assessment uses the "
                       f"group that best matches your profile: {best_cohort}.")
    if facts.pending_review_count:
        caveats.append(f"{facts.pending_review_count} item(s) extracted from your documents are awaiting your review and "
                       "were not used.")
    if parsed.unstructured:
        caveats.append("The registry's criteria are not split into inclusion and exclusion sections.")

    counts: dict[str, int] = {}
    for r in applicable:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1

    return AssessmentResult(
        classification=cls,
        summary=summary,
        key_reasons=key[:5],
        missing_information=missing[:12],
        potential_exclusions=[_short(r.text, 90) for r in open_exc][:6],
        questions=questions[:8],
        criteria=rows,
        counts=counts,
        best_cohort=best_cohort,
        caveats=caveats,
    )


__all__ = ["assess", "AssessmentResult", "CriterionResult", "ENGINE_VERSION", "PARSER_VERSION", "parse_age"]
