# Architecture & key decisions

## 1. System overview

```
Browser ──► Next.js (UI, /api rewrite) ──► FastAPI modular monolith ──► PostgreSQL
                                              │
                                              ├─► ClinicalTrials.gov API v2 (rate-limited, cached in DB)
                                              │      └─ fallback: offline snapshot of real records
                                              ├─► Encrypted document store (local disk → S3 + KMS later)
                                              └─► Optional LLM (Anthropic, structured outputs, guarded)
```

A **modular monolith**: one deployable API with strict module boundaries, no microservices at MVP stage.

| Module | Responsibility | Key tables |
|---|---|---|
| `accounts` | registration, consent records, sessions, export, deletion | `users`, `auth_sessions`, `consents`, `audit_events` |
| `profiles` | patient health information with provenance; caregivers manage several profiles | `patient_profiles`, `profile_access`, `conditions`, `lab_results`, `medications`, `procedures`, `biomarker_results` |
| `documents` | encrypted upload, extraction, review | `documents`, `extracted_facts` |
| `trials` | source adapters, normalization, ingestion, search plan, ranking, geo | `clinical_trials`, `trial_locations`, `trial_criteria` |
| `eligibility` | criteria parsing, evaluation, classification, explanations | `eligibility_assessments`, `criterion_evaluations` |
| `agents` | guarded LLM access (one choke point for PHI gating) | – |
| `enrollment` | saved trials, inquiries, events, follow-up tasks | `saved_trials`, `enrollment_inquiries`, `inquiry_events`, `follow_up_tasks` |

## 2. Data flow for a match

1. **Profile → facts.** `build_patient_facts` loads only *confirmed* facts. Extracted-but-unreviewed items are counted and surfaced ("3 items awaiting review were not used"), never used.
2. **Facts → search plan.** `build_search_plan` maps facts to vocabulary concepts. An Lp(a) result activates the *elevated Lp(a)* concept: direct registry terms (`lipoprotein(a)`, `Lp(a)`, `hyperlipoproteinemia(a)`…), Lp(a)-targeted drug names, and *related* conditions (ASCVD, CAD, aortic stenosis, dyslipidemia). Related concepts widen discovery only. Broad related queries are restricted to the travel radius; direct queries are nationwide and sorted by distance later.
3. **Source → records.** `TrialRepository` queries the live API (or snapshot), normalizes every record to `TrialRecord`, and lists any fields the source could not supply in `field_gaps`.
4. **Ingestion.** Trials are upserted by NCT ID. Criteria are parsed into `trial_criteria` (re-parsed only when the criteria text hash or parser version changes). Study category is classified from the registry's primary outcomes.
5. **Assessment.** The engine evaluates every criterion and stores an `eligibility_assessment` with one `criterion_evaluation` per criterion (verbatim text, patient information, outcome, explanation, evidence). Assessments are versioned (`is_current`). They are recomputed automatically when the profile fingerprint, pending-review count or engine version changes.
6. **Ranking.** A transparent formula, shown to users: topic match + eligibility fit + recruitment status + proximity.

## 3. Eligibility engine (hybrid: deterministic first)

```
eligibility text ─► criteria_parser ─► tree of nodes (inclusion/exclusion, nesting, ANY/ALL groups, cohorts)
                         │
                         ▼
                  recognizers (rules) ─► structured requirement  (or "unparsed")
                         │                    │
                         │      [optional] LLM interpreter → validated requirement
                         ▼
 patient facts ─► evaluator ─► true / false / unknown / review / conflict / n/a / confirm
                         │
                         ▼
                  engine: per-criterion outcome, evidence, explanation, missing info,
                          coordinator questions, classification (per cohort, best wins)
```

**Design rules (and why):**

- **Missing ≠ negative.** "No record" is *unknown*. *Absent* requires an explicit statement ("No", "denies", "no history of"), or every member of an umbrella concept being explicitly absent (for example, ASCVD is absent only if MI, CAD, stroke and PAD are each absent).
- **No invented thresholds.** Numbers come only from the criterion text. "Elevated Lp(a)" without a number is *needs review*, even when the patient's value exceeds the lab's reference range.
- **Units are preserved, and Lp(a) is never converted.** nmol/L ↔ mg/dL for Lp(a) depends on apo(a) isoform size. LDL-C/HDL/TC (×38.67), triglycerides (×88.57) and ApoB (g/L ×100) use exact factors, and both the original and converted values are shown.
- **Dates matter.** The most recent dated result is used, and earlier results on the other side of a threshold are mentioned. Results older than an analyte-specific window (for example 12 months for LDL-C) become *needs review*. Time-windowed criteria ("MI within 90 days") need event dates.
- **No diagnosis from labs.** Condition requirements consult only condition facts. An LDL-C of 250 is not FH, and an Lp(a) of 300 is not ASCVD.
- **Contradictions surface.** The same concept recorded as present (for example from a document) and absent (for example patient-reported) gives *conflicting*, with both sources cited.
- **Severity/control qualifiers** ("uncontrolled hypertension", "NYHA class III–IV") are checked only when the qualifier is recorded. Otherwise they are *needs review*.
- **Administrative and investigator-judgment items** (consent, contraception, "clinically significant per investigator") are listed as *Study team confirms* and never affect classification.
- **Multi-cohort studies** (for example "Part A healthy volunteers / Part B dyslipidemia") are evaluated per cohort, and the best-matching cohort is reported.
- **Classification.** *Potentially ineligible* if any clinical criterion conflicts. *Uncertain* if any clinical inclusion criterion can't be evaluated. Otherwise *potentially eligible*, with unknown exclusions listed "to confirm". Summaries always state that the study team decides.
- **Traceability.** Every criterion evaluation carries the trial-criterion evidence (text and registry URL) plus each patient fact used: provenance, verification, document, page and verbatim excerpt.

