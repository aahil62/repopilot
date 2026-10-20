"use client";

import { CaretDown, CaretRight, CheckCircle, Warning, XCircle } from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import type { FileView, Finding, ReviewReport as Report } from "@/lib/types";
import { DiffHunk } from "./DiffView";
import { Orbit } from "./Orbit";
import "./review.css";

function anchor(path: string) {
  return `file-${path.replace(/[^a-zA-Z0-9]/g, "-")}`;
}

function FindingCard({ f }: { f: Finding }) {
  return (
    <article className={`finding ${f.severity}`}>
      <header className="row">
        <span className={`chip ${f.severity}`}>{f.severity}</span>
        <a className="mono finding-loc" href={`#${anchor(f.path)}`}>{f.path}:{f.line}</a>
      </header>
      <h3>{f.title}</h3>
      <p>{f.explanation}</p>
      {f.evidence_detail.length > 0 && (
        <ul className="evidence">
          {f.evidence_detail.map((e) => (
            <li key={e.ref}>
              <span className="chip">{e.kind === "fix_commit" ? "past fix" : "past review"} · {e.ref}</span>
              <span>{e.excerpt}</span>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

function FileDiff({ file, flagged }: { file: FileView; flagged: number[] }) {
  const [showMechanical, setShowMechanical] = useState(false);
  const mech = file.hunks.filter((h) => h.label === "mechanical");
  const behavior = file.hunks.filter((h) => h.label === "behavior");
  const reasons = [...new Set(mech.map((h) => h.reason.split(" (")[0]))].slice(0, 3).join(", ");
  return (
    <section className="panel file-diff" id={anchor(file.path)}>
      <header className="file-diff-head">
        <span className="mono truncate">{file.path}</span>
        <span className="hint">{file.status}</span>
        {file.behavior_hunks > 0 && <span className="chip behavior">{file.behavior_hunks} to read</span>}
      </header>
      {behavior.map((h, i) => <DiffHunk key={`b${i}`} hunk={h} flaggedLines={flagged} />)}
      {mech.length > 0 && (
        <>
          <button className="mech-toggle" onClick={() => setShowMechanical(!showMechanical)} aria-expanded={showMechanical}>
            {showMechanical ? <CaretDown size={13} /> : <CaretRight size={13} />}
            Mechanical · {mech.length} hunk{mech.length > 1 ? "s" : ""} — {reasons}
          </button>
          {showMechanical && mech.map((h, i) => <DiffHunk key={`m${i}`} hunk={h} />)}
        </>
      )}
    </section>
  );
}

const CHECK_ICON = { passed: CheckCircle, failed: XCircle, timeout: Warning, skipped: Warning, not_applied: XCircle };

export function ReviewReportView({ report }: { report: Report }) {
  const flaggedByFile = useMemo(() => {
    const map: Record<string, number[]> = {};
    for (const f of report.findings) (map[f.path] ||= []).push(f.line);
    return map;
  }, [report]);
  const total = report.mechanical_count + report.behavior_count;
  const Icon = CHECK_ICON[report.checks.status];
  const files = [...report.files].sort((a, b) => b.behavior_hunks - a.behavior_hunks);
  const mechReasons = [...new Set(report.files.flatMap((f) => f.hunks.filter((h) => h.label === "mechanical").map((h) => h.reason.split(" (")[0])))];

  return (
    <div className="review">
      <section className="review-head">
        <p className="review-count">
          <span className="mark-num">{report.behavior_count}</span> of {total} hunks change behavior.
          {report.mechanical_count > 0 && <> The other {report.mechanical_count} are {mechReasons.join(", ")} — collapsed below.</>}
        </p>
        <p className="review-summary">{report.summary.replace(/\s*Behavior changes to read:.*$/, "")}</p>
        {report.model_error && <div className="notice">{report.model_error} Deterministic results are shown.</div>}
      </section>

      <div className="review-grid">
        <nav className="review-files" aria-label="Changed files">
          <h2 className="section-title">Files</h2>
          <ul>
            {files.map((f) => (
              <li key={f.path}>
                <a href={`#${anchor(f.path)}`} className="mono truncate">{f.path}</a>
                <span className="hint">{f.behavior_hunks ? `${f.behavior_hunks} to read` : "mechanical only"}</span>
              </li>
            ))}
          </ul>
        </nav>

        <div className="review-main">
          <h2 className="section-title">Findings</h2>
          {report.findings.length === 0 ? (
            <p className="hint" style={{ marginBottom: 16 }}>No problems found in the behavior changes.</p>
          ) : (
            <div className="stack" style={{ marginBottom: 20 }}>{report.findings.map((f, i) => <FindingCard key={i} f={f} />)}</div>
          )}
          {report.dropped_unverifiable > 0 && (
            <p className="hint dropped">
              {report.dropped_unverifiable} model finding{report.dropped_unverifiable > 1 ? "s were" : " was"} discarded because
              {report.dropped_unverifiable > 1 ? " they" : " it"} pointed at lines outside this change.
            </p>
          )}
          <div className="stack">{files.map((f) => <FileDiff key={f.path} file={f} flagged={flaggedByFile[f.path] ?? []} />)}</div>
          <section className={`panel panel-pad checks ${report.checks.status}`}>
            <h2 className="section-title row"><Icon size={18} weight="fill" /> Checks {report.checks.status.replace("_", " ")}</h2>
            {report.checks.command && <p className="mono hint">{report.checks.command} · {report.checks.duration_s}s</p>}
            {report.checks.message && <p className="hint">{report.checks.message}</p>}
            {report.checks.status === "failed" && <pre className="checks-out">{report.checks.output_tail}</pre>}
          </section>
        </div>

        <aside className="review-side">
          {report.blast && (
            <section className="panel panel-pad">
              <h2 className="section-title row">Blast radius <span className={`chip ${report.blast.risk}`}>{report.blast.risk}</span></h2>
              <Orbit report={report.blast} />
              <ul className="reasons">{report.blast.risk_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              {report.blast.owners.length > 0 && (
                <p className="hint" style={{ marginTop: 10 }}>
                  Who knows this code: {report.blast.owners.map((o) => `${o.author} (${o.commits} commit${o.commits === 1 ? "" : "s"})`).join(", ")}
                </p>
              )}
            </section>
          )}
          {report.precedents.length > 0 && (
            <section className="panel panel-pad">
              <h2 className="section-title">Similar past changes</h2>
              <ul className="evidence">
                {report.precedents.map((p) => (
                  <li key={p.ref + p.excerpt}><span className="chip">{p.ref}</span><span>{p.excerpt}</span></li>
                ))}
              </ul>
            </section>
          )}
          <p className="hint mono" style={{ fontSize: 11 }}>
            {Object.entries(report.model).filter(([k]) => k !== "embed").map(([k, v]) => `${k}: ${v}`).join(" · ")} · {Math.round(report.timings_ms.total / 100) / 10}s
          </p>
        </aside>
      </div>
    </div>
  );
}
