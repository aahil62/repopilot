<p align="center"><img src="vscode-extension/media/icon.png" width="72" alt="RepoPilot"></p>

<h1 align="center">RepoPilot</h1>

<p align="center"><strong>Private, history-aware code review on open models you run yourself.</strong><br>
Sets aside mechanical edits, points you at the lines that change behavior, and explains why they matter using your repository's own history.</p>

![RepoPilot reviewing a Flask commit: 13 formatting hunks set aside, one behavior change highlighted](docs/screenshots/landing.png)

## The problem

AI coding tools made code cheap to write and slow to review. A 2026 Harvard working paper covering 725,938 workers at 718 companies found that adopting AI coding agents raised code written per person by 30% — and the time to review a pull request by 49%, with no significant rise in finished work ([Ars Technica](https://arstechnica.com/ai/2026/10/ai-coding-agents-generate-more-code-but-not-more-software/)). The bottleneck moved from writing code to trusting it.

Meanwhile many teams can't send source code to a cloud AI provider at all. RepoPilot runs entirely on your machine — and because it is allowed to read everything, it reads your git history too.

## What it does

| | |
|---|---|
| **Review with memory** | Every change — yours, a teammate's or another AI's — is split into *mechanical* hunks (whitespace, comments, docs, import order, true renames, identical syntax trees) and *behavior* hunks. Behavior is checked against your tests in a throwaway `git worktree`, against past bug fixes and review comments, and by a local model whose findings are discarded if they cite lines outside the change. |
| **Blast radius from history** | For any file: what usually changes with it (co-change mined from commits), what imports it, the bug fixes it has needed, which tests cover it, and who knows it best. Risk is scored relative to *your* repository, not fixed thresholds. |
| **Night shift** | Overnight, reviews each new commit, writes tests for new code — keeping only tests that pass, on a separate branch — and lists docs that mention removed code. Free to run nightly because the models are local. |
| **Which model should we run?** | Replays real past commits from your repository against every installed model and scores whether each change applies, passes your tests and matches what your team wrote, on your hardware. |
| **Verified edits & grounded Q&A** | Edits are applied and tested in a temporary worktree, retried with the failure output, and only shown once they pass. Answers cite exact line ranges; uncited claims are removed; "I couldn't find this in the repository" when the code doesn't say. |

<table><tr>
<td><img src="docs/screenshots/review.png" alt="Review page"></td>
<td><img src="docs/screenshots/blast.png" alt="Blast radius page"></td>
</tr></table>

## Private by design

- Model calls go only to the runtime **on your machine** — [Ollama](https://ollama.com), LM Studio or a llama.cpp server. No API keys.
- No accounts, analytics or telemetry. Embeddings are stored in a local SQLite file per repository.
- The only optional outbound call is importing public PR review comments from `api.github.com`, off unless `REPOPILOT_ALLOW_GITHUB_IMPORT=1`.
- Without any model runtime, indexing, blast radius, mechanical/behavior review and test checks still work.

Details: [docs/PRIVACY.md](docs/PRIVACY.md).

## Quick start

Requires Python 3.12+ and git. For the model-powered features, a local runtime.

```bash
pipx install "https://github.com/aahil62/repopilot/releases/download/v2.0.0/repopilot-2.0.0-py3-none-any.whl"
ollama pull qwen2.5-coder:7b && ollama pull qwen2.5-coder:1.5b && ollama pull nomic-embed-text
repopilot serve                     # web app at http://127.0.0.1:7341
```

From a terminal inside any git repository:

```bash
repopilot review                    # review uncommitted changes
repopilot blast src/app/payments.py # blast radius of a file
repopilot ask "Why do we retry the payment call?"
repopilot bench                     # which installed model works best on this repo
repopilot nightshift install        # schedule the night shift (prints the command to activate it)
```

RepoPilot picks models that fit your memory; change them with `repopilot models` or the Models page.

## VS Code

Install `repopilot-2.0.0.vsix` from the [releases page](https://github.com/aahil62/repopilot/releases) (*Extensions → … → Install from VSIX*). Commands: **Review Working Changes** (findings in the Problems panel), **Show Blast Radius** (also a CodeLens on every file), **Ask**, **Edit with Verification**, **Pick Models**. See [vscode-extension/README.md](vscode-extension/README.md). `npm run test:e2e` launches VS Code with the extension against a real repository and checks that a review lands in the Problems panel.

## Measured

Run on an Apple M4 laptop (16 GB) with `qwen2.5-coder:7b`, `qwen2.5-coder:1.5b` and `nomic-embed-text` through Ollama, on pinned versions of [pallets/flask](https://github.com/pallets/flask) (`3.1.0`) and [psf/requests](https://github.com/psf/requests) (`v2.32.3`). Scripts: [`eval/run_eval.py`](eval/run_eval.py), [`eval/seeded_bugs.py`](eval/seeded_bugs.py). Datasets are in [`eval/datasets/`](eval/datasets); results in [`eval/results/`](eval/results).

**Review — does it catch bugs without crying wolf?** 20 one-line bugs planted in Flask's library code (flipped comparisons, dropped `not`, inverted `is None`, swapped `and`/`or`), and 20 real merged Flask bug fixes that are presumed correct. Tests not run, so this is the model alone.

| | Result |
|---|---|
| Planted bugs flagged on the changed line (medium or high) | **70%** (14 of 20) |
| Correct merged fixes given a medium finding | 30% (6 of 20) |
| Correct merged fixes given a **high** finding | **0%** (0 of 20) |
| Model findings citing real changed lines | 100% (4 of 4 on Flask fix commits; others are discarded) |

High findings need a failing test or a matching past fix or review behind them, which is why `--fail-on high` is the CI gate. Medium findings are worth a look, and wrong about 30% of the time on correct code.

**Mechanical vs behavior** (no model):

| | Result |
|---|---|
| Python, **held-out** set labelled blind | **100% precision, 75% recall** (30 hunks): it never hid a behavior change |
| Python, set the rules were tuned on | 100% precision, 91% recall (60 hunks) |
| JavaScript/TypeScript (axios, zustand), not tuned on | **100% precision, 72% recall** (41 hunks) |
| Hunks set aside as mechanical | 61% of 252 hunks in Flask's last 40 commits; 24% of 128 in Requests' |

**Search and Ask:**

| | Flask | Requests |
|---|---|---|
| Right file in the top 5: keyword / vector / hybrid | 88% / 80% / **88%** | 88% / 92% / **96%** |
| "Not in this repository" decided correctly (25 answerable + 5 unanswerable) | **100%** | 93% |

**Scale** — [django/django](https://github.com/django/django) (529k lines of Python, 35k commits): 17,513 chunks and the newest 5,000 commits indexed in 30 minutes, almost all of it embedding time (52 s of CPU); 235 MB peak memory, 134 MB on disk. Afterwards blast radius takes 2.3 s and a 7B review of a 6-hunk commit about 2 minutes.

**Which model?** On six replayed Flask commits, `qwen2.5-coder:7b` scored 0.40 (median 93 s per task) and `1.5b` 0.18 (13 s). The benchmark recommends the 7B: on this laptop it is slow, but the faster model is much worse. Flask's own tests were not installed in the runner, so this score covers whether the edit applies and how close it is to the real commit, not whether tests pass.

## How it works

```mermaid
flowchart LR
  subgraph Repo[Your repository]
    code[Code] ; git[(Git history)]
  end
  subgraph Memory[Repository memory · SQLite]
    chunks[Symbol-aware chunks + FTS + vectors]
    graph[Import graph]
    hist[Commits, co-change, fix detection, PR links]
    prec[Past fixes & review comments]
  end
  subgraph Engines
    review[Review] ; blast[Blast radius] ; night[Night shift] ; bench[Model bench] ; edit[Verified edits] ; ask[Ask]
  end
  runtime[Local model runtime<br/>Ollama · LM Studio · llama.cpp]
  wt[Temporary git worktrees<br/>tests run here]
  code --> chunks & graph
  git --> hist --> prec
  Memory --> Engines
  Engines <--> runtime
  review & edit & night & bench --> wt
  Engines --> web[Web app] & vsc[VS Code] & cli[CLI]
```

Design notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
../scripts/check_backend.sh         # ruff + 78 tests (no model or network needed)
cd ../web && npm ci && npm test && npm run dev    # UI on :7342 against the API on :7341
python scripts/bundle_web.py        # build the UI into the wheel
python scripts/build_demo.py        # regenerate the public demo data from a real run on Flask
```

## Limits

- Small local models miss subtle bugs; review quality depends on the model you run. On correct code, about 30% of commits still get a medium finding (high findings need evidence and were 0%). RepoPilot narrows what you read and checks what it can — it does not replace a human reviewer.
- A finding's line can be off within the changed hunk (the line check only proves it is inside the change).
- On a 16 GB laptop the 7B model takes 1–2 minutes per review and about 30 minutes to embed a repository the size of Django; the 1.5B model is fast but too weak for edits.
- Co-change and fix detection are heuristics over commit history; repositories with squashed or very large commits give weaker signals.
- Tests run with your project's own environment; if dependencies aren't installed, checks will fail for reasons unrelated to the change.
- Import resolution covers Python and JavaScript/TypeScript.

## Credits

RepoPilot began at the AlphaByte 3.0 hackathon as a team project ([CREDITS.md](CREDITS.md)). Version 2 — the local runtime layer, repository memory, history-aware review, blast radius, night shift, model benchmark, verified edits, web app and extension — is a solo rebuild by Aahil Sayed.

MIT licensed.
