// Mirrors apps/backend/copilot/domain.py (InvestigationResponse and friends).

export type Confidence = "high" | "medium" | "low";

export interface AlarmRow {
  alarm_id: string;
  asset_name: string;
  alarm_name: string;
  severity: string;
  status: string;
  start_time: string;
  acknowledged: boolean;
  priority_score?: number | null;
  priority_band?: string | null;
}

export interface AlarmSummaryPanel {
  asset?: Record<string, string | null> | null;
  scope_label: string;
  window?: { days: number; start_time: string; end_time: string; label: string } | null;
  total_alarms: number;
  by_severity: Record<string, number>;
  active_alarms: AlarmRow[];
  top_alarm_groups: {
    alarm_name: string;
    count: number;
    recurring_rate?: number | null;
    avg_ack_delay_s?: number | null;
    critical_count?: number | null;
    last_occurrence?: string | null;
  }[];
  trend?: {
    direction: string;
    first_half_count: number;
    second_half_count: number;
    bucket: string;
    series: { t: string; v: number }[];
  } | null;
  primary_alarm?: AlarmRow | null;
  priority_rationale?: string | null;
  related_assets: { asset_id: string; asset_name: string; relationship: string; asset_type?: string }[];
  kpis: Record<string, unknown>;
}

export interface Evidence {
  kind: "tool" | "document";
  ref: string;
  detail: string;
}

export interface CauseFinding {
  cause: string;
  confidence: Confidence;
  evidence: Evidence[];
}

export interface RecommendationAssessment {
  action: string;
  source: "api" | "document";
  urgency?: string | null;
  status: "consistent" | "conflict" | "not_covered" | "document_guidance";
  explanation: string;
  citations: string[];
}

export interface Citation {
  id: string;
  chunk_id: string;
  doc_id: string;
  title: string;
  section: string;
  doc_type: string;
  revision?: string | null;
  source_path: string;
  score: number;
  confidence: number;
  snippet: string;
  trust_level: string;
}

export interface ApiCall {
  method: string;
  path: string;
  params?: Record<string, unknown> | null;
  body?: unknown;
  attempt: number;
  status?: number | null;
  duration_ms: number;
  outcome: string;
  error?: string | null;
  request_id?: string | null;
}

export interface ToolCallRecord {
  step_id: string;
  kind: "mcp" | "rag";
  server?: string | null;
  tool: string;
  purpose: string;
  status: "pending" | "ok" | "error" | "skipped";
  wave: number;
  arguments: Record<string, unknown>;
  request?: unknown;
  response?: unknown;
  error?: { code?: string; message?: string; [k: string]: unknown } | null;
  duration_ms: number;
  retries: number;
  api_calls: ApiCall[];
  trace_id?: string | null;
  iteration?: number | null;
}

export interface PlanStep {
  id: string;
  kind: "mcp" | "rag";
  tool: string;
  purpose: string;
  args: Record<string, unknown>;
  optional: boolean;
}

export interface RetrievalInfo {
  query: string;
  filters: Record<string, unknown>;
  low_confidence: boolean;
  top_confidence: number;
  fallback_used: boolean;
  results: { id: string; chunk_id: string; score: number; confidence: number; bm25: number; dense: number; boost: number }[];
  quarantined: { chunk_id: string; patterns: string[]; doc_id: string }[];
}

export interface InvestigationResponse {
  conversation_id: string;
  request_id: string;
  trace_id: string;
  intent: {
    name: string;
    confidence: number;
    rationale: string;
    source: string;
    entities: Record<string, unknown>;
  };
  plan: PlanStep[];
  answer: { markdown: string; confidence: Confidence; grounded: boolean; generator: string; safety_flags: string[] };
  alarm_summary?: AlarmSummaryPanel | null;
  likely_causes: CauseFinding[];
  recommendations: RecommendationAssessment[];
  citations: Citation[];
  retrieval?: RetrievalInfo | null;
  tool_trace: ToolCallRecord[];
  discovered_tools: string[];
  warnings: string[];
  errors: string[];
  timings: Record<string, number>;
}

export interface ToolSpec {
  name: string;
  title?: string | null;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema?: Record<string, unknown> | null;
  read_only: boolean;
  server: string;
}

export interface Health {
  status: string;
  llm_provider: string;
  rag: { documents?: number; chunks?: number; embedder?: string; created_at?: string };
  mcp_server_url: string;
}

/** One investigation run in the session history. */
export interface InvestigationRun {
  id: string;
  query: string;
  startedAt: string;
  response?: InvestigationResponse;
  error?: string;
  pending?: boolean;
}
