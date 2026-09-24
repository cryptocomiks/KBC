// Mirrors backend/app/models.py and backend/app/schemas.py

export type EntityType = "person" | "company" | "address";
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
  demo: boolean;
  documents: DocumentRef[];
  record_ids: string[];
  sources: Provenance[];
  extra: Record<string, unknown>;
}

export type RelationType = "officer" | "shareholder" | "beneficial_owner" | "registered_at";

export interface Relationship {
  id: string;
  type: RelationType;
  source_id: string;
  target_id: string;
  role: string | null;
  share_pct: number | null;
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
    "mandates" | "companies" | "shareholders" | "ownership" | "screening" | "leaks" | "sources" | "documents",
    Row[]
  >;
  queries: QueryLog[];
  merges: Row[];
  warnings: string[];
  truncated: boolean;
  stats: Record<string, number>;
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
}
