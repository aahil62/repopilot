import type {
  BenchResult, BlastReport, Citation, CommitRef, FileContent, FileEntry, Job, ModelsResponse, NightListItem,
  NightReport, RepoSummary, ReviewListItem, ReviewReport,
} from "./types";

export const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "1";

export function apiBase(): string {
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE;
  if (typeof window !== "undefined" && window.location.port === "7342") return "http://127.0.0.1:7341";
  return "";
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

async function demo<T>(name: string): Promise<T> {
  const res = await fetch(`/demo/${name}.json`);
  if (!res.ok) throw new ApiError(res.status, `Demo data ${name} is missing.`);
  return res.json() as Promise<T>;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiBase()}/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let body: unknown = undefined;
    try {
      body = await res.json();
    } catch {
      /* not json */
    }
    const detail = (body as { detail?: unknown })?.detail;
    throw new ApiError(res.status, typeof detail === "string" ? detail : `Request failed (${res.status})`, body);
  }
  return res.json() as Promise<T>;
}

export const api = {
  repos: () => (DEMO ? demo<RepoSummary[]>("repos") : call<RepoSummary[]>("/repos")),
  addRepo: (body: { path?: string; git_url?: string }) => call<RepoSummary>("/repos", { method: "POST", body: JSON.stringify(body) }),
  deleteRepo: (id: string) => call<{ deleted: string }>(`/repos/${id}`, { method: "DELETE" }),
  index: (id: string) => call<{ job_id: string }>(`/repos/${id}/index`, { method: "POST", body: "{}" }),
  job: <T,>(jobId: string) => call<Job<T>>(`/jobs/${jobId}`),
  files: (id: string, q: string) =>
    DEMO ? demo<FileEntry[]>("files").then((f) => f.filter((x) => x.path.toLowerCase().includes(q.toLowerCase())).slice(0, 50))
      : call<FileEntry[]>(`/repos/${id}/files?q=${encodeURIComponent(q)}`),
  file: (id: string, path: string, start = 1, end?: number) =>
    DEMO ? demo<Record<string, FileContent>>("file-excerpts").then((all) => {
      const f = all[path];
      if (!f) throw new ApiError(404, "This file is not part of the demo data.");
      return f;
    }) : call<FileContent>(`/repos/${id}/file?path=${encodeURIComponent(path)}&start=${start}${end ? `&end=${end}` : ""}`),
  blast: (id: string, paths: string[]) =>
    DEMO ? demo<Record<string, BlastReport>>("blast").then((all) => {
      const r = all[paths[0]];
      if (!r) throw new ApiError(404, "The demo includes blast radius for a few files only — pick one from the list.");
      return r;
    }) : call<BlastReport>(`/repos/${id}/blast?${paths.map((p) => `path=${encodeURIComponent(p)}`).join("&")}`),
  startReview: (id: string, body: { diff?: string; base?: string; head?: string; staged?: boolean; run_checks?: boolean }) =>
    call<{ job_id: string }>(`/repos/${id}/review`, { method: "POST", body: JSON.stringify(body) }),
  reviews: (id: string) => (DEMO ? demo<ReviewListItem[]>("reviews") : call<ReviewListItem[]>(`/repos/${id}/reviews`)),
  review: (id: string, reviewId: string) =>
    DEMO ? demo<ReviewReport>("review") : call<ReviewReport>(`/repos/${id}/reviews/${reviewId}`),
  nightReports: (id: string) => (DEMO ? demo<NightListItem[]>("nightshift-list") : call<NightListItem[]>(`/repos/${id}/nightshift/reports`)),
  nightReport: (id: string, day: string) => (DEMO ? demo<NightReport>("nightshift") : call<NightReport>(`/repos/${id}/nightshift/reports/${day}`)),
  runNightShift: (id: string) => call<{ job_id: string }>(`/repos/${id}/nightshift/run`, { method: "POST" }),
  schedule: (id: string) => call<{ kind: string; activate: string; content?: string; path?: string }>(`/repos/${id}/nightshift/schedule`),
  models: () => (DEMO ? demo<ModelsResponse>("models") : call<ModelsResponse>("/models")),
  setRoles: (roles: Partial<Record<"fast" | "strong" | "embed", string>>) =>
    call<{ roles: Record<string, string> }>("/models/roles", { method: "PUT", body: JSON.stringify(roles) }),
  bench: (id: string) => (DEMO ? demo<BenchResult>("bench") : call<BenchResult>(`/repos/${id}/bench/latest`)),
  startBench: (id: string, tasks = 10) => call<{ job_id: string }>(`/repos/${id}/bench`, { method: "POST", body: JSON.stringify({ tasks }) }),
  settings: (id: string) => call<{ test_command?: string | null; detected_test_command: string | null }>(`/repos/${id}/settings`),
  saveSettings: (id: string, body: { test_command: string | null }) =>
    call<{ test_command?: string | null; detected_test_command: string | null }>(`/repos/${id}/settings`, { method: "PUT", body: JSON.stringify(body) }),
  privacy: () => call<{ data_dir: string; model_runtime_urls: string[]; github_review_import: boolean; telemetry: boolean; network_calls: string[] }>("/privacy"),
  startEdit: (id: string, body: { instruction: string; paths?: string[] }) =>
    call<{ job_id: string }>(`/repos/${id}/edit`, { method: "POST", body: JSON.stringify(body) }),
  applyEdit: (id: string, jobId: string) => call<{ applied: boolean }>(`/repos/${id}/edit/${jobId}/apply`, { method: "POST" }),
};

export async function waitForJob<T>(jobId: string, onProgress?: (p: Record<string, unknown>) => void, intervalMs = 700): Promise<T> {
  for (;;) {
    const job = await api.job<T>(jobId);
    if (job.progress && onProgress) onProgress(job.progress);
    if (job.status === "done") return job.result as T;
    if (job.status === "failed") throw new ApiError(500, job.error || "The job failed.");
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export type AskEvent =
  | { event: "retrieval"; data: { path: string; start_line: number; end_line: number }[] }
  | { event: "token"; data: string }
  | { event: "citations"; data: Citation[] }
  | { event: "done"; data: { refused: boolean; removed_citations: number; commits: CommitRef[] } };

/** Parse a Server-Sent Events stream from a POST response. */
export async function* askStream(id: string, question: string): AsyncGenerator<AskEvent> {
  if (DEMO) {
    const transcripts = await demo<{ question: string; events: AskEvent[] }[]>("ask");
    const match = transcripts.find((t) => t.question === question) ?? transcripts[0];
    for (const e of match.events) yield e;
    return;
  }
  const res = await fetch(`${apiBase()}/api/repos/${id}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
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
