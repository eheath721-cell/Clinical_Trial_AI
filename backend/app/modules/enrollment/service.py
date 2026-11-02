"""Enrollment navigation: draft inquiries for the USER to review and send.

Principles
  * The platform never sends email or shares health information. It drafts; the user edits,
    copies or opens their own mail client, and records what happened.
  * Only confirmed profile facts that the user explicitly selects are included
    ("minimum necessary").
  * Contacts are copied exactly as listed in the registry. If the registry lists no contact,
    the draft says so and points to the registry page - nothing is invented.
  * A site is never described as "accepting participants" - only "listed in the registry as
    Recruiting (as of <date>)".
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.models import ClinicalTrial, EligibilityAssessment, PatientProfile, TrialLocation
from app.modules.eligibility.patient import PatientFacts

SITE_STATUS_TEXT = {
    "RECRUITING": "listed in the registry as Recruiting",
    "NOT_YET_RECRUITING": "listed in the registry as Not yet recruiting",
    "ENROLLING_BY_INVITATION": "listed in the registry as Enrolling by invitation",
    "ACTIVE_NOT_RECRUITING": "listed in the registry as Active, not recruiting",
}

GENERIC_QUESTIONS = [
    "Is this site currently enrolling new participants?",
    "What does screening involve, and how many visits would it take?",
    "How long does participation last, and how often are visits?",
    "Are travel or other costs reimbursed?",
    "Which of my medical records would you need before a screening visit?",
]


def contact_for(trial: ClinicalTrial, location: TrialLocation | None) -> dict:
    """Pick the most specific contact the registry lists. Never fabricates details."""
    if location is not None and location.contacts:
        c = location.contacts[0]
        return {"name": c.get("name"), "role": c.get("role"), "phone": c.get("phone"), "email": c.get("email"),
                "scope": "site", "facility": location.facility,
                "source": "Site contact listed on ClinicalTrials.gov"}
    if trial.central_contacts:
        c = trial.central_contacts[0]
        return {"name": c.get("name"), "role": c.get("role"), "phone": c.get("phone"), "email": c.get("email"),
                "scope": "central", "facility": None, "source": "Central contact listed on ClinicalTrials.gov"}
    return {"name": None, "role": None, "phone": None, "email": None, "scope": "none", "facility": None,
            "source": "No contact details are listed in the registry record available to us. Use the "
                      "'Contacts and Locations' section of the ClinicalTrials.gov page."}


def shareable_facts(facts: PatientFacts) -> list[dict]:
    """Facts the user may choose to include. Keys are stable so the UI can toggle them."""
    out: list[dict] = []
    if facts.age_years is not None:
        out.append({"key": "age", "label": f"Age: {facts.age_years:g}", "default": True})
    seen_labs: set[tuple] = set()
    for analyte in dict.fromkeys(lab.analyte for lab in facts.labs):
        # most recent first; identical value/unit repeats (e.g. typed in and also extracted) are offered once
        for i, lab in enumerate(facts.labs_for(analyte)):
            if lab.value is None or (analyte, lab.value, lab.unit) in seen_labs:
                continue
            seen_labs.add((analyte, lab.value, lab.unit))
            when = f" (measured {lab.collected_on:%b %d, %Y})" if lab.collected_on else ""
            out.append({"key": f"lab:{lab.ref.fact_id}", "label": f"{lab.name}: {lab.value:g} {lab.unit or ''}{when}".strip(),
                        "default": analyte == "lpa" and i == 0})
    for c in facts.conditions:
        if c.assertion == "present":
            out.append({"key": f"cond:{c.ref.fact_id}", "label": f"Diagnosis: {c.name}", "default": False})
        elif c.assertion == "absent":
            out.append({"key": f"cond:{c.ref.fact_id}", "label": f"No history of {c.name.lower()} (self-reported)",
                        "default": False})
    for m in facts.meds:
        words = {"current": "Currently taking", "past": "Previously took", "not_current": "Not currently taking",
                 "never": "Never taken"}
        if m.status in words:
            out.append({"key": f"med:{m.ref.fact_id}", "label": f"{words[m.status]} {m.name.lower()}", "default": False})
    return out


def draft_email(trial: ClinicalTrial, profile: PatientProfile, location: TrialLocation | None, contact: dict,
                shared: list[dict], questions: list[str], distance_miles: float | None) -> tuple[str, str]:
    title = trial.acronym or trial.brief_title
    subject = f"Question about the {title} study ({trial.nct_id})"
    if location is not None and location.facility:
        subject += f" at {location.facility}"
    greeting = f"Hello {contact['name']}," if contact.get("name") and contact["name"].lower() not in (
        "study coordinator", "research site") else "Hello,"
    lines = [greeting, ""]
    where = ""
    if location is not None:
        place = ", ".join(p for p in [location.city, location.state] if p)
        where = f" at your {location.facility or 'site'}{' in ' + place if place else ''}"
    lines.append(f"I found the study “{trial.brief_title}” ({trial.nct_id}) on ClinicalTrials.gov and would "
                 f"like to learn whether I might be a candidate to participate{where}.")
    if shared:
        lines += ["", "Some information that may be relevant:"]
        lines += [f"- {s['label']}" for s in shared]
    lines += ["", "I understand that eligibility can only be determined by the study team. I would appreciate it if you "
                  "could let me know:"]
    lines += [f"- {q}" for q in questions]
    home = ", ".join(p for p in [profile.city, profile.state] if p)
    if home:
        lines += ["", f"I live in {home}" + (f", about {distance_miles:.0f} miles from your site." if distance_miles else ".")]
    lines += ["", "I can share copies of relevant medical records if that would help.", "", "Thank you for your time,",
              "[Your name]", "[Your phone number or email]"]
    return subject, "\n".join(lines)


def build_questions(assessment: EligibilityAssessment | None, location: TrialLocation | None) -> list[str]:
    qs: list[str] = []
    if location is None:
        qs.append("Which of your sites is closest to me, and is it currently enrolling?")
    else:
        qs.append(GENERIC_QUESTIONS[0])
    if assessment is not None:
        for q in (assessment.counts or {}).get("_questions", [])[:3]:
            qs.append(q)
        tests = [m for m in (assessment.missing_information or []) if re.search(r"\b(result|score|level)\b", m, re.I)]
        for m in tests[:2]:  # only measurable items can be "checked at screening"; history questions can't
            qs.append(f"I don't have a {m[0].lower() + m[1:]} on file. Is that something you would measure at screening?")
    qs += GENERIC_QUESTIONS[1:]
    seen: list[str] = []
    for q in qs:
        if q not in seen:
            seen.append(q)
    return seen[:8]


def document_checklist(trial: ClinicalTrial, assessment: EligibilityAssessment | None, doc_types: set[str]) -> list[dict]:
    items = [
        {"key": "lab_report", "label": "Most recent lab report (lipid panel, including Lp(a) if measured)",
         "reason": "Studies in this area use lab values in their eligibility criteria.", "have": "lab_report" in doc_types},
        {"key": "medication_list", "label": "Current medication list with doses",
         "reason": "Many criteria depend on current or past medications.", "have": "medication_list" in doc_types},
        {"key": "physician_note", "label": "Recent visit notes or a problem list from your clinician",
         "reason": "Helps the team confirm diagnoses and history.", "have": "physician_note" in doc_types},
    ]
    missing = " ".join(assessment.missing_information if assessment else []).lower()
    if "calcium" in missing or "imaging" in missing or (trial.study_category or {}).get("code") == "imaging":
        items.append({"key": "imaging", "label": "Any heart imaging reports (e.g. coronary CT or calcium score)",
                      "reason": "Some criteria refer to imaging findings.", "have": False})
    if "genetic" in missing or "familial" in missing:
        items.append({"key": "genetic_report", "label": "Genetic test results (if you have had genetic testing)",
                      "reason": "Some criteria refer to inherited lipid disorders.", "have": "genetic_report" in doc_types})
    items.append({"key": "id_insurance", "label": "Photo ID (and insurance card if the site asks for it)",
                  "reason": "Commonly requested at screening visits.", "have": False})
    return items


def default_tasks(today: date | None = None) -> list[tuple[str, date]]:
    today = today or date.today()
    return [("Review and send your inquiry email", today + timedelta(days=1)),
            ("Follow up if you haven't heard back", today + timedelta(days=8))]
