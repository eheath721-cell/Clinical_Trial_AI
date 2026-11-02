from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core import audit
from app.core.db import get_db, utcnow
from app.core.deps import AuthContext, get_auth, profile_editor, profile_reader
from app.models import (
    ClinicalTrial,
    Document,
    EligibilityAssessment,
    EnrollmentInquiry,
    FollowUpTask,
    InquiryEvent,
    PatientProfile,
    SavedTrial,
    TrialLocation,
)
from app.models.enums import InquiryStatus, TaskStatus
from app.modules.eligibility.service import current_assessment, patient_facts
from app.modules.enrollment.service import (
    SITE_STATUS_TEXT,
    build_questions,
    contact_for,
    default_tasks,
    document_checklist,
    draft_email,
    shareable_facts,
)
from app.modules.trials.geo import haversine_miles
from app.modules.trials.router import STATUS_LABELS, trial_summary

router = APIRouter(prefix="/api/profiles/{profile_id}", tags=["enrollment"])


# ----------------------------------------------------------------------------- saved trials


class SaveIn(BaseModel):
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    note: str | None = Field(None, max_length=2000)


@router.get("/saved")
def list_saved(profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    rows = db.scalars(select(SavedTrial).where(SavedTrial.profile_id == profile.id).order_by(SavedTrial.created_at.desc())).all()
    out = []
    for s in rows:
        t = db.scalar(select(ClinicalTrial).where(ClinicalTrial.nct_id == s.nct_id).options(selectinload(ClinicalTrial.locations)))
        a = db.scalar(select(EligibilityAssessment).where(EligibilityAssessment.profile_id == profile.id,
                                                          EligibilityAssessment.nct_id == s.nct_id,
                                                          EligibilityAssessment.is_current.is_(True)))
        out.append({"nct_id": s.nct_id, "note": s.note, "saved_at": s.created_at.isoformat(),
                    "trial": trial_summary(t) if t else None,
                    "classification": a.classification.value if a else None,
                    "nearest_site": a.nearest_site if a else None})
    return out


@router.post("/saved", status_code=201)
def save_trial(body: SaveIn, request: Request, profile: PatientProfile = Depends(profile_editor),
               auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    trial, _a = current_assessment(db, profile, body.nct_id)
    if trial is None:
        raise HTTPException(404, "Trial not found")
    existing = db.scalar(select(SavedTrial).where(SavedTrial.profile_id == profile.id, SavedTrial.nct_id == trial.nct_id))
    if existing is None:
        db.add(SavedTrial(profile_id=profile.id, nct_id=trial.nct_id, note=body.note))
    elif body.note is not None:
        existing.note = body.note
    audit.record(db, "trial.save", actor_id=auth.user.id, request=request, resource_type="trial",
                 resource_id=trial.nct_id, profile_id=profile.id)
    db.commit()
    return {"saved": True, "nct_id": trial.nct_id}


@router.delete("/saved/{nct_id}")
def unsave_trial(nct_id: str, request: Request, profile: PatientProfile = Depends(profile_editor),
                 auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    s = db.scalar(select(SavedTrial).where(SavedTrial.profile_id == profile.id, SavedTrial.nct_id == nct_id.upper()))
    if s:
        db.delete(s)
        audit.record(db, "trial.unsave", actor_id=auth.user.id, request=request, resource_type="trial",
                     resource_id=nct_id, profile_id=profile.id)
        db.commit()
    return {"saved": False}


# ----------------------------------------------------------------------------- inquiries


class InquiryIn(BaseModel):
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    location_id: uuid.UUID | None = None
    shared_fields: list[str] | None = None  # keys from /inquiries/share-options


class InquiryPatch(BaseModel):
    email_subject: str | None = Field(None, max_length=500)
    email_body: str | None = Field(None, max_length=20000)
    notes: str | None = Field(None, max_length=5000)
    questions: list[str] | None = None
    document_checklist: list[dict] | None = None


class EventIn(BaseModel):
    status: InquiryStatus
    note: str | None = Field(None, max_length=2000)


def inquiry_out(i: EnrollmentInquiry) -> dict:
    loc = i.location
    return {
        "id": str(i.id), "nct_id": i.nct_id, "status": i.status.value, "trial": trial_summary(i.trial),
        "location": None if loc is None else {
            "id": str(loc.id), "facility": loc.facility, "city": loc.city, "state": loc.state, "country": loc.country,
            "status": loc.status, "status_text": SITE_STATUS_TEXT.get(loc.status or "", "Site status not listed"),
            "status_label": STATUS_LABELS.get(loc.status or "", "Status not listed")},
        "contact": i.contact_snapshot, "shared_fields": i.shared_fields or [], "email_subject": i.email_subject,
        "email_body": i.email_body, "questions": i.questions or [], "document_checklist": i.document_checklist or [],
        "sent_at": i.sent_at.isoformat() if i.sent_at else None,
        "last_response_at": i.last_response_at.isoformat() if i.last_response_at else None, "notes": i.notes,
        "created_at": i.created_at.isoformat(), "updated_at": i.updated_at.isoformat(),
        "events": [{"type": e.event_type, "note": e.note, "at": e.occurred_at.isoformat()} for e in i.events],
    }


def _load_inquiry(db: Session, profile: PatientProfile, inquiry_id: uuid.UUID) -> EnrollmentInquiry:
    i = db.scalar(select(EnrollmentInquiry).where(EnrollmentInquiry.id == inquiry_id, EnrollmentInquiry.profile_id == profile.id)
                  .options(selectinload(EnrollmentInquiry.events), selectinload(EnrollmentInquiry.trial)
                           .selectinload(ClinicalTrial.locations), selectinload(EnrollmentInquiry.location))
                  .execution_options(populate_existing=True))
    if i is None:
        raise HTTPException(404, "Inquiry not found")
    return i


@router.get("/inquiries/share-options")
def share_options(profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    return shareable_facts(patient_facts(db, profile))


@router.get("/inquiries")
def list_inquiries(profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    rows = db.scalars(select(EnrollmentInquiry).where(EnrollmentInquiry.profile_id == profile.id)
                      .order_by(EnrollmentInquiry.updated_at.desc())
                      .options(selectinload(EnrollmentInquiry.events), selectinload(EnrollmentInquiry.trial)
                               .selectinload(ClinicalTrial.locations), selectinload(EnrollmentInquiry.location))).all()
    return [inquiry_out(i) for i in rows]


@router.post("/inquiries", status_code=201)
def create_inquiry(body: InquiryIn, request: Request, profile: PatientProfile = Depends(profile_editor),
                   auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    trial, assessment = current_assessment(db, profile, body.nct_id)
    if trial is None:
        raise HTTPException(404, "Trial not found")
    location = None
    if body.location_id:
        location = db.get(TrialLocation, body.location_id)
        if location is None or location.nct_id != trial.nct_id:
            raise HTTPException(400, "Location does not belong to this trial")
    elif assessment and assessment.nearest_site and assessment.nearest_site.get("location_id"):
        location = db.get(TrialLocation, uuid.UUID(assessment.nearest_site["location_id"]))
    facts = patient_facts(db, profile)
    options = shareable_facts(facts)
    keys = body.shared_fields if body.shared_fields is not None else [o["key"] for o in options if o["default"]]
    shared = [o for o in options if o["key"] in keys]
    contact = contact_for(trial, location)
    questions = build_questions(assessment, location)
    dist = None
    if location is not None and location.latitude is not None and profile.latitude is not None:
        dist = haversine_miles((profile.latitude, profile.longitude), (location.latitude, location.longitude))
    subject, email = draft_email(trial, profile, location, contact, shared, questions, dist)
    doc_types = {d.doc_type.value for d in db.scalars(select(Document).where(Document.profile_id == profile.id)).all()}
    inquiry = EnrollmentInquiry(profile_id=profile.id, nct_id=trial.nct_id, location_id=location.id if location else None,
                                status=InquiryStatus.draft, contact_snapshot=contact, shared_fields=[s["key"] for s in shared],
                                email_subject=subject, email_body=email, questions=questions,
                                document_checklist=document_checklist(trial, assessment, doc_types))
    db.add(inquiry)
    db.flush()
    db.add(InquiryEvent(inquiry_id=inquiry.id, event_type="draft_created", note="Draft prepared for your review."))
    for title, due in default_tasks():
        db.add(FollowUpTask(profile_id=profile.id, inquiry_id=inquiry.id, title=f"{title} ({trial.acronym or trial.nct_id})",
                            due_on=due))
    if db.scalar(select(SavedTrial).where(SavedTrial.profile_id == profile.id, SavedTrial.nct_id == trial.nct_id)) is None:
        db.add(SavedTrial(profile_id=profile.id, nct_id=trial.nct_id))
    audit.record(db, "inquiry.create", actor_id=auth.user.id, request=request, resource_type="inquiry",
                 resource_id=inquiry.id, profile_id=profile.id, meta={"nct_id": trial.nct_id, "count": len(shared)})
    db.commit()
    return inquiry_out(_load_inquiry(db, profile, inquiry.id))


@router.get("/inquiries/{inquiry_id}")
def get_inquiry(inquiry_id: uuid.UUID, profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    return inquiry_out(_load_inquiry(db, profile, inquiry_id))


@router.patch("/inquiries/{inquiry_id}")
def patch_inquiry(inquiry_id: uuid.UUID, body: InquiryPatch, request: Request,
                  profile: PatientProfile = Depends(profile_editor), auth: AuthContext = Depends(get_auth),
                  db: Session = Depends(get_db)):
    i = _load_inquiry(db, profile, inquiry_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    if i.status == InquiryStatus.draft and (body.email_body is not None or body.email_subject is not None):
        i.status = InquiryStatus.ready
    audit.record(db, "inquiry.update", actor_id=auth.user.id, request=request, resource_type="inquiry",
                 resource_id=i.id, profile_id=profile.id)
    db.commit()
    return inquiry_out(_load_inquiry(db, profile, inquiry_id))


@router.post("/inquiries/{inquiry_id}/events")
def add_event(inquiry_id: uuid.UUID, body: EventIn, request: Request, profile: PatientProfile = Depends(profile_editor),
              auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Status changes are recorded by the user (e.g. 'I sent it', 'they replied')."""
    i = _load_inquiry(db, profile, inquiry_id)
    i.status = body.status
    if body.status == InquiryStatus.sent_by_user and i.sent_at is None:
        i.sent_at = utcnow()
    if body.status == InquiryStatus.response_received:
        i.last_response_at = utcnow()
        db.add(FollowUpTask(profile_id=profile.id, inquiry_id=i.id, title=f"Reply to the study team ({i.nct_id})",
                            due_on=date.today()))
    db.add(InquiryEvent(inquiry_id=i.id, event_type=body.status.value, note=body.note))
    audit.record(db, "inquiry.status", actor_id=auth.user.id, request=request, resource_type="inquiry",
                 resource_id=i.id, profile_id=profile.id, meta={"status": body.status.value})
    db.commit()
    return inquiry_out(_load_inquiry(db, profile, inquiry_id))


@router.delete("/inquiries/{inquiry_id}")
def delete_inquiry(inquiry_id: uuid.UUID, request: Request, profile: PatientProfile = Depends(profile_editor),
                   auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    i = _load_inquiry(db, profile, inquiry_id)
    db.delete(i)
    audit.record(db, "inquiry.delete", actor_id=auth.user.id, request=request, resource_type="inquiry",
                 resource_id=inquiry_id, profile_id=profile.id)
    db.commit()
    return {"deleted": True}


# ----------------------------------------------------------------------------- tasks


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    due_on: date | None = None
    inquiry_id: uuid.UUID | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(None, max_length=255)
    due_on: date | None = None
    status: TaskStatus | None = None


def task_out(t: FollowUpTask) -> dict:
    return {"id": str(t.id), "title": t.title, "due_on": t.due_on.isoformat() if t.due_on else None,
            "status": t.status.value, "inquiry_id": str(t.inquiry_id) if t.inquiry_id else None,
            "overdue": bool(t.due_on and t.status == TaskStatus.open and t.due_on < date.today())}


@router.get("/tasks")
def list_tasks(profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    rows = db.scalars(select(FollowUpTask).where(FollowUpTask.profile_id == profile.id)).all()
    rows = sorted(rows, key=lambda t: (t.status != TaskStatus.open, t.due_on or date.max))
    return [task_out(t) for t in rows]


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, profile: PatientProfile = Depends(profile_editor), db: Session = Depends(get_db)):
    t = FollowUpTask(profile_id=profile.id, title=body.title, due_on=body.due_on, inquiry_id=body.inquiry_id)
    db.add(t)
    db.commit()
    return task_out(t)


@router.patch("/tasks/{task_id}")
def patch_task(task_id: uuid.UUID, body: TaskPatch, profile: PatientProfile = Depends(profile_editor),
               db: Session = Depends(get_db)):
    t = db.get(FollowUpTask, task_id)
    if t is None or t.profile_id != profile.id:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    return task_out(t)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: uuid.UUID, profile: PatientProfile = Depends(profile_editor), db: Session = Depends(get_db)):
    t = db.get(FollowUpTask, task_id)
    if t is None or t.profile_id != profile.id:
        raise HTTPException(404, "Not found")
    db.delete(t)
    db.commit()
    return {"deleted": True}
