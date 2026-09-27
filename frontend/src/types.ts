// Mirrors backend/app/models.py and backend/app/schemas.py

export type EntityType = "person" | "company" | "address" | "wallet";
export type RiskLevel = "none" | "low" | "medium" | "high" | "critical" | "incomplete";

export interface Provenance {
  source: string;
  source_label: string;
  record_id: string | null;
  url: string | null;
  retrieved_at: string;
}

export interface DocumentRef {
  title: string;
  kind: string;
  date: string | null;
  url: string | null;
  summary: string | null;
  source: string;
  flags: string[];
}

export interface Entity {
  id: string;
  type: EntityType;
  name: string;
  aliases: string[];
  birth_date: string | null;
  nationalities: string[];
  jurisdiction: string | null;
  registration_number: string | null;
  legal_form: string | null;
  status: "active" | "dissolved" | "unknown" | null;
  incorporation_date: string | null;
  dissolution_date: string | null;
  last_accounts_date: string | null;
  activity: string | null;
  address: string | null;
  identifiers: Record<string, string>;
  is_offshore: boolean;
  chain: string | null;
  demo: boolean;
  documents: DocumentRef[];
  record_ids: string[];
  sources: Provenance[];
  extra: Record<string, unknown>;
}

export type RelationType = "officer" | "shareholder" | "beneficial_owner" | "registered_at" | "controls" | "transfer" | "relative";

export interface Relationship {
  id: string;
  type: RelationType;
  source_id: string;
  target_id: string;
  role: string | null;
  share_pct: number | null;
  amount: number | null;
  currency: string | null;
  tx_count: number | null;
  start_date: string | null;
  end_date: string | null;
  sources: Provenance[];
}

export interface ScreeningHit {
  entity_id: string;
  list_type: "sanction" | "pep" | "leak" | "adverse";
  dataset: string;
  matched_name: string;
  score: number;
  explanation: string[];
  details: Record<string, unknown>;
  provenance: Provenance;
  triage?: "likely" | "verify" | "namesake" | "dismissed" | null;
  triage_reasons?: string[];
}

export interface SearchCandidate {
  entity: Entity;
  score: number;
  explanation: string[];
  linked_companies: string[];
  roles_count: number;
}

export interface SearchResponse {
  query: string;
  type: string;
  candidates: SearchCandidate[];
  sources: string[];
  warnings: string[];
}

export interface RiskFactor {
  key: string;
  label: string;
  weight: number;
  distance: number;
  multiplier: number;
  points: number;
  entities: string[];
  evidence: string[];
}

export interface RiskAssessment {
  score: number;
  level: Exclude<RiskLevel, "none">;
  factors: RiskFactor[];
  entity_flags: Record<string, string[]>;
  entity_points: Record<string, number>;
  entity_levels: Record<string, RiskLevel>;
  cycles: string[][];
  methodology: string[];
}

export interface QueryLog {
  source: string;
  source_label: string;
  operation: string;
  target: string;
  results: number;
  error: string | null;
  retrieved_at: string;
}

export interface InvestigationParams {
  record_ids: string[];
  depth: number;
  max_nodes: number;
}

export type Row = Record<string, unknown>;

export interface Investigation {
  id: string;
  subject_id: string;
  params: InvestigationParams;
  generated_at: string;
  demo: boolean;
  disclaimer: string;
  entities: Entity[];
  depth: Record<string, number>;
  relationships: Relationship[];
  hits: ScreeningHit[];
  risk: RiskAssessment;
  tables: Record<
    | "mandates"
    | "companies"
    | "shareholders"
    | "ownership"
    | "screening"
    | "leaks"
    | "sources"
    | "documents"
    | "crypto"
    | "jurisdictions"
    | "financials",
    Row[]
  >;
  queries: QueryLog[];
  merges: Row[];
  warnings: string[];
  truncated: boolean;
  unscreened?: string[];
  stats: Record<string, number>;
  summary: Finding[];
  timeline: TimelineEvent[];
  brief: Brief | null;
  requests?: DocRequest[];
}

export interface DocRequest {
  document: string;
  reason: string;
  priority: "required" | "standard";
  entity_ids: string[];
}

