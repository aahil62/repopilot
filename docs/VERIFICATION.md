# Verification — v2 (2026-10-20)

What was actually run on this machine (Apple M4, 16 GB, macOS) and what was not. Models: `qwen2.5-coder:7b` (strong), `qwen2.5-coder:1.5b` (fast) and `nomic-embed-text` (embeddings) through Ollama.

## Automated

| Check | Command | Result |
|---|---|---|
| Backend lint + tests | `scripts/check_backend.sh` | ruff clean; **78 passed** (no model or network: `FakeRuntime`, temporary git repos) |
| Web tests | `npm --prefix web test` | **12 passed** (components and every app page with a mocked API) |
| Web lint / types | `npm --prefix web run lint`, `npx tsc --noEmit` | clean |
| Web production build | `NEXT_PUBLIC_DEMO_MODE=1 npm --prefix web run build` | 10 static routes |
| Extension | `npm --prefix vscode-extension run typecheck`, `vsce package` | builds; `repopilot-2.0.0.vsix` 137 KB (includes the three bundled fonts) |
| Extension end to end | `REPOPILOT_TEST_REPO=… npm --prefix vscode-extension run test:e2e` | **passed**: in a real VS Code, *Review Working Changes* on a planted sign flip put an Error on the file in the Problems panel, and the blast-radius CodeLens appeared |

Tests run real `git` commands, real `pytest` subprocesses inside temporary worktrees, and the FastAPI app through `TestClient`.

## With real models

| What | Result | Source |
|---|---|---|
| Planted bugs caught (20 one-line mutations in Flask, model only) | 70% medium/high on the changed line | `eval/results/seeded-bugs.md` |
| Correct merged Flask fixes flagged | 30% medium, **0% high** (20 commits) | same |
| Hybrid retrieval, right file in top 5 | Flask 88%, Requests 96% | `eval/results/*-latest.md` |
| Refusal decided correctly | Flask 100%, Requests 93% (30 questions each) | same |
| Findings citing real changed lines | 100% (Flask 4 of 4, Requests 1 of 1) | same |
| Benchmark, 6 recent Flask commits | 7B 0.27 (median 154 s), 1.5B 0.25 (27 s); 3 of 6 edits applied each; recommends 7B with a warning that no model edits Flask reliably | `web/public/demo/bench.json` |
| Verified edit ("reject rates outside 0–1") | verified on the first attempt in 19 s | manual run |
| Ask with citations | answers cite line ranges; "Kafka" question refused | manual run |
| Night shift | demo repo: 4 passing tests for new code; Flask 3.1.0: reviewed 5 commits and wrote tests for `SessionMixin` that pass Flask's full 489-test suite (3rd attempt, 8 min); both on `repopilot/nightshift-<date>`, current branch untouched | manual run, `web/public/demo/nightshift.json` |
| Django scale test | 17,513 chunks, 5,000 commits in 30 min; 235 MB peak; blast 2.3 s; review ~2 min | `/usr/bin/time -l repopilot index` |
| JS/TS mechanical label vs hand labels | 100% precision, 72% recall (41 hunks, axios + zustand) | `eval/datasets/mechanical_hunks_js.jsonl` |

### Problems found on real models and fixed

Each came from a run above, got a regression test, and is in the git log:

- A correct merged Flask fix (`4995a775`) drew three HIGH findings. Reviews now get the commit message as intent, every finding must name a failing input, a second pass must confirm it, and unsupported findings are capped at medium.
- The second pass then dropped *every* finding (planted bugs caught: 5%), because the 7B model left the optional `failing_input` empty. It is now required in the schema the runtime enforces, and the verdict schema puts its reasoning before the decision. Caught: 70%.
- In the VS Code test, the project's tests failed on the planted bug but the second pass still rejected the finding; it now sees the failing test output.
- Ask answered without citations on 7B; the rule is repeated at the end of the prompt, and an uncited answer is labelled unverified.
- Verified edits always failed on 7B (it sends whole files); a short file the model saw in full may now be rewritten whole, and tests still decide.
- Night shift rejected correct tests because the suite was already red; it now checks first and says so.
- Ollama aborting a looping generation ("token repeat limit reached") crashed the benchmark and the demo build; it is now retried as a bad answer.
- The benchmark replayed 2010-era commits whose tests no longer run, gave one attempt where the product gives a retry, and recommended the 1.5B model at less than half the 7B's score. All fixed; when no model is good enough it now says so.
- Night shift had the 7B rewrite whole Flask test files (6-8 minutes per call); new tests now go in a file of their own when the usual one is long.
- Earlier: vectors from a different embedding model were kept (now rebuilt), the refusal threshold was miscalibrated on real embeddings, and the 1.5B model produced truncated JSON (schema length limits).

## Earlier manual checks (2026-10-18)

- **Clean install:** fresh Python 3.12 venv, `pip install` of the wheel, `repopilot serve` served the UI and demo data; with no runtime, model endpoints return 503 with setup instructions.
- **Calibration on real data:** fixed-threshold risk rated every Flask core file "high" (replaced with a repo-relative score); tooling chores counted as bug fixes (excluded); owners split across git name variants (`.mailmap` honoured).
- **Browser:** landing and app pages at 1440 px light and dark, and 375 px, with no horizontal overflow.
- **Classifier vs human labels (Python):** the first 60 hand-labelled hunks found three rule gaps, fixed with a per-hunk syntax-tree comparison (100% / 91% on that set); a fresh held-out set of 30 hunks labelled blind: 100% precision, 75% recall.

## Not verified

- Linux and Windows; NVIDIA hardware detection.
- The GitHub review-comment import against the live API (tested with a mocked transport).
- The benchmark's test-pass rate on Flask: with today's dependencies, Flask's tests ran at only 1 of the 6 replayed commits.
- Larger models (14B and up): the laptop's 16 GB can't hold them alongside the embedding model.
