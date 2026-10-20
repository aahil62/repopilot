"use client";

import { useEffect, useState } from "react";

import { AppShell, useRepo } from "@/components/AppShell";
import { Empty, ErrorNotice, Loading, NeedsRepo } from "@/components/States";
import { api, DEMO, waitForJob } from "@/lib/api";
import type { NightListItem, NightReport } from "@/lib/types";
import "../app.css";

function NightShift() {
  const { repo, loading, error } = useRepo();
  const [list, setList] = useState<NightListItem[] | null>(null);
  const [report, setReport] = useState<NightReport | null>(null);
  const [running, setRunning] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [schedule, setSchedule] = useState<{ activate: string; content?: string; path?: string } | null>(null);

  useEffect(() => {
    if (!repo) return;
    api.nightReports(repo.repo_id).then((items) => {
      setList(items);
      if (items[0]) api.nightReport(repo.repo_id, items[0].date).then(setReport).catch(setFailure);
    }).catch((e) => { setList([]); setFailure(e); });
  }, [repo]);

  if (loading) return <Loading lines={4} />;
  if (error) return <ErrorNotice error={error} />;
  if (!repo) return <NeedsRepo />;

  const runNow = async () => {
    setRunning(true);
    setFailure(null);
    try {
      const { job_id } = await api.runNightShift(repo.repo_id);
      const result = await waitForJob<NightReport>(job_id);
      setReport(result);
      setList(await api.nightReports(repo.repo_id));
    } catch (e) {
      setFailure(e);
    } finally {
      setRunning(false);
    }
  };

  const verified = report?.tests_written.filter((t) => t.status === "verified") ?? [];
  const findings = report?.commits_reviewed.reduce((n, c) => n + c.findings.length, 0) ?? 0;

  return (
    <div className="stack" style={{ gap: 22 }}>
      <p className="page-intro">
        While you sleep, RepoPilot reviews every new commit, writes tests for new code — kept only if they pass, on a
        separate branch — and lists docs that mention code that no longer exists. Local models make this free to run every night.
      </p>
      {!DEMO && (
        <div className="row">
          <button className="btn" onClick={runNow} disabled={running}>{running ? "Running…" : "Run now"}</button>
          <button className="btn secondary" onClick={() => api.schedule(repo.repo_id).then(setSchedule).catch(setFailure)}>Schedule nightly</button>
        </div>
      )}
      {schedule && (
        <div className="panel panel-pad">
          <p className="hint" style={{ marginBottom: 8 }}>RepoPilot never schedules itself. Run this in a terminal to turn it on:</p>
          <pre className="panel" style={{ padding: "10px 12px", margin: 0, overflowX: "auto" }}>{schedule.content && !schedule.path ? schedule.content : `repopilot nightshift install --repo ${repo.path}\n${schedule.activate}`}</pre>
        </div>
      )}
      {failure !== null && <ErrorNotice error={failure} />}
      {list === null ? <Loading lines={3} /> : !report ? (
        <Empty title="No night-shift reports yet">Run it once to see what it does, then schedule it.</Empty>
      ) : (
        <div className="night-layout">
          <nav className="panel panel-pad" aria-label="Reports">
            <h2 className="section-title">Mornings</h2>
            <ul className="fix-list">
              {list.map((r) => (
                <li key={r.date}>
                  <button className="link-btn" aria-current={r.date === report.date}
                    onClick={() => api.nightReport(repo.repo_id, r.date).then(setReport).catch(setFailure)}>{r.date}</button>
                  <span className="hint">{r.commits} commits · {r.findings} findings · {r.tests_verified} tests</span>
                </li>
              ))}
            </ul>
          </nav>
          <article className="stack">
            <section className="panel panel-pad">
              <h2 style={{ fontSize: "var(--t-2xl)", marginBottom: 6 }}>Good morning.</h2>
              <p style={{ fontSize: "var(--t-lg)", maxWidth: "62ch" }}>
                Overnight RepoPilot read {report.commits_reviewed.length} commit{report.commits_reviewed.length === 1 ? "" : "s"},
                found {findings} thing{findings === 1 ? "" : "s"} worth a look, wrote {verified.length} passing test{verified.length === 1 ? "" : "s"} and
                spotted {report.stale_docs.length} out-of-date doc reference{report.stale_docs.length === 1 ? "" : "s"}.
              </p>
              <p className="hint mono" style={{ marginTop: 8, fontSize: 11 }}>{report.model.strong} · {Math.round(report.duration_s)}s</p>
            </section>
            <section className="panel panel-pad">
              <h3 className="section-title">Commits</h3>
              <ul className="fix-list">
                {report.commits_reviewed.map((c) => (
                  <li key={c.sha}>
                    <span><span className="mono hint">{c.sha.slice(0, 8)}</span> {c.subject}</span>
                    {c.findings.length === 0 ? <span className="hint">Nothing to flag · {c.behavior_hunks} behavior hunk{c.behavior_hunks === 1 ? "" : "s"}</span> :
                      c.findings.map((f, i) => (
                        <span key={i}><span className={`chip ${f.severity}`}>{f.severity}</span> <span className="mono" style={{ fontSize: 12 }}>{f.path}:{f.line}</span> {f.title}</span>
                      ))}
                  </li>
                ))}
              </ul>
            </section>
            <div className="grid-2">
              <section className="panel panel-pad">
                <h3 className="section-title">Tests written</h3>
                {report.tests_written.length ? (
                  <ul className="fix-list">{report.tests_written.map((t) => (
                    <li key={t.symbol + t.test_path}>
                      <span><span className={`chip ${t.status === "verified" ? "verified" : "failed"}`}>{t.status === "verified" ? "passes" : "discarded"}</span>{" "}
                        <code>{t.symbol}</code> → <span className="mono" style={{ fontSize: 12 }}>{t.test_path}</span></span>
                      {t.branch && <span className="hint">on branch <code>{t.branch}</code></span>}
                    </li>
                  ))}</ul>
                ) : <p className="hint">Every changed function already has tests.</p>}
              </section>
              <section className="panel panel-pad">
                <h3 className="section-title">Stale docs</h3>
                {report.stale_docs.length ? (
                  <ul className="fix-list">{report.stale_docs.map((d) => (
                    <li key={d.doc_path + d.line + d.symbol}><span className="mono" style={{ fontSize: 12 }}>{d.doc_path}:{d.line}</span>
                      <span className="hint">mentions <code>{d.symbol}</code>, removed in {d.commit}</span></li>
                  ))}</ul>
                ) : <p className="hint">No documentation mentions removed code.</p>}
              </section>
            </div>
          </article>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return <AppShell title="Night shift"><NightShift /></AppShell>;
}
