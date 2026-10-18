import * as vscode from "vscode";

import { askStream, baseUrl, BlastReport, call, EditResult, ReviewReport, waitForJob } from "./client";
import { ensureRepo, showError } from "./server";

const SEVERITY: Record<string, vscode.DiagnosticSeverity> = {
  high: vscode.DiagnosticSeverity.Error,
  medium: vscode.DiagnosticSeverity.Warning,
  low: vscode.DiagnosticSeverity.Information,
};

export const diagnostics = vscode.languages.createDiagnosticCollection("repopilot");

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function panelHtml(title: string, body: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
body{font-family:var(--vscode-font-family);font-size:13px;line-height:1.55;color:var(--vscode-foreground);padding:4px 18px 24px;max-width:860px}
h1{font-size:18px;margin:14px 0 6px} h2{font-size:14px;margin:18px 0 6px}
.mark{background:rgba(255,214,64,.35);padding:0 3px;border-radius:2px}
.f{border-left:3px solid var(--vscode-editorWarning-foreground);padding:2px 0 2px 12px;margin:10px 0}
.f.high{border-color:var(--vscode-editorError-foreground)} .f.low{border-color:var(--vscode-editorInfo-foreground)}
.muted{opacity:.75} code,pre{font-family:var(--vscode-editor-font-family);font-size:12px}
pre{background:var(--vscode-textCodeBlock-background);padding:8px 10px;overflow-x:auto}
a{color:var(--vscode-textLink-foreground);cursor:pointer}
</style></head><body><h1>${escapeHtml(title)}</h1>${body}
<script>const vscode=acquireVsCodeApi();document.addEventListener('click',e=>{const a=e.target.closest('[data-open]');if(a){e.preventDefault();vscode.postMessage(JSON.parse(a.dataset.open));}});</script></body></html>`;
}

function openOnMessage(panel: vscode.WebviewPanel, root: vscode.Uri): void {
  panel.webview.onDidReceiveMessage(async (msg: { path?: string; line?: number; end?: number; url?: string }) => {
    if (msg.url) return void vscode.env.openExternal(vscode.Uri.parse(msg.url));
    if (!msg.path) return;
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.joinPath(root, msg.path));
    const start = Math.max(0, (msg.line ?? 1) - 1);
    const end = Math.max(start, (msg.end ?? msg.line ?? 1) - 1);
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.One, selection: new vscode.Range(start, 0, end, 0) });
  });
}

function link(label: string, target: object): string {
  return `<a data-open='${escapeHtml(JSON.stringify(target))}'>${escapeHtml(label)}</a>`;
}

// ------------------------------------------------------------------ review

export async function review(staged: boolean): Promise<void> {
  try {
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "RepoPilot", cancellable: true }, async (progress, token) => {
      const { repoId, root } = await ensureRepo(progress);
      progress.report({ message: staged ? "Reviewing staged changes…" : "Reviewing working changes…" });
      const runChecks = vscode.workspace.getConfiguration("repopilot").get<boolean>("runChecks", true);
      const { job_id } = await call<{ job_id: string }>(`/repos/${repoId}/review`, {
        method: "POST", body: JSON.stringify({ staged, run_checks: runChecks }),
      });
      const report = await waitForJob<ReviewReport>(job_id, token);
      publishDiagnostics(root, report);
      showReport(root, repoId, report);
    });
  } catch (err) {
    showError(err);
  }
}

function publishDiagnostics(root: vscode.Uri, report: ReviewReport): void {
  diagnostics.clear();
  const byFile = new Map<string, vscode.Diagnostic[]>();
  for (const f of report.findings) {
    const line = Math.max(0, f.line - 1);
    const d = new vscode.Diagnostic(new vscode.Range(line, 0, line, 200), `${f.title} — ${f.explanation}`, SEVERITY[f.severity]);
    d.source = "RepoPilot";
    if (f.evidence_detail.length) {
      d.relatedInformation = f.evidence_detail.map((e) => new vscode.DiagnosticRelatedInformation(
        new vscode.Location(vscode.Uri.joinPath(root, f.path), new vscode.Position(line, 0)), `${e.ref}: ${e.excerpt}`));
    }
    byFile.set(f.path, [...(byFile.get(f.path) ?? []), d]);
  }
  for (const [path, list] of byFile) diagnostics.set(vscode.Uri.joinPath(root, path), list);
}

function showReport(root: vscode.Uri, repoId: string, r: ReviewReport): void {
  const panel = vscode.window.createWebviewPanel("repopilot.review", "RepoPilot review", vscode.ViewColumn.Beside, { enableScripts: true });
  const total = r.behavior_count + r.mechanical_count;
  const findings = r.findings.length
    ? r.findings.map((f) => `<div class="f ${f.severity}"><strong>${escapeHtml(f.title)}</strong> ${link(`${f.path}:${f.line}`, { path: f.path, line: f.line })}
        <div>${escapeHtml(f.explanation)}</div>${f.evidence_detail.map((e) => `<div class="muted">↳ ${escapeHtml(e.ref)}: ${escapeHtml(e.excerpt)}</div>`).join("")}</div>`).join("")
    : `<p class="muted">No problems found in the behavior changes.</p>`;
  const blast = r.blast ? `<h2>Blast radius: ${r.blast.risk}</h2><ul>${r.blast.risk_reasons.map((x) => `<li>${escapeHtml(x.replace(/`/g, ""))}</li>`).join("")}</ul>` : "";
  const checks = `<h2>Checks: ${escapeHtml(r.checks.status.replace("_", " "))}</h2>${r.checks.command ? `<p class="muted"><code>${escapeHtml(r.checks.command)}</code></p>` : ""}
    ${r.checks.message ? `<p class="muted">${escapeHtml(r.checks.message)}</p>` : ""}${r.checks.status === "failed" ? `<pre>${escapeHtml(r.checks.output_tail)}</pre>` : ""}`;
  const body = `<p><span class="mark">${r.behavior_count}</span> of ${total} hunks change behavior; ${r.mechanical_count} mechanical hunks were set aside.</p>
    <p>${escapeHtml(r.summary.replace(/\s*Behavior changes to read:.*$/, ""))}</p>
    ${r.model_error ? `<p class="muted">${escapeHtml(r.model_error)}</p>` : ""}
    <h2>Findings</h2>${findings}
    ${r.dropped_unverifiable ? `<p class="muted">${r.dropped_unverifiable} model finding(s) discarded: they cited lines outside the change.</p>` : ""}
    ${blast}${checks}
    <p>${link("Open the full report in RepoPilot", { url: `${baseUrl()}/app/review/?repo=${repoId}&review=${r.review_id}` })}</p>`;
  panel.webview.html = panelHtml("Review", body);
  openOnMessage(panel, root);
}

