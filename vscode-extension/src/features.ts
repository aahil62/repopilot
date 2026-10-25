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

let mediaRoot: vscode.Uri | undefined;
let lastPanelHtml = "";
let statusItem: vscode.StatusBarItem | undefined;

/** Called once from activate(): where the bundled fonts live. */
export function initFeatures(extensionUri: vscode.Uri): void {
  mediaRoot = vscode.Uri.joinPath(extensionUri, "media");
}

/** Test hook: the HTML of the most recently rendered panel. */
export function getLastPanelHtml(): string {
  return lastPanelHtml;
}

function createPanel(id: string, title: string): vscode.WebviewPanel {
  return vscode.window.createWebviewPanel(id, title, vscode.ViewColumn.Beside, {
    enableScripts: true,
    localResourceRoots: mediaRoot ? [mediaRoot] : [],
  });
}

const MARK = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M3 18 9 9l4 5 3-4 5 8" stroke="#e6904f" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/><circle cx="9" cy="9" r="1.7" fill="#e6904f"/></svg>`;

/**
 * Panels follow the user's editor theme (--vscode-* colours) and carry RepoPilot's type:
 * Bricolage for the headline and big numbers, Instrument Sans for reading, Fragment Mono for data.
 * Fonts are bundled; nothing is fetched from the internet.
 */
