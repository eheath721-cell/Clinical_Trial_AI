"""Criteria parsing, recognizers, trial search/expansion, normalization and extraction."""

from __future__ import annotations

from pathlib import Path

from app.clinical.vocab import convert, find_concepts
from app.modules.documents.extraction import document_pages, extract_candidates
from app.modules.eligibility.criteria_parser import parse_criteria
from app.modules.eligibility.llm_interpreter import Atomic, Interpretation, Threshold, validate
from app.modules.eligibility.recognizers import recognize
from app.modules.trials.classify import classify_study
from app.modules.trials.normalize import from_ctgov_v2
from app.modules.trials.search import build_search_plan
from app.modules.trials.sources import SearchQuery, SnapshotSource
from tests.conftest import demo_patient

SYNTH = Path(__file__).resolve().parents[1] / "data" / "synthetic"


def test_parser_nesting_and_any_logic():
    p = parse_criteria(SnapshotSource().get("NCT07157774").eligibility_text)
    group = next(n for n in p.inclusion if n.text.startswith("Meet one of"))
    assert group.is_group and group.logic == "any" and len(group.children) == 2
    nested = group.children[1]
    assert nested.is_group and len(nested.children) == 4


def test_parser_cohorts_and_partial_lists():
    snap = SnapshotSource()
    assert parse_criteria(snap.get("NCT06980428").eligibility_text).cohorts == [
        "healthy participants", "participants with dyslipidemia"]
    assert parse_criteria(snap.get("NCT07614984").eligibility_text).partial_list


def test_recognizer_thresholds_and_units():
    cat, req = recognize("Have Lipoprotein(a) [Lp(a)] ≥175 nanomoles per liter (nmol/L).", "inclusion")
    assert req["thresholds"] == [{"op": ">=", "value": 175.0, "unit": "nmol/L"}]
    _, req = recognize("screening Lp(a) must be ≥75 nmol/L or ≥30 mg/dL", "inclusion")
    assert req["combine"] == "any" and {t["unit"] for t in req["thresholds"]} == {"nmol/L", "mg/dL"}


def test_recognizer_does_not_read_risk_as_diagnosis():
    _, req = recognize("Participants with no clinical history of atherosclerotic cardiovascular disease (ASCVD) and a "
                       "10-year ASCVD risk estimated as low", "inclusion")
    conds = [i for i in req["items"] if i["type"] == "condition"]
    assert conds == [{"type": "condition", "concept": "ascvd", "negated": True}]


def test_recognizer_umbrella_event_with_window():
    _, req = recognize("Have experienced a major cardiovascular event or surgery, such as heart attack, stroke, or "
                       "procedure to restore blood flow to the heart, within 90 days prior to screening", "exclusion")
    assert req == {"type": "condition", "concept": "ascvd_event", "negated": False, "window_days": 90}


def test_unrecognized_criterion_is_flagged_not_guessed():
    assert recognize("Undergoing clinically indicated cardiac CT", "inclusion") == ("unparsed", None)


def test_related_terminology_found():
    hits = {m.code for m in find_concepts("Hyperlipoproteinemia (a); Atherosclerotic Cardiovascular Disease (ASCVD)")}
    assert {"elevated_lpa", "ascvd"} <= hits


def test_search_plan_expands_lpa_to_related_and_drugs():
    profile = type("P", (), {"latitude": 33.58, "longitude": -101.86, "travel_radius_miles": 250, "conditions": []})()
    plan = build_search_plan(profile, demo_patient())
    assert "lipoprotein(a)" in [t.lower() for t in plan.direct_terms]
    assert "pelacarsen" in plan.drug_terms and "atherosclerotic cardiovascular disease" in plan.related_terms
    assert {q.radius_miles for q in plan.queries()} == {None, 250}  # broad related query restricted by distance


