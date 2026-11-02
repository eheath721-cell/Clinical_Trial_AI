# TrialCompass — clinical trial discovery & enrollment navigation

> *Tell us about your health, and we'll find clinical trials you may qualify for, explain why, identify where you can participate, and help you pursue enrollment.*

TrialCompass is a patient-facing web application that:

1. **Builds a health profile** with per-data-point provenance (patient-reported / extracted from a document / clinician-confirmed / unknown), including lab values with units, reference ranges and collection dates.
2. **Extracts clinical facts from uploaded records** (PDF/text) and asks the user to verify each one before it is used.
3. **Discovers trials beyond keyword search** — patient terminology is expanded into registry terms, related conditions and investigational-drug names, then searched against the **ClinicalTrials.gov API v2**.
4. **Assesses eligibility criterion by criterion** with a deterministic, evidence-linked engine (LLM only as a guarded fallback): *potentially eligible*, *eligibility uncertain* or *potentially ineligible* — never "eligible".
5. **Navigates enrollment**: nearest sites with registry-listed contacts, a draft inquiry the user controls (nothing is sent automatically), coordinator questions, document checklist, and status/follow-up tracking.

The launch use case is **elevated lipoprotein(a)**. See [docs/STATUS.md](docs/STATUS.md) for what is complete, known limitations and next steps, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions, and [docs/PRIVACY_AND_COMPLIANCE.md](docs/PRIVACY_AND_COMPLIANCE.md) for the HIPAA / privacy analysis.

> **Synthetic data only.** This MVP must not be used with real patient information until the safeguards in `docs/PRIVACY_AND_COMPLIANCE.md` are in place. With `ALLOW_REAL_PHI=false` (default) every profile is stored as synthetic and the UI shows a persistent banner.

---

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, Radix primitives (shadcn-style components), SWR |
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 (JSONB); SQLite in-memory for fast unit tests |
| Trial data | ClinicalTrials.gov Data API v2 + offline snapshot of real records |
| AI (optional) | Anthropic Messages API with structured outputs, behind validation guardrails |

```
frontend/   Next.js app (landing, auth, onboarding, profile, documents, matches, trial detail, compare, enrollment)
backend/
  app/core/         config, db, security (sessions, CSRF), audit, PHI-safe logging, encryption, storage
  app/clinical/     clinical vocabulary: concepts, synonyms, hierarchies, analytes, units
  app/modules/
    accounts/       registration, consent, login/logout, export, account deletion
    profiles/       patient profiles, conditions/labs/medications/procedures/biomarkers, screener, demo patient
    documents/      encrypted upload, rules-based (+ optional LLM) extraction, review workflow
    trials/         ClinicalTrials.gov v2 client, snapshot source, normalization, geo, search plan, ranking
    eligibility/    criteria parser, recognizers, evaluator, engine, LLM interpreter, matching service
    enrollment/     saved trials, inquiries (drafts), events, follow-up tasks
    agents/         guarded LLM client
  alembic/          migrations
  data/snapshots/   real ClinicalTrials.gov records (Lp(a)/ASCVD) for offline use
  data/synthetic/   synthetic PDFs (lab report, clinic note) for demos/tests
  tests/            engine, parsing/search, API tests
scripts/e2e_journey.js   Playwright walk-through of the full user journey
docs/               architecture, privacy/compliance, status
```

---

## Quick start (Docker)

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

For local testing the defaults in `.env` are enough. With `DOCUMENT_ENCRYPTION_KEY` left blank in development, an ephemeral key is generated, so uploaded files can't be reopened after the API restarts (extracted, accepted facts are kept). Set a real key to keep files readable; it is required in staging/production:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`TRIAL_SOURCE=auto` uses live ClinicalTrials.gov data when reachable. For exactly the data the demo was verified with, set `TRIAL_SOURCE=snapshot` in `.env`.

Open http://localhost:3000 → **Try the Lp(a) demo** (creates an account and the synthetic patient from the product brief) or **Get started** for the guided onboarding. API docs: http://localhost:8000/api/docs.

## Local development (without Docker)

Prerequisites: Python ≥ 3.11, Node ≥ 20, PostgreSQL 16.

```bash
createdb trialcompass
```

