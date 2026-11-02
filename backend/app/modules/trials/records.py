"""Canonical, source-independent trial record. Every source adapter (ClinicalTrials.gov live
API, offline snapshot, and future sponsor/hospital/international registries) normalizes into
this shape before ingestion."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Contact(BaseModel):
    name: str | None = None
    role: str | None = None
    phone: str | None = None
    email: str | None = None


class LocationRecord(BaseModel):
    facility: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    status: str | None = None  # site-level recruitment status as listed in the registry
    latitude: float | None = None
    longitude: float | None = None
    geo_source: str | None = None
    contacts: list[Contact] = Field(default_factory=list)


class Intervention(BaseModel):
    name: str
    type: str | None = None
    description: str | None = None
    other_names: list[str] = Field(default_factory=list)


class Outcome(BaseModel):
    measure: str
    time_frame: str | None = None
    description: str | None = None


class Official(BaseModel):
    name: str | None = None
    affiliation: str | None = None
    role: str | None = None


class TrialRecord(BaseModel):
    nct_id: str
    registry: str = "clinicaltrials.gov"
    data_source: str  # live | snapshot
    brief_title: str
    official_title: str | None = None
    acronym: str | None = None
    brief_summary: str | None = None
    detailed_description: str | None = None
    overall_status: str
    phases: list[str] = Field(default_factory=list)
    study_type: str | None = None
    conditions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)
    eligibility_text: str | None = None
    minimum_age: str | None = None
    maximum_age: str | None = None
    sex: str | None = None
    healthy_volunteers: bool | None = None
    sponsor: str | None = None
    collaborators: list[str] = Field(default_factory=list)
    enrollment_target: int | None = None
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    last_update_posted: str | None = None
    status_verified_date: str | None = None
    overall_officials: list[Official] = Field(default_factory=list)
    central_contacts: list[Contact] = Field(default_factory=list)
    primary_outcomes: list[Outcome] = Field(default_factory=list)
    locations: list[LocationRecord] = Field(default_factory=list)
    source_url: str
    # Fields the source could not provide (shown to users rather than silently omitted).
    field_gaps: list[str] = Field(default_factory=list)
    retrieved_at: str | None = None