function panelHtml(webview: vscode.Webview, title: string, body: string, pill = ""): string {
  const font = (file: string) => (mediaRoot ? webview.asWebviewUri(vscode.Uri.joinPath(mediaRoot, "fonts", file)).toString() : "");
  const html = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; font-src ${webview.cspSource}; script-src 'unsafe-inline';">
<style>
@font-face{font-family:"RP Display";src:url("${font("bricolage-grotesque.woff2")}") format("woff2");font-weight:200 800;font-display:swap}
@font-face{font-family:"RP Sans";src:url("${font("instrument-sans.woff2")}") format("woff2");font-weight:400 700;font-display:swap}
@font-face{font-family:"RP Mono";src:url("${font("fragment-mono-400.woff2")}") format("woff2");font-weight:400;font-display:swap}
:root{--accent:#e6904f;--accent-text:color-mix(in srgb,#e6904f 70%,var(--vscode-foreground));--accent-soft:color-mix(in srgb,#e6904f 14%,transparent);
  --hair:var(--vscode-panel-border,color-mix(in srgb,var(--vscode-foreground) 16%,transparent));--ease:cubic-bezier(.2,.8,.2,1)}
body.vscode-light,body.vscode-high-contrast-light{--accent-text:color-mix(in srgb,#e6904f 30%,var(--vscode-foreground))}
body.vscode-light :is(.sub,.path,.ev,.muted,.pill,.legend span:not(.hot),.stat span,.find p){opacity:.9}
body{font-family:"RP Sans",var(--vscode-font-family);font-size:13px;line-height:1.55;color:var(--vscode-foreground);padding:14px 20px 28px;max-width:860px}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}
.brand{display:flex;gap:7px;align-items:center;font-family:"RP Display",var(--vscode-font-family);font-weight:600;font-size:14px}
.pill,.mono,code,pre,.path,.sub,.chip,.legend{font-family:"RP Mono",var(--vscode-editor-font-family)}
.pill{font-size:10.5px;opacity:.75;border:1px solid var(--hair);border-radius:99px;padding:2px 8px;white-space:nowrap}
.headline{font-family:"RP Display",var(--vscode-font-family);font-weight:600;font-size:22px;letter-spacing:-.02em;line-height:1.15;margin:4px 0 4px}
h2{font-family:"RP Display",var(--vscode-font-family);font-weight:600;font-size:14px;margin:20px 0 6px}
.sub{font-size:11px;opacity:.7;margin-bottom:12px}
.bar{display:flex;height:6px;border-radius:99px;overflow:hidden;background:var(--hair);margin-bottom:6px}
.bar i{display:block}.bar .m{background:color-mix(in srgb,var(--vscode-foreground) 28%,transparent)}.bar .b{background:var(--accent)}
.legend{display:flex;justify-content:space-between;font-size:10.5px;margin-bottom:14px}.legend span:not(.hot){opacity:.8}.legend .hot{color:var(--accent-text)}
.find{border:1px solid var(--hair);border-radius:10px;padding:10px 12px;margin-bottom:8px;transition:border-color .2s var(--ease),background .2s var(--ease);cursor:pointer}
.find:hover{border-color:var(--accent);background:var(--accent-soft)}
.find .row{display:flex;justify-content:space-between;gap:10px}.find .title{font-weight:500}
.find p{margin:5px 0 0;opacity:.85}.path{font-size:11.5px;opacity:.72;overflow-wrap:anywhere}.ev{font-size:11px;opacity:.6;margin-top:6px}
.chip{font-size:10.5px;text-transform:lowercase;color:var(--accent-text)}.chip.high{color:var(--vscode-errorForeground)}.chip.low{opacity:.7;color:inherit}
.empty{border:1px dashed var(--hair);border-radius:10px;padding:12px;opacity:.8}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0}
.stat{border:1px solid var(--hair);border-radius:9px;padding:8px 10px}
.stat b{display:block;font-family:"RP Display",var(--vscode-font-family);font-size:18px;font-weight:600}.stat span{font-size:11.5px;opacity:.7}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
button{font:inherit;font-size:12px;padding:7px 11px;border-radius:8px;cursor:pointer;border:1px solid var(--hair);background:transparent;color:inherit;transition:transform .15s var(--ease),border-color .2s var(--ease)}
button.pr{background:var(--vscode-button-background);color:var(--vscode-button-foreground);border-color:transparent}
button:hover{transform:translateY(-1px);border-color:var(--accent)}button:active{transform:scale(.98)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
a{color:var(--vscode-textLink-foreground);cursor:pointer}.muted{opacity:.72}ul{padding-left:18px}li{margin:3px 0}
pre{background:var(--vscode-textCodeBlock-background);padding:8px 10px;overflow-x:auto;border-radius:6px}
</style></head><body>
<div class="top"><div class="brand">${MARK}RepoPilot</div>${pill ? `<span class="pill">${escapeHtml(pill)}</span>` : ""}</div>
<h1 class="headline">${escapeHtml(title)}</h1>${body}
<script>const vscode=acquireVsCodeApi();document.addEventListener('click',e=>{const a=e.target.closest('[data-open]');if(a){e.preventDefault();vscode.postMessage(JSON.parse(a.dataset.open));}});</script></body></html>`;
  lastPanelHtml = html;
  return html;
}

function openOnMessage(panel: vscode.WebviewPanel, root: vscode.Uri): void {
  panel.webview.onDidReceiveMessage(async (msg: { path?: string; line?: number; end?: number; url?: string; ask?: string }) => {
    if (msg.url) return void vscode.env.openExternal(vscode.Uri.parse(msg.url));
    if (msg.ask) return void ask(`What does ${msg.ask} do, and what depends on it?`);
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

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function button(label: string, target: object, primary = false): string {
  return `<button${primary ? ' class="pr"' : ""} data-open='${escapeHtml(JSON.stringify(target))}'>${escapeHtml(label)}</button>`;
}

function showReport(root: vscode.Uri, repoId: string, r: ReviewReport): void {
  const panel = createPanel("repopilot.review", "RepoPilot review");
  const total = r.behavior_count + r.mechanical_count;
  const share = total ? Math.round((r.behavior_count / total) * 100) : 0;
  const headline = r.behavior_count ? `${plural(r.behavior_count, "change")} worth reading` : "Only formatting changed";
  const focus = r.findings[0]?.path ?? r.blast?.targets[0];
  const findings = r.findings.length
    ? r.findings.map((f) => `<div class="find" data-open='${escapeHtml(JSON.stringify({ path: f.path, line: f.line }))}'>
        <div class="row"><span class="title">${escapeHtml(f.title)}</span><span class="chip ${f.severity}">${f.severity}</span></div>
        <div class="path">${escapeHtml(f.path)}:${f.line}</div><p>${escapeHtml(f.explanation)}</p>
        ${f.evidence_detail.length ? `<div class="ev">↳ ${f.evidence_detail.map((e) => escapeHtml(e.ref)).join(" · ")}</div>` : ""}</div>`).join("")
    : `<div class="empty">No problems found in the behavior changes.</div>`;
  const stats = r.blast
    ? `<div class="stats"><div class="stat"><b>${escapeHtml(r.blast.risk)}</b><span>blast radius</span></div><div class="stat"><b>${r.blast.dependents.length}</b><span>files depend on it</span></div></div>`
    : "";
  const body = `<div class="sub">${plural(total, "hunk")} · tests ${escapeHtml(r.checks.status.replace("_", " "))}</div>
    <div class="bar" role="img" aria-label="${r.mechanical_count} formatting, ${r.behavior_count} behavior"><i class="m" style="width:${100 - share}%"></i><i class="b" style="width:${share}%"></i></div>
    <div class="legend"><span>${r.mechanical_count} formatting set aside</span><span class="hot">${r.behavior_count} behavior</span></div>
    ${r.model_error ? `<p class="muted">${escapeHtml(r.model_error)}</p>` : ""}
    ${findings}
    ${r.dropped_unverifiable ? `<p class="muted">${r.dropped_unverifiable} model finding(s) discarded: they cited lines outside the change.</p>` : ""}
    ${stats}
    ${r.checks.status === "failed" ? `<h2>Failing checks</h2><pre>${escapeHtml(r.checks.output_tail)}</pre>` : ""}
    <div class="btns">${button("Open full report", { url: `${baseUrl()}/app/review/?repo=${repoId}&review=${r.review_id}` }, true)}${focus ? button(`Ask about ${focus.split("/").pop()}`, { ask: focus }) : ""}</div>`;
  panel.webview.html = panelHtml(panel.webview, headline, body, r.model?.strong ? `${r.model.strong} · local` : "local");
  openOnMessage(panel, root);
  if (statusItem) {
    statusItem.text = `$(circle-filled) RepoPilot · ${r.behavior_count} to read · ${r.mechanical_count} set aside`;
    statusItem.tooltip = "Last review. Click to pick models.";
  }
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
    const panel = createPanel("repopilot.blast", `Blast radius: ${r.targets[0]}`);
    const list = (items: string[]) => (items.length ? `<ul>${items.join("")}</ul>` : `<p class="muted">None.</p>`);
    panel.webview.html = panelHtml(panel.webview, `Blast radius: ${r.risk}`, `<div class="sub">${escapeHtml(r.targets[0])}</div>
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

export async function ask(prefill?: string): Promise<void> {
  const selection = vscode.window.activeTextEditor?.document.getText(vscode.window.activeTextEditor.selection);
  const question = await vscode.window.showInputBox({
    prompt: "Ask about this repository", placeHolder: "Where is authentication handled?",
    value: prefill ?? (selection && selection.length < 120 ? `What does ${selection.trim()} do?` : ""),
  });
  if (!question) return;
  try {
    const { repoId, root } = await ensureRepo();
    const panel = createPanel("repopilot.ask", `Ask: ${question.slice(0, 40)}`);
    openOnMessage(panel, root);
    let answer = "";
    const render = (cites: { n: number; path: string; start_line: number; end_line: number }[] = [], extra = "") => {
      const valid = new Map(cites.map((c) => [c.n, c]));
      const html = escapeHtml(answer).replace(/\[(\d{1,2})\]/g, (m, n) => {
        const c = valid.get(Number(n));
        return c ? link(`[${n}]`, { path: c.path, line: c.start_line, end: c.end_line }) : m;
      });
      const sources = cites.map((c) => `<li>${link(`[${c.n}] ${c.path}:${c.start_line}-${c.end_line}`, { path: c.path, line: c.start_line, end: c.end_line })}</li>`).join("");
      panel.webview.html = panelHtml(panel.webview, question, `<p style="white-space:pre-wrap">${html || "…"}</p>${sources ? `<h2>Sources</h2><ul>${sources}</ul>` : ""}${extra}`);
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
  statusItem = status;
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
