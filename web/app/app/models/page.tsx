"use client";

import { Fragment, useEffect, useState } from "react";

import { AppShell, useRepo } from "@/components/AppShell";
import { ErrorNotice, Loading } from "@/components/States";
import { api, ApiError, DEMO, waitForJob } from "@/lib/api";
import type { BenchResult, ModelsResponse } from "@/lib/types";
import "../app.css";

const gb = (b: number | null) => (b ? `${(b / 1024 ** 3).toFixed(1)} GB` : "–");
const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
const ROLE_TEXT = { strong: "Review and code", fast: "Classification and routing", embed: "Search embeddings" } as const;

function ModelsPage() {
  const { repo, models: initial } = useRepo();
  const [models, setModels] = useState<ModelsResponse | null>(initial);
  const [bench, setBench] = useState<BenchResult | null>(null);
  const [benchError, setBenchError] = useState<unknown>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => { api.models().then(setModels).catch(setError); }, []);
  useEffect(() => {
    if (!repo) return;
    api.bench(repo.repo_id).then(setBench).catch((e) => { if (!(e instanceof ApiError && e.status === 404)) setBenchError(e); });
  }, [repo]);

  const setRole = async (role: "fast" | "strong" | "embed", id: string) => {
    try {
      await api.setRoles({ [role]: id });
      setModels(await api.models());
    } catch (e) {
      setError(e);
    }
  };

  const runBench = async () => {
    if (!repo) return;
    setRunning(true);
    setBenchError(null);
    try {
      const { job_id } = await api.startBench(repo.repo_id);
      setBench(await waitForJob<BenchResult>(job_id));
    } catch (e) {
      setBenchError(e);
    } finally {
      setRunning(false);
    }
  };

  if (error) return <ErrorNotice error={error} />;
  if (!models) return <Loading lines={5} />;
  const chat = models.models.filter((m) => !m.is_embedding);
  const embeds = models.models.filter((m) => m.is_embedding);

  return (
    <div className="stack" style={{ gap: 22 }}>
      <section className="panel panel-pad">
        <h2 className="section-title">Which model should we run?</h2>
        <p className="hint" style={{ maxWidth: "70ch", marginBottom: 14 }}>
          RepoPilot replays real past commits from {repo ? <strong>{repo.name}</strong> : "your repository"}: each model gets the commit message
          and the code as it was, writes the change, and is scored on whether it applies, passes your tests and matches what your team actually wrote.
        </p>
        {bench && <p className="recommend">{bench.recommendation}</p>}
        {!DEMO && repo && <button className="btn" onClick={runBench} disabled={running} style={{ marginTop: 12 }}>{running ? "Replaying commits…" : bench ? "Run again" : "Run the benchmark"}</button>}
        {benchError !== null && <div style={{ marginTop: 12 }}><ErrorNotice error={benchError} /></div>}
        {bench && (
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table className="table">
              <thead><tr><th>Model</th><th>Score</th><th>Applies</th><th>Tests pass</th><th>Matches your change</th><th>Median time</th><th>Tokens/s</th></tr></thead>
              <tbody>
                {bench.models.map((m) => (
                  <tr key={m.model}>
                    <td className="mono">{m.model}{m.model === bench.recommended_strong && <span className="chip behavior" style={{ marginLeft: 8 }}>pick</span>}</td>
                    <td><div className="row" style={{ gap: 8, flexWrap: "nowrap" }}><div className="bar" style={{ width: 90 }}><span style={{ width: `${m.score * 100}%` }} /></div>{m.score.toFixed(2)}</div></td>
                    <td>{pct(m.applies_rate)}</td><td>{pct(m.tests_pass_rate)}</td><td>{m.similarity.toFixed(2)}</td>
                    <td>{m.median_latency_s.toFixed(0)}s</td><td>{m.tokens_per_second?.toFixed(0) ?? "–"}</td>
                  </tr>
                ))}
                {bench.skipped.map((s) => <tr key={s.model}><td className="mono hint">{s.model}</td><td colSpan={6} className="hint">skipped: {s.reason}</td></tr>)}
              </tbody>
            </table>
            <p className="hint" style={{ marginTop: 8 }}>{bench.tasks.length} past commits replayed · {new Date(bench.created_at).toLocaleString()}</p>
          </div>
        )}
      </section>

      <div className="grid-2">
        <section className="panel panel-pad">
          <h2 className="section-title">Roles</h2>
          <div className="stack" style={{ gap: 12 }}>
            {(["strong", "fast", "embed"] as const).map((role) => (
              <label key={role}>
                <span className="label">{ROLE_TEXT[role]}</span>
                <select className="select mono" value={models.roles[role] ?? ""} disabled={DEMO}
                  onChange={(e) => setRole(role, e.target.value)}>
                  {(role === "embed" ? [...embeds, ...chat] : chat).map((m) => <option key={m.id} value={m.id}>{m.id}</option>)}
                </select>
              </label>
            ))}
          </div>
        </section>
        <section className="panel panel-pad">
          <h2 className="section-title">This machine</h2>
          <dl className="kv">
            <dt>Memory</dt><dd>{gb(models.hardware.total_ram_bytes)}{models.hardware.unified_memory && " unified"}</dd>
            <dt>GPU</dt><dd>{models.hardware.gpu ?? "none detected"}</dd>
            <dt>Model budget</dt><dd>{gb(models.hardware.model_budget_bytes)}</dd>
            {models.runtimes.map((r) => (
              <Fragment key={r.base_url}>
                <dt>{r.kind === "ollama" ? "Ollama" : "OpenAI-compatible"}</dt>
                <dd className="mono" style={{ fontSize: 12 }}>{r.base_url} · {r.reachable ? "running" : "not running"}</dd>
              </Fragment>
            ))}
          </dl>
        </section>
      </div>

      <section className="panel panel-pad">
        <h2 className="section-title">Installed models</h2>
        {models.models.length === 0 ? <p className="hint">No models found. Try <code>ollama pull qwen2.5-coder:7b</code>.</p> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Model</th><th>Size</th><th>Context</th><th>Fits this machine</th></tr></thead>
            <tbody>{models.models.map((m) => (
              <tr key={m.id}><td className="mono">{m.id}{m.is_embedding && <span className="hint"> · embeddings</span>}</td><td>{gb(m.size_bytes)}</td>
                <td>{m.context_length?.toLocaleString() ?? "–"}</td><td>{m.fits ? "yes" : <span className="hint">no — needs more memory</span>}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}

export default function Page() {
  return <AppShell title="Models"><ModelsPage /></AppShell>;
}