**Distinguishing biomarker studies from outcome trials.** `classify_study` reads the registry's primary outcomes: MACE / time-to-event → *cardiovascular outcomes trial*; percent change in Lp(a)/LDL-C → *biomarker-lowering*; plaque / CCTA → *imaging*; Phase 1 safety/PK → *early-phase safety*. Outcome trials show an explainer that elevated Lp(a) alone is usually insufficient, and the criteria breakdown shows exactly which ASCVD/risk requirement is missing.

## 4. Key decisions and trade-offs

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| D1 | **Deterministic rules first, LLM as a validated fallback** | LLM-only eligibility reasoning | Rules are auditable, reproducible, free and testable. LLM output can't add thresholds or concepts not grounded in the criterion text. Unparsed criteria are honestly marked *needs review*. |
| D2 | **Concept-graph query expansion instead of embeddings (for now)** | pgvector semantic search | Expansion is explainable ("searched X because of your Y"). The registry already applies synonym expansion, and recall for a focused vocabulary is high. Embeddings are a planned addition for long-tail terminology (see STATUS). |
| D3 | **Modular monolith (FastAPI) + Next.js BFF rewrite** | microservices; Next.js API routes | Fewer moving parts. Python keeps the clinical NLP close to the data. The rewrite keeps cookies first-party with no CORS. |
| D4 | **Server-side sessions (httpOnly cookie) + double-submit CSRF** | JWT in localStorage | Revocable sessions, no token exposure to XSS, audit-friendly. |
| D5 | **Separate tables per clinical fact type with a shared provenance mixin** | single EAV "facts" table | Type safety for units/dates/assertions while keeping provenance uniform. |
| D6 | **Extracted facts are staged** (`extracted_facts`) and copied to the profile only on acceptance | write directly with a "pending" flag | Guarantees unverified data can't leak into assessments. Rejections are retained for audit/QA. |
| D7 | **Assessments persisted per criterion, versioned** | compute on every view | History and auditability ("what did we tell the user, based on what?"). Lets ranking and filters run in SQL. |
| D8 | **Offline snapshot of real registry data** (verbatim, with provenance metadata) | hard-coded sample trials | The dev environment could not reach clinicaltrials.gov. A real-data snapshot keeps demos and tests faithful, with gaps labelled in the UI. |
| D9 | **Offline ZIP-centroid geocoding** for patients | third-party geocoder | The patient's location never leaves our servers. Registry coordinates are preferred for sites when available. |
| D10 | **Never send messages on the user's behalf (MVP)** | automated referral | Explicit user control over PHI disclosure. Referral workflows need site/sponsor agreements and consent flows (see next steps). |

## 5. ClinicalTrials.gov API v2 — capabilities and limitations

- **Search** is keyword/Essie-expression based (`query.cond`, `query.intr`, `query.term`, `filter.overallStatus`, `filter.geo=distance(lat,lon,Nmi)`), with registry synonym expansion. It is not semantic, so we expand terms first.
- **Eligibility criteria are free text** with inconsistent formatting (nested bullets, numbered lists, "Part A/Part B" cohorts, escaped markdown). Many sponsors publish only "main criteria … not limited to". We detect and disclose this.
- **Recruitment status** is sponsor-reported at study and site level and can lag reality. `lastUpdatePostDate` and `statusVerifiedDate` are shown. Sites are never described as "accepting participants", only as "listed in the registry as Recruiting".
- **Contacts** are often generic ("Study Coordinator") or missing. We copy them exactly and fall back to the registry page, never inventing details.
- **Rate limits:** about 50 requests/minute per IP. The client throttles itself to 40/min, retries transient errors, and caches records in Postgres (24 h TTL).
- **Coverage:** ClinicalTrials.gov covers most U.S. and many international studies, but not all sponsor-only or ex-U.S. registries. Additional sources plug in through the `TrialSource` protocol (official APIs or licensed feeds only, no indiscriminate scraping), for example WHO ICTRP, EU CTIS, ISRCTN and sponsor/hospital feeds.

## 6. Security architecture (summary)

Argon2id password hashing; revocable server-side sessions storing only token hashes; CSRF double-submit; profile-level RBAC (owner/editor/viewer, 404 on unauthorized access to prevent ID probing); login throttling; Fernet encryption of uploaded files and original filenames; audit log of reads/writes with an allow-listed metadata schema and salted IP hashes; JSON logs that record route templates only, with a PHI scrubber as a backstop and HTTP-client loggers silenced; strict upload validation (type sniffing, size cap); security headers; data export and hard deletion. Details and gaps are in [PRIVACY_AND_COMPLIANCE.md](PRIVACY_AND_COMPLIANCE.md).

## 7. Scaling path

1. Move matching to a background worker (RQ/Celery/Arq) with progress events; batch registry calls.
2. Nightly incremental sync of relevant registry slices (by condition) plus change detection on `lastUpdatePostDate`, triggering notifications ("a new trial may fit you").
3. pgvector embeddings over titles, conditions and criteria for long-tail recall. Keep explanation via matched concepts and snippets.
4. Expand the vocabulary through standard terminologies (SNOMED CT, RxNorm, LOINC, MeSH from the registry's `derivedSection`).
5. Object storage with KMS (S3/GCS), managed Postgres with encryption at rest, private networking, WAF, and centralized audit export to a SIEM.
