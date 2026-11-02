# Privacy, security & regulatory considerations

> This is an engineering assessment to guide product decisions, not legal advice. Before handling real patient data, review it with healthcare privacy and regulatory counsel.

## 1. Is TrialCompass subject to HIPAA?

HIPAA applies to **covered entities** (most providers, health plans, clearinghouses) and to their **business associates** (vendors handling PHI on their behalf).

| Product configuration | Likely HIPAA status | Implication |
|---|---|---|
| **Direct-to-consumer app** (current MVP): individuals enter or upload their own information for their own use | Generally **not** a covered entity or business associate | HIPAA likely does not apply, but other laws do (see §2). We still build to HIPAA-grade safeguards. |
| Health system / clinic offering TrialCompass to *its* patients, or receiving data from an EHR on the provider's behalf | TrialCompass becomes a **business associate** | A BAA with each covered-entity customer; full Security Rule compliance (risk analysis, policies, workforce training, breach procedures); a BAA with each subcontractor touching PHI (cloud, LLM, email, monitoring). |
| Research sites/sponsors receiving referrals | Depends on the flow. A patient-authorized disclosure to a research site is usually covered by the patient's authorization; a site acting as a covered entity may require a BAA or data-use terms | Model it explicitly before building referral workflows. |

**Using an LLM API does not make a product HIPAA compliant.** If HIPAA applies, each vendor that receives PHI (including the LLM provider) must sign a BAA. Its data-retention and training terms must be acceptable, typically zero data retention for the relevant endpoints, and the feature must be configured within the BAA's scope. The codebase enforces this as a switch: patient data reaches the LLM only when the profile is synthetic, **or** when `ALLOW_REAL_PHI=true` **and** `LLM_BAA_IN_PLACE=true` **and** the user has opted into AI processing. Criterion interpretation sends only public registry text.

## 2. Obligations that apply even without HIPAA

- **FTC Act §5 (unfair/deceptive practices).** Privacy promises must match practice. Recent FTC actions against health apps involved sharing health data with advertising platforms. Our rule: no third-party advertising or analytics SDKs on authenticated pages; no sale of health data; no undisclosed sharing.
- **FTC Health Breach Notification Rule** (amended 2024). Consumer health apps that are not HIPAA-covered must notify users, the FTC and sometimes the media of breaches, *including unauthorized disclosures*, of identifiable health information.
- **State consumer health data laws.** Washington's *My Health My Data Act* (and Nevada's and Connecticut's equivalents) require separate consent to collect and to share consumer health data, a consumer health data privacy policy, and deletion rights, and they restrict geofencing. **State comprehensive privacy laws** (e.g. CCPA/CPRA, Texas TDPSA) treat health data as *sensitive*, requiring consent (or opt-out rights) and data-protection assessments.
- **Research-recruitment ethics.** Sponsored listings, if ever introduced, must be clearly labelled and kept out of eligibility logic. Per-referral payments from sponsors raise ethical and potential fraud-and-abuse questions (e.g. physician "finder's fees"). Patient-facing study descriptions should come from IRB-approved or registry text, as they do today.
- **FDA / software-as-a-medical-device.** The product discovers and explains trial eligibility. It does not diagnose, treat or recommend therapy, and it shows its basis so users and clinicians can independently review it. We believe it falls outside device regulation, but avoid features that recommend treatments or interpret results clinically, and re-check this as features evolve.
- **ClinicalTrials.gov terms.** Attribute the National Library of Medicine, don't imply NLM endorsement, respect rate limits, and show data currency (implemented).

## 3. Safeguards implemented in the MVP

| Area | Implementation |
|---|---|
| Authentication | Argon2id hashes; server-side revocable sessions (only SHA-256 of the token stored); httpOnly, SameSite=Lax cookies (`COOKIE_SECURE` behind TLS); login throttling |
| CSRF | Double-submit token bound to the session, required on all state-changing requests |
| Authorization (RBAC) | Account roles (`member`/`admin`); per-profile roles (`owner`/`editor`/`viewer`) via `profile_access`; unauthorized profile access returns 404 to prevent enumeration |
| Consent | Required consents (terms, privacy, health data) recorded with version and timestamp; separate opt-in for AI processing, revocable in Settings |
| Minimum necessary | No full name, phone or address collected; ZIP code only; inquiry drafts include only the facts the user selects |
| Encryption | TLS in transit (deployment); uploaded files and original filenames encrypted with Fernet (AES-128-CBC + HMAC); database encryption at rest provided by the managed Postgres/disk |
| Audit logging | Reads and writes of profiles, facts, documents, assessments and inquiries; metadata allow-listed (no clinical values or free text); IPs stored as salted hashes; user-visible activity log |
| Application logging | JSON logs with route templates (no query strings or bodies); PHI scrubber backstop; HTTP-client loggers that would print search URLs silenced |
| Data rights | Full JSON export; profile deletion and account deletion (cascading, including encrypted files) |
| Real vs synthetic separation | `ALLOW_REAL_PHI=false` by default forces all profiles to synthetic and shows a persistent banner; synthetic demo data is labelled in data and UI |
| Uploads | Size cap, type sniffing (PDF magic bytes), no execution, `Cache-Control: no-store`, `nosniff` |
| Secrets | Environment variables only; `SecretStr` in config; never logged |
| Third parties | None on authenticated pages; no analytics or ad SDKs |

## 4. Gaps to close before real patient data

1. **Formal risk analysis** (HIPAA Security Rule style) and written security policies; incident-response and breach-notification runbooks (FTC HBNR plus state laws).
2. **Infrastructure:** managed Postgres with encryption at rest and automated, encrypted, tested backups; object storage with KMS-managed keys and key rotation (replace the single Fernet key); private networking; WAF; secrets manager.
3. **Identity:** email verification, password reset, MFA (TOTP/WebAuthn), session listing and revocation, account-recovery controls.
4. **Distributed rate limiting** (Redis) and abuse protection.
5. **Field-level encryption** for the most sensitive free-text fields (excerpts, notes) and optionally for lab values.
6. **Vendor management:** BAAs/DPAs (cloud, LLM, email, monitoring); zero-data-retention configuration for any LLM endpoint receiving PHI.
7. **Privacy program:** consumer health data privacy policy (WA MHMDA), separate sharing consent, retention schedule with automatic deletion of inactive accounts, DPIAs.
8. **Security testing:** dependency scanning, SAST, penetration test; audit-log tamper evidence (append-only storage / WORM export).
9. **Accessibility** audit (WCAG 2.1 AA) and plain-language review of all patient-facing copy.
