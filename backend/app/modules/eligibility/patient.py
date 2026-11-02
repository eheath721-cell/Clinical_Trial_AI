"""Patient facts as seen by the eligibility engine.

Key rules (clinical-accuracy requirements):
  * Only CONFIRMED facts are used. Extracted-but-unreviewed facts are counted and surfaced,
    never silently used.
  * "No record" means UNKNOWN. A condition is ABSENT only when explicitly stated as absent
    (or every member of an umbrella concept is explicitly absent).
  * Diagnoses are never inferred from lab values (an elevated LDL-C is not "familial
    hypercholesterolemia"; an elevated Lp(a) is not "cardiovascular disease").
  * Contradictory facts produce CONFLICT, shown with both sources.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.clinical.vocab import concept_index, descendants, get_concept


@dataclass
class FactRef:
    fact_type: str
    fact_id: str | None
    label: str
    provenance: str
    verification: str = "confirmed"
    document_id: str | None = None
    document_name: str | None = None
    source_page: int | None = None
    source_excerpt: str | None = None
    recorded_on: str | None = None

    def as_evidence(self) -> dict[str, Any]:
        return {"kind": "patient_fact", **{k: v for k, v in self.__dict__.items() if v is not None}}


@dataclass
class ConditionFact:
    concept: str
    name: str
    assertion: str  # present | absent | unknown
    onset: date | None
    qualifiers: dict[str, Any]
    ref: FactRef


@dataclass
class LabFact:
    analyte: str
    name: str
    value: float | None
    value_text: str | None
    unit: str | None
    ref_low: float | None
    ref_high: float | None
    collected_on: date | None
    ref: FactRef


@dataclass
class MedFact:
    concept: str
    name: str
    status: str  # current | past | not_current | never | unknown
    started_on: date | None
    stopped_on: date | None
    ref: FactRef


@dataclass
class PatientFacts:
    as_of: date
    age_years: float | None = None
    age_basis: str | None = None
    age_ref: FactRef | None = None
    sex: str = "unknown"
    can_become_pregnant: str = "unknown"
    conditions: list[ConditionFact] = field(default_factory=list)  # includes procedures
    labs: list[LabFact] = field(default_factory=list)
    meds: list[MedFact] = field(default_factory=list)
    pending_review_count: int = 0

    # ------------------------------------------------------------------ conditions
    def concept_status(self, code: str, _depth: int = 0) -> tuple[str, list[ConditionFact]]:
        """Return (present|absent|unknown|conflict, supporting facts)."""
        family = {code} | descendants(code)
        facts = [f for f in self.conditions if f.concept in family and f.assertion != "unknown"]
        present = [f for f in facts if f.assertion == "present"]
        absent_direct = [f for f in self.conditions if f.concept == code and f.assertion == "absent"]
        # contradictions on the same concept
        for c in {f.concept for f in present}:
            neg = [f for f in self.conditions if f.concept == c and f.assertion == "absent"]
            if neg:
                return "conflict", [f for f in present if f.concept == c] + neg
        if present and absent_direct:
            return "conflict", present + absent_direct
        if present:
            return "present", present
        if absent_direct:
            return "absent", absent_direct
        # an explicitly absent ancestor implies absence ("no ASCVD" -> no MI)
        concept = get_concept(code)
        if concept:
            for anc in _ancestors_ordered(code):
                neg = [f for f in self.conditions if f.concept == anc and f.assertion == "absent"]
                if neg:
                    return "absent", neg
            if concept.absent_requires and _depth < 4:
                support: list[ConditionFact] = []
                for member in concept.absent_requires:
                    st, fs = self.concept_status(member, _depth + 1)
                    if st != "absent":
                        return "unknown", []
                    support.extend(fs)
                return "absent", support
        return "unknown", []

    def condition_facts(self, code: str) -> list[ConditionFact]:
        family = {code} | descendants(code)
        return [f for f in self.conditions if f.concept in family]

    # ------------------------------------------------------------------ medications
    def med_status(self, code: str) -> tuple[str, list[MedFact]]:
        """Return (current|past|not_current|never|unknown|conflict, facts)."""
        family = {code} | descendants(code)
        facts = [f for f in self.meds if f.concept in family and f.status != "unknown"]
        current = [f for f in facts if f.status == "current"]
        direct_neg = [f for f in self.meds if f.concept == code and f.status in ("never", "not_current")]
        if current and direct_neg:
            return "conflict", current + direct_neg
        if current:
            return "current", current
        past = [f for f in facts if f.status == "past"]
        if past:
            return "past", past
        if direct_neg:
            return ("never" if all(f.status == "never" for f in direct_neg) else "not_current"), direct_neg
        concept = get_concept(code)
        for anc in _ancestors_ordered(code):
            neg = [f for f in self.meds if f.concept == anc and f.status in ("never", "not_current", "past")]
            if neg:
                st = neg[0].status
                return ("not_current" if st == "past" else st), neg
        if concept and concept.absent_requires:
            sts, support = [], []
            for member in concept.absent_requires:
                st, fs = self.med_status(member)
                if st not in ("never", "not_current"):
                    return "unknown", []
                sts.append(st)
                support.extend(fs)
            return ("never" if all(s == "never" for s in sts) else "not_current"), support
        return "unknown", []

    # ------------------------------------------------------------------ labs
    def labs_for(self, analyte: str) -> list[LabFact]:
        rows = [lf for lf in self.labs if lf.analyte == analyte]
        return sorted(rows, key=lambda lf: (lf.collected_on is None, -(lf.collected_on.toordinal() if lf.collected_on else 0)))

    def fingerprint(self) -> str:
        payload = {
            "age": self.age_years, "sex": self.sex, "preg": self.can_become_pregnant,
            "c": sorted((f.concept, f.assertion, str(f.onset), json.dumps(f.qualifiers, sort_keys=True)) for f in self.conditions),
            "l": sorted((f.analyte, f.value, f.unit, str(f.collected_on), f.ref_high) for f in self.labs),
            "m": sorted((f.concept, f.status, str(f.started_on), str(f.stopped_on)) for f in self.meds),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _ancestors_ordered(code: str) -> list[str]:
    out: list[str] = []
    idx = concept_index()
    frontier = list(idx[code].parents) if code in idx else []
    while frontier:
        c = frontier.pop(0)
        if c not in out:
            out.append(c)
            frontier.extend(idx[c].parents if c in idx else ())
    return out


# ---------------------------------------------------------------------------- builder


def build_patient_facts(profile, as_of: date | None = None) -> PatientFacts:
    """Build facts from a PatientProfile ORM object (with relationships loaded)."""
    as_of = as_of or date.today()
    facts = PatientFacts(as_of=as_of)
    doc_names = {str(d.id): f"Document uploaded {d.created_at:%b %d, %Y}" for d in getattr(profile, "documents", [])}

    if profile.date_of_birth:
        dob = profile.date_of_birth
        years = as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))
        facts.age_years, facts.age_basis = float(years), "date_of_birth"
        facts.age_ref = FactRef("demographic", None, f"Date of birth on file (age {years})", "patient_reported")
    elif profile.age_years_reported is not None:
        facts.age_years, facts.age_basis = float(profile.age_years_reported), "reported_age"
        facts.age_ref = FactRef("demographic", None, f"Reported age {profile.age_years_reported}", "patient_reported")
    facts.sex = getattr(profile.sex, "value", profile.sex) or "unknown"
    facts.can_become_pregnant = getattr(profile.can_become_pregnant, "value", profile.can_become_pregnant) or "unknown"

    def ref(kind: str, row, label: str, recorded: date | None = None) -> FactRef:
        doc_id = str(row.source_document_id) if row.source_document_id else None
        return FactRef(
            fact_type=kind,
            fact_id=str(row.id),
            label=label,
            provenance=getattr(row.provenance, "value", row.provenance),
            verification=getattr(row.verification, "value", row.verification),
            document_id=doc_id,
            document_name=doc_names.get(doc_id) if doc_id else None,
            source_page=row.source_page,
            source_excerpt=row.source_excerpt,
            recorded_on=recorded.isoformat() if recorded else None,
        )

    def usable(row) -> bool:
        v = getattr(row.verification, "value", row.verification)
        return v == "confirmed"

    pending = 0
    for row in list(profile.conditions) + list(profile.procedures):
        if not usable(row):
            pending += getattr(row.verification, "value", row.verification) == "pending_review"
            continue
        assertion = getattr(row.assertion, "value", row.assertion)
        onset = getattr(row, "onset_date", None) or getattr(row, "performed_on", None)
        word = {"present": "Yes", "absent": "No", "unknown": "Unknown"}[assertion]
        label = f"{row.name}: {word}" + (f" (since {onset:%b %Y})" if onset else "")
        facts.conditions.append(ConditionFact(row.concept or "", row.name, assertion, onset,
                                              getattr(row, "qualifiers", None) or {}, ref("condition", row, label, onset)))
    for row in profile.labs:
        if not usable(row):
            pending += getattr(row.verification, "value", row.verification) == "pending_review"
            continue
        val = f"{row.value_numeric:g}" if row.value_numeric is not None else (row.value_text or "?")
        label = f"{row.display_name} {val} {row.unit or ''}".strip() + (
            f" (collected {row.collected_on:%b %d, %Y})" if row.collected_on else " (collection date not recorded)")
        facts.labs.append(LabFact(row.analyte, row.display_name, row.value_numeric, row.value_text, row.unit,
                                  row.reference_low, row.reference_high, row.collected_on,
                                  ref("lab", row, label, row.collected_on)))
    for row in profile.medications:
        if not usable(row):
            pending += getattr(row.verification, "value", row.verification) == "pending_review"
            continue
        status = getattr(row.status, "value", row.status)
        words = {"current": "currently taking", "past": "taken in the past", "not_current": "not currently taking",
                 "never": "never taken", "unknown": "unknown"}
        facts.meds.append(MedFact(row.concept or "", row.name, status, row.started_on, row.stopped_on,
                                  ref("medication", row, f"{row.name}: {words[status]}", row.started_on)))
    facts.pending_review_count = pending
    return facts
