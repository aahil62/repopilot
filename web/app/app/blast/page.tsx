"use client";

import { useEffect, useState } from "react";

import { AppShell, useRepo } from "@/components/AppShell";
import { Orbit } from "@/components/Orbit";
import { ErrorNotice, Loading, NeedsRepo } from "@/components/States";
import { api, DEMO } from "@/lib/api";
import type { BlastReport, FileEntry } from "@/lib/types";
import "../app.css";

function BlastPage() {
  const { repo, loading, error } = useRepo();
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [path, setPath] = useState<string | null>(null);
  const [result, setResult] = useState<{ path: string; report?: BlastReport; error?: unknown } | null>(null);

  useEffect(() => {
    if (!repo) return;
    const t = setTimeout(() => {
      api.files(repo.repo_id, query).then((list) => {
        setFiles(list);
        const wanted = new URLSearchParams(window.location.search).get("path");
        if (list.length && (DEMO || wanted)) setPath((p) => p ?? wanted ?? list[0].path);
      }).catch(() => setFiles([]));
    }, 150);
    return () => clearTimeout(t);
  }, [repo, query]);

  useEffect(() => {
    if (!repo || !path) return;
    api.blast(repo.repo_id, [path]).then((report) => setResult({ path, report }), (error) => setResult({ path, error }));
  }, [repo, path]);

  const current = result?.path === path ? result : null;
  const report = current?.report ?? null;
  const failure = current?.error ?? null;

  if (loading) return <Loading lines={4} />;
  if (error) return <ErrorNotice error={error} />;
  if (!repo) return <NeedsRepo />;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <p className="page-intro">
        Before you change a file, see what usually changes or breaks with it — learned from the git history and the import graph, not guessed.
      </p>
      <div className="blast-layout">
        <section className="panel panel-pad">
          <label>
            <span className="label">File</span>
            <input className="input mono" placeholder="Search files…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <ul className="file-pick" role="listbox" aria-label="Files">
            {files.map((f) => (
              <li key={f.path}>
                <button role="option" aria-selected={f.path === path} className="mono" onClick={() => setPath(f.path)}>{f.path}</button>
              </li>
            ))}
            {!files.length && <li className="hint" style={{ padding: 8 }}>No matching files.</li>}
          </ul>
        </section>
        <div className="stack">
          {failure !== null && <ErrorNotice error={failure} />}
          {!path && <p className="hint">Pick a file to see its blast radius.</p>}
          {path && !current && <Loading lines={5} />}
          {report && (
            <>
              <section className="panel panel-pad">
                <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
                  <h2 className="mono" style={{ fontSize: "var(--t-md)" }}>{report.targets[0]}</h2>
                  <span className={`chip ${report.risk}`}>{report.risk} risk</span>
                </div>
                <div className="blast-hero">
                  <Orbit report={report} onSelect={(p) => setPath(p)} />
                  <ul className="reasons" style={{ fontSize: "var(--t-md)" }}>
                    {report.risk_reasons.map((r) => <li key={r}>{r}</li>)}
                    {report.owners.length > 0 && <li>Who knows it best: {report.owners.map((o) => `${o.author} (${o.commits} commit${o.commits === 1 ? "" : "s"})`).join(", ")}.</li>}
                  </ul>
                </div>
              </section>
              <div className="blast-details">
                <section className="panel panel-pad">
                  <h3 className="section-title">Changes together with</h3>
                  {report.cochanged.length ? (
                    <table className="table"><tbody>
                      {report.cochanged.map((c) => (
                        <tr key={c.path}>
                          <td className="mono" style={{ fontSize: 12 }}><button className="link-btn" onClick={() => setPath(c.path)}>{c.path}</button></td>
                          <td style={{ width: 120 }}><div className="bar" title={`${Math.round(c.confidence * 100)}%`}><span style={{ width: `${c.confidence * 100}%` }} /></div></td>
                          <td className="hint" style={{ width: 120, whiteSpace: "nowrap" }}>{c.support} of {Math.round(c.support / Math.max(c.confidence, 0.01))} commits</td>
                        </tr>
                      ))}
                    </tbody></table>
                  ) : <p className="hint">No file changes with this one at least three times.</p>}
                </section>
                <section className="panel panel-pad">
                  <h3 className="section-title">Past bug fixes here</h3>
                  {report.past_fixes.length ? (
                    <ul className="fix-list">
                      {report.past_fixes.map((f) => (
                        <li key={f.sha}><span className="mono hint">{f.sha.slice(0, 8)} · {f.date.slice(0, 10)}</span>{f.subject}</li>
                      ))}
                    </ul>
                  ) : <p className="hint">No commits that look like bug fixes touched this file.</p>}
                </section>
                <section className="panel panel-pad">
                  <h3 className="section-title">Depends on it</h3>
                  {report.dependents.length ? (
                    <ul className="fix-list">{report.dependents.map((d) => (
                      <li key={d.path}><button className="link-btn mono" onClick={() => setPath(d.path)}>{d.path}</button>
                        <span className="hint">{d.depth === 1 ? "imports it directly" : "through another file"}</span></li>
                    ))}</ul>
                  ) : <p className="hint">Nothing in the repository imports this file.</p>}
                </section>
                <section className="panel panel-pad">
                  <h3 className="section-title">Tests to run</h3>
                  {report.tests.length ? <ul className="fix-list">{report.tests.map((t) => <li key={t} className="mono">{t}</li>)}</ul>
                    : <p className="hint">No test file imports it or changes with it.</p>}
                </section>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Page() {
  return <AppShell title="Blast radius"><BlastPage /></AppShell>;
}
