"use client";

import { ArrowsClockwise, FolderSimple, GithubLogo } from "@phosphor-icons/react";
import { useState } from "react";

import { AppShell, useRepo } from "@/components/AppShell";
import { Empty, ErrorNotice, Loading } from "@/components/States";
import { api, DEMO, waitForJob } from "@/lib/api";
import type { RepoSummary } from "@/lib/types";
import "./app.css";

const STAGES: Record<string, string> = {
  scanning: "Listing files", chunking: "Reading code", embedding: "Building the search index",
  graph: "Resolving imports", history: "Reading git history", done: "Ready",
};

function useIndexer(onDone: () => Promise<void>) {
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ stage?: string; done?: number; total?: number; message?: string }>({});
  const [error, setError] = useState<unknown>(null);
  const run = async (repoId: string) => {
    setBusy(repoId);
    setError(null);
    setProgress({ stage: "scanning" });
    try {
      const { job_id } = await api.index(repoId);
      await waitForJob(job_id, (p) => setProgress(p as typeof progress));
      await onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return { busy, progress, error, run };
}

function when(iso: string | null) {
  if (!iso) return "never";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function RepoCard({ repo, indexing, progress, onReindex }: {
  repo: RepoSummary; indexing: boolean; progress: { stage?: string; done?: number; total?: number }; onReindex: () => void;
}) {
  const pct = progress.total ? Math.round(((progress.done ?? 0) / progress.total) * 100) : null;
  return (
    <article className="panel panel-pad repo-card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 style={{ fontSize: "var(--t-lg)" }}>{repo.name}</h2>
          <p className="hint mono" style={{ fontSize: 12 }}>{repo.path}</p>
        </div>
        {!DEMO && (
          <button className="btn secondary small" onClick={onReindex} disabled={indexing}>
            <ArrowsClockwise size={14} /> {indexing ? "Updating…" : "Update memory"}
          </button>
        )}
      </div>
      <dl className="kv" style={{ marginTop: 14 }}>
        <dt>Files</dt><dd>{repo.files.toLocaleString()}</dd>
        <dt>Searchable chunks</dt><dd>{repo.chunks.toLocaleString()}</dd>
        <dt>Commits remembered</dt><dd>{repo.commits.toLocaleString()}{repo.history_truncated && <span className="hint"> (newest only)</span>}</dd>
        <dt>Review comments</dt><dd>{repo.review_comments.toLocaleString()}</dd>
        <dt>Last updated</dt><dd>{when(repo.indexed_at)}</dd>
      </dl>
      {indexing && (
        <div style={{ marginTop: 14 }} aria-live="polite">
          <div className="progress-line">{STAGES[progress.stage ?? "scanning"] ?? progress.stage}{pct !== null && ` · ${pct}%`}</div>
          <div className="progress-track"><span style={{ width: `${pct ?? 8}%` }} /></div>
        </div>
      )}
    </article>
  );
}

function AddRepository({ onAdded }: { onAdded: (repo: RepoSummary) => Promise<void> }) {
  const [mode, setMode] = useState<"path" | "git_url">("path");
  const [value, setValue] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const repo = await api.addRepo(mode === "path" ? { path: value.trim() } : { git_url: value.trim() });
      setValue("");
      await onAdded(repo);
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="panel panel-pad stack" onSubmit={submit} style={{ maxWidth: 620 }}>
      <div>
        <h2 className="section-title" style={{ marginBottom: 4 }}>Add a repository</h2>
        <p className="hint">RepoPilot reads the code and git history on this machine. Nothing is uploaded.</p>
      </div>
      <div className="seg" role="group" aria-label="Repository source">
        <button type="button" aria-pressed={mode === "path"} onClick={() => setMode("path")}><FolderSimple size={14} /> Folder on this machine</button>
        <button type="button" aria-pressed={mode === "git_url"} onClick={() => setMode("git_url")}><GithubLogo size={14} /> Clone from GitHub</button>
      </div>
      <label>
        <span className="label">{mode === "path" ? "Folder path" : "GitHub URL"}</span>
        <input className="input mono" value={value} onChange={(e) => setValue(e.target.value)} required
          placeholder={mode === "path" ? "/Users/you/code/my-service" : "https://github.com/pallets/flask"} />
      </label>
      {error !== null && <ErrorNotice error={error} />}
      <div><button className="btn" disabled={saving || !value.trim()}>{saving ? "Adding…" : "Add and index"}</button></div>
    </form>
  );
}

function Overview() {
  const { repos, loading, error, refresh, selectRepo } = useRepo();
  const indexer = useIndexer(refresh);

  if (loading) return <Loading lines={4} />;
  if (error) return <ErrorNotice error={error} />;

  return (
    <div className="stack" style={{ gap: 24 }}>
      <p className="page-intro">
        Each repository gets a private memory: its code, how files import each other, and its git history. Reviews,
        blast radius and the night shift all read from it.
      </p>
      {indexer.error !== null && <ErrorNotice error={indexer.error} />}
      {repos.length === 0 ? (
        <Empty title="No repositories yet">Add a folder or clone a public GitHub repository to begin.</Empty>
      ) : (
        <div className="grid-2">
          {repos.map((r) => (
            <RepoCard key={r.repo_id} repo={r} indexing={indexer.busy === r.repo_id} progress={indexer.progress}
              onReindex={() => indexer.run(r.repo_id)} />
          ))}
        </div>
      )}
      {!DEMO && <AddRepository onAdded={async (repo) => { await refresh(); selectRepo(repo.repo_id); await indexer.run(repo.repo_id); }} />}
    </div>
  );
}

export default function Page() {
  return <AppShell title="Overview"><Overview /></AppShell>;
}
