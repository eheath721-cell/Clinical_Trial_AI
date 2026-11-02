export type Classification = "potentially_eligible" | "uncertain" | "potentially_ineligible";
export type Outcome =
  | "satisfied"
  | "not_satisfied"
  | "unknown"
  | "needs_review"
  | "conflicting"
  | "not_applicable"
  | "confirm_with_team";

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  consents: Record<string, boolean>;
}

export interface ProfileSummary {
  id: string;
  display_name: string;
  relationship: string;
  is_synthetic: boolean;
  onboarding_completed: boolean;
  city: string | null;
  state: string | null;
}

export interface ProvenanceFields {
  id: string;
  provenance: "patient_reported" | "document_extracted" | "clinician_confirmed" | "unknown";
  verification: "confirmed" | "pending_review" | "rejected";
  source_document_id: string | null;
  source_page: number | null;
  source_excerpt: string | null;
  extraction_method: string | null;
  notes: string | null;
  confirmed_at: string | null;
  created_at: string | null;
}

export interface ConditionRow extends ProvenanceFields {
  concept: string | null;
  name: string;
  assertion: "present" | "absent" | "unknown";
  onset_date: string | null;
  qualifiers: Record<string, unknown>;
}
export interface LabRow extends ProvenanceFields {
  analyte: string;
  display_name: string;
  value_numeric: number | null;
  value_text: string | null;
  unit: string | null;
  reference_low: number | null;
  reference_high: number | null;
  reference_text: string | null;
  collected_on: string | null;
}
export interface MedicationRow extends ProvenanceFields {
  concept: string | null;
  name: string;
  status: "current" | "past" | "not_current" | "never" | "unknown";
  dose: string | null;
  started_on: string | null;
  stopped_on: string | null;
}
export interface ProcedureRow extends ProvenanceFields {
  concept: string | null;
  name: string;
  assertion: "present" | "absent" | "unknown";
  performed_on: string | null;
}
export interface BiomarkerRow extends ProvenanceFields {
  name: string;
  result: string;
  interpretation: string | null;
  tested_on: string | null;
}

export interface Profile {
  id: string;
  display_name: string;
  relationship: string;
  is_synthetic: boolean;
  date_of_birth: string | null;
  age_years_reported: number | null;
  age: number | null;
  sex: "female" | "male" | "intersex" | "unknown";
  can_become_pregnant: "present" | "absent" | "unknown";
  postal_code: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  has_coordinates: boolean;
  travel_radius_miles: number;
  additional_info: string | null;
  onboarding_completed: boolean;
  conditions: ConditionRow[];
  labs: LabRow[];
  medications: MedicationRow[];
  procedures: ProcedureRow[];
  biomarkers: BiomarkerRow[];
}

export interface Vocab {
  screener: { concept: string; label: string; question: string | null }[];
  conditions: { code: string; label: string }[];
  procedures: { code: string; label: string }[];
  medications: { code: string; label: string }[];
  analytes: { code: string; label: string; units: string[]; convertible: boolean; note: string | null }[];
}

export interface StudyCategory {
  code: string;
  label: string;
  explanation: string;
  basis: string;
}

export interface TrialSummary {
  nct_id: string;
  title: string;
  official_title: string | null;
  acronym: string | null;
  brief_summary: string | null;
  phases: string[];
  phase_label: string;
  status: string;
  status_label: string;
  study_type: string | null;
  conditions: string[];
  interventions: string[];
  sponsor: string | null;
  enrollment_target: number | null;
  start_date: string | null;
  primary_completion_date: string | null;
  completion_date: string | null;
  last_update_posted: string | null;
  data_source: "live" | "snapshot";
  retrieved_at: string | null;
  source_url: string;
  study_category: StudyCategory | null;
  field_gaps: string[];
  location_count: number;
  minimum_age: string | null;
  maximum_age: string | null;
  sex: string | null;
  healthy_volunteers: boolean | null;
}

export interface Contact {
  name: string | null;
  role: string | null;
  phone: string | null;
  email: string | null;
}

export interface TrialLocation {
  id: string;
  facility: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  status: string | null;
  status_label: string;
  distance_miles: number | null;
  geo_source: string | null;
  contacts: Contact[];
}

export interface TrialDetail extends TrialSummary {
  detailed_description: string | null;
  keywords: string[];
  interventions_full: { name: string; type: string | null; description: string | null }[];
  eligibility_text: string | null;
  collaborators: string[];
  overall_officials: { name: string | null; affiliation: string | null; role: string | null }[];
  central_contacts: Contact[];
  primary_outcomes: { measure: string; time_frame: string | null; description: string | null }[];
  status_verified_date: string | null;
  locations: TrialLocation[];
}

