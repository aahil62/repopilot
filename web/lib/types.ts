// Mirrors the backend's Pydantic models (backend/repopilot/**). Keep field names identical.

export type Risk = "low" | "medium" | "high";
export type Severity = "high" | "medium" | "low";

export interface RepoSummary {
  repo_id: string;
  name: string;
  path: string;
  source: "local" | "clone";
  remote: string | null;
  added_at: string;
  files: number;
  chunks: number;
  commits: number;
  review_comments: number;
  indexed_at: string | null;
  history_truncated: boolean;
  last_index: { files_changed: number; chunks_embedded: number; notes: string[] } | null;
}

export interface CoChange { path: string; support: number; confidence: number }
export interface Dependent { path: string; depth: number }
export interface PastFix { sha: string; date: string; subject: string; author: string }
export interface Owner { author: string; commits: number }

export interface BlastReport {
  targets: string[];
  cochanged: CoChange[];
  dependents: Dependent[];
  past_fixes: PastFix[];
  tests: string[];
  owners: Owner[];
  risk: Risk;
  risk_reasons: string[];
}

export interface Precedent {
  kind: "review_comment" | "fix_commit";
  ref: string;
  sha: string | null;
  path: string | null;
  excerpt: string;
  similarity: number;
}

export interface Finding {
  severity: Severity;
  path: string;
  line: number;
  title: string;
  explanation: string;
  evidence: string[];
  evidence_detail: Precedent[];
}

export interface HunkView {
  old_start: number;
  new_start: number;
  new_end: number;
  label: "mechanical" | "behavior";
  reason: string;
  text: string;
}

export interface FileView {
  path: string;
  status: string;
  mechanical_hunks: number;
  behavior_hunks: number;
  hunks: HunkView[];
}

export interface ChecksResult {
  command: string | null;
  status: "passed" | "failed" | "skipped" | "timeout" | "not_applied";
  output_tail: string;
  duration_s: number;
  message: string;
}

export interface ReviewReport {
  review_id: string;
  created_at: string;
  source: { kind: string; base: string | null; head: string | null };
  summary: string;
  files: FileView[];
  mechanical_count: number;
  behavior_count: number;
  findings: Finding[];
  dropped_unverifiable: number;
  blast: BlastReport | null;
  precedents: Precedent[];
  checks: ChecksResult;
  model: Record<string, string>;
  model_error: string | null;
  truncated: boolean;
  timings_ms: Record<string, number>;
}

export interface ReviewListItem {
  review_id: string;
  created_at: string;
  source: { kind: string; base: string | null; head: string | null };
  summary: string;
  behavior: number;
  mechanical: number;
}

export interface Job<T = unknown> {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  progress: Record<string, unknown> | null;
  result: T | null;
  error: string | null;
}

export interface ModelInfo {
  id: string;
  runtime: string;
  base_url: string;
  size_bytes: number | null;
  context_length: number | null;
  is_embedding: boolean;
  fits: boolean;
}

export interface ModelsResponse {
  runtimes: { base_url: string; kind: string; reachable: boolean; error: string | null }[];
  models: ModelInfo[];
  roles: Partial<Record<"fast" | "strong" | "embed", string>>;
  hardware: { total_ram_bytes: number; gpu: string | null; vram_bytes: number | null; unified_memory: boolean; model_budget_bytes: number };
}

export interface TaskScore {
  sha: string;
  applies: boolean;
  tests_pass: boolean | null;
  similarity: number;
  latency_s: number;
  tokens_per_second: number | null;
  score: number;
  error: string | null;
}

export interface ModelScore {
  model: string;
  size_bytes: number | null;
  score: number;
  applies_rate: number;
  tests_pass_rate: number | null;
  similarity: number;
  median_latency_s: number;
  tokens_per_second: number | null;
  tasks: TaskScore[];
}

export interface BenchResult {
  created_at: string;
  repo_id: string;
  tasks: { sha: string; subject: string; paths: string[] }[];
  models: ModelScore[];
  skipped: { model: string; reason: string }[];
  recommendation: string;
  recommended_strong: string | null;
  recommended_fast: string | null;
}

export interface NightListItem { date: string; commits: number; findings: number; tests_verified: number; stale_docs: number }

export interface NightReport {
  date: string;
  repo_id: string;
  commits_reviewed: { sha: string; subject: string; findings: Finding[]; behavior_hunks: number }[];
  tests_written: { symbol: string; source_path: string; test_path: string; branch: string | null; status: string; attempts: number }[];
  stale_docs: { doc_path: string; line: number; symbol: string; commit: string }[];
  model: Record<string, string>;
  duration_s: number;
  notes: string[];
}

export interface Citation { n: number; path: string; start_line: number; end_line: number; snippet: string }
export interface CommitRef { sha: string; date: string; subject: string; author: string }

export interface FileContent { path: string; start: number; end: number; total_lines: number; lines: string[] }
export interface FileEntry { path: string; language: string; lines: number }

/** web/public/demo/hero.json: the commit the landing page shows. */
export interface HeroDemo {
  repo: string;
  commit: string;
  subject: string;
  files: FileView[];
  mechanical: number;
  behavior: number;
  blast: BlastReport | null;
}