export interface Brief {
  subject_type: "person" | "company" | "wallet" | "address";
  level: RiskLevel;
  score: number;
  headline: string;
  action?: string;
  figures: { key: string; label: string; value: string; tone: "neutral" | "good" | "warning" | "critical"; hint: string | null; tab: string | null }[];
  flags: { key: string; title: string; severity: "critical" | "warning" | "info"; points: number; evidence: string[]; next_step: string | null; entity_ids: string[] }[];
  owners: { entity_id: string; name: string; kind: string; pct: number; path: string[]; flags: string[] }[];
  coverage: string;
}

export interface Finding {
  text: string;
  severity: "info" | "warning" | "critical";
  entity_ids: string[];
  urls: string[];
}

export interface TimelineEvent {
  date: string;
  kind: "company" | "role" | "ownership" | "filing" | "legal_notice" | "sanction" | "media" | "transfer" | "country";
  title: string;
  entity_id: string | null;
  detail: string | null;
  url: string | null;
  source: string | null;
}

export interface ConnectorStatus {
  name: string;
  label: string;
  kind: string;
  enabled: boolean;
  message: string;
  demo: boolean;
  homepage: string | null;
  jurisdictions: string[] | null;
}

export interface Meta {
  version: string;
  demo_mode: boolean;
  disclaimer: string;
  max_depth: number;
  max_nodes_limit: number;
  cases?: CasesStatus;
}

export interface CasesStatus {
  enabled: boolean;
  auth_required: boolean;
  storage: string | null;
  message: string | null;
}

export interface CaseRecord {
  id: string;
  title: string;
  subject_name: string;
  subject_type: string;
  record_ids: string[];
  depth: number;
  max_nodes: number;
  demo: boolean;
  status: "open" | "closed";
  monitor: boolean;
  notes: string;
  risk_score: number | null;
  risk_level: RiskLevel | null;
  countries: string[];
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  unseen_changes?: number;
  questionnaire?: { vigilance?: Vigilance; next_review?: string; answered_at?: string };
  import_state?: ImportState;
  import_info?: ImportInfo;
  queue?: Queue | null;
  workflow_state?: WorkflowState;
}

export type Queue = "sensitive" | "to_validate" | "to_complete" | "review_due" | "validated";
export type WorkflowState = "to_complete" | "pending_validation" | "validated" | "rejected";
export type WorkflowAction = "submit" | "validate" | "reject" | "reopen";

export interface WorkflowView {
  state: WorkflowState;
  label: string;
  history: { at: string; by: string; action: WorkflowAction; comment: string }[];
  submitted_by: string | null;
  validated_by: string | null;
  validated_at: string | null;
  blockers: string[];
}

export interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
  by: string;
  at: string | null;
  note: string;
  reason?: string;
  required?: boolean;
  custom?: boolean;
}

export interface Checklist {
  documents: ChecklistItem[];
  diligences: ChecklistItem[];
  missing_required: string[];
}

export type ImportState = "" | "pending" | "resolved" | "ambiguous" | "not_found" | "error";

export interface ImportChoice {
  record_ids: string[];
  name: string;
  jurisdiction: string | null;
  registration_number: string | null;
  status: string | null;
  score: number;
}

export interface ImportInfo {
  line?: number;
  name?: string;
  identifier?: string;
  country?: string | null;
  reference?: string;
  query?: string;
  batch?: string;
  note?: string;
  matched?: string;
  choices?: ImportChoice[];
}

export interface ImportStatus {
  counts: Record<string, number>;
  remaining: number;
  to_fix: number;
}

export type Vigilance = "simplified" | "standard" | "enhanced";

export interface KycOption {
  value: string;
  label: string;
  points: number;
  enhanced: string | null;
}

export interface KycQuestion {
  id: string;
  section: string;
  label: string;
  type: "choice" | "text" | "countries";
  help?: string;
  options?: KycOption[];
}

export type KycAnswers = Record<string, string | string[]>;

export interface RiskAxis {
  label: string;
  score: number;
  level: "low" | "medium" | "high";
  items: string[];
}

export interface VigilanceOverride {
  level: Vigilance | null;
  justification: string;
  by: string;
  at: string;
}

export interface KycAssessment {
  level: Vigilance;
  computed_level: Vigilance;
  override: VigilanceOverride | null;
  axes: Record<"geography" | "activity" | "client" | "transactions", RiskAxis>;
  points: number;
  reasons: { item: string; detail: string; points: number }[];
  triggers: string[];
  measures: string[];
  missing: string[];
  complete: boolean;
  review_months: number;
  next_review: string;
}