Backend:

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,llm]"
```

```bash
cp ../.env.example .env   # adjust DATABASE_URL if needed
```

```bash
alembic upgrade head && uvicorn app.main:app --reload --port 8000
```

Frontend (second terminal):

```bash
cd frontend && npm install && npm run dev
```

The browser only talks to Next.js; `/api/*` is proxied to `API_URL` (default `http://localhost:8000`), so session cookies stay first-party.

---

## Configuration

All configuration is environment-based (see [`.env.example`](.env.example)); secrets are never logged.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://trialcompass:trialcompass@localhost:5432/trialcompass` | SQLAlchemy URL |
| `DOCUMENT_ENCRYPTION_KEY` | – (ephemeral in dev) | Fernet key for documents at rest. **Required** in staging/production |
| `AUDIT_IP_SALT` | dev value | Salt for hashing client IPs in the audit log |
| `COOKIE_SECURE` | `false` | `true` behind HTTPS |
| `SESSION_TTL_HOURS` | `12` | Server-side session lifetime |
| `TRIAL_SOURCE` | `auto` | `live` (ClinicalTrials.gov API), `snapshot` (offline real records) or `auto` (live, falling back to snapshot and re-probing every 10 min) |
| `CTGOV_REQUESTS_PER_MINUTE` | `40` | Client-side rate limit (NLM asks for ≈50 req/min max) |
| `TRIAL_CACHE_TTL_HOURS` | `24` | Re-fetch trial records older than this |
| `ALLOW_REAL_PHI` | `false` | When false, all profiles are forced synthetic and the UI shows a warning banner |
| `LLM_ENABLED` / `ANTHROPIC_API_KEY` / `LLM_MODEL` | off / – / `claude-opus-5-5` | Optional LLM layer |
| `LLM_BAA_IN_PLACE` | `false` | Required (with `ALLOW_REAL_PHI`) before any non-synthetic profile data may be sent to the LLM vendor |
| `API_URL` (frontend) | `http://localhost:8000` | Backend address for the `/api` rewrite (resolved at build time) |

### ClinicalTrials.gov API

- Endpoint: `https://clinicaltrials.gov/api/v2` (`/studies`, `/studies/{nctId}`); no API key. The client rate-limits itself, retries 429/5xx with backoff, fails fast when the host is unreachable, and sends an identifying User-Agent.
- In `auto` mode the app falls back to the **offline snapshot** — 14 real registry records retrieved 2026-11-02 (`backend/data/snapshots/ctgov_lpa_snapshot.json`, provenance in its `meta` block). The UI labels snapshot data clearly and shows which fields the snapshot lacks (last-update date, site coordinates, contact phone/email).
- Refreshing the snapshot: `scripts/extract_connector_snapshot.py` + `scripts/build_snapshot.py` (see their docstrings). With live access, the app needs no snapshot.

### Optional LLM layer

Disabled by default. When `LLM_ENABLED=true` and `ANTHROPIC_API_KEY` is set:

- **Criterion interpretation** (public registry text only, no patient data) for criteria the rules cannot parse. Output is validated: thresholds must appear verbatim in the criterion, concepts must exist in the vocabulary; otherwise the criterion stays "needs review".
- **Document extraction** for profiles that are synthetic, or — only with `ALLOW_REAL_PHI=true`, `LLM_BAA_IN_PLACE=true` and the user's AI-processing consent — real profiles. Every extracted fact must quote an excerpt found verbatim in the document, and remains pending user review.

---

## Tests

```bash
cd backend && pytest
```

```bash
cd backend && DATABASE_URL=postgresql+psycopg://trialcompass:trialcompass@localhost:5432/trialcompass_test pytest
```

56 tests cover the eligibility engine against real registry criteria and synthetic profiles with known outcomes (satisfied / violated / missing / contradictory, unit handling, measurement dates, no diagnosis from a single lab, never declaring eligibility), parsing and search expansion, document extraction (including family-history exclusion), and the API (auth, CSRF, cross-account isolation, upload → review → accept, matching, saving, comparing, inquiries, deletion, no health values in audit/application logs).

Frontend type-check and build:

```bash
cd frontend && npx tsc --noEmit && npm run build
```

End-to-end browser journey (both servers running; uses Playwright):

```bash
node scripts/e2e_journey.js /tmp/shots backend/data/synthetic/synthetic_lipid_panel.pdf
```

## Demo walkthrough (synthetic Lp(a) patient)

1. **Try the Lp(a) demo** → a 24-year-old in Lubbock, TX with Lp(a) 185 nmol/L, no documented MI or CAD, not on lipid-lowering therapy.
2. **Matches**: e.g. *MOVE-Lp(a)* (muvalaplin outcomes trial) is **uncertain** — Lp(a) ≥ 175 nmol/L is met (flagged as close to the threshold) but the trial also requires a prior ASCVD event or specific risk features, which aren't recorded. *OCEAN(a)-PreEvent* has a site in Lubbock but is **potentially ineligible** (age ≥ 50 and Lp(a) ≥ 200 nmol/L). Merck's MK-7262 study requires a current statin. AstraZeneca's AZD4954 states its threshold in mg/dL, which can't be compared with a nmol/L result.
3. Upload `synthetic_lipid_panel.pdf` under **Documents**, review the extracted values (with page and excerpt), accept them, and search again.
4. Open a trial → **Contact study team** → review the draft, copy it or open it in your email app, then record that you sent it.
