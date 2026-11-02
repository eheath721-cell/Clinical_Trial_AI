"""Patient profile -> registry search plan -> ranked, explained matches.

Terminology mismatch is handled by concept expansion: a patient who reports an Lp(a) lab
result is searched against registry terms for lipoprotein(a) (several spellings), against
Lp(a)-targeted investigational drugs, and against related conditions under which Lp(a)
trials are often indexed (ASCVD, coronary artery disease, aortic stenosis, dyslipidemia).
Related concepts widen *discovery only*; they never count as a diagnosis.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.clinical.vocab import concept_index, find_concepts, get_concept
from app.modules.eligibility.patient import PatientFacts
from app.modules.trials.geo import haversine_miles
from app.modules.trials.records import TrialRecord
from app.modules.trials.sources import ACTIVE_STATUSES, SearchQuery

# Lab analytes whose presence makes their condition area relevant for discovery.
LAB_DISCOVERY = {"lpa": "elevated_lpa"}
CONDITION_DRUGS = {"elevated_lpa": "lpa_targeted"}


@dataclass
class PlanConcept:
    code: str
    label: str
    why: str
    weight: str  # direct | related


@dataclass
class SearchPlan:
    concepts: list[PlanConcept] = field(default_factory=list)
    direct_terms: list[str] = field(default_factory=list)
    related_terms: list[str] = field(default_factory=list)
    drug_terms: list[str] = field(default_factory=list)
    free_terms: list[str] = field(default_factory=list)
    near: tuple[float, float] | None = None
    radius_miles: int | None = None
    statuses: list[str] = field(default_factory=lambda: list(ACTIVE_STATUSES))

    def queries(self) -> list[SearchQuery]:
        qs: list[SearchQuery] = []
        if self.direct_terms or self.free_terms:
            # direct concepts: nationwide (few trials; patients may travel), sorted by distance later
            # include active-not-recruiting studies so the UI can show (but not rank) them on request
            qs.append(SearchQuery(condition_terms=self.direct_terms + self.free_terms,
                                  statuses=self.statuses + ["ACTIVE_NOT_RECRUITING"], max_results=200))
        if self.drug_terms:
            qs.append(SearchQuery(intervention_terms=self.drug_terms, statuses=self.statuses + ["ACTIVE_NOT_RECRUITING"],
                                  max_results=100))
        if self.related_terms:
            # related concepts are broad (thousands of trials), so restrict to the travel radius
            qs.append(SearchQuery(condition_terms=self.related_terms, statuses=self.statuses, near=self.near,
                                  radius_miles=self.radius_miles if self.near else None, max_results=100))
        return qs

    def describe(self) -> dict:
        return {
            "concepts": [c.__dict__ for c in self.concepts],
            "direct_terms": self.direct_terms,
            "related_terms": self.related_terms,
            "drug_terms": self.drug_terms,
            "free_terms": self.free_terms,
            "radius_miles": self.radius_miles,
            "statuses": self.statuses,
        }


def _terms(code: str) -> list[str]:
    c = get_concept(code)
    if c is None:
        return []
    return list(c.search_terms) or [c.label]


def build_search_plan(profile, facts: PatientFacts, include_related: bool = True) -> SearchPlan:
    plan = SearchPlan()
    direct: list[str] = []
    seen: set[str] = set()

    for analyte, code in LAB_DISCOVERY.items():
        labs = facts.labs_for(analyte)
        if labs:
            lab = labs[0]
            plan.concepts.append(PlanConcept(code, get_concept(code).label,
                                             f"You have an {lab.name} result on file ({lab.ref.label}).", "direct"))
            direct.append(code)
    for cf in facts.conditions:
        if cf.assertion == "present" and cf.concept and cf.concept not in direct:
            c = get_concept(cf.concept)
            if c and c.kind in ("condition", "event", "trait"):
                plan.concepts.append(PlanConcept(cf.concept, c.label, f"You reported: {cf.name}.", "direct"))
                direct.append(cf.concept)
    # free-text conditions that are not in the vocabulary
    for row in getattr(profile, "conditions", []) or []:
        if getattr(row.assertion, "value", row.assertion) == "present" and not row.concept:
            plan.free_terms.append(row.name)

    for code in direct:
        for t in _terms(code):
            if t.lower() not in seen:
                seen.add(t.lower())
                plan.direct_terms.append(t)
        drug = CONDITION_DRUGS.get(code)
        if drug:
            plan.drug_terms.extend(t for t in _terms(drug) if t not in plan.drug_terms)
    if include_related:
        for code in direct:
            for rel in concept_index()[code].related:
                if rel in direct:
                    continue
                c = get_concept(rel)
                plan.concepts.append(PlanConcept(rel, c.label, f"Related to {get_concept(code).label.lower()}; "
                                                               "included to find trials indexed under related terms.",
                                                 "related"))
                for t in _terms(rel):
                    if t.lower() not in seen:
                        seen.add(t.lower())
                        plan.related_terms.append(t)
    if profile.latitude is not None and profile.longitude is not None:
        plan.near = (profile.latitude, profile.longitude)
        plan.radius_miles = profile.travel_radius_miles or 250
    return plan


# ----------------------------------------------------------------------------- matching


def match_reasons(r: TrialRecord, plan: SearchPlan, facts: PatientFacts) -> list[dict]:
    reasons: list[dict] = []
    trial_text = " ; ".join([r.brief_title, r.official_title or "", *r.conditions, *r.keywords])
    found = {m.code: m.text for m in find_concepts(trial_text)}
    interventions = " ; ".join(i.name + " " + " ".join(i.other_names) for i in r.interventions)
    drug_hits = {m.code: m.text for m in find_concepts(interventions, kinds=("drug", "drug_class"))}
    for pc in plan.concepts:
        if pc.code in found:
            reasons.append({
                "type": "condition", "strength": pc.weight,
                "label": f"Studies {pc.label.lower()}" if pc.weight == "direct"
                else f"Listed under a related condition: {pc.label.lower()}",
                "matched_text": found[pc.code],
                "patient_basis": pc.why,
            })
    for code, text in drug_hits.items():
        if code in [CONDITION_DRUGS.get(pc.code) for pc in plan.concepts if pc.weight == "direct"]:
            reasons.append({"type": "intervention", "strength": "direct",
                            "label": f"Tests an investigational {get_concept(code).label} ({text})",
                            "matched_text": text, "patient_basis": "Matches the condition area in your profile."})
    for term in plan.free_terms:
        if term.lower() in trial_text.lower():
            reasons.append({"type": "condition", "strength": "direct", "label": f"Mentions “{term}”",
                            "matched_text": term, "patient_basis": f"You reported: {term}."})
    return reasons


def nearest_site(r: TrialRecord, origin: tuple[float, float] | None, location_ids: list[str] | None = None) -> dict | None:
    if origin is None:
        return None
    best = None
    pref = {"RECRUITING": 0, "NOT_YET_RECRUITING": 1, "ENROLLING_BY_INVITATION": 2, None: 3}
    for idx, loc in enumerate(r.locations):
        if loc.latitude is None or loc.longitude is None:
            continue
        if loc.status not in pref:  # skip terminated/withdrawn/completed sites
            continue
        d = haversine_miles(origin, (loc.latitude, loc.longitude))
        key = (round(d), pref[loc.status])
        if best is None or key < best[0]:
            best = (key, idx, d, loc)
    if best is None:
        return None
    _, idx, d, loc = best
    return {
        "location_id": location_ids[idx] if location_ids and idx < len(location_ids) else None,
        "facility": loc.facility, "city": loc.city, "state": loc.state, "country": loc.country,
        "site_status": loc.status, "distance_miles": round(d, 1), "geo_source": loc.geo_source,
    }


def relevance(reasons: list[dict], classification: str, status: str, nearest: dict | None, radius: int | None) -> float:
    """Transparent ranking formula (also documented in the UI):
    topic match (direct 50 / drug 40 / related 20) + eligibility (eligible 25 / uncertain 12)
    + recruitment (recruiting 10 / not yet 5) + proximity (up to 15 within travel radius)."""
    topic = 0
    for rs in reasons:
        topic = max(topic, {"direct": 50 if rs["type"] == "condition" else 40, "related": 20}.get(rs["strength"], 0))
    elig = {"potentially_eligible": 25, "uncertain": 12, "potentially_ineligible": 0}.get(classification, 0)
    rec = {"RECRUITING": 10, "NOT_YET_RECRUITING": 5, "ENROLLING_BY_INVITATION": 2}.get(status, -15)
    prox = 0.0
    if nearest and radius:
        d = nearest["distance_miles"]
        prox = 15 * max(0.0, 1 - d / radius) if d <= radius else (-5 if d > 3 * radius else 0)
    return round(topic + elig + rec + prox, 1)