export interface KycQuestionnaire {
  form: KycQuestion[];
  answers: KycAnswers;
  author: string;
  answered_at: string | null;
  override_history?: VigilanceOverride[];
  suggested: KycAnswers;
  assessment: KycAssessment | null;
}

export interface CaseChange {
  id?: string;
  case_id?: string;
  case_title?: string;
  run_at?: string;
  kind: string;
  severity: "critical" | "warning" | "info";
  description: string;
  seen?: number;
}

export type DecisionValue = "confirmed" | "false_positive" | "to_review";

export interface Decision {
  case_id: string;
  item_key: string;
  item_label: string;
  decision: DecisionValue;
  comment: string;
  author: string;
  decided_at: string;
  /** A "false positive" whose evidence changed since (the alert came back). */
  stale?: boolean;
}

export interface CaseView {
  case: CaseRecord;
  investigation: Investigation | null; // null while an imported case waits in the queue
  decisions: Decision[];
  changes: CaseChange[];
  questionnaire: KycQuestionnaire;
  checklist?: Checklist;
  workflow?: WorkflowView;
  overview?: CaseOverview;
}

export interface CaseOverview {
  risk: { score: number; level: RiskLevel };
  alerts: { total: number; open: number; triage: Record<string, number>; by_list: Record<string, { total: number; open: number }> };
  documents: { received: number; total: number; required_missing: number };
  cdb: { forms: string[]; missing: number; persons: number };
  sow: { verdict: "plausible" | "partial" | "gap" | "incomplete"; coverage: number | null; sources: number } | null;
  review: { status: "not_set" | "overdue" | "due" | "not_due"; days_left: number | null; next_review: string | null };
  vigilance: Vigilance | null;
  workflow: WorkflowState | null;
  readiness: { key: string; label: string; done: boolean; detail: string; tab: string }[];
  ready: number;
}

export interface Dashboard {
  cases: CaseRecord[];
  by_level: Record<string, number>;
  by_country: { code: string; country: string; cases: number }[];
  recent_changes: CaseChange[];
  to_review: number;
  imports?: ImportStatus;
  queues?: Record<Queue, number>;
  changes_by_day?: { day: string; critical: number; warning: number; info: number }[];
  vigilance?: Record<string, number>;
  workflow?: Record<string, number>;
  upcoming_reviews?: { id: string; title: string; date: string }[];
  memory?: number;
}

export interface DeclaredPerson {
  name: string;
  role?: string | null;
  pct?: number | null;
  birth?: string | null;
}

export interface DocExtraction {
  kind: string;
  pages: number;
  characters: number;
  company: { name: string | null; registration_number: string | null; address: string | null };
  officers: DeclaredPerson[];
  owners: DeclaredPerson[];
  warnings: string[];
}

export interface DocComparison {
  rows: {
    kind: "officer" | "owner" | "company";
    name: string;
    declared: string | null;
    registry: string | null;
    status: "match" | "mismatch" | "missing_in_registry" | "missing_in_document";
    note: string | null;
    entity_id: string | null;
  }[];
  summary: Record<string, number>;
}

export interface Memo {
  title: string;
  draft: boolean;
  text: string;
  generated_at?: string;
  updated_by?: string | null;
  updated_at?: string | null;
}

/* ---------------- Alert memory & batch triage ---------------- */
export interface AlertRow {
  key: string;
  label: string;
  entity: string;
  entity_type: string | null;
  dataset: string;
  list_type: string;
  matched_name: string;
  score: number;
  triage: "likely" | "verify" | "namesake" | "dismissed";
  reasons: string[];
  realert: string[] | null;
  decision: Decision | null;
  memory: { decided_at: string; author: string; comment: string; case_id: string } | null;
  proposed: string | null;
  url: string | null;
}
export interface AlertsView {
  alerts: AlertRow[];
  counts: Record<string, number>;
  cleared_by_memory: number;
  batch_candidates: number;
  minutes_per_alert: number;
  minutes_saved: number;
  memory_enabled: boolean;
  dismissed?: number;
}
export interface MemoryItem {
  item_key: string;
  item_label: string;
  comment: string;
  author: string;
  decided_at: string;
  case_id: string;
  case_title: string | null;
  tracked: boolean;
  evidence: { list?: Record<string, unknown>; ours?: Record<string, unknown> };
}

