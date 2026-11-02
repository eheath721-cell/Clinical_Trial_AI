from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.clinical.vocab import find_concepts, get_concept
from app.core import audit
from app.core.db import get_db
from app.core.deps import AuthContext, get_auth, load_profile, profile_editor, profile_reader
from app.models import ClinicalTrial, EligibilityAssessment, PatientProfile, SavedTrial
from app.models.enums import ProfileAccessRole
from app.modules.eligibility.service import current_assessment, refresh_matches
from app.modules.trials.geo import haversine_miles
from app.modules.trials.search import CONDITION_DRUGS
from app.modules.trials.service import get_or_fetch_trial, upsert_trial
from app.modules.trials.sources import ACTIVE_STATUSES, SearchQuery, SourceUnavailable, get_repository

router = APIRouter(prefix="/api", tags=["trials"])

STATUS_LABELS = {
    "RECRUITING": "Recruiting", "NOT_YET_RECRUITING": "Not yet recruiting",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation", "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "COMPLETED": "Completed", "SUSPENDED": "Suspended", "TERMINATED": "Terminated", "WITHDRAWN": "Withdrawn",
    "UNKNOWN": "Unknown status",
}
PHASE_LABELS = {"EARLY_PHASE1": "Early phase 1", "PHASE1": "Phase 1", "PHASE2": "Phase 2", "PHASE3": "Phase 3",
                "PHASE4": "Phase 4", "NA": "Not applicable"}


def trial_summary(t: ClinicalTrial) -> dict:
    return {
        "nct_id": t.nct_id, "title": t.brief_title, "official_title": t.official_title, "acronym": t.acronym,
        "brief_summary": t.brief_summary, "phases": t.phases or [],
        "phase_label": " / ".join(PHASE_LABELS.get(p, p) for p in (t.phases or [])) or "Not specified",
        "status": t.overall_status, "status_label": STATUS_LABELS.get(t.overall_status, t.overall_status),
        "study_type": t.study_type, "conditions": t.conditions or [],
        "interventions": [i.get("name") for i in t.interventions or [] if not (i.get("name") or "").lower().startswith("placebo")],
        "sponsor": t.sponsor, "enrollment_target": t.enrollment_target, "start_date": t.start_date,
        "primary_completion_date": t.primary_completion_date, "completion_date": t.completion_date,
        "last_update_posted": t.last_update_posted, "data_source": t.data_source,
        "retrieved_at": t.fetched_at.date().isoformat() if t.fetched_at else None, "source_url": t.source_url,
        "study_category": t.study_category, "field_gaps": t.field_gaps or [], "location_count": len(t.locations),
        "minimum_age": t.minimum_age, "maximum_age": t.maximum_age, "sex": t.sex,
        "healthy_volunteers": t.healthy_volunteers,
    }


def trial_detail(t: ClinicalTrial, origin: tuple[float, float] | None) -> dict:
    locs = []
    for loc in t.locations:
        dist = None
        if origin and loc.latitude is not None:
            dist = round(haversine_miles(origin, (loc.latitude, loc.longitude)), 1)
        locs.append({"id": str(loc.id), "facility": loc.facility, "city": loc.city, "state": loc.state,
                     "postal_code": loc.postal_code, "country": loc.country, "status": loc.status,
                     "status_label": STATUS_LABELS.get(loc.status or "", "Status not listed"),
                     "distance_miles": dist, "geo_source": loc.geo_source, "contacts": loc.contacts or []})
    locs.sort(key=lambda x: (x["distance_miles"] is None, x["distance_miles"] or 0))
    return {**trial_summary(t), "detailed_description": t.detailed_description, "keywords": t.keywords or [],
            "interventions_full": t.interventions or [], "eligibility_text": t.eligibility_text,
            "collaborators": t.collaborators or [], "overall_officials": t.overall_officials or [],
            "central_contacts": t.central_contacts or [], "primary_outcomes": t.primary_outcomes or [],
            "status_verified_date": t.status_verified_date, "locations": locs}


