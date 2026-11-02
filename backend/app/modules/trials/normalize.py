"""Adapters that map source payloads to `TrialRecord`."""

from __future__ import annotations

from typing import Any

from app.modules.trials.geo import fill_location_geo
from app.modules.trials.records import (
    Contact,
    Intervention,
    LocationRecord,
    Official,
    Outcome,
    TrialRecord,
)

STUDY_URL = "https://clinicaltrials.gov/study/{nct}"


def _g(d: dict | None, *path: str, default: Any = None) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return default if cur is None else cur


def from_ctgov_v2(study: dict[str, Any], retrieved_at: str | None = None) -> TrialRecord:
    """Map a ClinicalTrials.gov API v2 `study` object (protocolSection/derivedSection)."""
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    sponsor = ps.get("sponsorCollaboratorsModule", {})
    desc = ps.get("descriptionModule", {})
    conds = ps.get("conditionsModule", {})
    design = ps.get("designModule", {})
    arms = ps.get("armsInterventionsModule", {})
    outcomes = ps.get("outcomesModule", {})
    elig = ps.get("eligibilityModule", {})
    cl = ps.get("contactsLocationsModule", {})
    nct = ident["nctId"]

    hv = elig.get("healthyVolunteers")
    locations = []
    for loc in cl.get("locations", []) or []:
        geo = loc.get("geoPoint") or {}
        rec = LocationRecord(
            facility=loc.get("facility"),
            city=loc.get("city"),
            state=loc.get("state"),
            postal_code=loc.get("zip"),
            country=loc.get("country"),
            status=loc.get("status"),
            latitude=geo.get("lat"),
            longitude=geo.get("lon"),
            geo_source="registry" if geo else None,
            contacts=[
                Contact(name=c.get("name"), role=c.get("role"), phone=_phone(c), email=c.get("email"))
                for c in loc.get("contacts", []) or []
            ],
        )
        fill_location_geo(rec)
        locations.append(rec)

    return TrialRecord(
        nct_id=nct,
        data_source="live",
        brief_title=ident.get("briefTitle") or ident.get("officialTitle") or nct,
        official_title=ident.get("officialTitle"),
        acronym=ident.get("acronym"),
        brief_summary=desc.get("briefSummary"),
        detailed_description=desc.get("detailedDescription"),
        overall_status=status.get("overallStatus", "UNKNOWN"),
        phases=design.get("phases", []) or [],
        study_type=design.get("studyType"),
        conditions=conds.get("conditions", []) or [],
        keywords=conds.get("keywords", []) or [],
        interventions=[
            Intervention(
                name=i.get("name", ""),
                type=i.get("type"),
                description=i.get("description"),
                other_names=i.get("otherNames", []) or [],
            )
            for i in arms.get("interventions", []) or []
        ],
        eligibility_text=elig.get("eligibilityCriteria"),
        minimum_age=elig.get("minimumAge"),
        maximum_age=elig.get("maximumAge"),
        sex=elig.get("sex"),
        healthy_volunteers=hv if isinstance(hv, bool) else None,
        sponsor=_g(sponsor, "leadSponsor", "name"),
        collaborators=[c.get("name") for c in sponsor.get("collaborators", []) or [] if c.get("name")],
        enrollment_target=_g(design, "enrollmentInfo", "count"),
        start_date=_g(status, "startDateStruct", "date"),
        primary_completion_date=_g(status, "primaryCompletionDateStruct", "date"),
        completion_date=_g(status, "completionDateStruct", "date"),
        last_update_posted=_g(status, "lastUpdatePostDateStruct", "date"),
        status_verified_date=status.get("statusVerifiedDate"),
        overall_officials=[
            Official(name=o.get("name"), affiliation=o.get("affiliation"), role=o.get("role"))
            for o in cl.get("overallOfficials", []) or []
        ],
        central_contacts=[
            Contact(name=c.get("name"), role=c.get("role"), phone=_phone(c), email=c.get("email"))
            for c in cl.get("centralContacts", []) or []
        ],
        primary_outcomes=[
            Outcome(measure=o.get("measure", ""), time_frame=o.get("timeFrame"), description=o.get("description"))
            for o in outcomes.get("primaryOutcomes", []) or []
        ],
        locations=locations,
        source_url=STUDY_URL.format(nct=nct),
        retrieved_at=retrieved_at,
    )


def _phone(c: dict) -> str | None:
    phone = c.get("phone")
    if phone and c.get("phoneExt"):
        return f"{phone} ext. {c['phoneExt']}"
    return phone


SNAPSHOT_FIELD_GAPS = [
    "last_update_posted",
    "site_coordinates",
    "contact_phone_email",
    "overall_officials",
    "keywords",
    "intervention_types",
]


def from_connector(trial: dict[str, Any], retrieved_at: str) -> TrialRecord:
    """Map the ClinicalTrials.gov connector's (flattened) trial object used to build the
    offline snapshot. Fields that format does not carry are listed in `field_gaps`."""
    nct = trial["nct_id"]
    hv = trial.get("healthy_volunteers")
    locations = []
    for loc in trial.get("locations") or []:
        rec = LocationRecord(
            facility=loc.get("facility"),
            city=loc.get("city"),
            state=loc.get("state"),
            postal_code=loc.get("zip"),
            country=loc.get("country"),
            status=loc.get("status"),
            contacts=[Contact(name=n) for n in (loc.get("contacts") or []) if n],
        )
        fill_location_geo(rec)
        locations.append(rec)
    return TrialRecord(
        nct_id=nct,
        data_source="snapshot",
        brief_title=trial.get("brief_title") or trial.get("title") or nct,
        official_title=trial.get("title"),
        acronym=trial.get("acronym"),
        brief_summary=trial.get("brief_summary"),
        detailed_description=trial.get("detailed_description"),
        overall_status=trial.get("status") or "UNKNOWN",
        phases=[p for p in (trial.get("phase") or []) if p],
        study_type=trial.get("study_type"),
        conditions=trial.get("conditions") or [],
        interventions=[Intervention(name=n) for n in (trial.get("interventions") or [])],
        eligibility_text=trial.get("eligibility_criteria"),
        minimum_age=trial.get("minimum_age"),
        maximum_age=trial.get("maximum_age"),
        sex=trial.get("sex"),
        healthy_volunteers={"Yes": True, "No": False}.get(hv) if isinstance(hv, str) else hv,
        sponsor=trial.get("sponsor"),
        collaborators=trial.get("collaborators") or [],
        enrollment_target=trial.get("enrollment"),
        start_date=trial.get("start_date"),
        primary_completion_date=trial.get("primary_completion_date"),
        completion_date=trial.get("completion_date"),
        primary_outcomes=[
            Outcome(measure=o.get("measure", ""), time_frame=o.get("time_frame"), description=o.get("description"))
            for o in (trial.get("primary_outcomes") or [])
        ],
        locations=locations,
        source_url=trial.get("url") or STUDY_URL.format(nct=nct),
        field_gaps=list(SNAPSHOT_FIELD_GAPS),
        retrieved_at=retrieved_at,
    )