/* ---------------- CDB 20 forms ---------------- */
export interface CdbPerson {
  key: string;
  entity_id: string | null;
  role: string;
  role_label: string;
  basis: string;
  pct: number | null;
  path: string[];
  flags: string[];
  source: string;
  is_company: boolean;
  last_name: string;
  first_name: string;
  birth_date: string;
  nationality: string;
  address: string;
  country: string;
  missing: string[];
  edited?: string[];
}
export interface CdbForm {
  id: string;
  code: "A" | "K" | "S" | "T";
  title: string;
  entity: string;
  why: string;
  structure: { key: string; label: string; value: string }[];
  persons: CdbPerson[];
  notes: string[];
  missing_count: number;
}
export interface CdbData {
  title: string;
  contracting_party: Record<string, string>;
  primary: string | null;
  forms: CdbForm[];
  exemption: string | null;
  declaration: string;
  draft_note: string;
  missing_total: number;
  edited_by: string | null;
  edited_at: string | null;
}

/* ---------------- Source of wealth ---------------- */
export interface SowSourceIn {
  id: string;
  type: string;
  description: string;
  amount: number;
  annual: number;
  year_from: number | null;
  year_to: number | null;
  rate: number | null;
  country: string;
  received: string[];
}
export interface SowSource extends SowSourceIn {
  label: string;
  explained: number;
  how: string;
  public: string[];
  documents: { label: string; received: boolean }[];
  corroborated: boolean;
  risk: string;
}
export interface SowData {
  person_id: string;
  person: string | null;
  people: { id: string; name: string; why: string }[];
  types: Record<string, { label: string; mode: "annual" | "lump"; rate?: number }>;
  currency: string;
  declared_total: number;
  sources: SowSource[];
  notes: string;
  explained_total: number;
  gap: number | null;
  coverage: number | null;
  verdict: "plausible" | "partial" | "gap" | "incomplete";
  verdict_text: string;
  roles: { company: string; kind: string; role: string; share_pct: number | null; start: string | null; end: string | null; company_status: string | null; dissolved: string | null; source: string }[];
  flags: { severity: string; text: string }[];
  to_request: string[];
  narrative: string;
  by?: string;
  at?: string;
}

/* ---------------- Periodic review ---------------- */
export interface ReviewDoc {
  label: string;
  received_on: string | null;
  required: boolean;
  status: "ok" | "missing" | "not_received" | "expired" | "expiring" | "stale";
  why: string;
}
export interface ReviewPack {
  title: string;
  last_review: string | null;
  last_review_basis: "validation" | "opening";
  next_review: string | null;
  days_left: number | null;
  status: "not_set" | "overdue" | "due" | "not_due";
  changes: CaseChange[];
  changes_count: Record<string, number>;
  open_alerts: { label: string; triage: string; score: number }[];
  documents: ReviewDoc[];
  to_renew: ReviewDoc[];
  vigilance: { saved: string | null; now: string | null };
  actions: { severity: string; tab: string; text: string }[];
  email: { subject: string; body: string };
  reviews: { started_at: string; by: string; previous_validation: string | null; due: string | null; changes: number; actions: number }[];
  workflow_state: string | null;
  warning?: string | null;
}

/* ------------------------------------------------------------ quick checks */
export type CheckStatus = "ok" | "info" | "warn" | "alert" | "unknown";
export interface CheckLine {
  label: string;
  status: CheckStatus;
  detail: string;
  source: string | null;
}
export interface CheckBlock {
  input: string;
  valid: boolean;
  checks: CheckLine[];
  normalized?: string;
  country?: { code: string; name: string };
  bank?: { name: string; bic: string | null; town: string; iid: number };
  domain?: string;
  chain?: string;
}
export interface QuickCheckRequest {
  iban?: string;
  email?: string;
  website?: string;
  wallet?: string;
  company?: string;
  client_country?: string;
}
export interface QuickCheckResult {
  iban?: CheckBlock;
  email?: CheckBlock;
  website?: CheckBlock;
  wallet?: CheckBlock;
  verdict: CheckStatus;
}
