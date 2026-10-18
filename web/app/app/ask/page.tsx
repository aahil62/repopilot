"use client";

import { Fragment, useState } from "react";

import { AppShell, useRepo } from "@/components/AppShell";
import { CodePanel } from "@/components/CodePanel";
import { ErrorNotice, Loading, NeedsRepo } from "@/components/States";
import { askStream, DEMO } from "@/lib/api";
import type { Citation, CommitRef } from "@/lib/types";
import "../app.css";

interface Turn { question: string; answer: string; citations: Citation[]; commits: CommitRef[]; refused: boolean; removed: number; done: boolean }

const DEMO_QUESTIONS = ["Where is the request context pushed?", "Why does Flask's teardown run even when an exception happened?"];

export function Answer({ text, citations, active, onCite }: { text: string; citations: Citation[]; active: number | null; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d{1,2}\])/g);
  const valid = new Set(citations.map((c) => c.n));
  return (
    <p className="answer">
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d{1,2})\]$/);
        if (m && valid.has(Number(m[1]))) {
          const n = Number(m[1]);
          return <button key={i} className="cite-chip" aria-pressed={active === n} onClick={() => onCite(n)} aria-label={`Show source ${n}`}>{n}</button>;
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </p>
  );
}

function AskPage() {
  const { repo, loading, error } = useRepo();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [open, setOpen] = useState<Citation | null>(null);

  if (loading) return <Loading lines={4} />;
  if (error) return <ErrorNotice error={error} />;
  if (!repo) return <NeedsRepo />;

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setBusy(true);
    setFailure(null);
    setQuestion("");
    const idx = turns.length;
    setTurns((t) => [...t, { question: q, answer: "", citations: [], commits: [], refused: false, removed: 0, done: false }]);
    const update = (fn: (t: Turn) => Turn) => setTurns((all) => all.map((t, i) => (i === idx ? fn(t) : t)));
    try {
      for await (const ev of askStream(repo.repo_id, q)) {
        if (ev.event === "token") update((t) => ({ ...t, answer: t.answer + ev.data }));
        if (ev.event === "citations") update((t) => ({ ...t, citations: ev.data }));
        if (ev.event === "done") update((t) => ({ ...t, refused: ev.data.refused, removed: ev.data.removed_citations, commits: ev.data.commits, done: true }));
      }
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`ask-layout${open ? " with-code" : ""}`}>
      <div className="stack">
        <p className="page-intro">Ask about this repository. Answers cite the exact lines they come from; “why” questions also read the git history. If the code doesn’t contain the answer, RepoPilot says so.</p>
        {turns.map((t, i) => (
          <article key={i} className="turn">
            <h2 className="turn-q">{t.question}</h2>
            {!t.answer && !t.done ? <Loading lines={2} label="Answering" /> : (
              <Answer text={t.answer} citations={t.citations} active={open && t.citations.includes(open) ? open.n : null}
                onCite={(n) => setOpen(t.citations.find((c) => c.n === n) ?? null)} />
            )}
            {t.removed > 0 && <p className="hint">{t.removed} citation{t.removed > 1 ? "s" : ""} pointed at nothing retrieved and {t.removed > 1 ? "were" : "was"} removed.</p>}
            {t.citations.length > 0 && (
              <ul className="sources">
                {t.citations.map((c) => (
                  <li key={c.n}><button className="link-btn mono" onClick={() => setOpen(c)}>[{c.n}] {c.path}:{c.start_line}–{c.end_line}</button></li>
                ))}
              </ul>
            )}
            {t.commits.length > 0 && (
              <ul className="sources">
                {t.commits.map((c) => <li key={c.sha} className="hint"><span className="mono">{c.sha.slice(0, 8)}</span> {c.date.slice(0, 10)} · {c.subject}</li>)}
              </ul>
            )}
          </article>
        ))}
        {failure !== null && <ErrorNotice error={failure} />}
        <form className="ask-form" onSubmit={(e) => { e.preventDefault(); void ask(question); }}>
          <label className="sr-only" htmlFor="q">Question</label>
          <input id="q" className="input" value={question} onChange={(e) => setQuestion(e.target.value)} disabled={busy || DEMO}
            placeholder={DEMO ? "The demo answers the questions below" : "Where is authentication handled?"} />
          <button className="btn" disabled={busy || DEMO || !question.trim()}>Ask</button>
        </form>
        {DEMO && turns.length === 0 && (
          <div className="row">{DEMO_QUESTIONS.map((q) => <button key={q} className="btn secondary small" onClick={() => ask(q)}>{q}</button>)}</div>
        )}
      </div>
      {open && (
        <div className="ask-code">
          <CodePanel repoId={repo.repo_id} path={open.path} start={open.start_line} end={open.end_line} onClose={() => setOpen(null)} />
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return <AppShell title="Ask"><AskPage /></AppShell>;
}
