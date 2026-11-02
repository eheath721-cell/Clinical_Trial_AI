"""Matching orchestration: profile -> search plan -> trials -> assessments (persisted)."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ClinicalTrial,
    CriterionEvaluation,
    EligibilityAssessment,
    ExtractedFact,
    PatientProfile,
)
from app.models.enums import ReviewStatus
from app.modules.agents.llm import get_llm
from app.modules.eligibility.engine import ENGINE_VERSION, AssessmentResult, assess
from app.modules.eligibility.llm_interpreter import interpret_criterion
from app.modules.eligibility.patient import PatientFacts, build_patient_facts
from app.modules.trials.records import TrialRecord
from app.modules.trials.search import build_search_plan, match_reasons, nearest_site, relevance
from app.modules.trials.service import get_or_fetch_trial, record_from_db, upsert_trial
from app.modules.trials.sources import get_repository

log = logging.getLogger("trialcompass.matching")


def load_profile_full(db: Session, profile_id: uuid.UUID) -> PatientProfile:
    return db.scalar(
        select(PatientProfile).where(PatientProfile.id == profile_id).options(
            selectinload(PatientProfile.conditions), selectinload(PatientProfile.labs),
            selectinload(PatientProfile.medications), selectinload(PatientProfile.procedures),
            selectinload(PatientProfile.biomarkers), selectinload(PatientProfile.documents))
        .execution_options(populate_existing=True))


def patient_facts(db: Session, profile: PatientProfile) -> PatientFacts:
    profile = load_profile_full(db, profile.id)
    facts = build_patient_facts(profile)
    facts.pending_review_count = db.scalar(
        select(func.count()).select_from(ExtractedFact).where(
            ExtractedFact.profile_id == profile.id, ExtractedFact.review_status == ReviewStatus.pending)) or 0
    return facts


def _store(db: Session, profile: PatientProfile, trial: ClinicalTrial, record: TrialRecord, result: AssessmentResult,
           facts: PatientFacts, reasons: list[dict], nearest: dict | None, score: float) -> EligibilityAssessment:
    db.execute(update(EligibilityAssessment)
               .where(EligibilityAssessment.profile_id == profile.id, EligibilityAssessment.nct_id == trial.nct_id,
                      EligibilityAssessment.is_current.is_(True))
               .values(is_current=False))
    a = EligibilityAssessment(
        profile_id=profile.id, nct_id=trial.nct_id, classification=result.classification, summary=result.summary,
        key_reasons=result.key_reasons, missing_information=result.missing_information,
        potential_exclusions=result.potential_exclusions, match_reasons=reasons, relevance_score=score,
        nearest_site=nearest, counts={**result.counts, "_caveats": result.caveats, "_questions": result.questions,
                                      "_best_cohort": result.best_cohort},
        engine_version=ENGINE_VERSION, profile_fingerprint=facts.fingerprint(),
        pending_facts_count=facts.pending_review_count, is_current=True)
    for c in result.criteria:
        a.evaluations.append(CriterionEvaluation(
            position=c.position, depth=c.depth, kind=c.kind, criterion_text=c.text, category=c.category,
            outcome=c.outcome, patient_information=c.patient_information, explanation=c.explanation,
            evidence=c.evidence, requirement={**(c.requirement or {}), "_cohort": c.cohort, "_group": c.is_group,
                                              "_missing": c.missing, "_source": c.source}))
    db.add(a)
    return a


def _interpreter():
    return interpret_criterion if get_llm().available else None


def assess_trial(db: Session, profile: PatientProfile, trial: ClinicalTrial, facts: PatientFacts | None = None,
                 plan=None) -> EligibilityAssessment:
    facts = facts or patient_facts(db, profile)
    record = record_from_db(trial)
    result = assess(record, facts, llm_interpreter=_interpreter())
    plan = plan or build_search_plan(load_profile_full(db, profile.id), facts)
    reasons = match_reasons(record, plan, facts)
    origin = (profile.latitude, profile.longitude) if profile.latitude is not None else None
    loc_ids = [str(loc.id) for loc in trial.locations]
    nearest = nearest_site(record, origin, loc_ids)
    score = relevance(reasons, result.classification.value, record.overall_status, nearest, profile.travel_radius_miles)
    return _store(db, profile, trial, record, result, facts, reasons, nearest, score)


def refresh_matches(db: Session, profile: PatientProfile, include_related: bool = True) -> dict:
    full = load_profile_full(db, profile.id)
    facts = patient_facts(db, full)
    plan = build_search_plan(full, facts, include_related=include_related)
    repo = get_repository()
    records: dict[str, TrialRecord] = {}
    sources: set[str] = set()
    for q in plan.queries():
        found, src = repo.search(q)
        sources.add(src)
        for r in found:
            records.setdefault(r.nct_id, r)
    assessed = 0
    for r in records.values():
        trial = upsert_trial(db, r)
        assess_trial(db, full, trial, facts, plan)
        assessed += 1
    db.flush()
    status = repo.status()
    return {
        "trials_found": len(records),
        "assessed": assessed,
        "data_source": "live" if sources == {"live"} else ("snapshot" if sources == {"snapshot"} else "mixed"),
        "source_message": status.message,
        "plan": plan.describe(),
        "pending_review_count": facts.pending_review_count,
    }


def current_assessment(db: Session, profile: PatientProfile, nct_id: str, recompute: bool = False):
    trial = get_or_fetch_trial(db, nct_id)
    if trial is None:
        return None, None
    a = db.scalar(select(EligibilityAssessment)
                  .where(EligibilityAssessment.profile_id == profile.id, EligibilityAssessment.nct_id == trial.nct_id,
                         EligibilityAssessment.is_current.is_(True))
                  .options(selectinload(EligibilityAssessment.evaluations)))
    facts = patient_facts(db, profile)
    if recompute or a is None or a.profile_fingerprint != facts.fingerprint() or a.engine_version != ENGINE_VERSION \
            or a.pending_facts_count != facts.pending_review_count:
        a = assess_trial(db, profile, trial, facts)
        db.flush()
    return trial, a


def reassess_all(db: Session, profile: PatientProfile) -> int:
    """Re-run assessments for trials already matched (after the profile changes)."""
    ncts = db.scalars(select(EligibilityAssessment.nct_id).where(
        EligibilityAssessment.profile_id == profile.id, EligibilityAssessment.is_current.is_(True))).all()
    if not ncts:
        return 0
    facts = patient_facts(db, profile)
    plan = build_search_plan(load_profile_full(db, profile.id), facts)
    for nct in ncts:
        trial = db.get(ClinicalTrial, nct)
        if trial is not None:
            assess_trial(db, profile, trial, facts, plan)
    db.flush()
    return len(ncts)
