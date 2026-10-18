"use client";

import { useEffect, useState } from "react";

import { AppShell, useRepo } from "@/components/AppShell";
import { Empty, ErrorNotice, Loading, NeedsRepo } from "@/components/States";
import { api, DEMO } from "@/lib/api";
import "../app.css";

function DeleteMemory({ repoId, name, onDeleted }: { repoId: string; name: string; onDeleted: () => Promise<void> }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const remove = async () => {
    setBusy(true);
    try {
      await api.deleteRepo(repoId);
      await onDeleted();
    } catch (e) {
      setFailure(e);
      setBusy(false);
    }
  };
  return (
    <section className="panel panel-pad stack" style={{ maxWidth: 680 }}>
      <div>
        <h2 className="section-title" style={{ marginBottom: 4 }}>Delete repository memory</h2>
        <p className="hint">Removes RepoPilot’s index, history, saved reviews and reports for {name}. Your code and git history are not touched.</p>
      </div>
      {failure !== null && <ErrorNotice error={failure} />}
      {confirming ? (
        <div className="row" role="alertdialog" aria-label={`Delete memory for ${name}?`}>
          <span>Delete the memory for <strong>{name}</strong>?</span>
          <button className="btn danger" onClick={remove} disabled={busy}>{busy ? "Deleting…" : "Delete memory"}</button>
          <button className="btn secondary" onClick={() => setConfirming(false)} disabled={busy}>Keep it</button>
        </div>
      ) : (
        <div><button className="btn secondary" onClick={() => setConfirming(true)}>Delete memory…</button></div>
      )}
    </section>
  );
}

function SettingsPage() {
  const { repo, loading, error, refresh } = useRepo();
  const [command, setCommand] = useState("");
  const [detected, setDetected] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  useEffect(() => {
    if (!repo || DEMO) return;
    api.settings(repo.repo_id).then((s) => { setCommand(s.test_command ?? ""); setDetected(s.detected_test_command); }).catch(setFailure);
  }, [repo]);

  if (loading) return <Loading lines={3} />;
  if (error) return <ErrorNotice error={error} />;
  if (!repo) return <NeedsRepo />;
  if (DEMO) return <Empty title="Settings are local">Run RepoPilot on your machine to configure test commands for your repositories.</Empty>;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(false);
    try {
      const s = await api.saveSettings(repo.repo_id, { test_command: command.trim() || null });
      setDetected(s.detected_test_command);
      setSaved(true);
    } catch (err) {
      setFailure(err);
    }
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
    <form className="panel panel-pad stack" onSubmit={save} style={{ maxWidth: 680 }}>
      <div>
        <h2 className="section-title" style={{ marginBottom: 4 }}>Checks for {repo.name}</h2>
        <p className="hint">Reviews, verified edits and the night shift run this command in a temporary copy of the repository. Leave it empty to detect it.</p>
      </div>
      <label>
        <span className="label">Test command</span>
        <input className="input mono" value={command} onChange={(e) => { setCommand(e.target.value); setSaved(false); }} placeholder={detected ?? "pytest -q"} />
      </label>
      <p className="hint">Currently used: <code>{detected ?? "none — checks will be skipped"}</code></p>
      {failure !== null && <ErrorNotice error={failure} />}
      <div className="row"><button className="btn">Save settings</button>{saved && <span className="hint" role="status">Saved.</span>}</div>
    </form>
    <DeleteMemory repoId={repo.repo_id} name={repo.name} onDeleted={refresh} />
    </div>
  );
}

export default function Page() {
  return <AppShell title="Settings"><SettingsPage /></AppShell>;
}