export interface NearestSite {
  location_id: string | null;
  facility: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  site_status: string | null;
  distance_miles: number | null;
  geo_source: string | null;
}

export interface MatchReason {
  type: string;
  strength: "direct" | "related";
  label: string;
  matched_text: string;
  patient_basis: string;
}

export interface Evidence {
  kind: "trial_criterion" | "patient_fact";
  text?: string;
  source_url?: string;
  nct_id?: string;
  fact_type?: string;
  fact_id?: string;
  label?: string;
  provenance?: string;
  verification?: string;
  document_id?: string;
  document_name?: string;
  source_page?: number;
  source_excerpt?: string;
  recorded_on?: string;
}

export interface CriterionRow {
  position: number;
  depth: number;
  kind: "inclusion" | "exclusion";
  text: string;
  category: string;
  outcome: Outcome;
  patient_information: string;
  explanation: string;
  evidence: Evidence[];
  cohort: string | null;
  is_group: boolean;
  source: string | null;
  missing: string[];
  requirement: Record<string, unknown>;
}

export interface Assessment {
  id: string;
  nct_id: string;
  classification: Classification;
  summary: string;
  key_reasons: string[];
  missing_information: string[];
  potential_exclusions: string[];
  match_reasons: MatchReason[];
  relevance_score: number;
  nearest_site: NearestSite | null;
  counts: Record<string, number>;
  caveats: string[];
  questions: string[];
  best_cohort: string | null;
  engine_version: string;
  assessed_at: string;
  pending_facts_count: number;
  criteria?: CriterionRow[];
}

export interface MatchItem {
  trial: TrialSummary;
  assessment: Assessment;
  saved: boolean;
}

export interface SourceStatus {
  mode: string;
  active: "live" | "snapshot";
  live_reachable: boolean | null;
  snapshot_retrieved_at: string | null;
  message: string;
}

export interface MatchesResponse {
  items: MatchItem[];
  total: number;
  facets: Record<string, Record<string, number>>;
  source: SourceStatus;
}

export interface RefreshSummary {
  trials_found: number;
  assessed: number;
  data_source: string;
  source_message: string;
  plan: {
    concepts: { code: string; label: string; why: string; weight: string }[];
    direct_terms: string[];
    related_terms: string[];
    drug_terms: string[];
    free_terms: string[];
    radius_miles: number | null;
  };
  pending_review_count: number;
}

export interface ExtractedFact {
  id: string;
  document_id: string;
  fact_type: "lab" | "condition" | "medication" | "procedure" | "biomarker";
  payload: Record<string, unknown>;
  source_page: number | null;
  source_excerpt: string | null;
  method: string;
  confidence: number | null;
  warnings: string[];
  review_status: "pending" | "accepted" | "rejected";
  created_fact_id: string | null;
}

export interface DocumentRow {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  doc_type: string;
  status: string;
  page_count: number | null;
  extraction_methods: string[];
  error_code: string | null;
  uploaded_at: string;
  pending_count: number;
  fact_count: number;
  facts?: ExtractedFact[];
}

export interface Inquiry {
  id: string;
  nct_id: string;
  status: string;
  trial: TrialSummary;
  location: {
    id: string;
    facility: string | null;
    city: string | null;
    state: string | null;
    country: string | null;
    status: string | null;
    status_text: string;
    status_label: string;
  } | null;
  contact: {
    name: string | null;
    role: string | null;
    phone: string | null;
    email: string | null;
    scope: string;
    facility: string | null;
    source: string;
  } | null;
  shared_fields: string[];
  email_subject: string | null;
  email_body: string | null;
  questions: string[];
  document_checklist: { key: string; label: string; reason: string; have: boolean }[];
  sent_at: string | null;
  last_response_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  events: { type: string; note: string | null; at: string }[];
}

export interface Task {
  id: string;
  title: string;
  due_on: string | null;
  status: "open" | "done";
  inquiry_id: string | null;
  overdue: boolean;
}

export interface SavedTrial {
  nct_id: string;
  note: string | null;
  saved_at: string;
  trial: TrialSummary | null;
  classification: Classification | null;
  nearest_site: NearestSite | null;
}

export interface PublicConfig {
  app_name: string;
  environment: string;
  synthetic_data_only: boolean;
  llm_available: boolean;
  trial_source: SourceStatus;
}
