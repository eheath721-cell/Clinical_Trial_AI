"""Trial ingestion (normalized record -> relational tables) and lookup helpers."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.db import utcnow
from app.models import ClinicalTrial, TrialCriterion, TrialLocation
from app.modules.eligibility.criteria_parser import parse_criteria
from app.modules.eligibility.engine import recognize_tree
from app.modules.eligibility.recognizers import PARSER_VERSION
from app.modules.trials.classify import classify_study
from app.modules.trials.records import (
    Contact,
    Intervention,
    LocationRecord,
    Official,
    Outcome,
    TrialRecord,
)
from app.modules.trials.sources import get_repository


def criteria_hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def upsert_trial(db: Session, r: TrialRecord) -> ClinicalTrial:
    trial = db.get(ClinicalTrial, r.nct_id, options=[selectinload(ClinicalTrial.locations),
                                                      selectinload(ClinicalTrial.criteria)])
    if trial is None:
        trial = ClinicalTrial(nct_id=r.nct_id)
        db.add(trial)
    trial.source_registry = r.registry
    trial.data_source = r.data_source
    trial.brief_title = r.brief_title
    trial.official_title = r.official_title
    trial.acronym = r.acronym
    trial.brief_summary = r.brief_summary
    trial.detailed_description = r.detailed_description
    trial.overall_status = r.overall_status
    trial.phases = r.phases
    trial.study_type = r.study_type
    trial.conditions = r.conditions
    trial.keywords = r.keywords
    trial.interventions = [i.model_dump() for i in r.interventions]
    trial.eligibility_text = r.eligibility_text
    trial.minimum_age = r.minimum_age
    trial.maximum_age = r.maximum_age
    trial.sex = r.sex
    trial.healthy_volunteers = r.healthy_volunteers
    trial.sponsor = r.sponsor
    trial.collaborators = r.collaborators
    trial.enrollment_target = r.enrollment_target
    trial.start_date = r.start_date
    trial.primary_completion_date = r.primary_completion_date
    trial.completion_date = r.completion_date
    trial.last_update_posted = r.last_update_posted
    trial.status_verified_date = r.status_verified_date
    trial.overall_officials = [o.model_dump() for o in r.overall_officials]
    trial.central_contacts = [c.model_dump() for c in r.central_contacts]
    trial.primary_outcomes = [o.model_dump() for o in r.primary_outcomes]
    trial.study_category = classify_study(r)
    trial.source_url = r.source_url
    trial.field_gaps = r.field_gaps
    trial.fetched_at = utcnow()

    trial.locations.clear()
    for loc in r.locations:
        trial.locations.append(TrialLocation(
            facility=loc.facility, city=loc.city, state=loc.state, postal_code=loc.postal_code, country=loc.country,
            status=loc.status, latitude=loc.latitude, longitude=loc.longitude, geo_source=loc.geo_source,
            contacts=[c.model_dump() for c in loc.contacts]))

    h = criteria_hash(r.eligibility_text)
    if trial.criteria_hash != h or not trial.criteria or any(c.parser_version != PARSER_VERSION for c in trial.criteria):
        trial.criteria.clear()
        parsed = parse_criteria(r.eligibility_text)
        recognized = recognize_tree(parsed)
        for n in parsed.walk():
            cat, req = recognized[n.ordinal]
            trial.criteria.append(TrialCriterion(
                kind=n.kind, ordinal=n.ordinal, parent_ordinal=n.parent.ordinal if n.parent else None, text=n.text,
                logic=n.logic, category="group" if n.is_group else cat, requirement=req, parser="rules",
                parser_version=PARSER_VERSION))
        trial.criteria_hash = h
    db.flush()
    return trial


def record_from_db(t: ClinicalTrial) -> TrialRecord:
    return TrialRecord(
        nct_id=t.nct_id, registry=t.source_registry, data_source=t.data_source, brief_title=t.brief_title,
        official_title=t.official_title, acronym=t.acronym, brief_summary=t.brief_summary,
        detailed_description=t.detailed_description, overall_status=t.overall_status, phases=t.phases or [],
        study_type=t.study_type, conditions=t.conditions or [], keywords=t.keywords or [],
        interventions=[Intervention(**i) for i in t.interventions or []], eligibility_text=t.eligibility_text,
        minimum_age=t.minimum_age, maximum_age=t.maximum_age, sex=t.sex, healthy_volunteers=t.healthy_volunteers,
        sponsor=t.sponsor, collaborators=t.collaborators or [], enrollment_target=t.enrollment_target,
        start_date=t.start_date, primary_completion_date=t.primary_completion_date, completion_date=t.completion_date,
        last_update_posted=t.last_update_posted, status_verified_date=t.status_verified_date,
        overall_officials=[Official(**o) for o in t.overall_officials or []],
        central_contacts=[Contact(**c) for c in t.central_contacts or []],
        primary_outcomes=[Outcome(**o) for o in t.primary_outcomes or []],
        locations=[LocationRecord(facility=loc.facility, city=loc.city, state=loc.state, postal_code=loc.postal_code,
                                  country=loc.country, status=loc.status, latitude=loc.latitude,
                                  longitude=loc.longitude, geo_source=loc.geo_source,
                                  contacts=[Contact(**c) for c in loc.contacts or []]) for loc in t.locations],
        source_url=t.source_url, field_gaps=t.field_gaps or [],
        retrieved_at=t.fetched_at.date().isoformat() if t.fetched_at else None,
    )


def get_or_fetch_trial(db: Session, nct_id: str, refresh: bool = False) -> ClinicalTrial | None:
    nct_id = nct_id.upper()
    trial = db.scalar(select(ClinicalTrial).where(ClinicalTrial.nct_id == nct_id)
                      .options(selectinload(ClinicalTrial.locations), selectinload(ClinicalTrial.criteria)))
    ttl = timedelta(hours=get_settings().trial_cache_ttl_hours)
    fresh = trial is not None and trial.fetched_at and (utcnow() - _aware(trial.fetched_at)) < ttl
    if trial is not None and (fresh or not refresh) and trial.data_source == "snapshot":
        return trial
    if trial is not None and fresh and not refresh:
        return trial
    record, _source = get_repository().get(nct_id)
    if record is None:
        return trial
    return upsert_trial(db, record)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)
