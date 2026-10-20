"use client";

import { ArrowRight, ArrowUpRight, GithubLogo } from "@phosphor-icons/react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Brand } from "@/components/Brand";
import { HeroWindow } from "@/components/HeroWindow";
import { Orbit } from "@/components/Orbit";
import { Terrain } from "@/components/Terrain";
import { peaksFromBlast } from "@/lib/terrain";
import type { BenchResult, BlastReport, HeroDemo, NightReport } from "@/lib/types";
import "./landing.css";

interface EvalRow { name: string; value: string; detail: string }
interface EvalData { generated_at: string; rows: EvalRow[]; models: string[] }

function useDemo<T>(name: string): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    fetch(`/demo/${name}.json`).then((r) => (r.ok ? r.json() : null)).then(setData).catch(() => setData(null));
  }, [name]);
  return data;
}

export default function Landing() {
  const hero = useDemo<HeroDemo>("hero");
  const blast = useDemo<Record<string, BlastReport>>("blast");
  const night = useDemo<NightReport>("nightshift");
  const bench = useDemo<BenchResult>("bench");
  const evals = useDemo<EvalData>("eval");
  const peaks = useMemo(() => (blast ? peaksFromBlast(blast) : []), [blast]);
  const orbitReport = blast ? Object.values(blast).sort((a, b) => b.dependents.length + b.cochanged.length - (a.dependents.length + a.cochanged.length))[0] : null;

  return (
    <div className="landing">
      <div className="l-top">
        <Terrain peaks={peaks} />
        <div className="l-top-fade" aria-hidden="true" />
        <header className="l-nav">
          <Link href="/" aria-label="RepoPilot home"><Brand /></Link>
          <nav aria-label="Sections" className="l-menu">
            <a href="#how">Product</a>
            {evals && <a href="#measured">Benchmark</a>}
            <a href="#private">Privacy</a>
            <a href="https://github.com/aahil62/repopilot#readme" target="_blank" rel="noreferrer">Docs</a>
          </nav>
          <div className="l-nav-end">
            <span className="l-version mono">v2.1.0</span>
            <a className="l-gh" href="https://github.com/aahil62/repopilot" target="_blank" rel="noreferrer"><GithubLogo size={16} /> GitHub</a>
          </div>
        </header>

        <section className="l-hero">
          <p className="l-eyebrow">Open source · runs on your machine · no API keys</p>
          <h1>Code review<em>with a memory.</em></h1>
          <p className="l-lede">Every diff is checked against your repository&apos;s history: past bug fixes, files that change together, the tests that cover it. Runs on your machine, on open models, with no API keys.</p>
          <div className="l-ctas">
            <Link className="btn" href="/app/review/">See it review Flask</Link>
            <a className="l-textlink" href="#install">Install locally <ArrowRight size={14} /></a>
          </div>
          <HeroWindow hero={hero} blast={blast} />
        </section>
      </div>

      <section className="l-steps" aria-labelledby="steps-title">
        <p className="l-kicker">How it works</p>
        <h2 id="steps-title">From a noisy diff to <em>a clear decision</em> in three steps.</h2>
        <div className="l-step-grid">
          <article className="l-step"><p className="l-step-no">01 · Remember</p><h3>Index the history</h3><p>Code, imports and every commit go into a local SQLite memory: what changes together, the bug fixes, who owns what.</p><code>repopilot index</code></article>
          <article className="l-step"><p className="l-step-no">02 · Triage</p><h3>Set aside the noise</h3><p>Syntax trees separate formatting from behavior, so you read only the changes that can break something.</p><code>{hero ? `${hero.mechanical} of ${hero.mechanical + hero.behavior} hunks set aside` : "repopilot review"}</code></article>
          <article className="l-step"><p className="l-step-no">03 · Decide</p><h3>Review with evidence</h3><p>Tests run in a throwaway worktree; past fixes and a local model weigh in. High findings need proof.</p><code>--fail-on high</code></article>
        </div>
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
        <pre className="l-code">{`pipx install "https://github.com/aahil62/repopilot/releases/download/v2.1.0/repopilot-2.1.0-py3-none-any.whl"
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