// ------------------------------------------------------------------ blast radius

const blastCache = new Map<string, { at: number; report: BlastReport }>();

async function blastFor(doc: vscode.TextDocument): Promise<{ report: BlastReport; repoId: string; root: vscode.Uri } | null> {
  const { repoId, root } = await ensureRepo();
  const rel = vscode.workspace.asRelativePath(doc.uri, false);
  const key = `${repoId}:${rel}`;
  const hit = blastCache.get(key);
  if (hit && Date.now() - hit.at < 120_000) return { report: hit.report, repoId, root };
  const report = await call<BlastReport>(`/repos/${repoId}/blast?path=${encodeURIComponent(rel)}`);
  blastCache.set(key, { at: Date.now(), report });
  return { report, repoId, root };
}

export class BlastLens implements vscode.CodeLensProvider {
  async provideCodeLenses(doc: vscode.TextDocument): Promise<vscode.CodeLens[]> {
    if (!vscode.workspace.getConfiguration("repopilot").get<boolean>("codeLens", true) || doc.uri.scheme !== "file") return [];
    try {
      const data = await blastFor(doc);
      if (!data) return [];
      const r = data.report;
      const parts = [`Blast radius: ${r.risk}`];
      if (r.cochanged.length) parts.push(`${r.cochanged.length} co-changed`);
      if (r.dependents.length) parts.push(`${r.dependents.length} dependents`);
      if (r.past_fixes.length) parts.push(`${r.past_fixes.length} past fixes`);
      return [new vscode.CodeLens(new vscode.Range(0, 0, 0, 0), { title: parts.join(" · "), command: "repopilot.blastRadius" })];
    } catch {
      return [];
    }
  }
}

