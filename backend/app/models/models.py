"""Relational schema.

Modules map to table groups:
  accounts      -> users, auth_sessions, consents, audit_events
  profiles      -> patient_profiles, profile_access, conditions, lab_results, medications,
                   procedures, biomarker_results
  documents     -> documents, extracted_facts
  trials        -> clinical_trials, trial_locations, trial_criteria
  eligibility   -> eligibility_assessments, criterion_evaluations
  enrollment    -> saved_trials, enrollment_inquiries, inquiry_events, follow_up_tasks
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, JSONType, utcnow
from app.models.enums import (
    Assertion,
    CriterionOutcome,
    DocumentStatus,
    DocumentType,
    EligibilityClass,
    FactType,
    InquiryStatus,
    MedicationStatus,
    ProfileAccessRole,
    Provenance,
    Relationship,
    ReviewStatus,
    Sex,
    TaskStatus,
    UserRole,
    Verification,
)


def _enum(e):
    return Enum(e, native_enum=False, length=32, values_callable=lambda x: [m.value for m in x], validate_strings=True)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


# ----------------------------------------------------------------------------- accounts


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole), default=UserRole.member)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user", cascade="all, delete-orphan")
    consents: Mapped[list[Consent]] = relationship(back_populates="user", cascade="all, delete-orphan")
    profiles: Mapped[list[PatientProfile]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class AuthSession(Base):
    """Server-side sessions (revocable). Only a SHA-256 of the token is stored."""

    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    user: Mapped[User] = relationship(back_populates="sessions")


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    consent_type: Mapped[str] = mapped_column(String(64))  # terms, privacy, health_data, ai_processing
    version: Mapped[str] = mapped_column(String(32))
    granted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    user: Mapped[User] = relationship(back_populates="consents")


class AuditEvent(Base):
    """Append-only audit trail. Never stores clinical values or free text."""

    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), default="success")
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType)


# ----------------------------------------------------------------------------- profiles


class PatientProfile(TimestampMixin, Base):
    """A person whose health information is managed. An account may manage several
    profiles (e.g. a caregiver managing a parent's and a child's profiles)."""

    __tablename__ = "patient_profiles"
    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    relationship_to_account: Mapped[Relationship] = mapped_column(_enum(Relationship), default=Relationship.self_)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    date_of_birth: Mapped[date | None] = mapped_column(Date)
    age_years_reported: Mapped[int | None] = mapped_column(Integer)  # if DOB not shared
    sex: Mapped[Sex] = mapped_column(_enum(Sex), default=Sex.unknown)
    can_become_pregnant: Mapped[Assertion] = mapped_column(_enum(Assertion), default=Assertion.unknown)

    postal_code: Mapped[str | None] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(64), default="United States")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    travel_radius_miles: Mapped[int] = mapped_column(Integer, default=250)

    additional_info: Mapped[str | None] = mapped_column(Text)
    onboarding_completed_at: Mapped[datetime | None]

    owner: Mapped[User] = relationship(back_populates="profiles")
    access: Mapped[list[ProfileAccess]] = relationship(cascade="all, delete-orphan")
    conditions: Mapped[list[Condition]] = relationship(cascade="all, delete-orphan")
    labs: Mapped[list[LabResult]] = relationship(cascade="all, delete-orphan")
    medications: Mapped[list[Medication]] = relationship(cascade="all, delete-orphan")
    procedures: Mapped[list[Procedure]] = relationship(cascade="all, delete-orphan")
    biomarkers: Mapped[list[BiomarkerResult]] = relationship(cascade="all, delete-orphan")
    documents: Mapped[list[Document]] = relationship(cascade="all, delete-orphan")


class ProfileAccess(Base):
    """Delegated access to a profile (role-based). The owning account always has full access."""

    __tablename__ = "profile_access"
    __table_args__ = (UniqueConstraint("profile_id", "user_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[ProfileAccessRole] = mapped_column(_enum(ProfileAccessRole))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ProvenanceMixin(TimestampMixin):
    """Every clinical data point records where it came from and whether it is verified."""

    provenance: Mapped[Provenance] = mapped_column(_enum(Provenance), default=Provenance.patient_reported)
    verification: Mapped[Verification] = mapped_column(_enum(Verification), default=Verification.confirmed)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str | None] = mapped_column(String(16))  # manual | rules | llm
    confirmed_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)


class Condition(ProvenanceMixin, Base):
    __tablename__ = "conditions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    concept: Mapped[str | None] = mapped_column(String(64), index=True)  # internal vocabulary code
    name: Mapped[str] = mapped_column(String(255))
    assertion: Mapped[Assertion] = mapped_column(_enum(Assertion), default=Assertion.present)
    onset_date: Mapped[date | None] = mapped_column(Date)
    qualifiers: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # e.g. {"controlled": true}


class LabResult(ProvenanceMixin, Base):
    __tablename__ = "lab_results"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    analyte: Mapped[str] = mapped_column(String(64), index=True)  # vocabulary code, e.g. "lpa"
    display_name: Mapped[str] = mapped_column(String(120))
    value_numeric: Mapped[float | None] = mapped_column(Float)
    value_text: Mapped[str | None] = mapped_column(String(120))
    unit: Mapped[str | None] = mapped_column(String(32))  # preserved exactly as reported
    reference_low: Mapped[float | None] = mapped_column(Float)
    reference_high: Mapped[float | None] = mapped_column(Float)
    reference_text: Mapped[str | None] = mapped_column(String(120))
    collected_on: Mapped[date | None] = mapped_column(Date)


class Medication(ProvenanceMixin, Base):
    __tablename__ = "medications"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    concept: Mapped[str | None] = mapped_column(String(64), index=True)  # drug or class code
    status: Mapped[MedicationStatus] = mapped_column(_enum(MedicationStatus), default=MedicationStatus.current)
    dose: Mapped[str | None] = mapped_column(String(120))
    started_on: Mapped[date | None] = mapped_column(Date)
    stopped_on: Mapped[date | None] = mapped_column(Date)


class Procedure(ProvenanceMixin, Base):
    __tablename__ = "procedures"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    concept: Mapped[str | None] = mapped_column(String(64), index=True)
    assertion: Mapped[Assertion] = mapped_column(_enum(Assertion), default=Assertion.present)
    performed_on: Mapped[date | None] = mapped_column(Date)


class BiomarkerResult(ProvenanceMixin, Base):
    """Genetic and other biomarker results (e.g. LPA variants, FH genetic testing)."""

    __tablename__ = "biomarker_results"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    concept: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(255))
    interpretation: Mapped[str | None] = mapped_column(String(255))
    tested_on: Mapped[date | None] = mapped_column(Date)


# ----------------------------------------------------------------------------- documents


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Original filenames can contain names/dates, so they are stored encrypted.
    filename_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(128))
    doc_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType), default=DocumentType.other)
    status: Mapped[DocumentStatus] = mapped_column(_enum(DocumentStatus), default=DocumentStatus.uploaded)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extraction_methods: Mapped[list[str] | None] = mapped_column(JSONType)
    error_code: Mapped[str | None] = mapped_column(String(64))

    extracted_facts: Mapped[list[ExtractedFact]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ExtractedFact(TimestampMixin, Base):
    """A candidate fact found in a document. It is *not* used for eligibility until the
    user reviews it; accepting creates a row in the corresponding profile table."""

    __tablename__ = "extracted_facts"
    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    fact_type: Mapped[FactType] = mapped_column(_enum(FactType))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16))  # rules | llm
    confidence: Mapped[float | None] = mapped_column(Float)
    warnings: Mapped[list[str] | None] = mapped_column(JSONType)
    review_status: Mapped[ReviewStatus] = mapped_column(_enum(ReviewStatus), default=ReviewStatus.pending)
    reviewed_at: Mapped[datetime | None]
    created_fact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    document: Mapped[Document] = relationship(back_populates="extracted_facts")


# ----------------------------------------------------------------------------- trials


class ClinicalTrial(Base):
    """Normalized registry record. Keyed by the stable NCT identifier."""

    __tablename__ = "clinical_trials"
    nct_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_registry: Mapped[str] = mapped_column(String(32), default="clinicaltrials.gov")
    data_source: Mapped[str] = mapped_column(String(16))  # live | snapshot
    brief_title: Mapped[str] = mapped_column(Text)
    official_title: Mapped[str | None] = mapped_column(Text)
    acronym: Mapped[str | None] = mapped_column(String(64))
    brief_summary: Mapped[str | None] = mapped_column(Text)
    detailed_description: Mapped[str | None] = mapped_column(Text)
    overall_status: Mapped[str] = mapped_column(String(32), index=True)
    phases: Mapped[list[str]] = mapped_column(JSONType, default=list)
    study_type: Mapped[str | None] = mapped_column(String(32))
    conditions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    interventions: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    eligibility_text: Mapped[str | None] = mapped_column(Text)
    minimum_age: Mapped[str | None] = mapped_column(String(32))
    maximum_age: Mapped[str | None] = mapped_column(String(32))
    sex: Mapped[str | None] = mapped_column(String(16))
    healthy_volunteers: Mapped[bool | None] = mapped_column(Boolean)
    sponsor: Mapped[str | None] = mapped_column(String(255))
    collaborators: Mapped[list[str]] = mapped_column(JSONType, default=list)
    enrollment_target: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[str | None] = mapped_column(String(16))
    primary_completion_date: Mapped[str | None] = mapped_column(String(16))
    completion_date: Mapped[str | None] = mapped_column(String(16))
    last_update_posted: Mapped[str | None] = mapped_column(String(16))
    status_verified_date: Mapped[str | None] = mapped_column(String(16))
    overall_officials: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    central_contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    primary_outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    study_category: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    source_url: Mapped[str] = mapped_column(String(255))
    field_gaps: Mapped[list[str]] = mapped_column(JSONType, default=list)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
    criteria_hash: Mapped[str | None] = mapped_column(String(64))

    locations: Mapped[list[TrialLocation]] = relationship(cascade="all, delete-orphan", back_populates="trial")
    criteria: Mapped[list[TrialCriterion]] = relationship(cascade="all, delete-orphan", back_populates="trial")


class TrialLocation(Base):
    __tablename__ = "trial_locations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    nct_id: Mapped[str] = mapped_column(ForeignKey("clinical_trials.nct_id", ondelete="CASCADE"), index=True)
    facility: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geo_source: Mapped[str | None] = mapped_column(String(16))  # registry | postal_centroid
    contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    trial: Mapped[ClinicalTrial] = relationship(back_populates="locations")


class TrialCriterion(Base):
    """Structured representation of one eligibility criterion (tree via parent_id)."""

    __tablename__ = "trial_criteria"
    id: Mapped[uuid.UUID] = _uuid_pk()
    nct_id: Mapped[str] = mapped_column(ForeignKey("clinical_trials.nct_id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # inclusion | exclusion
    ordinal: Mapped[int] = mapped_column(Integer)
    parent_ordinal: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    logic: Mapped[str] = mapped_column(String(8), default="all")  # how children combine: all | any
    category: Mapped[str] = mapped_column(String(32))  # clinical | administrative | investigator | unparsed
    requirement: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    parser: Mapped[str] = mapped_column(String(16), default="rules")
    parser_version: Mapped[str] = mapped_column(String(16))
    trial: Mapped[ClinicalTrial] = relationship(back_populates="criteria")


# ----------------------------------------------------------------------------- eligibility


class EligibilityAssessment(Base):
    __tablename__ = "eligibility_assessments"
    __table_args__ = (Index("ix_assessment_profile_trial", "profile_id", "nct_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    nct_id: Mapped[str] = mapped_column(ForeignKey("clinical_trials.nct_id", ondelete="CASCADE"))
    classification: Mapped[EligibilityClass] = mapped_column(_enum(EligibilityClass))
    summary: Mapped[str] = mapped_column(Text)
    key_reasons: Mapped[list[str]] = mapped_column(JSONType, default=list)
    missing_information: Mapped[list[str]] = mapped_column(JSONType, default=list)
    potential_exclusions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    match_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    relevance_score: Mapped[float] = mapped_column(Float, default=0)
    nearest_site: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    counts: Mapped[dict[str, int]] = mapped_column(JSONType, default=dict)
    engine_version: Mapped[str] = mapped_column(String(16))
    profile_fingerprint: Mapped[str] = mapped_column(String(64))
    pending_facts_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    evaluations: Mapped[list[CriterionEvaluation]] = relationship(
        cascade="all, delete-orphan", back_populates="assessment", order_by="CriterionEvaluation.position"
    )
    trial: Mapped[ClinicalTrial] = relationship()


class CriterionEvaluation(Base):
    __tablename__ = "criterion_evaluations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eligibility_assessments.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16))
    criterion_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[CriterionOutcome] = mapped_column(_enum(CriterionOutcome))
    patient_information: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    requirement: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    assessment: Mapped[EligibilityAssessment] = relationship(back_populates="evaluations")


# ----------------------------------------------------------------------------- enrollment


class SavedTrial(Base):
    __tablename__ = "saved_trials"
    __table_args__ = (UniqueConstraint("profile_id", "nct_id"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    nct_id: Mapped[str] = mapped_column(ForeignKey("clinical_trials.nct_id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EnrollmentInquiry(TimestampMixin, Base):
    """A user-driven contact attempt with a study team. The platform drafts; the user sends."""

    __tablename__ = "enrollment_inquiries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    nct_id: Mapped[str] = mapped_column(ForeignKey("clinical_trials.nct_id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trial_locations.id", ondelete="SET NULL"))
    status: Mapped[InquiryStatus] = mapped_column(_enum(InquiryStatus), default=InquiryStatus.draft)
    contact_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # as listed in the registry
    shared_fields: Mapped[list[str]] = mapped_column(JSONType, default=list)  # what health info the user chose to include
    email_subject: Mapped[str | None] = mapped_column(Text)
    email_body: Mapped[str | None] = mapped_column(Text)
    questions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    document_checklist: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    sent_at: Mapped[datetime | None]
    last_response_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)

    events: Mapped[list[InquiryEvent]] = relationship(
        cascade="all, delete-orphan", order_by="InquiryEvent.occurred_at"
    )
    trial: Mapped[ClinicalTrial] = relationship()
    location: Mapped[TrialLocation | None] = relationship()


class InquiryEvent(Base):
    __tablename__ = "inquiry_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    inquiry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enrollment_inquiries.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)


class FollowUpTask(TimestampMixin, Base):
    __tablename__ = "follow_up_tasks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient_profiles.id", ondelete="CASCADE"), index=True)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enrollment_inquiries.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus), default=TaskStatus.open)
