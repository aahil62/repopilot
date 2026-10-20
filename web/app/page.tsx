"use client";

import { ArrowUpRight, GithubLogo } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Brand } from "@/components/Brand";
import { DiffHunk } from "@/components/DiffView";
import { Orbit } from "@/components/Orbit";
import type { BenchResult, BlastReport, FileView, NightReport } from "@/lib/types";
import "./landing.css";

interface Hero { repo: string; commit: string; subject: string; files: FileView[]; mechanical: number; behavior: number; blast: BlastReport | null }
interface EvalRow { name: string; value: string; detail: string }
interface EvalData { generated_at: string; rows: EvalRow[]; models: string[] }

function useDemo<T>(name: string): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    fetch(`/demo/${name}.json`).then((r) => (r.ok ? r.json() : null)).then(setData).catch(() => setData(null));
  }, [name]);
  return data;
}

function Specimen({ hero }: { hero: Hero }) {
  const behaviorFile = hero.files.find((f) => f.behavior_hunks > 0) ?? hero.files[0];
  const hunk = behaviorFile.hunks.find((h) => h.label === "behavior") ?? behaviorFile.hunks[0];
  const others = hero.files.filter((f) => f !== behaviorFile);
  const coupled = hero.blast?.risk_reasons.find((r) => r.includes("usually changes together"));
  const reasons = [...new Set(hero.files.flatMap((f) => f.hunks.filter((h) => h.label === "mechanical").map((h) => h.reason.split(" (")[0])))];
  return (
    <figure className="specimen" aria-label={`RepoPilot reviewing ${hero.repo} commit ${hero.commit.slice(0, 8)}`}>
      <header className="specimen-head">
        <span className="mono">{hero.repo} at {hero.commit.slice(0, 8)}</span>
        <span className="specimen-subject">{hero.subject}</span>
      </header>
      <div className="specimen-file mono">{behaviorFile.path}</div>
      <DiffHunk hunk={hunk} />
      <div className="specimen-collapsed">
        {hero.mechanical} mechanical hunk{hero.mechanical === 1 ? "" : "s"} set aside
        {others.length > 0 && <> across {others.map((f) => f.path.split("/").pop()).slice(0, 3).join(", ")}</>}
        {reasons.length > 0 && <span>: {reasons.join(", ")}</span>}
      </div>
      {coupled && <figcaption className="specimen-note">{coupled.replace(/`/g, "")}</figcaption>}
    </figure>
  );
}

export default function Landing() {
  const hero = useDemo<Hero>("hero");
  const blast = useDemo<Record<string, BlastReport>>("blast");
  const night = useDemo<NightReport>("nightshift");
  const bench = useDemo<BenchResult>("bench");
  const evals = useDemo<EvalData>("eval");
  const orbitReport = blast ? Object.values(blast).sort((a, b) => b.dependents.length + b.cochanged.length - (a.dependents.length + a.cochanged.length))[0] : null;

  return (
    <div className="landing">
      <header className="l-nav">
        <Link href="/" aria-label="RepoPilot home"><Brand /></Link>
        <nav aria-label="Sections">
          <a href="#how">How it works</a>
          <a href="#private">Privacy</a>
          {evals && <a href="#measured">Results</a>}
          <a href="#install">Install</a>
        </nav>
        <a className="l-gh" href="https://github.com/aahil62/repopilot" target="_blank" rel="noreferrer"><GithubLogo size={18} /> Source</a>
      </header>

      <section className="l-hero">
        <div className="l-hero-copy">
          <h1>Read the lines that matter.</h1>
          <p className="l-lede">
            AI made code cheap to write and slow to review. RepoPilot reads your repository’s history on open models you run yourself,
            sets aside the mechanical edits and points you at the lines that change behavior — with the past bug fixes and
            reviews that explain why they matter.
          </p>
          <div className="row">
            <Link className="btn" href="/app/review/">See it review Flask</Link>
            <a className="btn secondary" href="#install">Run it locally</a>
          </div>
          <p className="l-fine">Open source. Works with Ollama, LM Studio or llama.cpp. No API keys, no telemetry.</p>
        </div>
        <div className="l-hero-art">{hero ? <Specimen hero={hero} /> : <div className="specimen specimen-empty" aria-hidden="true" />}</div>
      </section>

      <section className="l-problem">
        <p>
          In a study of 725,938 workers at 718 companies, adopting AI coding agents raised code written per person by 30% — and the
          time to review a pull request by 49%, with no significant rise in finished work.{" "}
          <a href="https://arstechnica.com/ai/2026/10/ai-coding-agents-generate-more-code-but-not-more-software/" target="_blank" rel="noreferrer">
            Ars Technica on the Harvard working paper<ArrowUpRight size={12} /></a>
        </p>
        <p className="hint">The bottleneck moved from writing code to trusting it. RepoPilot is built for that half of the job.</p>
      </section>

      <section className="l-features" id="how">
        <article className="l-feature">
          <div>
            <h2>Review with memory</h2>
            <p>Every change — yours, a teammate’s or another AI’s — is split into mechanical edits and behavior changes. Behavior is checked
              against your tests in a throwaway copy, and against past bug fixes and review comments from your own history. Findings
              that cite lines outside the change are discarded before you see them.</p>
          </div>
          <dl className="l-facts">
            <dt>Mechanical edits recognised</dt><dd>whitespace, comments, import order, true renames, identical syntax trees</dd>
            <dt>Checks run</dt><dd>your test and type-check commands, in a temporary git worktree</dd>
          </dl>
        </article>

        <article className="l-feature l-feature-orbit">
          <div>
            <h2>Blast radius from history</h2>
            <p>Before you touch a file, see what usually changes with it, what imports it, the bug fixes it has needed, and who knows it best —
              learned from commits, not guessed.</p>
            <Link className="btn secondary small" href="/app/blast/">Explore Flask’s blast radius</Link>
          </div>
          {orbitReport && <Orbit report={orbitReport} animate />}
        </article>

        <article className="l-feature">
          <div>
            <h2>A night shift that costs nothing</h2>
            <p>Cloud tools bill per token, so nobody lets them read every commit. Local models don’t. Overnight, RepoPilot reviews each new
              commit, writes tests for new code — keeping only tests that pass, on a separate branch — and lists docs that mention code that no
              longer exists.</p>
          </div>
          {night && (
            <div className="l-morning">
              <p className="l-morning-title">Good morning.</p>
              <p>Overnight it read {night.commits_reviewed.length} commits, flagged {night.commits_reviewed.reduce((n, c) => n + c.findings.length, 0)},
                wrote {night.tests_written.filter((t) => t.status === "verified").length} passing tests and found {night.stale_docs.length} stale doc references.</p>
              <Link href="/app/nightshift/">Read the report</Link>
            </div>
          )}
        </article>

        <article className="l-feature">
          <div>
            <h2>Which model should we run?</h2>
            <p>RepoPilot replays real past commits from your repository against every model you have installed, and scores whether each one’s
              change applies, passes your tests and matches what your team actually wrote — on your hardware.</p>
          </div>
          {bench && bench.models.length > 0 && (
            <div className="l-bench">
              {bench.models.slice(0, 4).map((m) => (
                <div key={m.model} className="l-bench-row">
                  <span className="mono">{m.model}</span>
                  <span className="bar"><span style={{ width: `${m.score * 100}%` }} /></span>
                  <span className="mono">{m.score.toFixed(2)}</span>
                </div>
              ))}
              <p className="hint">{bench.recommendation}</p>
            </div>
          )}
        </article>

        <article className="l-feature">
          <div>
            <h2>Edits it has already tested</h2>
            <p>Ask for a change and RepoPilot writes it in a temporary worktree, runs your checks, feeds failures back to the model and tries
              again. You only see a diff that passed — and your working tree is untouched until you apply it.</p>
          </div>
          <dl className="l-facts">
            <dt>Attempts</dt><dd>up to three, each with the previous failure as feedback</dd>
            <dt>Answers to questions</dt><dd>cite exact line ranges; uncited claims are removed; “I couldn’t find this” when the code doesn’t say</dd>
          </dl>
        </article>
      </section>

      <section className="l-private" id="private">
        <h2>Your code stays on your machine</h2>
        <p>Teams that can’t send source code to a cloud provider can still use RepoPilot — and because it is allowed to read everything, it can
          read your history too.</p>
        <table className="table">
          <thead><tr><th>Destination</th><th>When</th></tr></thead>
          <tbody>
            <tr><td className="mono">127.0.0.1 — your model runtime</td><td>Every review, question and edit</td></tr>
            <tr><td className="mono">api.github.com</td><td>Only if you turn on review-history import</td></tr>
            <tr><td>Anything else</td><td>Never. No accounts, analytics or telemetry.</td></tr>
          </tbody>
        </table>
      </section>

      {evals && (
        <section className="l-measured" id="measured">
          <h2>Measured</h2>
          <p className="hint">From <code>eval/run_eval.py</code> on pinned open-source repositories with {evals.models.join(", ")}.</p>
          <table className="table">
            <tbody>{evals.rows.map((r) => <tr key={r.name}><td>{r.name}</td><td className="mono">{r.value}</td><td className="hint">{r.detail}</td></tr>)}</tbody>
          </table>
        </section>
      )}

      <section className="l-install" id="install">
        <div>
          <h2>Run it locally</h2>
          <p>Python 3.12 and a model runtime. RepoPilot picks models that fit your memory.</p>
        </div>
        <pre className="l-code">{`pipx install "git+https://github.com/aahil62/repopilot#subdirectory=backend"
ollama pull qwen2.5-coder:7b && ollama pull nomic-embed-text
repopilot serve            # http://127.0.0.1:7341
repopilot review           # or review from the terminal`}</pre>
        <p className="hint">In VS Code: install the RepoPilot extension, then run “RepoPilot: Review Working Changes”. Findings appear in the Problems panel.</p>
      </section>

      <footer className="l-foot">
        <Brand />
        <p>RepoPilot began at the AlphaByte 3.0 hackathon as a team project. Version 2 is a solo rebuild by Aahil Sayed. <Link href="https://github.com/aahil62/repopilot/blob/main/CREDITS.md">Credits</Link></p>
      </footer>
    </div>
  );
}