def assessment_out(a: EligibilityAssessment, include_criteria: bool = False) -> dict:
    meta = a.counts or {}
    out = {
        "id": str(a.id), "nct_id": a.nct_id, "classification": a.classification.value, "summary": a.summary,
        "key_reasons": a.key_reasons or [], "missing_information": a.missing_information or [],
        "potential_exclusions": a.potential_exclusions or [], "match_reasons": a.match_reasons or [],
        "relevance_score": a.relevance_score, "nearest_site": a.nearest_site,
        "counts": {k: v for k, v in meta.items() if not k.startswith("_")}, "caveats": meta.get("_caveats", []),
        "questions": meta.get("_questions", []), "best_cohort": meta.get("_best_cohort"),
        "engine_version": a.engine_version, "assessed_at": a.created_at.isoformat(),
        "pending_facts_count": a.pending_facts_count,
    }
    if include_criteria:
        out["criteria"] = [{
            "position": e.position, "depth": e.depth, "kind": e.kind, "text": e.criterion_text, "category": e.category,
            "outcome": e.outcome.value, "patient_information": e.patient_information, "explanation": e.explanation,
            "evidence": e.evidence, "cohort": (e.requirement or {}).get("_cohort"),
            "is_group": (e.requirement or {}).get("_group", False), "source": (e.requirement or {}).get("_source"),
            "missing": (e.requirement or {}).get("_missing", []),
            "requirement": {k: v for k, v in (e.requirement or {}).items() if not k.startswith("_")},
        } for e in a.evaluations]
    return out


# ----------------------------------------------------------------------------- general trial endpoints


@router.get("/trials/source-status")
def source_status():
    s = get_repository().status()
    return s.__dict__


@router.get("/trials/search")
def search_trials(q: str = Query(min_length=2, max_length=200), include_inactive: bool = False,
                  auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    """Free-text search with terminology expansion (e.g. 'Lp(a)' also searches
    'lipoprotein(a)', 'hyperlipoproteinemia(a)' and Lp(a)-targeted drug names)."""
    concepts = [m.code for m in find_concepts(q)]
    terms, drugs, labels = [q], [], []
    for code in dict.fromkeys(concepts):
        c = get_concept(code)
        labels.append(c.label)
        terms += [t for t in (c.search_terms or (c.label,)) if t not in terms]
        drug = CONDITION_DRUGS.get(code)
        if drug:
            drugs += list(get_concept(drug).search_terms)
    statuses = [] if include_inactive else list(ACTIVE_STATUSES)
    repo = get_repository()
    try:
        found, src = repo.search(SearchQuery(condition_terms=terms, statuses=statuses, max_results=100))
        if drugs:
            more, _ = repo.search(SearchQuery(intervention_terms=drugs, statuses=statuses, max_results=50))
            found += [r for r in more if r.nct_id not in {x.nct_id for x in found}]
    except SourceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    trials = [upsert_trial(db, r) for r in found]
    db.commit()
    return {"query": q, "recognized_concepts": labels, "expanded_terms": terms, "drug_terms": drugs,
            "data_source": src, "results": [trial_summary(t) for t in trials]}


@router.get("/trials/{nct_id}")
def get_trial(nct_id: str, request: Request, profile_id: uuid.UUID | None = None, auth: AuthContext = Depends(get_auth),
              db: Session = Depends(get_db)):
    try:
        trial = get_or_fetch_trial(db, nct_id)
    except SourceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if trial is None:
        raise HTTPException(404, "Trial not found in the registry")
    origin = None
    if profile_id:
        p = load_profile(db, auth, profile_id, ProfileAccessRole.viewer)
        if p.latitude is not None:
            origin = (p.latitude, p.longitude)
    db.commit()
    return trial_detail(trial, origin)


# ----------------------------------------------------------------------------- personalized matching


@router.post("/profiles/{profile_id}/matches/refresh")
def refresh(request: Request, include_related: bool = True, profile: PatientProfile = Depends(profile_editor),
            auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    try:
        summary = refresh_matches(db, profile, include_related=include_related)
    except SourceUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    audit.record(db, "matches.refresh", actor_id=auth.user.id, request=request, resource_type="profile",
                 resource_id=profile.id, profile_id=profile.id,
                 meta={"count": summary["assessed"], "source": summary["data_source"]})
    db.commit()
    return summary


@router.get("/profiles/{profile_id}/matches")
def list_matches(
    profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db),
    classification: list[str] = Query(default=[]), phase: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]), max_distance: float | None = None, intervention: str | None = None,
    category: list[str] = Query(default=[]), sort: str = "relevance", include_inactive: bool = False,
):
    rows = db.scalars(select(EligibilityAssessment)
                      .where(EligibilityAssessment.profile_id == profile.id, EligibilityAssessment.is_current.is_(True))
                      .options(selectinload(EligibilityAssessment.trial).selectinload(ClinicalTrial.locations))).all()
    saved = set(db.scalars(select(SavedTrial.nct_id).where(SavedTrial.profile_id == profile.id)).all())
    items = []
    for a in rows:
        t = a.trial
        if not include_inactive and not status and t.overall_status not in ACTIVE_STATUSES:
            continue
        if classification and a.classification.value not in classification:
            continue
        if phase and not set(phase) & set(t.phases or ["NA"]):
            continue
        if status and t.overall_status not in status:
            continue
        if category and (t.study_category or {}).get("code") not in category:
            continue
        if max_distance is not None and (not a.nearest_site or a.nearest_site["distance_miles"] > max_distance):
            continue
        if intervention and not any(intervention.lower() in (i.get("name") or "").lower() for i in t.interventions or []):
            continue
        items.append({"trial": trial_summary(t), "assessment": assessment_out(a), "saved": t.nct_id in saved})
    key = {
        "relevance": lambda x: -x["assessment"]["relevance_score"],
        "distance": lambda x: (x["assessment"]["nearest_site"] or {}).get("distance_miles", 1e9),
        "eligibility": lambda x: ({"potentially_eligible": 0, "uncertain": 1, "potentially_ineligible": 2}
                                  [x["assessment"]["classification"]], -x["assessment"]["relevance_score"]),
        "start_date": lambda x: x["trial"]["start_date"] or "",
    }.get(sort, lambda x: -x["assessment"]["relevance_score"])
    items.sort(key=key)
    facets = {"classification": {}, "phase": {}, "status": {}, "category": {}}
    for it in items:
        facets["classification"][it["assessment"]["classification"]] = facets["classification"].get(
            it["assessment"]["classification"], 0) + 1
        for p in it["trial"]["phases"] or ["NA"]:
            facets["phase"][p] = facets["phase"].get(p, 0) + 1
        facets["status"][it["trial"]["status"]] = facets["status"].get(it["trial"]["status"], 0) + 1
        cat = (it["trial"]["study_category"] or {}).get("code", "other")
        facets["category"][cat] = facets["category"].get(cat, 0) + 1
    return {"items": items, "total": len(items), "facets": facets, "source": get_repository().status().__dict__}


