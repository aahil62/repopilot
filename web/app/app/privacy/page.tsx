"use client";

import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { ErrorNotice, Loading } from "@/components/States";
import { api, DEMO } from "@/lib/api";
import "../app.css";

type Privacy = Awaited<ReturnType<typeof api.privacy>>;

function PrivacyPage() {
  const [info, setInfo] = useState<Privacy | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  useEffect(() => { if (!DEMO) api.privacy().then(setInfo).catch(setFailure); }, []);

  return (
    <div className="stack" style={{ gap: 20, maxWidth: 760 }}>
      <section className="panel panel-pad">
        <h2 className="section-title">What leaves this machine</h2>
        <p style={{ marginBottom: 12 }}>Nothing, unless you turn on review-history import. RepoPilot has no account, no analytics and no telemetry.</p>
        <table className="table"><thead><tr><th>Destination</th><th>When</th><th>What is sent</th></tr></thead><tbody>
          <tr><td className="mono">127.0.0.1 (your model runtime)</td><td>Every review, question or edit</td><td>Code excerpts and prompts — to a program on this computer</td></tr>
          <tr><td className="mono">api.github.com</td><td>Only if you enable review import</td><td>Requests for your repository’s public PR comments</td></tr>
          <tr><td className="mono">github.com</td><td>Only when you clone a repository by URL</td><td>A normal git clone</td></tr>
        </tbody></table>
      </section>
      <section className="panel panel-pad">
        <h2 className="section-title">Where data is stored</h2>
        {DEMO ? <p className="hint">Locally, in <code>~/.repopilot</code>: one SQLite file per repository with code chunks, vectors, history and reviews.</p>
          : failure !== null ? <ErrorNotice error={failure} /> : !info ? <Loading lines={2} /> : (
          <dl className="kv">
            <dt>Data folder</dt><dd className="mono">{info.data_dir}</dd>
            <dt>Model runtimes</dt><dd className="mono">{info.model_runtime_urls.join(", ")}</dd>
            <dt>Review import</dt><dd>{info.github_review_import ? "enabled" : "off"}</dd>
            <dt>Telemetry</dt><dd>{info.telemetry ? "on" : "none"}</dd>
          </dl>
        )}
      </section>
      <section className="panel panel-pad">
        <h2 className="section-title">Check it yourself</h2>
        <p className="hint" style={{ marginBottom: 8 }}>While RepoPilot is working, list its network connections:</p>
        <pre className="panel" style={{ padding: "10px 12px", margin: 0, overflowX: "auto" }}>lsof -i -P | grep -i python</pre>
        <p className="hint" style={{ marginTop: 8 }}>You should only see connections to 127.0.0.1.</p>
      </section>
    </div>
  );
}

export default function Page() {
  return <AppShell title="Privacy"><PrivacyPage /></AppShell>;
}
