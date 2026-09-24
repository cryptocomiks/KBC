// Mirrors backend/app/models.py and backend/app/schemas.py

export type EntityType = "person" | "company" | "address" | "wallet";
export type RiskLevel = "none" | "low" | "medium" | "high" | "critical";

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
}

export interface CaseView {
  case: CaseRecord;
  investigation: Investigation;
  decisions: Decision[];
  changes: CaseChange[];
}

export interface Dashboard {
  cases: CaseRecord[];
  by_level: Record<string, number>;
  by_country: { code: string; country: string; cases: number }[];
  recent_changes: CaseChange[];
  to_review: number;
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
