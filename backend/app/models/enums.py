from __future__ import annotations

import enum


class StrEnum(enum.StrEnum):
    pass


class UserRole(StrEnum):
    member = "member"  # patients and caregivers
    admin = "admin"


class ProfileAccessRole(StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class Relationship(StrEnum):
    self_ = "self"
    child = "child"
    parent = "parent"
    spouse_partner = "spouse_partner"
    other = "other"


class Sex(StrEnum):
    female = "female"
    male = "male"
    intersex = "intersex"
    unknown = "unknown"


class Provenance(StrEnum):
    """Where a clinical data point came from."""

    patient_reported = "patient_reported"
    document_extracted = "document_extracted"
    clinician_confirmed = "clinician_confirmed"
    unknown = "unknown"


class Verification(StrEnum):
    """Whether the user has reviewed a data point. Only confirmed facts are used for eligibility."""

    confirmed = "confirmed"
    pending_review = "pending_review"
    rejected = "rejected"


class Assertion(StrEnum):
    """For conditions/procedures: is it present, explicitly absent, or unknown?
    'absent' is a *positive statement of absence* and is different from 'no record'."""

    present = "present"
    absent = "absent"
    unknown = "unknown"


class MedicationStatus(StrEnum):
    current = "current"
    past = "past"  # took it before, not now
    not_current = "not_current"  # not taking it now; past use not stated
    never = "never"
    unknown = "unknown"


class DocumentType(StrEnum):
    lab_report = "lab_report"
    physician_note = "physician_note"
    medication_list = "medication_list"
    pathology_report = "pathology_report"
    genetic_report = "genetic_report"
    other = "other"


class DocumentStatus(StrEnum):
    uploaded = "uploaded"
    processing = "processing"
    extracted = "extracted"
    no_text = "no_text"  # scanned/image-only PDF; OCR is not in the MVP
    failed = "failed"


class FactType(StrEnum):
    condition = "condition"
    lab = "lab"
    medication = "medication"
    procedure = "procedure"
    biomarker = "biomarker"


class ReviewStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class EligibilityClass(StrEnum):
    potentially_eligible = "potentially_eligible"
    uncertain = "uncertain"
    potentially_ineligible = "potentially_ineligible"


class CriterionOutcome(StrEnum):
    """Outcome from the patient's perspective.
    For inclusion criteria: satisfied = meets the criterion.
    For exclusion criteria: satisfied = the exclusion does NOT appear to apply."""

    satisfied = "satisfied"
    not_satisfied = "not_satisfied"
    unknown = "unknown"  # required information is missing
    needs_review = "needs_review"  # criterion could not be interpreted reliably / ambiguous
    conflicting = "conflicting"  # sources disagree
    not_applicable = "not_applicable"
    confirm_with_team = "confirm_with_team"  # administrative / investigator judgment


class InquiryStatus(StrEnum):
    draft = "draft"
    ready = "ready"
    sent_by_user = "sent_by_user"
    response_received = "response_received"
    prescreen_scheduled = "prescreen_scheduled"
    screening = "screening"
    enrolled = "enrolled"
    not_eligible = "not_eligible"
    declined = "declined"
    closed = "closed"


class TaskStatus(StrEnum):
    open = "open"
    done = "done"
