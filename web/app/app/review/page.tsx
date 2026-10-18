"use client";

import { useCallback, useEffect, useState } from "react";

import { AppShell, useRepo } from "@/components/AppShell";
import { ReviewReportView } from "@/components/ReviewReport";
import { ErrorNotice, Loading, NeedsRepo } from "@/components/States";
import { api, DEMO, waitForJob } from "@/lib/api";
import type { ReviewListItem, ReviewReport } from "@/lib/types";
import "../app.css";

type Source = "working" | "staged" | "refs" | "paste";
const SOURCES: { id: Source; label: string }[] = [
  { id: "working", label: "Working changes" },
  { id: "staged", label: "Staged" },
  { id: "refs", label: "Compare branches" },
  { id: "paste", label: "Paste a diff" },
];

function ReviewPage() {
  const { repo, loading, error } = useRepo();
  const [source, setSource] = useState<Source>("working");
  const [base, setBase] = useState("main");
  const [head, setHead] = useState("HEAD");
  const [diff, setDiff] = useState("");
  const [runChecks, setRunChecks] = useState(true);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [history, setHistory] = useState<ReviewListItem[]>([]);
  const [failure, setFailure] = useState<unknown>(null);

  const load = useCallback(async (reviewId: string) => {
    if (!repo) return;
    setFailure(null);
    try {
      setReport(await api.review(repo.repo_id, reviewId));
    } catch (e) {
      setFailure(e);
    }
  }, [repo]);

  useEffect(() => {
    if (!repo) return;
    api.reviews(repo.repo_id).then((list) => {
      setHistory(list);
      const wanted = new URLSearchParams(window.location.search).get("review");
      const pick = wanted ?? (DEMO ? list[0]?.review_id : null);
      if (pick) void load(pick);
    }).catch(() => setHistory([]));
  }, [repo, load]);

  if (loading) return <Loading lines={4} />;
  if (error) return <ErrorNotice error={error} />;
  if (!repo) return <NeedsRepo />;

  const start = async (e: React.FormEvent) => {
    e.preventDefault();
    setRunning(true);
    setFailure(null);
    setReport(null);
    try {
      const body = source === "paste" ? { diff } : source === "staged" ? { staged: true } : source === "refs" ? { base, head } : {};
      const { job_id } = await api.startReview(repo.repo_id, { ...body, run_checks: runChecks });
      const result = await waitForJob<ReviewReport>(job_id);
      setReport(result);
      setHistory(await api.reviews(repo.repo_id));
      window.history.replaceState(null, "", `?review=${result.review_id}`);
    } catch (err) {
      setFailure(err);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="stack" style={{ gap: 24 }}>
      {!DEMO && (
        <form className="panel panel-pad stack" onSubmit={start}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="seg" role="group" aria-label="What to review">
              {SOURCES.map((s) => (
                <button key={s.id} type="button" aria-pressed={source === s.id} onClick={() => setSource(s.id)}>{s.label}</button>
              ))}
            </div>
            {history.length > 0 && (
              <label className="row hint">
                Earlier reviews
                <select className="select" style={{ width: 260 }} onChange={(e) => e.target.value && load(e.target.value)} defaultValue="">
                  <option value="">Choose…</option>
                  {history.map((h) => (
                    <option key={h.review_id} value={h.review_id}>
                      {new Date(h.created_at).toLocaleString()} · {h.behavior} to read
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {source === "refs" && (
            <div className="row">
              <label style={{ flex: 1 }}><span className="label">Base</span><input className="input mono" value={base} onChange={(e) => setBase(e.target.value)} /></label>
              <label style={{ flex: 1 }}><span className="label">Compare</span><input className="input mono" value={head} onChange={(e) => setHead(e.target.value)} /></label>
            </div>
          )}
          {source === "paste" && (
            <label><span className="label">Unified diff</span>
              <textarea className="textarea" value={diff} onChange={(e) => setDiff(e.target.value)} placeholder="diff --git a/app.py b/app.py" required />
            </label>
          )}
          <div className="row" style={{ justifyContent: "space-between" }}>
            <label className="row hint">
              <input type="checkbox" checked={runChecks} onChange={(e) => setRunChecks(e.target.checked)} />
              Run the project’s tests in a temporary copy
            </label>
            <button className="btn" disabled={running}>{running ? "Reviewing…" : "Review changes"}</button>
          </div>
          {running && <p className="progress-line" aria-live="polite">Classifying hunks, reading history, running checks and asking the model. Large changes take a minute.</p>}
        </form>
      )}
      {failure !== null && <ErrorNotice error={failure} />}
      {report ? <ReviewReportView report={report} /> : !running && !DEMO && (
        <p className="hint">Review your uncommitted work, a staged change or a branch. Mechanical edits are set aside so you read only what changes behavior.</p>
      )}
    </div>
  );
}

export default function Page() {
  return <AppShell title="Review"><ReviewPage /></AppShell>;
}
