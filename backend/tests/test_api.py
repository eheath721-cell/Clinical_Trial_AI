"""Application tests: auth, profiles, documents, matching, saved trials, inquiries, privacy."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from app.core import db as dbmod
from app.models import AuditEvent
from tests.conftest import Session, register

SYNTH = Path(__file__).resolve().parents[1] / "data" / "synthetic"


# ----------------------------------------------------------------------------- auth


def test_register_requires_consents(client):
    r = client.post("/api/auth/register", json={"email": "a@example.com", "password": "long enough pw",
                                               "accept_terms": True, "accept_privacy": True, "accept_health_data": False})
    assert r.status_code == 400


def test_login_logout_and_session(client):
    register(client, "b@example.com", "correct horse battery")
    s = Session(client)
    assert s.get("/api/auth/me").status_code == 200
    assert s.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"email": "b@example.com", "password": "wrong password"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"email": "b@example.com", "password": "correct horse battery"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").json()["email"] == "b@example.com"


def test_csrf_required_for_mutations(user):
    r = user.c.post("/api/profiles", json={"display_name": "No CSRF"})
    assert r.status_code == 403
    assert user.post("/api/profiles", json={"display_name": "With CSRF"}).status_code == 201


def test_unauthenticated_access_denied(client):
    assert client.get("/api/profiles").status_code == 401


def test_profiles_are_isolated_between_accounts(client):
    a = register(client, "owner@example.com")
    pid = a.post("/api/demo-profiles/lpa").json()["id"]
    a.post("/api/auth/logout")
    b = register(client, "intruder@example.com")
    assert b.get(f"/api/profiles/{pid}").status_code == 404
    assert b.get(f"/api/profiles/{pid}/matches").status_code == 404
    assert b.post(f"/api/profiles/{pid}/labs", json={"analyte": "lpa", "value_numeric": 1, "unit": "nmol/L"}).status_code == 404


# ----------------------------------------------------------------------------- profile & provenance


def test_demo_profile_matches_brief(user):
    p = user.post("/api/demo-profiles/lpa").json()
    assert p["is_synthetic"] and p["age"] == 24 and p["city"] == "Lubbock"
    lpa = p["labs"][0]
    assert (lpa["value_numeric"], lpa["unit"], lpa["provenance"]) == (185, "nmol/L", "patient_reported")
    assert {(c["concept"], c["assertion"]) for c in p["conditions"]} == {("mi", "absent"), ("cad", "absent")}
    assert p["medications"][0]["status"] == "not_current"


def test_screener_not_sure_records_nothing(user):
    pid = user.post("/api/profiles", json={"display_name": "Test"}).json()["id"]
    p = user.post(f"/api/profiles/{pid}/screener", json={"answers": {"stroke": "absent", "diabetes": "unknown"}}).json()
    concepts = {c["concept"]: c["assertion"] for c in p["conditions"]}
    assert concepts == {"stroke": "absent"}  # "not sure" is stored as no fact (unknown), never as a guess


def test_location_geocoded_from_zip(user):
    pid = user.post("/api/profiles", json={"display_name": "Geo"}).json()["id"]
    p = user.patch(f"/api/profiles/{pid}", json={"postal_code": "79401"}).json()
    assert p["city"] == "Lubbock" and p["state"] == "TX" and p["has_coordinates"]


def test_lab_units_preserved(user):
    pid = user.post("/api/profiles", json={"display_name": "Units"}).json()["id"]
    p = user.post(f"/api/profiles/{pid}/labs", json={"analyte": "lpa", "value_numeric": 72, "unit": "mg/dl",
                                                     "collected_on": "2026-05-01"}).json()
    assert p["labs"][0]["unit"] == "mg/dL" and p["labs"][0]["value_numeric"] == 72


# ----------------------------------------------------------------------------- documents


def test_upload_review_and_accept_document(user):
    pid = user.post("/api/demo-profiles/lpa").json()["id"]
    with open(SYNTH / "synthetic_lipid_panel.pdf", "rb") as fh:
        r = user.c.post(f"/api/profiles/{pid}/documents", files={"file": ("lab.pdf", fh, "application/pdf")},
                        data={"doc_type": "lab_report"}, headers={"x-csrf-token": user.c.cookies.get("tc_csrf")})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["status"] == "extracted" and doc["filename"] == "lab.pdf"
    lpa = next(f for f in doc["facts"] if f["payload"].get("analyte") == "lpa")
    assert lpa["review_status"] == "pending"
    assert lpa["payload"]["unit"] == "nmol/L" and lpa["payload"]["collected_on"] == "2026-09-14"
    assert lpa["source_page"] == 1 and "185" in lpa["source_excerpt"]

    # Unreviewed facts are not used; the assessment says so.
    user.post(f"/api/profiles/{pid}/matches/refresh")
    a = user.get(f"/api/profiles/{pid}/trials/NCT07157774/assessment").json()["assessment"]
    assert a["pending_facts_count"] == len(doc["facts"])

    acc = user.post(f"/api/profiles/{pid}/extracted-facts/{lpa['id']}/accept")
    assert acc.status_code == 200 and acc.json()["review_status"] == "accepted"
    prof = user.get(f"/api/profiles/{pid}").json()
    extracted = [lab for lab in prof["labs"] if lab["provenance"] == "document_extracted"]
    assert extracted and extracted[0]["source_document_id"] == doc["id"] and extracted[0]["source_page"] == 1
    hdl = next(f for f in doc["facts"] if f["payload"].get("analyte") == "hdl_c")
    assert user.post(f"/api/profiles/{pid}/extracted-facts/{hdl['id']}/reject").json()["review_status"] == "rejected"

    # Download returns the decrypted original; file on disk is encrypted.
    file_resp = user.get(f"/api/profiles/{pid}/documents/{doc['id']}/file")
    assert file_resp.content[:5] == b"%PDF-"
    import os

    stored = list(Path(os.environ["DOCUMENT_STORAGE_DIR"]).iterdir())
    assert stored and all(not p.read_bytes().startswith(b"%PDF") for p in stored)


def test_family_history_not_attributed_to_patient(user):
    pid = user.post("/api/profiles", json={"display_name": "Note"}).json()["id"]
    with open(SYNTH / "synthetic_clinic_note.pdf", "rb") as fh:
        doc = user.c.post(f"/api/profiles/{pid}/documents", files={"file": ("note.pdf", fh, "application/pdf")},
                          data={"doc_type": "physician_note"},
                          headers={"x-csrf-token": user.c.cookies.get("tc_csrf")}).json()
    mi = [f for f in doc["facts"] if f["payload"].get("concept") == "mi"]
    assert mi and all(f["payload"]["assertion"] == "absent" for f in mi)  # "No history of MI"; father's MI skipped
    assert not any(f["payload"].get("concept") == "hypertension" for f in doc["facts"])  # mother's HTN skipped
    assert any("family-history" in m for m in doc["extraction_methods"])


def test_rejects_non_pdf_upload(user):
    pid = user.post("/api/profiles", json={"display_name": "X"}).json()["id"]
    r = user.c.post(f"/api/profiles/{pid}/documents", files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")},
                    headers={"x-csrf-token": user.c.cookies.get("tc_csrf")})
    assert r.status_code == 415


# ----------------------------------------------------------------------------- matching, saving, comparing, enrollment


def test_end_to_end_lpa_journey(user):
    pid = user.post("/api/demo-profiles/lpa").json()["id"]
    summary = user.post(f"/api/profiles/{pid}/matches/refresh").json()
    assert summary["data_source"] == "snapshot" and summary["assessed"] >= 8
    assert "lipoprotein(a)" in [t.lower() for t in summary["plan"]["direct_terms"]]
    assert "olpasiran" in summary["plan"]["drug_terms"]

    m = user.get(f"/api/profiles/{pid}/matches").json()
    ncts = {i["trial"]["nct_id"] for i in m["items"]}
    assert {"NCT07157774", "NCT07136012", "NCT07614984"} <= ncts
    # active-not-recruiting trials hidden by default
    assert "NCT06292013" not in ncts
    assert "NCT06292013" in {i["trial"]["nct_id"] for i in
                             user.get(f"/api/profiles/{pid}/matches?include_inactive=true").json()["items"]}
    # recruitment status filter
    only_nyr = user.get(f"/api/profiles/{pid}/matches?status=NOT_YET_RECRUITING").json()["items"]
    assert only_nyr and all(i["trial"]["status"] == "NOT_YET_RECRUITING" for i in only_nyr)
    # distance: OCEAN(a)-PreEvent has a Lubbock site
    pre = next(i for i in m["items"] if i["trial"]["nct_id"] == "NCT07136012")
    assert pre["assessment"]["nearest_site"]["city"] == "Lubbock"
    assert pre["assessment"]["nearest_site"]["distance_miles"] < 10
    assert pre["assessment"]["classification"] == "potentially_ineligible"
    near = user.get(f"/api/profiles/{pid}/matches?max_distance=50").json()["items"]
    assert all(i["assessment"]["nearest_site"]["distance_miles"] <= 50 for i in near)

    detail = user.get(f"/api/profiles/{pid}/trials/NCT07157774/assessment").json()
    assert detail["assessment"]["classification"] == "uncertain"
    assert detail["trial"]["locations"][0]["distance_miles"] is not None
    assert any(c["outcome"] == "satisfied" and "Lp(a)" in c["text"] for c in detail["assessment"]["criteria"])

    assert user.post(f"/api/profiles/{pid}/saved", json={"nct_id": "NCT07157774"}).status_code == 201
    assert [s["nct_id"] for s in user.get(f"/api/profiles/{pid}/saved").json()] == ["NCT07157774"]

    cmp = user.get(f"/api/profiles/{pid}/compare?ids=NCT07157774,NCT07136012").json()["items"]
    assert len(cmp) == 2

    inq = user.post(f"/api/profiles/{pid}/inquiries", json={"nct_id": "NCT07157774"}).json()
    assert inq["status"] == "draft"
    assert "NCT07157774" in inq["email_subject"]
    assert "Lp(a)" in inq["email_body"] and "185" in inq["email_body"]
    assert "eligibility can only be determined by the study team" in inq["email_body"]
    assert inq["contact"]["source"]  # provenance of contact details
    assert inq["location"]["status_text"].startswith("listed in the registry as")
    tasks = user.get(f"/api/profiles/{pid}/tasks").json()
    assert len(tasks) == 2
    sent = user.post(f"/api/profiles/{pid}/inquiries/{inq['id']}/events", json={"status": "sent_by_user"}).json()
    assert sent["status"] == "sent_by_user" and sent["sent_at"]
    replied = user.post(f"/api/profiles/{pid}/inquiries/{inq['id']}/events",
                        json={"status": "response_received", "note": "Coordinator called"}).json()
    assert replied["last_response_at"] and len(replied["events"]) == 3
    done = user.patch(f"/api/profiles/{pid}/tasks/{tasks[0]['id']}", json={"status": "done"}).json()
    assert done["status"] == "done"


def test_inquiry_shares_only_selected_fields(user):
    pid = user.post("/api/demo-profiles/lpa").json()["id"]
    inq = user.post(f"/api/profiles/{pid}/inquiries", json={"nct_id": "NCT07136012", "shared_fields": []}).json()
    assert "185" not in inq["email_body"] and inq["shared_fields"] == []


def test_assessment_updates_when_profile_changes(user):
    pid = user.post("/api/demo-profiles/lpa").json()["id"]
    a1 = user.get(f"/api/profiles/{pid}/trials/NCT07614984/assessment").json()["assessment"]
    assert a1["classification"] == "potentially_ineligible"
    prof = user.get(f"/api/profiles/{pid}").json()
    med = prof["medications"][0]
    user.patch(f"/api/profiles/{pid}/medications/{med['id']}", json={"status": "unknown"})
    a2 = user.get(f"/api/profiles/{pid}/trials/NCT07614984/assessment").json()["assessment"]
    assert a2["classification"] == "uncertain"


def test_search_expands_terminology(user):
    r = user.get("/api/trials/search?q=Lp(a)").json()
    assert "Elevated lipoprotein(a)" in r["recognized_concepts"]
    assert "lipoprotein(a)" in [t.lower() for t in r["expanded_terms"]]
    assert {"NCT07157774", "NCT07614984"} <= {t["nct_id"] for t in r["results"]}
    assert all(t["status"] in ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION") for t in r["results"])


# ----------------------------------------------------------------------------- privacy


def test_delete_profile_and_account(user):
    pid = user.post("/api/demo-profiles/lpa").json()["id"]
    assert user.delete(f"/api/profiles/{pid}").status_code == 200
    assert user.get(f"/api/profiles/{pid}").status_code == 404
    pid2 = user.post("/api/demo-profiles/lpa").json()["id"]
    assert user.delete("/api/account").status_code == 200
    assert user.c.get("/api/auth/me").status_code == 401
    del pid2


def test_audit_log_contains_no_health_values(user):
    pid = user.post("/api/demo-profiles/lpa").json()["id"]
    user.post(f"/api/profiles/{pid}/labs", json={"analyte": "ldl_c", "value_numeric": 133, "unit": "mg/dL"})
    user.post(f"/api/profiles/{pid}/matches/refresh")
    with dbmod.session_factory()() as db:
        events = db.scalars(select(AuditEvent)).all()
    assert any(e.action == "fact.create" for e in events)
    blob = " ".join(f"{e.action} {e.resource_type} {e.meta}" for e in events)
    assert "133" not in blob and "185" not in blob and "nmol" not in blob


def test_application_logs_contain_no_health_values(user, caplog):
    caplog.set_level(logging.INFO)
    pid = user.post("/api/demo-profiles/lpa").json()["id"]
    user.post(f"/api/profiles/{pid}/labs", json={"analyte": "ldl_c", "value_numeric": 133, "unit": "mg/dL"})
    text = "\n".join(r.getMessage() + str(getattr(r, "path", "")) for r in caplog.records)
    assert "133" not in text and "patient@example.com" not in text
