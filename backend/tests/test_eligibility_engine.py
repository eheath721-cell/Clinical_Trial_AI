"""Eligibility engine tests: synthetic profiles with known outcomes, including against REAL
registry criteria from the offline snapshot."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.models.enums import CriterionOutcome as O
from app.models.enums import EligibilityClass as EC
from app.modules.eligibility.engine import assess
from app.modules.trials.sources import SnapshotSource
from tests.conftest import AS_OF, demo_patient, facts


def trial(text: str, min_age="18 Years", max_age=None, sex="ALL", nct="NCT00000000"):
    return SimpleNamespace(eligibility_text=text, minimum_age=min_age, maximum_age=max_age, sex=sex, nct_id=nct,
                           source_url=f"https://clinicaltrials.gov/study/{nct}")


@pytest.fixture(scope="module")
def snapshot():
    return SnapshotSource()


def row(result, startswith: str):
    for r in result.criteria:
        if r.text.startswith(startswith):
            return r
    raise AssertionError(f"criterion not found: {startswith}")


# ----------------------------------------------------------------------------- the Lp(a) demonstration patient


def test_demo_patient_outcomes_trial_is_uncertain_not_eligible(snapshot):
    """MOVE-Lp(a): Lp(a) threshold met, but the outcomes trial also needs prior ASCVD or high-risk features."""
    r = assess(snapshot.get("NCT07157774"), demo_patient())
    assert r.classification == EC.uncertain
    lpa = row(r, "Have Lp(a) ≥175")
    assert lpa.outcome == O.satisfied
    assert "185 nmol/L" in lpa.patient_information
    assert "close to the threshold" in lpa.explanation
    group = row(r, "Meet one of the following criteria")
    assert group.outcome == O.unknown
    assert any("cardiovascular event" in m.lower() for m in r.missing_information)


def test_demo_patient_primary_prevention_trial_with_lubbock_site_is_ineligible(snapshot):
    """OCEAN(a)-PreEvent requires age >=50 and Lp(a) >=200 nmol/L; the demo patient is 24 with 185 nmol/L."""
    r = assess(snapshot.get("NCT07136012"), demo_patient())
    assert r.classification == EC.potentially_ineligible
    assert row(r, "Age ≥50").outcome == O.not_satisfied
    assert row(r, "Lp(a)≥ 200").outcome == O.not_satisfied


def test_statin_required_trial_is_ineligible_when_not_on_statin(snapshot):
    r = assess(snapshot.get("NCT07614984"), demo_patient())
    assert r.classification == EC.potentially_ineligible
    statin = row(r, "Is receiving an optimized")
    assert statin.outcome == O.not_satisfied
    assert "not currently taking" in statin.explanation


def test_lpa_mg_dl_threshold_is_never_converted_from_nmol(snapshot):
    """AZD4954 states Lp(a) >= 30 mg/dL; a nmol/L result cannot be compared -> needs review, not met/not met."""
    r = assess(snapshot.get("NCT06980428"), demo_patient())
    lpa = row(r, "Participants must have elevated Lp(a) ≥ 30 mg/dL")
    assert lpa.outcome == O.needs_review
    assert "cannot be reliably converted" in lpa.explanation
    assert r.best_cohort == "healthy participants"  # dyslipidemia cohort requires statin therapy


def test_alternative_units_any_satisfied(snapshot):
    r = assess(snapshot.get("NCT07804160"), demo_patient())
    assert row(r, "For participants required to have elevated").outcome == O.satisfied


def test_threshold_without_number_is_not_invented(snapshot):
    """SYH2068 requires 'Elevated Lp(a)' with no published threshold."""
    r = assess(snapshot.get("NCT07640217"), demo_patient())
    elevated = row(r, "Elevated Lp(a)")
    assert elevated.outcome == O.needs_review
    assert "does not publish a numeric threshold" in elevated.explanation


def test_never_declares_eligibility(snapshot):
    for rec in snapshot.records.values():
        r = assess(rec, demo_patient())
        assert "study team" in r.summary.lower()
        assert "you are eligible" not in r.summary.lower()
        assert "you are not eligible" not in r.summary.lower()


# ----------------------------------------------------------------------------- satisfied / violated / missing


def test_established_ascvd_patient_meets_secondary_prevention_branch(snapshot):
    f = facts(age=62, labs=[("lpa", 240.0, "nmol/L", date(2026, 8, 1))],
              conditions=[("mi", "present", date(2021, 5, 1))])
    r = assess(snapshot.get("NCT07157774"), f)
    assert row(r, "Have had a prior atherosclerotic").outcome == O.satisfied
    assert row(r, "Meet one of the following").outcome == O.satisfied
    assert r.classification == EC.potentially_eligible
    assert r.potential_exclusions  # unknown exclusions are listed to confirm, not hidden


def test_event_outside_window_is_not_satisfied(snapshot):
    f = facts(age=62, labs=[("lpa", 240.0, "nmol/L", date(2026, 8, 1))], conditions=[("mi", "present", date(2010, 1, 1))])
    r = assess(snapshot.get("NCT07157774"), f)
    assert row(r, "Have had a prior atherosclerotic").outcome == O.not_satisfied


def test_event_without_date_is_unknown_for_windowed_criterion(snapshot):
    f = facts(age=62, labs=[("lpa", 240.0, "nmol/L", None)], conditions=[("mi", "present")])
    r = assess(snapshot.get("NCT07157774"), f)
    assert row(r, "Have had a prior atherosclerotic").outcome == O.unknown


def test_exclusion_applies(snapshot):
    f = facts(age=62, labs=[("lpa", 240.0, "nmol/L", None)], conditions=[("mi", "present", date(2021, 5, 1)),
                                                                        ("cancer", "present", date(2024, 2, 1))])
    r = assess(snapshot.get("NCT07157774"), f)
    assert row(r, "Have had cancer within 5 years").outcome == O.not_satisfied
    assert r.classification == EC.potentially_ineligible


def test_missing_information_is_not_a_negative_finding():
    t = trial("Inclusion Criteria:\n\n* History of myocardial infarction\n\nExclusion Criteria:\n\n* History of cancer")
    r = assess(t, facts(age=60))
    assert row(r, "History of myocardial").outcome == O.unknown
    assert row(r, "History of cancer").outcome == O.unknown
    assert r.classification == EC.uncertain


def test_explicit_absence_is_a_negative_finding():
    t = trial("Inclusion Criteria:\n\n* History of myocardial infarction\n\nExclusion Criteria:\n\n* History of cancer")
    r = assess(t, facts(age=60, conditions=[("mi", "absent"), ("cancer", "absent")]))
    assert row(r, "History of myocardial").outcome == O.not_satisfied
    assert row(r, "History of cancer").outcome == O.satisfied


def test_contradictory_information_is_flagged():
    t = trial("Inclusion Criteria:\n\n* Type 2 diabetes\n")
    f = facts(age=55, conditions=[("t2d", "present", None, {}, "document_extracted"),
                                  ("t2d", "absent", None, {}, "patient_reported")])
    r = assess(t, f)
    d = row(r, "Type 2 diabetes")
    assert d.outcome == O.conflicting
    provs = {e.get("provenance") for e in d.evidence if e["kind"] == "patient_fact"}
    assert provs == {"document_extracted", "patient_reported"}
    assert r.classification == EC.uncertain


def test_severity_qualifier_requires_more_information():
    t = trial("Inclusion Criteria:\n\n* Adults\n\nExclusion Criteria:\n\n* Have uncontrolled hypertension")
    r = assess(t, facts(age=50, conditions=[("hypertension", "present")]))
    assert row(r, "Have uncontrolled hypertension").outcome == O.needs_review
    r2 = assess(t, facts(age=50, conditions=[("hypertension", "present", None, {"controlled": True})]))
    assert row(r2, "Have uncontrolled hypertension").outcome == O.satisfied


# ----------------------------------------------------------------------------- clinical accuracy


def test_does_not_infer_diagnosis_from_single_lab():
    """An LDL-C of 250 mg/dL must NOT be treated as familial hypercholesterolemia; an HbA1c of 7%
    must NOT be treated as diabetes."""
    t = trial("Inclusion Criteria:\n\n* Diagnosis of familial hypercholesterolemia\n\nExclusion Criteria:\n\n"
              "* Type 2 diabetes")
    f = facts(age=40, labs=[("ldl_c", 250.0, "mg/dL", AS_OF), ("hba1c", 7.0, "%", AS_OF)])
    r = assess(t, f)
    assert row(r, "Diagnosis of familial").outcome == O.unknown
    assert row(r, "Type 2 diabetes").outcome == O.unknown


def test_elevated_lpa_alone_does_not_imply_cardiovascular_disease():
    t = trial("Inclusion Criteria:\n\n* Established atherosclerotic cardiovascular disease")
    r = assess(t, facts(age=40, labs=[("lpa", 300.0, "nmol/L", AS_OF)]))
    assert row(r, "Established").outcome == O.unknown


def test_units_preserved_and_ldl_converted_exactly():
    t = trial("Inclusion Criteria:\n\n* LDL-C ≥ 70 mg/dL")
    r = assess(t, facts(age=50, labs=[("ldl_c", 2.5, "mmol/L", AS_OF)]))  # 2.5 mmol/L ≈ 96.7 mg/dL
    ldl = row(r, "LDL-C")
    assert ldl.outcome == O.satisfied
    assert "2.5 mmol/L" in ldl.patient_information  # original unit shown
    assert "after unit conversion" in ldl.explanation


def test_old_lab_value_is_flagged_for_review():
    t = trial("Inclusion Criteria:\n\n* LDL-C ≥ 70 mg/dL")
    r = assess(t, facts(age=50, labs=[("ldl_c", 150.0, "mg/dL", date(2023, 1, 5))]))
    ldl = row(r, "LDL-C")
    assert ldl.outcome == O.needs_review
    assert "more than 12 months old" in ldl.explanation


def test_most_recent_lab_value_wins_and_earlier_value_is_mentioned():
    t = trial("Inclusion Criteria:\n\n* Lp(a) ≥ 175 nmol/L")
    f = facts(age=40, labs=[("lpa", 160.0, "nmol/L", date(2025, 1, 1)), ("lpa", 190.0, "nmol/L", date(2026, 9, 1))])
    lpa = row(assess(t, f), "Lp(a)")
    assert lpa.outcome == O.satisfied
    assert "earlier result" in lpa.explanation


def test_registry_sex_restriction():
    t = trial("Inclusion Criteria:\n\n* Adults", sex="FEMALE")
    assert assess(t, facts(age=40, sex="male")).classification == EC.potentially_ineligible
    assert assess(t, facts(age=40, sex="unknown")).classification == EC.uncertain


def test_every_evaluated_criterion_cites_the_trial_text_and_patient_sources(snapshot):
    r = assess(snapshot.get("NCT07157774"), demo_patient())
    for c in r.criteria:
        crit = [e for e in c.evidence if e["kind"] == "trial_criterion"]
        assert crit and crit[0]["source_url"].endswith("NCT07157774")
    lpa = row(r, "Have Lp(a) ≥175")
    assert any(e["kind"] == "patient_fact" and e["fact_type"] == "lab" for e in lpa.evidence)


def test_administrative_items_never_affect_classification():
    t = trial("Inclusion Criteria:\n\n* Able and willing to provide informed consent\n* Age ≥ 18 years")
    r = assess(t, facts(age=30))
    assert row(r, "Able and willing").outcome == O.confirm_with_team
    assert r.classification == EC.potentially_eligible
