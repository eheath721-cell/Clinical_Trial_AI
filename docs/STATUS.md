# Status: completed features, known limitations, next steps

_Last updated: 2026-11-02_

## Completed

**Foundation**
- [x] FastAPI modular monolith, SQLAlchemy 2 models, Alembic migration (23 tables), PostgreSQL + SQLite test support
- [x] Registration with explicit consents, login/logout, server-side sessions, CSRF, login throttling
- [x] Profile-level RBAC and multiple profiles per account (caregivers); profile switcher in the UI
- [x] Audit log (user-visible), PHI-safe JSON logging, data export, profile and account deletion
- [x] Synthetic-only guardrail (`ALLOW_REAL_PHI=false`) with persistent banner

**Patient health profile**
- [x] Demographics (DOB or age, sex, ZIP → offline geocoding, travel radius)
- [x] Conditions, labs (value, unit as reported, reference range, collection date), medications (current/past/not current/never), procedures, genetic/biomarker results
- [x] Provenance on every data point (patient-reported / document-extracted / clinician-confirmed / unknown) plus verification state
- [x] Yes / No / Not-sure screener where "Not sure" is stored as unknown, never as a guess
- [x] Guided onboarding wizard; one-click synthetic Lp(a) demo patient from the brief

**Documents**
- [x] Encrypted upload (PDF/text), page-level text extraction
- [x] Rules-based extraction: labs with units, flags, reference ranges and collection dates; diagnoses and procedures with negation; medications with status; genetic variants; family-history mentions excluded; contradictory mentions flagged
- [x] Review workflow: accept / edit / reject each item, with page and verbatim excerpt; nothing used until accepted
- [x] Optional LLM extraction pass behind PHI gating and verbatim-excerpt validation

**Trial discovery**
- [x] ClinicalTrials.gov API v2 client (rate limiting, retries, fast fail, caching) with `live | snapshot | auto` modes and periodic re-probe
- [x] Offline snapshot of 14 real Lp(a)/ASCVD registry records with provenance metadata
- [x] Concept-expanded search plan (direct terms, Lp(a)-targeted drugs, related conditions within travel radius)
- [x] Normalized storage of all brief-listed fields (NCT ID, titles, summaries, phase, type, interventions, conditions, criteria, age/sex, status, locations, PI when available, sponsor, enrollment, dates, last update, source URL), with explicit field-gap disclosure
- [x] Study-category classification (outcomes vs biomarker vs imaging vs early-phase vs observational)
- [x] Distance to sites (registry coordinates or ZIP centroids; approximate distances labelled)

**Eligibility engine**
- [x] Criteria tree parser (nesting, ANY/ALL groups, cohorts, partial-list detection)
- [x] Recognizers for age, sex, lab thresholds (alternative units, ranges, ×ULN), qualitative labs, conditions/events with time windows, severity/control qualifiers, screening-assessed findings, medications (current / within window / ever / stable-if-current), procedures (history / planned), pregnancy, protocol-defined ("vague") items, administrative and investigator items
- [x] Evaluator with evidence, explanations, missing information, coordinator questions; three-way classification; per-cohort evaluation
- [x] Guarded LLM interpreter for unparsed criteria (validated against criterion text)

**Dashboard and UX**
- [x] Landing page, auth, onboarding, matches dashboard (classification tiles, filters for distance/phase/status/study type/treatment, four sort orders, "how we searched and ranked"), save, compare (up to 4), trial detail with criterion-by-criterion breakdown and sources, locations with registry contacts, about-the-study
- [x] Responsive layout with a mobile tab bar

**Enrollment navigation**
- [x] Inquiry drafts (user chooses which facts to share; registry contacts only; nothing auto-sent), copy / open in mail app
- [x] Status timeline (sent → response → pre-screen → screening → enrolled / not eligible / declined), notes, follow-up tasks with due dates, document checklist, coordinator questions

**Quality**
- [x] 56 backend tests (engine on real criteria plus synthetic profiles, parsing/search, extraction, API, privacy), passing on SQLite and PostgreSQL
- [x] Frontend type-check and production build
- [x] Playwright end-to-end journey script (sign-up → onboarding → upload/review → matches → breakdown → save → compare → inquiry → tracking → mobile), passing with no console errors
- [x] Dockerfiles, docker-compose, CI workflow

## Known limitations

1. **Live ClinicalTrials.gov access not verified in the build environment.** The development sandbox's network policy blocked `clinicaltrials.gov`, so all end-to-end runs used the snapshot (`auto` mode fell back correctly). The live adapter is tested against a schema-shaped v2 fixture only. **First action in a networked environment:** run with `TRIAL_SOURCE=live` and confirm search, detail and geo filters.
2. **Snapshot gaps:** no last-update date, site coordinates (ZIP centroids used), contact phone/email or PI names. All are labelled in the UI.
3. **Vocabulary scope:** recognizers cover the cardiometabolic domain (50 concepts, 17 analytes). Criteria in other therapeutic areas will mostly show as *needs review* until the vocabulary grows or the LLM interpreter is enabled.
4. **LLM paths not exercised against the live API** (no key in the build environment). Validation guardrails are unit-tested.
5. **Rules-based NLP limits:** complex syntax (nested exceptions, "unless", cross-references to other criteria, numeric criteria for non-vocabulary measures such as body weight) may be misread or marked *needs review*. Explanations always show the verbatim criterion so users and coordinators can check.
6. **No OCR** for scanned PDFs (flagged as "no selectable text").
7. **Identity features missing:** email verification, password reset, MFA. Rate limiting is in-memory (single instance).
8. **Profile sharing:** the data model and RBAC support delegated access, but there is no invite UI/API yet.
9. **Synchronous matching:** a refresh runs in the request (fine for tens of trials; needs a worker for hundreds).
10. **Distances** are straight-line, not travel time.
11. **No notifications** (new trials, status changes, task reminders by email/SMS).
12. **Docker images not built in the build environment** (no Docker daemon was available). The Dockerfiles and compose file follow the verified local setup (Postgres 16, `alembic upgrade head`, `next build`/`next start`) but should be smoke-tested once.

## Next steps (prioritized)

1. Verify and tune the live API integration (pagination, `filter.geo`, `fields` to reduce payload, MeSH-based expansion from `derivedSection`).
2. Background jobs plus nightly sync of relevant registry slices; "new trial may fit you" alerts.
3. Expand the vocabulary using MeSH/SNOMED/RxNorm/LOINC mappings, and build an evaluation set of 200+ annotated criteria to measure recognizer precision/recall.
4. Enable the LLM interpreter with an eval harness (agreement with clinician annotations, refusal and error rates), effort tuning, and cost tracking.
5. pgvector embeddings for long-tail recall; measure search recall against clinician-curated relevance judgments for 10 conditions.
6. Identity hardening (MFA, verification, reset), Redis rate limiting, object storage with KMS, field-level encryption.
7. Caregiver invitations and clinician-confirmation workflow (`clinician_confirmed` provenance via secure share link).
8. OCR for scanned documents; FHIR / SMART-on-FHIR import (patient-authorized) to reduce manual entry.
9. Referral workflow pilots with research sites (explicit authorization, site agreements, IRB-approved language).
10. Accessibility audit and plain-language review; usability testing with patients and caregivers.

## Business notes

Initial revenue options, in order of trust risk (lowest first): enterprise subscriptions for health systems and research sites (navigation tooling); an API for patient-facing apps; recruitment partnerships billed per **qualified, patient-initiated** inquiry with full disclosure; premium patient features. Principles: no sale of identifiable health data; any sponsored listing is clearly labelled and never touches eligibility logic or organic ranking.