@router.get("/profiles/{profile_id}/trials/{nct_id}/assessment")
def get_assessment(nct_id: str, request: Request, recompute: bool = False, profile: PatientProfile = Depends(profile_reader),
                   auth: AuthContext = Depends(get_auth), db: Session = Depends(get_db)):
    trial, a = current_assessment(db, profile, nct_id, recompute=recompute)
    if trial is None:
        raise HTTPException(404, "Trial not found")
    audit.record(db, "assessment.view", actor_id=auth.user.id, request=request, resource_type="trial",
                 resource_id=trial.nct_id, profile_id=profile.id, meta={"classification": a.classification.value})
    db.commit()
    a = db.scalar(select(EligibilityAssessment).where(EligibilityAssessment.id == a.id)
                  .options(selectinload(EligibilityAssessment.evaluations)))
    origin = (profile.latitude, profile.longitude) if profile.latitude is not None else None
    saved = db.scalar(select(SavedTrial).where(SavedTrial.profile_id == profile.id, SavedTrial.nct_id == trial.nct_id))
    return {"trial": trial_detail(trial, origin), "assessment": assessment_out(a, include_criteria=True),
            "saved": saved is not None}


@router.get("/profiles/{profile_id}/compare")
def compare(ids: str, profile: PatientProfile = Depends(profile_reader), db: Session = Depends(get_db)):
    ncts = [x.strip().upper() for x in ids.split(",") if x.strip()][:4]
    out = []
    for nct in ncts:
        trial, a = current_assessment(db, profile, nct)
        if trial is None:
            continue
        out.append({"trial": trial_summary(trial), "assessment": assessment_out(a)})
    db.commit()
    return {"items": out}