def test_snapshot_search_status_filter():
    snap = SnapshotSource()
    rec = snap.search(SearchQuery(condition_terms=["lipoprotein(a)"], statuses=["RECRUITING"]))
    assert rec and all(r.overall_status == "RECRUITING" for r in rec)
    allr = snap.search(SearchQuery(condition_terms=["lipoprotein(a)"], statuses=[]))
    assert any(r.overall_status == "ACTIVE_NOT_RECRUITING" for r in allr)


def test_study_category_distinguishes_outcomes_from_biomarker_trials():
    snap = SnapshotSource()
    assert classify_study(snap.get("NCT07157774"))["code"] == "cv_outcomes"
    assert classify_study(snap.get("NCT07614984"))["code"] == "biomarker"
    assert classify_study(snap.get("NCT07293260"))["code"] == "imaging"
    assert classify_study(snap.get("NCT06610669"))["code"] == "observational"


def test_ctgov_v2_mapping():
    """Schema-shaped fixture for the live API adapter (field names per the v2 data model)."""
    study = {"protocolSection": {
        "identificationModule": {"nctId": "NCT99999999", "briefTitle": "Example", "acronym": "EX"},
        "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-10-20"},
                         "startDateStruct": {"date": "2026-01"}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example Sponsor"}},
        "conditionsModule": {"conditions": ["Lipoprotein(a)"], "keywords": ["Lp(a)"]},
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE2"], "enrollmentInfo": {"count": 100}},
        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Drug X"}]},
        "eligibilityModule": {"eligibilityCriteria": "Inclusion Criteria:\n\n* Age ≥ 18 years", "sex": "ALL",
                              "minimumAge": "18 Years", "healthyVolunteers": False},
        "contactsLocationsModule": {
            "centralContacts": [{"name": "Central Desk", "phone": "555-0100", "email": "trial@example.test"}],
            "locations": [{"facility": "Site A", "city": "Lubbock", "state": "Texas", "country": "United States",
                           "status": "RECRUITING", "geoPoint": {"lat": 33.59, "lon": -101.85},
                           "contacts": [{"name": "Coordinator", "role": "CONTACT", "email": "site@example.test"}]}]},
    }}
    r = from_ctgov_v2(study, "2026-11-02")
    assert r.last_update_posted == "2026-10-20" and r.data_source == "live" and not r.field_gaps
    assert r.locations[0].geo_source == "registry" and r.locations[0].contacts[0].email == "site@example.test"
    assert r.central_contacts[0].phone == "555-0100"


def test_lpa_units_not_convertible_but_ldl_is():
    assert convert("lpa", 100, "mg/dL", "nmol/L") is None
    assert abs(convert("ldl_c", 2.5, "mmol/L", "mg/dL") - 96.675) < 0.01


def test_extraction_from_synthetic_lab_report():
    data = (SYNTH / "synthetic_lipid_panel.pdf").read_bytes()
    r = extract_candidates(document_pages(data, "application/pdf"))
    lpa = next(c for c in r.candidates if c.payload.get("analyte") == "lpa")
    assert lpa.payload["value_numeric"] == 185 and lpa.payload["unit"] == "nmol/L"
    assert lpa.payload["reference_high"] == 75 and lpa.payload["collected_on"] == "2026-09-14"
    assert not any(c.payload.get("analyte") == "hdl_c" and c.payload.get("value_numeric") != 52 for c in r.candidates)


def test_llm_interpretation_rejects_invented_thresholds():
    text = "Have LDL-C at least 100 mg/dL"
    good = Interpretation(interpretable=True, combine="all", items=[
        Atomic(type="lab", analyte="ldl_c", thresholds=[Threshold(op=">=", value=100, unit="mg/dL")])])
    bad = Interpretation(interpretable=True, combine="all", items=[
        Atomic(type="lab", analyte="ldl_c", thresholds=[Threshold(op=">=", value=130, unit="mg/dL")])])
    unknown_concept = Interpretation(interpretable=True, combine="all", items=[Atomic(type="condition", concept="made_up")])
    assert validate(good, text)["thresholds"][0]["value"] == 100
    assert validate(bad, text) is None
    assert validate(unknown_concept, text) is None