export async function showBlast(): Promise<void> {
  const doc = vscode.window.activeTextEditor?.document;
  if (!doc) return void vscode.window.showInformationMessage("Open a file to see its blast radius.");
  try {
    const data = await blastFor(doc);
    if (!data) return;
    const { report: r, root, repoId } = data;
    const panel = vscode.window.createWebviewPanel("repopilot.blast", `Blast radius: ${r.targets[0]}`, vscode.ViewColumn.Beside, { enableScripts: true });
    const list = (items: string[]) => (items.length ? `<ul>${items.join("")}</ul>` : `<p class="muted">None.</p>`);
    panel.webview.html = panelHtml(`Blast radius: ${r.risk}`, `
      <ul>${r.risk_reasons.map((x) => `<li>${escapeHtml(x.replace(/`/g, ""))}</li>`).join("")}</ul>
      <h2>Changes together with</h2>${list(r.cochanged.map((c) => `<li>${link(c.path, { path: c.path })} <span class="muted">${Math.round(c.confidence * 100)}% of ${c.support} commits</span></li>`))}
      <h2>Depends on it</h2>${list(r.dependents.slice(0, 25).map((d) => `<li>${link(d.path, { path: d.path })} <span class="muted">${d.depth === 1 ? "direct" : "indirect"}</span></li>`))}
      <h2>Past bug fixes</h2>${list(r.past_fixes.map((f) => `<li><code>${f.sha.slice(0, 8)}</code> ${escapeHtml(f.subject)} <span class="muted">${f.date.slice(0, 10)}</span></li>`))}
      <h2>Tests to run</h2>${list(r.tests.map((t) => `<li>${link(t, { path: t })}</li>`))}
      ${r.owners.length ? `<p class="muted">Who knows it best: ${r.owners.map((o) => escapeHtml(o.author)).join(", ")}</p>` : ""}
      <p>${link("Open in RepoPilot", { url: `${baseUrl()}/app/blast/?repo=${repoId}&path=${encodeURIComponent(r.targets[0])}` })}</p>`);
    openOnMessage(panel, root);
  } catch (err) {
    showError(err);
  }
}

// ------------------------------------------------------------------ ask

export async function ask(): Promise<void> {
  const selection = vscode.window.activeTextEditor?.document.getText(vscode.window.activeTextEditor.selection);
  const question = await vscode.window.showInputBox({
    prompt: "Ask about this repository", placeHolder: "Where is authentication handled?",
    value: selection && selection.length < 120 ? `What does ${selection.trim()} do?` : "",
  });
  if (!question) return;
  try {
    const { repoId, root } = await ensureRepo();
    const panel = vscode.window.createWebviewPanel("repopilot.ask", `Ask: ${question.slice(0, 40)}`, vscode.ViewColumn.Beside, { enableScripts: true });
    openOnMessage(panel, root);
    let answer = "";
    const render = (cites: { n: number; path: string; start_line: number; end_line: number }[] = [], extra = "") => {
      const valid = new Map(cites.map((c) => [c.n, c]));
      const html = escapeHtml(answer).replace(/\[(\d{1,2})\]/g, (m, n) => {
        const c = valid.get(Number(n));
        return c ? link(`[${n}]`, { path: c.path, line: c.start_line, end: c.end_line }) : m;
      });
      const sources = cites.map((c) => `<li>${link(`[${c.n}] ${c.path}:${c.start_line}-${c.end_line}`, { path: c.path, line: c.start_line, end: c.end_line })}</li>`).join("");
      panel.webview.html = panelHtml(question, `<p style="white-space:pre-wrap">${html || "…"}</p>${sources ? `<h2>Sources</h2><ul>${sources}</ul>` : ""}${extra}`);
    };
    render();
    let cites: { n: number; path: string; start_line: number; end_line: number }[] = [];
    for await (const ev of askStream(repoId, question)) {
      if (ev.event === "token") { answer += ev.data; render(cites); }
      if (ev.event === "citations") { cites = ev.data; render(cites); }
      if (ev.event === "done" && ev.data.commits.length) {
        render(cites, `<h2>History</h2><ul>${ev.data.commits.map((c) => `<li><code>${c.sha.slice(0, 8)}</code> ${escapeHtml(c.subject)}</li>`).join("")}</ul>`);
      }
    }
  } catch (err) {
    showError(err);
  }
}

// ------------------------------------------------------------------ verified edit

class DiffDocs implements vscode.TextDocumentContentProvider {
  static scheme = "repopilot-diff";
  contents = new Map<string, string>();
  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.contents.get(uri.path) ?? "";
  }
}
export const diffDocs = new DiffDocs();

export async function edit(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  const instruction = await vscode.window.showInputBox({ prompt: "What should change? RepoPilot will test the edit before showing it.", placeHolder: "Reject negative discount rates" });
  if (!instruction) return;
  try {
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "RepoPilot", cancellable: true }, async (progress, token) => {
      const { repoId } = await ensureRepo(progress);
      const paths = editor ? [vscode.workspace.asRelativePath(editor.document.uri, false)] : undefined;
      progress.report({ message: "Writing and testing the change in a temporary copy…" });
      const { job_id } = await call<{ job_id: string }>(`/repos/${repoId}/edit`, { method: "POST", body: JSON.stringify({ instruction, paths }) });
      const result = await waitForJob<EditResult>(job_id, token);
      if (result.status === "failed") {
        const last = result.attempts.at(-1);
        void vscode.window.showWarningMessage(`RepoPilot couldn't produce a change that passes the checks after ${result.attempts.length} attempts.${last?.apply_error ? ` Last problem: ${last.apply_error}` : ""}`);
        return;
      }
      const key = `/${job_id}.diff`;
      diffDocs.contents.set(key, result.diff);
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.parse(`${DiffDocs.scheme}:${key}`));
      await vscode.languages.setTextDocumentLanguage(doc, "diff");
      await vscode.window.showTextDocument(doc, { preview: true, viewColumn: vscode.ViewColumn.Beside });
      const verdict = result.status === "verified" ? "Tests passed" : "No test command found; the change applies cleanly";
      const pick = await vscode.window.showInformationMessage(`${verdict}. ${result.explanation}`, { modal: true }, "Apply", "Discard");
      if (pick === "Apply") {
        await call(`/repos/${repoId}/edit/${job_id}/apply`, { method: "POST" });
        void vscode.window.showInformationMessage(`Applied to ${result.target_paths.join(", ")}.`);
      }
    });
  } catch (err) {
    showError(err);
  }
}

