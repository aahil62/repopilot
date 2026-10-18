import { spawn } from "child_process";
import * as vscode from "vscode";

import { ApiError, call, RepoSummary, waitForJob } from "./client";

let starting: Promise<void> | null = null;
const repoIds = new Map<string, string>();

async function healthy(): Promise<boolean> {
  try {
    await call<{ status: string }>("/health");
    return true;
  } catch {
    return false;
  }
}

/** Make sure the local service is reachable, starting `repopilot serve` if the user allows it. */
export async function ensureServer(): Promise<void> {
  if (await healthy()) return;
  if (!vscode.workspace.getConfiguration("repopilot").get<boolean>("autoStartServer", true)) {
    throw new ApiError(0, "RepoPilot is not running. Start it with `repopilot serve`.");
  }
  starting ??= (async () => {
    const child = spawn("repopilot", ["serve"], { detached: true, stdio: "ignore", shell: process.platform === "win32" });
    child.on("error", () => undefined);
    child.unref();
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 500));
      if (await healthy()) return;
    }
    throw new ApiError(0, "Could not start RepoPilot. Install it with `pipx install repopilot` and run `repopilot serve`.");
  })().finally(() => {
    starting = null;
  });
  return starting;
}

export function workspaceRoot(): vscode.WorkspaceFolder | undefined {
  const active = vscode.window.activeTextEditor?.document.uri;
  return (active && vscode.workspace.getWorkspaceFolder(active)) || vscode.workspace.workspaceFolders?.[0];
}

/** Register the open workspace with RepoPilot (idempotent) and index it the first time. */
export async function ensureRepo(progress?: vscode.Progress<{ message?: string }>): Promise<{ repoId: string; root: vscode.Uri }> {
  const folder = workspaceRoot();
  if (!folder) throw new ApiError(400, "Open a folder that is a git repository first.");
  await ensureServer();
  const root = folder.uri;
  const cached = repoIds.get(root.fsPath);
  if (cached) return { repoId: cached, root };
  const repo = await call<RepoSummary>("/repos", { method: "POST", body: JSON.stringify({ path: root.fsPath }) });
  repoIds.set(root.fsPath, repo.repo_id);
  if (repo.files === 0) {
    progress?.report({ message: "Building repository memory (first run)…" });
    const { job_id } = await call<{ job_id: string }>(`/repos/${repo.repo_id}/index`, { method: "POST", body: "{}" });
    await waitForJob(job_id, undefined, (p) => progress?.report({ message: `Indexing: ${p.stage ?? ""} ${p.done ?? ""}/${p.total ?? ""}` }));
  }
  return { repoId: repo.repo_id, root };
}

export function showError(err: unknown): void {
  if (err instanceof ApiError && err.status === 503) {
    void vscode.window.showErrorMessage(
      "No local model runtime found. Install Ollama, then run: ollama pull qwen2.5-coder:7b && ollama pull nomic-embed-text",
      "Open ollama.com",
    ).then((pick) => {
      if (pick) void vscode.env.openExternal(vscode.Uri.parse("https://ollama.com"));
    });
    return;
  }
  if (err instanceof ApiError && err.status === 499) return;
  void vscode.window.showErrorMessage(`RepoPilot: ${err instanceof Error ? err.message : String(err)}`);
}
