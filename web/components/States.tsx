"use client";

import Link from "next/link";

import { ApiError } from "@/lib/api";

export function Loading({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} style={{ display: "grid", gap: 10 }}>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton" style={{ height: 18, width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function Empty({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="panel panel-pad" style={{ maxWidth: 620 }}>
      <h2 style={{ fontSize: "var(--t-lg)", marginBottom: 6 }}>{title}</h2>
      {children && <div className="hint" style={{ marginBottom: action ? 14 : 0 }}>{children}</div>}
      {action}
    </div>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 503) {
    const setup = ((error.body as { setup?: string[] })?.setup) ?? ["ollama pull qwen2.5-coder:7b", "ollama pull nomic-embed-text"];
    return (
      <div className="panel panel-pad" style={{ maxWidth: 640 }} role="alert">
        <h2 style={{ fontSize: "var(--t-lg)", marginBottom: 6 }}>No local model runtime found</h2>
        <p className="hint" style={{ marginBottom: 12 }}>
          RepoPilot runs on models on this machine. Install <a href="https://ollama.com" target="_blank" rel="noreferrer">Ollama</a> or
          LM Studio, then pull a coding model and an embedding model:
        </p>
        <pre className="panel" style={{ padding: "10px 12px", margin: 0, overflowX: "auto" }}>{setup.join("\n")}</pre>
      </div>
    );
  }
  if (error instanceof ApiError && error.status === 0) {
    return (
      <div className="panel panel-pad" style={{ maxWidth: 640 }} role="alert">
        <h2 style={{ fontSize: "var(--t-lg)", marginBottom: 6 }}>RepoPilot isn’t running</h2>
        <p className="hint">Start the local service in a terminal, then reload this page:</p>
        <pre className="panel" style={{ padding: "10px 12px", margin: "10px 0 0" }}>repopilot serve</pre>
      </div>
    );
  }
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return <div className="notice error" role="alert">{message}</div>;
}

export function NeedsRepo() {
  return (
    <Empty title="Add a repository first" action={<Link className="btn" href="/app/">Add a repository</Link>}>
      RepoPilot builds a private memory of a repository — its code, imports and git history — before it can review changes.
    </Empty>
  );
}
