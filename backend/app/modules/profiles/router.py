from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clinical.vocab import ANALYTES, CONCEPTS, analyte_index, get_concept, normalize_unit
from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db, utcnow
from app.core.deps import AuthContext, get_auth, profile_editor, profile_owner, profile_reader
from app.core.storage import delete_blob
from app.models import (
    BiomarkerResult,
    Condition,
    LabResult,
    Medication,
    PatientProfile,
    Procedure,
)
from app.models.enums import Assertion, MedicationStatus, Provenance, Relationship, Sex, Verification
from app.modules.eligibility.service import load_profile_full
from app.modules.trials.geo import lookup_zip

router = APIRouter(prefix="/api", tags=["profiles"])

SCREENER = ["mi", "stroke", "revascularization", "cad", "pad", "heart_failure", "diabetes", "hypertension", "ckd",
            "liver_disease", "cancer", "bleeding_disorder", "fh"]


# ----------------------------------------------------------------------------- serializers


def _prov(row) -> dict:
    return {
        "id": str(row.id), "provenance": row.provenance.value, "verification": row.verification.value,
        "source_document_id": str(row.source_document_id) if row.source_document_id else None,
        "source_page": row.source_page, "source_excerpt": row.source_excerpt,
        "extraction_method": row.extraction_method, "notes": row.notes,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def profile_out(p: PatientProfile) -> dict:
    today = date.today()
    age = None
    if p.date_of_birth:
        age = today.year - p.date_of_birth.year - ((today.month, today.day) < (p.date_of_birth.month, p.date_of_birth.day))
    elif p.age_years_reported is not None:
        age = p.age_years_reported
    return {
        "id": str(p.id), "display_name": p.display_name, "relationship": p.relationship_to_account.value,
        "is_synthetic": p.is_synthetic, "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "age_years_reported": p.age_years_reported, "age": age, "sex": p.sex.value,
        "can_become_pregnant": p.can_become_pregnant.value, "postal_code": p.postal_code, "city": p.city,
        "state": p.state, "country": p.country, "has_coordinates": p.latitude is not None,
        "travel_radius_miles": p.travel_radius_miles, "additional_info": p.additional_info,
        "onboarding_completed": p.onboarding_completed_at is not None,
        "conditions": [{**_prov(c), "concept": c.concept, "name": c.name, "assertion": c.assertion.value,
                        "onset_date": c.onset_date.isoformat() if c.onset_date else None,
                        "qualifiers": c.qualifiers or {}} for c in p.conditions],
        "labs": [{**_prov(lab), "analyte": lab.analyte, "display_name": lab.display_name,
                  "value_numeric": lab.value_numeric, "value_text": lab.value_text, "unit": lab.unit,
                  "reference_low": lab.reference_low, "reference_high": lab.reference_high,
                  "reference_text": lab.reference_text,
                  "collected_on": lab.collected_on.isoformat() if lab.collected_on else None} for lab in p.labs],
        "medications": [{**_prov(m), "concept": m.concept, "name": m.name, "status": m.status.value, "dose": m.dose,
                         "started_on": m.started_on.isoformat() if m.started_on else None,
                         "stopped_on": m.stopped_on.isoformat() if m.stopped_on else None} for m in p.medications],
        "procedures": [{**_prov(x), "concept": x.concept, "name": x.name, "assertion": x.assertion.value,
                        "performed_on": x.performed_on.isoformat() if x.performed_on else None} for x in p.procedures],
        "biomarkers": [{**_prov(b), "name": b.name, "result": b.result, "interpretation": b.interpretation,
                        "tested_on": b.tested_on.isoformat() if b.tested_on else None} for b in p.biomarkers],
    }


def profile_summary(p: PatientProfile) -> dict:
    return {"id": str(p.id), "display_name": p.display_name, "relationship": p.relationship_to_account.value,
            "is_synthetic": p.is_synthetic, "onboarding_completed": p.onboarding_completed_at is not None,
            "city": p.city, "state": p.state}


# ----------------------------------------------------------------------------- profile CRUD


class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    relationship: Relationship = Relationship.self_
    is_synthetic: bool = False


class ProfilePatch(BaseModel):
    display_name: str | None = Field(None, max_length=120)
    relationship: Relationship | None = None
    date_of_birth: date | None = None
    age_years_reported: int | None = Field(None, ge=0, le=120)
    sex: Sex | None = None
    can_become_pregnant: Assertion | None = None
    postal_code: str | None = Field(None, max_length=16)
    city: str | None = Field(None, max_length=120)
    state: str | None = Field(None, max_length=64)
    travel_radius_miles: int | None = Field(None, ge=5, le=5000)
    additional_info: str | None = Field(None, max_length=4000)
    onboarding_completed: bool | None = None


@router.get("/profiles")
def list_profiles(auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    rows = db.scalars(select(PatientProfile).where(PatientProfile.owner_user_id == auth.user.id)
                      .order_by(PatientProfile.created_at)).all()
    return [profile_summary(p) for p in rows]


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileIn, request: Request, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    if not body.is_synthetic and not get_settings().allow_real_phi and get_settings().environment != "test":
        # Real health information is not accepted until the deployment has the required safeguards.
        body.is_synthetic = True
    p = PatientProfile(owner_user_id=auth.user.id, display_name=body.display_name,
                       relationship_to_account=body.relationship, is_synthetic=body.is_synthetic)
    db.add(p)
    db.flush()
    audit.record(db, "profile.create", actor_id=auth.user.id, request=request, resource_type="profile",
                 resource_id=p.id, profile_id=p.id)
    db.commit()
    return profile_out(load_profile_full(db, p.id))


@router.get("/profiles/{profile_id}")
def get_profile(request: Request, profile: PatientProfile = Depends(profile_reader), auth: AuthContext = Depends(get_auth),
                db: Session = Depends(get_db)):
    audit.record(db, "profile.read", actor_id=auth.user.id, request=request, resource_type="profile",
                 resource_id=profile.id, profile_id=profile.id)
    db.commit()
    return profile_out(load_profile_full(db, profile.id))


@router.patch("/profiles/{profile_id}")
def patch_profile(body: ProfilePatch, request: Request, profile: PatientProfile = Depends(profile_editor),
                  auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "relationship" in data:
        profile.relationship_to_account = data.pop("relationship")
    if data.pop("onboarding_completed", None):
        profile.onboarding_completed_at = profile.onboarding_completed_at or utcnow()
    for k, v in data.items():
        setattr(profile, k, v)
    if "postal_code" in data:
        geo = lookup_zip(data["postal_code"]) if data["postal_code"] else None
        if geo:
            profile.city = data.get("city") or geo["city"]
            profile.state = data.get("state") or geo["state"]
            profile.latitude, profile.longitude = geo["latitude"], geo["longitude"]
        else:
            profile.latitude = profile.longitude = None
    audit.record(db, "profile.update", actor_id=auth.user.id, request=request, resource_type="profile",
                 resource_id=profile.id, profile_id=profile.id)
    db.commit()
    return profile_out(load_profile_full(db, profile.id))


@router.delete("/profiles/{profile_id}")
def delete_profile(request: Request, profile: PatientProfile = Depends(profile_owner), auth: AuthContext = Depends(get_auth),
                   db: Session = Depends(get_db)):
    full = load_profile_full(db, profile.id)
    for d in full.documents:
        delete_blob(d.storage_key)
    audit.record(db, "profile.delete", actor_id=auth.user.id, request=request, resource_type="profile",
                 resource_id=profile.id, meta={"count": len(full.documents)})
    db.delete(full)
    db.commit()
    return {"deleted": True}


# ----------------------------------------------------------------------------- clinical facts


class ConditionIn(BaseModel):
    name: str | None = Field(None, max_length=255)
    concept: str | None = None
    assertion: Assertion = Assertion.present
    onset_date: date | None = None
    qualifiers: dict | None = None
    provenance: Provenance = Provenance.patient_reported
    notes: str | None = Field(None, max_length=1000)


class LabIn(BaseModel):
    analyte: str
    value_numeric: float | None = None
    value_text: str | None = Field(None, max_length=120)
    unit: str | None = Field(None, max_length=32)
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: str | None = Field(None, max_length=120)
    collected_on: date | None = None
    provenance: Provenance = Provenance.patient_reported
    notes: str | None = Field(None, max_length=1000)


class MedicationIn(BaseModel):
    name: str | None = Field(None, max_length=255)
    concept: str | None = None
    status: MedicationStatus = MedicationStatus.current
    dose: str | None = Field(None, max_length=120)
    started_on: date | None = None
    stopped_on: date | None = None
    provenance: Provenance = Provenance.patient_reported
    notes: str | None = Field(None, max_length=1000)


class ProcedureIn(BaseModel):
    name: str | None = Field(None, max_length=255)
    concept: str | None = None
    assertion: Assertion = Assertion.present
    performed_on: date | None = None
    provenance: Provenance = Provenance.patient_reported
    notes: str | None = Field(None, max_length=1000)


class BiomarkerIn(BaseModel):
    name: str = Field(max_length=255)
    result: str = Field(max_length=255)
    interpretation: str | None = Field(None, max_length=255)
    tested_on: date | None = None
    provenance: Provenance = Provenance.patient_reported
    notes: str | None = Field(None, max_length=1000)


def _concept_or_400(code: str | None, kinds: tuple[str, ...]) -> None:
    if code is None:
        return
    c = get_concept(code)
    if c is None or c.kind not in kinds:
        raise HTTPException(400, f"Unknown concept '{code}'")


def _name_for(code: str | None, name: str | None) -> str:
    if name:
        return name
    c = get_concept(code) if code else None
    if c is None:
        raise HTTPException(400, "Provide a name or a known concept code")
    return c.label


COLLECTIONS = {
    "conditions": (Condition, ConditionIn), "labs": (LabResult, LabIn), "medications": (Medication, MedicationIn),
    "procedures": (Procedure, ProcedureIn), "biomarkers": (BiomarkerResult, BiomarkerIn),
}


def _build_row(collection: str, body, profile_id: uuid.UUID):
    data = body.model_dump()
    verification = Verification.confirmed
    if collection == "conditions":
        _concept_or_400(body.concept, ("condition", "event", "trait"))
        data["name"] = _name_for(body.concept, body.name)
    elif collection == "procedures":
        _concept_or_400(body.concept, ("procedure",))
        data["name"] = _name_for(body.concept, body.name)
    elif collection == "medications":
        _concept_or_400(body.concept, ("drug", "drug_class"))
        data["name"] = _name_for(body.concept, body.name)
    elif collection == "labs":
        a = analyte_index().get(body.analyte)
        if a is None:
            raise HTTPException(400, f"Unknown analyte '{body.analyte}'")
        data["display_name"] = a.label
        data["unit"] = normalize_unit(body.unit) if body.unit else None
        if body.value_numeric is None and not body.value_text:
            raise HTTPException(400, "Provide a value")
    model = COLLECTIONS[collection][0]
    return model(profile_id=profile_id, verification=verification, extraction_method="manual",
                 confirmed_at=utcnow(), **data)


_ENUM_FIELDS = {"status": MedicationStatus, "assertion": Assertion, "provenance": Provenance,
                "verification": Verification}
_DATE_FIELDS = {"onset_date", "collected_on", "started_on", "stopped_on", "performed_on", "tested_on"}


def _register_collection(collection: str) -> None:
    """Explicit routes per collection (a wildcard segment would shadow other profile routes)."""
    model, schema = COLLECTIONS[collection]

    def add_fact(request: Request, payload: dict, profile: PatientProfile = Depends(profile_editor),
                 auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
        body = schema.model_validate(payload)
        row = _build_row(collection, body, profile.id)
        db.add(row)
        audit.record(db, "fact.create", actor_id=auth.user.id, request=request, resource_type=collection,
                     resource_id=row.id, profile_id=profile.id)
        db.commit()
        return profile_out(load_profile_full(db, profile.id))

    def update_fact(item_id: uuid.UUID, payload: dict, request: Request, profile: PatientProfile = Depends(profile_editor),
                    auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
        row = db.get(model, item_id)
        if row is None or row.profile_id != profile.id:
            raise HTTPException(404, "Not found")
        allowed = set(schema.model_fields) | {"verification"}
        for k, v in payload.items():
            if k not in allowed:
                continue
            try:
                if k == "unit" and v:
                    v = normalize_unit(v)
                elif k in _DATE_FIELDS and v:
                    v = date.fromisoformat(v)
                elif k in _ENUM_FIELDS and v is not None:
                    v = _ENUM_FIELDS[k](v)
            except ValueError as exc:
                raise HTTPException(400, f"Invalid value for {k}") from exc
            setattr(row, k, v)
        if payload.get("verification") == "confirmed":
            row.confirmed_at = utcnow()
        audit.record(db, "fact.update", actor_id=auth.user.id, request=request, resource_type=collection,
                     resource_id=row.id, profile_id=profile.id)
        db.commit()
        return profile_out(load_profile_full(db, profile.id))

    def delete_fact(item_id: uuid.UUID, request: Request, profile: PatientProfile = Depends(profile_editor),
                    auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
        row = db.get(model, item_id)
        if row is None or row.profile_id != profile.id:
            raise HTTPException(404, "Not found")
        db.delete(row)
        audit.record(db, "fact.delete", actor_id=auth.user.id, request=request, resource_type=collection,
                     resource_id=item_id, profile_id=profile.id)
        db.commit()
        return profile_out(load_profile_full(db, profile.id))

    base = f"/profiles/{{profile_id}}/{collection}"
    router.add_api_route(base, add_fact, methods=["POST"], status_code=201, name=f"add_{collection}")
    router.add_api_route(base + "/{item_id}", update_fact, methods=["PATCH"], name=f"update_{collection}")
    router.add_api_route(base + "/{item_id}", delete_fact, methods=["DELETE"], name=f"delete_{collection}")


for _c in COLLECTIONS:
    _register_collection(_c)


# ----------------------------------------------------------------------------- screener


class ScreenerIn(BaseModel):
    answers: dict[str, Assertion]  # concept -> present | absent | unknown
    lipid_lowering: MedicationStatus | None = None
    lpa_therapy: MedicationStatus | None = None


@router.post("/profiles/{profile_id}/screener")
def save_screener(body: ScreenerIn, request: Request, profile: PatientProfile = Depends(profile_editor),
                  auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Yes / No / Not sure answers. 'Not sure' removes any patient-reported answer (unknown is
    represented by the absence of a fact, never by a guess)."""
    full = load_profile_full(db, profile.id)
    for code, assertion in body.answers.items():
        c = get_concept(code)
        if c is None or code not in SCREENER:
            raise HTTPException(400, f"Unknown screener item '{code}'")
        model = Procedure if c.kind == "procedure" else Condition
        rows = full.procedures if c.kind == "procedure" else full.conditions
        for r in [r for r in rows if r.concept == code and r.provenance == Provenance.patient_reported
                  and r.extraction_method == "screener"]:
            db.delete(r)
        if assertion != Assertion.unknown:
            db.add(model(profile_id=profile.id, concept=code, name=c.label, assertion=assertion,
                         provenance=Provenance.patient_reported, verification=Verification.confirmed,
                         extraction_method="screener", confirmed_at=utcnow()))
    for code, status in (("lipid_lowering", body.lipid_lowering), ("lpa_targeted", body.lpa_therapy)):
        if status is None:
            continue
        for r in [r for r in full.medications if r.concept == code and r.extraction_method == "screener"]:
            db.delete(r)
        if status != MedicationStatus.unknown:
            db.add(Medication(profile_id=profile.id, concept=code, name=get_concept(code).label, status=status,
                              provenance=Provenance.patient_reported, verification=Verification.confirmed,
                              extraction_method="screener", confirmed_at=utcnow()))
    audit.record(db, "profile.screener", actor_id=auth.user.id, request=request, resource_type="profile",
                 resource_id=profile.id, profile_id=profile.id, meta={"count": len(body.answers)})
    db.commit()
    return profile_out(load_profile_full(db, profile.id))


# ----------------------------------------------------------------------------- demo


@router.post("/demo-profiles/lpa", status_code=201)
def create_demo_profile(request: Request, auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Creates the SYNTHETIC elevated-Lp(a) demonstration patient described in the product brief."""
    today = date.today()
    dob = date(today.year - 24, 3, 2) if (today.month, today.day) >= (3, 2) else date(today.year - 25, 3, 2)
    geo = lookup_zip("79401") or {}
    p = PatientProfile(owner_user_id=auth.user.id, display_name="Alex (synthetic demo)", is_synthetic=True,
                       relationship_to_account=Relationship.self_, date_of_birth=dob, postal_code="79401",
                       city=geo.get("city", "Lubbock"), state=geo.get("state", "TX"), latitude=geo.get("latitude"),
                       longitude=geo.get("longitude"), travel_radius_miles=250, onboarding_completed_at=utcnow(),
                       additional_info="Synthetic test data - not a real patient.")
    db.add(p)
    db.flush()
    common = dict(provenance=Provenance.patient_reported, verification=Verification.confirmed,
                  extraction_method="manual", confirmed_at=utcnow())
    db.add(LabResult(profile_id=p.id, analyte="lpa", display_name=analyte_index()["lpa"].label, value_numeric=185,
                     unit="nmol/L", notes="Synthetic demo value", **common))
    db.add(Condition(profile_id=p.id, concept="mi", name=get_concept("mi").label, assertion=Assertion.absent,
                     notes="No documented history of myocardial infarction", **common))
    db.add(Condition(profile_id=p.id, concept="cad", name=get_concept("cad").label, assertion=Assertion.absent,
                     notes="No documented coronary artery disease", **common))
    db.add(Medication(profile_id=p.id, concept="lipid_lowering", name=get_concept("lipid_lowering").label,
                      status=MedicationStatus.not_current, notes="No current lipid-lowering medication", **common))
    audit.record(db, "profile.create_demo", actor_id=auth.user.id, request=request, resource_type="profile",
                 resource_id=p.id, profile_id=p.id)
    db.commit()
    return profile_out(load_profile_full(db, p.id))


# ----------------------------------------------------------------------------- vocabulary


@router.get("/vocab")
def vocab():
    return {
        "screener": [{"concept": c, "label": get_concept(c).label, "question": get_concept(c).patient_question}
                     for c in SCREENER],
        "conditions": [{"code": c.code, "label": c.label} for c in CONCEPTS if c.kind in ("condition", "event")],
        "procedures": [{"code": c.code, "label": c.label} for c in CONCEPTS if c.kind == "procedure"],
        "medications": [{"code": c.code, "label": c.label} for c in CONCEPTS if c.kind in ("drug", "drug_class")],
        "analytes": [{"code": a.code, "label": a.label, "units": list(a.units), "convertible": a.convertible,
                      "note": a.non_convertible_reason} for a in ANALYTES],
    }
