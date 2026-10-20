import * as vscode from "vscode";

export interface Finding {
  severity: "high" | "medium" | "low";
  path: string;
  line: number;
  title: string;
  explanation: string;
  evidence_detail: { ref: string; kind: string; excerpt: string }[];
}

export interface BlastReport {
  targets: string[];
  risk: "low" | "medium" | "high";
  risk_reasons: string[];
  cochanged: { path: string; support: number; confidence: number }[];
  dependents: { path: string; depth: number }[];
  past_fixes: { sha: string; date: string; subject: string }[];
  owners: { author: string; commits: number }[];
  tests: string[];
}

export interface ReviewReport {
  review_id: string;
  summary: string;
  findings: Finding[];
  mechanical_count: number;
  behavior_count: number;
  dropped_unverifiable: number;
  blast: BlastReport | null;
  checks: { status: string; command: string | null; message: string; output_tail: string };
  model_error: string | null;
}

export interface EditResult {
  status: "verified" | "failed" | "no_checks";
  diff: string;
  explanation: string;
  attempts: { n: number; applied: boolean; apply_error: string | null; checks: { status: string } | null }[];
  target_paths: string[];
}

export interface RepoSummary { repo_id: string; name: string; path: string; files: number; commits: number }

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

export function baseUrl(): string {
  return vscode.workspace.getConfiguration("repopilot").get<string>("serverUrl", "http://127.0.0.1:7341").replace(/\/$/, "");
}

export async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${baseUrl()}/api${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  } catch {
    throw new ApiError(0, "RepoPilot is not running.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => undefined);
    const detail = (body as { detail?: unknown } | undefined)?.detail;
    throw new ApiError(res.status, typeof detail === "string" ? detail : `RepoPilot returned ${res.status}.`, body);
  }
  return (await res.json()) as T;
}

export async function waitForJob<T>(jobId: string, token?: vscode.CancellationToken, onProgress?: (p: Record<string, unknown>) => void): Promise<T> {
  for (;;) {
    if (token?.isCancellationRequested) throw new ApiError(499, "Cancelled.");
    const job = await call<{ status: string; result: T; error: string | null; progress: Record<string, unknown> | null }>(`/jobs/${jobId}`);
    if (job.progress && onProgress) onProgress(job.progress);
    if (job.status === "done") return job.result;
    if (job.status === "failed") throw new ApiError(500, job.error || "The job failed.");
    await new Promise((r) => setTimeout(r, 700));
  }
}

export type AskEvent =
  | { event: "retrieval"; data: { path: string; start_line: number; end_line: number }[] }
  | { event: "token"; data: string }
  | { event: "citations"; data: { n: number; path: string; start_line: number; end_line: number; snippet: string }[] }
  | { event: "done"; data: { refused: boolean; removed_citations: number; commits: { sha: string; date: string; subject: string }[] } };

export async function* askStream(repoId: string, question: string): AsyncGenerator<AskEvent> {
  const res = await fetch(`${baseUrl()}/api/repos/${repoId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  }).catch(() => {
    throw new ApiError(0, "RepoPilot is not running.");
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, (body as { detail?: string }).detail || "The question could not be answered.", body);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) yield { event, data: JSON.parse(data.join("\n")) } as AskEvent;
    }
  }
}