// ------------------------------------------------------------------ night shift & models

export async function nightShift(): Promise<void> {
  try {
    const { repoId } = await ensureRepo();
    await vscode.env.openExternal(vscode.Uri.parse(`${baseUrl()}/app/nightshift/?repo=${repoId}`));
  } catch (err) {
    showError(err);
  }
}

export async function pickModels(status: vscode.StatusBarItem): Promise<void> {
  try {
    const info = await call<{ models: { id: string; is_embedding: boolean; fits: boolean }[]; roles: Record<string, string> }>("/models");
    const role = await vscode.window.showQuickPick(
      [{ label: "strong", description: `Review and code · now ${info.roles.strong ?? "none"}` },
       { label: "fast", description: `Classification · now ${info.roles.fast ?? "none"}` },
       { label: "embed", description: `Search embeddings · now ${info.roles.embed ?? "none"}` }],
      { title: "Which role?" });
    if (!role) return;
    const choices = info.models.filter((m) => (role.label === "embed" ? true : !m.is_embedding)).map((m) => ({ label: m.id, description: m.fits ? "" : "may not fit in memory" }));
    const model = await vscode.window.showQuickPick(choices, { title: `Model for ${role.label}` });
    if (!model) return;
    await call("/models/roles", { method: "PUT", body: JSON.stringify({ [role.label]: model.label }) });
    await refreshStatus(status);
  } catch (err) {
    showError(err);
  }
}

export async function refreshStatus(status: vscode.StatusBarItem): Promise<void> {
  try {
    const info = await call<{ roles: Record<string, string> }>("/models");
    status.text = `$(shield) RepoPilot · ${info.roles.strong ?? "no model"} · local`;
    status.tooltip = "RepoPilot runs on models on this machine. Click to pick models.";
  } catch {
    status.text = "$(circle-slash) RepoPilot · not running";
    status.tooltip = "Start it with `repopilot serve`.";
  }
  status.show();
}

export async function reindex(): Promise<void> {
  try {
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "RepoPilot" }, async (progress) => {
      const { repoId } = await ensureRepo(progress);
      const { job_id } = await call<{ job_id: string }>(`/repos/${repoId}/index`, { method: "POST", body: "{}" });
      await waitForJob(job_id, undefined, (p) => progress.report({ message: `Updating memory: ${p.stage ?? ""}` }));
      blastCache.clear();
    });
  } catch (err) {
    showError(err);
  }
}
