# Verification — v2 (2026-10-18)

What was actually run on this machine (Apple M4, 16 GB, macOS), and what was not.

## Automated

| Check | Command | Result |
|---|---|---|
| Backend lint + tests | `scripts/check_backend.sh` | ruff clean; **66 passed** (no model or network: `FakeRuntime`, temporary git repos) |
| Web tests | `npm --prefix web test` | **5 passed** |
| Web lint / types | `npm --prefix web run lint`, `npx tsc --noEmit` | clean |
| Web production build | `NEXT_PUBLIC_DEMO_MODE=1 npm --prefix web run build` | 10 static routes |
| Extension | `npm --prefix vscode-extension run typecheck && npm run package`, `vsce package` | builds; `repopilot-2.0.0.vsix` 27 KB |

Tests run real `git` commands, real `pytest` subprocesses inside temporary worktrees, and the FastAPI app through `TestClient` (indexing, SSE ask, review jobs, blast radius, no-runtime fallback, static UI serving).

## Manual

- **Clean install:** fresh Python 3.12 venv, `pip install dist/repopilot-2.0.0-py3-none-any.whl`, `repopilot serve` → `/`, `/app/review/` and `/demo/hero.json` served (200); `POST /api/repos` registered a repository; with no runtime, model endpoints return 503 with setup instructions.
- **No-model CLI:** `repopilot blast backend/repopilot/engines/review.py --repo .` on this repository → risk, co-change table and the one bug-fix commit that touched the file.
- **Real repository:** `scripts/build_demo.py --offline` on `pallets/flask@3.1.0` — 224 files, 972 chunks, 3,718 commits indexed in ~17 s. The hero commit (`53c893b6`, "fix string concats left over by black") was classified 13 mechanical / 1 behavior; the behavior hunk changes an assertion message string, so the classification is correct.
- **Calibration found on real data and fixed:** fixed-threshold risk rated every Flask core file "high" (replaced with a repo-relative points score); tooling chores counted as bug fixes (excluded); duplicate React keys in the orbit; owners split across git name variants (`.mailmap` now honoured).
- **Browser:** landing, Overview, Review, Blast radius, Night shift (empty state) at 1440 px light and dark, and 375 px — no horizontal overflow; dev console free of errors after fixes.
- **Offline evaluation** (`eval/run_eval.py --offline`): keyword Recall@5 = 88% on 25 Flask questions; 54% of 252 hunks in the last 40 commits set aside as mechanical.

## Not verified yet

- **Anything that needs a language model** — no local runtime was installed. Not yet exercised against a real model: review findings, Ask answers, verified edits, night-shift test writing, the benchmark, vector/hybrid retrieval and refusal accuracy. The public demo's Ask, Night shift and Models pages have no data until `scripts/build_demo.py` is run with models.
- The VS Code extension inside a running VS Code (Extension Development Host).
- Linux and Windows; NVIDIA hardware detection.
- The GitHub review-comment import against the live API (tested with a mocked transport).
- Any deployment.
