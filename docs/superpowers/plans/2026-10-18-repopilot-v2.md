# RepoPilot v2: Private, History-Aware Code Review on Open Models — Implementation Plan

> **For agentic workers (Codex):** Implement task-by-task, in order. Each task ends with tests passing and a commit. Steps use checkbox (`- [ ]`) syntax. When a step names an exact value (threshold, path, label, copy), use it verbatim. Never add a cloud AI provider.

**Goal:** Rebuild RepoPilot into a fully local, open-model engineering teammate that makes code changes trustworthy: history-aware review, blast radius from history, a night shift that reviews every commit and writes verified tests, a "which model should we run?" benchmark on your own repository, and verified coding assistance — in a local web app and a VS Code extension.

**Architecture:** One local Python service (`repopilot` package: FastAPI + Typer CLI) owns a per-repository **memory** (code index, symbol/import graph, git history, review history) in SQLite + Chroma under `~/.repopilot/`. A **model runtime** layer talks only to local OpenAI-compatible/Ollama servers and makes open models reliable (context sizing, schema-validated outputs, retries). Feature engines (review, blast radius, night shift, bench, verified edit, ask) sit on top. Clients: Next.js local web UI (`web/`) and the VS Code extension (`vscode-extension/`). A static demo build of the web UI with precomputed results is the public showcase.

**Tech Stack:** Python 3.12, FastAPI, Typer, Pydantic v2, SQLite, ChromaDB (telemetry off), GitPython/`git` CLI, httpx, pytest; Ollama / LM Studio / llama.cpp server (local only); Next.js 16, React 19, TypeScript, Tailwind CSS 4, Geist + Geist Mono, @phosphor-icons/react, shiki, vitest; VS Code extension (TypeScript, webpack).

> **Implementation status (2026-10-18, Claude Code):** Tasks 0–11, 13–15, 17 and the repo side of 18–19 are implemented on branch `v2`.
> Deviations, all documented in `docs/ARCHITECTURE.md`: vectors in SQLite + NumPy instead of ChromaDB; API under `/api`;
> web routes under `/app/*`; verified edits use search/replace blocks instead of model-written diffs; blast-radius risk is a
> repo-relative points score; indexing and review also work without a model runtime. Task 12 (evaluation: Flask and Requests datasets, 60 tuning + 30 held-out hand-labelled hunks) and Task 16
> (demo data) are implemented but have only been run offline — they need a local model runtime for the full results.
> See `docs/VERIFICATION.md`.

**Spec:** Agreed in conversation on 2026-10-18 (summarised in "Design decisions"). Repository: https://github.com/aahil62/repopilot (current `main`).

---

## Design decisions (fixed — do not re-decide)

1. **Positioning:** "AI made code cheap to write and expensive to review. RepoPilot is a private reviewer that knows your repository's history, running on open models you control." Published evidence to cite in README (verify links during Task 18): Harvard working paper (Chen & Stratton, 2026) — +30% lines of code per worker, no significant rise in finished tasks, PR review time +49%; MIT/Wharton NBER paper (Demirer, Musolff, Yang) — large rise in code/PRs, releases up ~20%.
2. **Privacy guarantee:** No cloud AI providers in the codebase. Model calls go only to `localhost`/LAN URLs the user configures. No telemetry (Chroma `anonymized_telemetry=False`; no analytics in web UI). The only optional outbound network is to the code host (GitHub) for importing public review history, off by default.
3. **Any open model, no API key:** Supported runtimes: Ollama (`http://127.0.0.1:11434`), LM Studio (`http://127.0.0.1:1234/v1`), llama.cpp server (`http://127.0.0.1:8080/v1`). RepoPilot detects installed models and assigns three roles: `fast` (classification/routing), `strong` (review, code), `embed` (embeddings). Defaults when available: `qwen2.5-coder:7b` strong, `qwen2.5-coder:1.5b` fast, `nomic-embed-text` embed; otherwise the largest/smallest installed chat models and any installed embedding model.
4. **Five features, all included:** (1) history-aware review, (2) blast radius from history, (3) night shift, (4) model bench ("which model should we run?"), (5) verified coding assistance + grounded Q&A with line citations.
5. **Repository memory:** code chunks + symbols + import graph + git history (commits, numstat, co-change) + review history (merge-commit PR refs locally; optional GitHub PR review comments import).
6. **Never touch the user's working tree without an explicit apply.** All model-written code is applied and tested in a temporary `git worktree` under `~/.repopilot/worktrees/`.
7. **Any repository size:** streaming file walk, incremental re-index by content hash, batched embeddings, configurable caps (no hard 900-file cap), history capped at the last 5,000 commits by default.
8. **Public showcase:** static demo of the web UI (`DEMO_MODE`) with precomputed results for `pallets/flask` at a pinned commit, deployed to Vercel; the README links it plus a demo video. The real product runs locally. There is **no hosted backend** in v2 (a hosted backend would need a cloud model, which breaks the privacy promise). The existing Vercel serverless backend and the Railway service are retired (Task 19).

## Current deployment state (verified 2026-10-18 — read before Task 0)

- `https://repopilot-ext.vercel.app` serves the **`website` branch** (`website/frontend`, Next.js), not `main`. `main` has no frontend at all (deleted in commit `4ef120b`).
- That site rewrites `/api/*` to a **Python backend running as a Vercel serverless function** (`website/backend/vercel.json` → `api/index.py`, response header `server: Vercel`, region iad1). `/api/health` returns `{"status":"ok","version":"1.0.0","gemini_configured":true}`.
- **Analysis is broken in production:** `POST /api/analyze` for `pallets/itsdangerous` returns in ~1 s with "Unable to analyze data flow without LLM API key", and the tech stack lists only Markdown/TOML/Text/YAML/JSON — no Python — so the GitHub zipball fetch/scan is also missing source files. The Gemini key is set but not working (invalid or out of quota).
- **Railway:** GitHub deployment records show a Railway project (`heroic-determination / production`, project `6e9ab4af-33c0-4dd9-8b30-e3f379cb2b07`) deploying `main`; its latest deployment status is `inactive`. `backend/railway.json` and `frontend/railway.json` (website branch) exist.
- The VS Code extension defaults to `http://localhost:8000` and has no hosted backend configured.
- Branches on origin: `main`, `website`, `UI_Updates`, `sandbox`, `feature-2`, `feature_2`, `vscode-extension` (all hackathon-era).
9. **Credit:** README "Credits" states RepoPilot began at the AlphaByte 3.0 hackathon, names the teammates from git history, and states v2 is the author's solo rebuild.

## Global Constraints

- Python package name `repopilot`, located at `backend/repopilot/` (moved from `backend/app/` in Task 1). CLI entry point `repopilot` (`python -m repopilot`).
- Data root: `REPOPILOT_HOME` env, default `~/.repopilot`. Per repo: `~/.repopilot/repos/<repo_id>/` containing `memory.sqlite`, `chroma/`, `graph.json`. `repo_id` = first 12 hex of sha1 of the absolute repo path (local) or `owner/name` (remote clone).
- API binds `127.0.0.1:7341` by default (`REPOPILOT_PORT`). CORS allows only `http://127.0.0.1:7342`, `http://localhost:7342` (web UI) and `vscode-webview://*`.
- Web UI dev/prod port 7342.
- All LLM structured outputs go through `structured_call` (Task 2). No free-form JSON parsing elsewhere.
- Tests never call a real model or the network: use `FakeRuntime` (Task 2) and local temp git repos created in fixtures.
- Backend checks: `cd backend && python -m pytest -q` and `ruff check repopilot tests`. Web: `npm --prefix web run test`, `npm --prefix web run lint`, `cd web && npx tsc --noEmit`. Extension: `npm --prefix vscode-extension run compile`.
- Copy tone: plain, specific, no hype words ("revolutionary", "supercharge", "seamless"). No invented metrics; every number shown comes from a file produced by the code.
- No push/publish/deploy without the user's approval. Commit locally only, conventional commit messages. Never read, print or copy secrets from Vercel/Railway; account changes are the user's (Task 19).

## Review Focus

1. **Huge repository (50k files, 200k commits)** — indexing must stream and stay under ~2 GB RAM; history import stops at the 5,000-commit cap with a visible note. Test in Task 3 (generated 5,000-file repo, memory not asserted, time-bounded).
2. **Small model returns invalid JSON or a hallucinated file/line** — `structured_call` retries twice, then raises `ModelOutputError`; review findings citing lines not in the diff/repo are dropped and counted as `dropped_unverifiable`. Tests in Tasks 2 and 6.
3. **Model-written patch that does not apply or breaks tests** — verified-edit loop retries up to 3 times with the error output, then returns `status: "failed"` with the last diff and logs; the user's working tree is never modified. Test in Task 8.
4. **No model runtime running** — every API endpoint that needs a model returns HTTP 503 `{"detail":"No local model runtime found. Start Ollama or LM Studio.","runtimes_checked":[...]}`; UI shows a setup card with commands. Test in Task 2.
5. **Repository with no tests / unknown test runner** — review and night shift still work; the checks section says "No test command detected — set one in Settings" instead of failing. Test in Task 6.

---

## File map (target layout)

```
backend/
  repopilot/
    __init__.py, __main__.py         # python -m repopilot -> cli
    cli.py                           # Typer: serve, index, review, blast, nightshift, bench, models
    config.py                        # Settings (REPOPILOT_HOME, ports, caps)
    api/main.py, api/routes/{repos,ask,review,blast,nightshift,bench,models,edit}.py
    runtime/{detect.py, client.py, structured.py, hardware.py, roles.py}
    memory/{store.py, files.py, chunker.py, symbols.py, codegraph.py, embeddings.py, history.py, reviews.py}
    engines/{diffparse.py, classify.py, blast.py, precedents.py, checks.py, review.py, edit.py, ask.py, nightshift.py, bench.py}
    worktree.py
  tests/  (pytest; fixtures in tests/conftest.py)
  pyproject.toml
web/        # Next.js app (new)
vscode-extension/  # existing, updated
eval/       # datasets + results
docs/       # ARCHITECTURE.md, PRIVACY.md, screenshots, superpowers/plans/
```

---

### Task 0: Repository setup and cleanup

- [x] **Step 1:** Cloned to `~/Projects/portfolio/repopilot`. Create **local** archive tags so nothing from the hackathon is lost: `git tag archive/hackathon-main origin/main` and `git tag archive/hackathon-website origin/website` (do not push tags yet). Create branch `v2` from `origin/main`. Copy this plan to `docs/superpowers/plans/2026-10-18-repopilot-v2.md`.
- [x] **Step 1b:** Do **not** reuse code from the `website` branch frontend (generic dark template, Gemini-dependent). Only its idea of a codebase graph carries over, rebuilt as the blast-radius orbit in Task 14.
- [x] **Step 2:** Delete hackathon artifacts: `.github/chatmodes/`, `.github/instructions/`, `round2essential.md`, `future_roadmap.md`, `speed_optimization_roadmap.md`, `test.md`, `explain.md`, `docs/FINAL_SUBMISSION_PS7.md`, `docs/DEMO_CHECKLIST.md`, `docs/REPO_STRUCTURE.md`, `start_backend.bat`, `backend/vercel.json`, `backend/api/index.py`, `backend/railway.json`, `tests/verify_ps7.py`, `tests/verify_features.py`, `SETUP_GUIDE.md`. Keep `demo_repo/` (used as a test fixture later).
- [x] **Step 3:** Write `CREDITS.md` listing contributors from `git log --format='%an' | sort -u` (dedupe aliases of the same email) with the hackathon origin sentence from Design decision 9.
- [x] **Step 4:** Commit `chore: remove hackathon artifacts and add credits`.

---

### Task 1: Package restructure, config, CLI skeleton, test harness

**Files:** Move `backend/app/` → `backend/repopilot/` (keep git history with `git mv`); create `pyproject.toml`, `repopilot/__main__.py`, `repopilot/cli.py`, rewrite `repopilot/config.py`; `tests/conftest.py`.

**Interfaces:**
- `pyproject.toml`: project `repopilot`, version `2.0.0`, python `>=3.12`, deps: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `typer`, `httpx`, `chromadb`, `gitpython`, `pygments`, `numpy`, `psutil`, `unidiff`, `rich`; dev: `pytest`, `pytest-asyncio`, `ruff`. Script: `repopilot = "repopilot.cli:app"`.
- Remove deps: `openai`, `google-genai`, `tiktoken`, `backoff`, `tenacity`, `structlog` (replace logging with stdlib `logging` + `rich` handler). Delete `requirements.txt` (pyproject is the source of truth).
- `Settings` (pydantic-settings, env prefix `REPOPILOT_`): `home: Path = ~/.repopilot`, `port: int = 7341`, `web_port: int = 7342`, `max_file_kb: int = 512`, `max_files: int = 100_000`, `history_max_commits: int = 5_000`, `embed_batch: int = 64`, `runtime_urls: list[str] = ["http://127.0.0.1:11434", "http://127.0.0.1:1234/v1", "http://127.0.0.1:8080/v1"]`, `allow_github_import: bool = False`.
- CLI commands (stubs now, filled later): `serve`, `index PATH`, `review [--repo PATH] [--base REF] [--head REF] [--staged]`, `blast PATH_IN_REPO [--repo PATH]`, `nightshift run|install|report`, `bench [--repo PATH] [--tasks 10]`, `models`.
- `tests/conftest.py` fixtures: `tmp_home` (sets `REPOPILOT_HOME`), `git_repo(tmp_path)` factory that creates a repo with given files and a list of commits `[(message, {path: content})]`, `fake_runtime` (Task 2).

- [ ] **Step 1:** Failing test `tests/test_cli.py::test_help_lists_commands`: `CliRunner().invoke(app, ["--help"])` output contains all seven command names.
- [ ] **Step 2:** Restructure; fix imports; delete cloud provider code paths from the moved modules (`utils/llm.py`, `utils/embeddings.py` will be replaced in Task 2).
- [ ] **Step 3:** Tests pass; `ruff check` clean. Commit `refactor: repopilot package, settings and CLI skeleton`.

---

### Task 2: Local model runtime layer (reliability for open models)

**Files:** Create `repopilot/runtime/{detect.py, client.py, structured.py, hardware.py, roles.py}`; delete old `utils/llm.py`, `utils/embeddings.py`. Tests: `tests/test_runtime.py`.

**Interfaces:**
- `@dataclass ModelInfo: id: str, runtime: Literal["ollama","openai_compat"], base_url: str, size_bytes: int | None, context_length: int | None, is_embedding: bool`
- `async def detect_models(urls: list[str]) -> list[ModelInfo]` — Ollama: `GET /api/tags` (+ `POST /api/show` for context length from `model_info["*.context_length"]`); OpenAI-compatible: `GET /models`. Embedding models: name contains `embed` or `bge` or `nomic` or Ollama `families` contains `bert`. Timeout 1.5 s per URL; unreachable URLs are skipped.
- `def hardware() -> Hardware(total_ram_bytes, gpu: str | None, vram_bytes: int | None, unified_memory: bool)` — `psutil` RAM; `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits` if present; Apple Silicon (`platform.machine()=="arm64"` and Darwin) → unified memory, VRAM = 75% of RAM.
- `def assign_roles(models: list[ModelInfo], hw: Hardware, overrides: dict[str,str]) -> dict[Literal["fast","strong","embed"], ModelInfo]` — Rule: candidates must fit (`size_bytes <= 0.8 * (vram or ram)`); strong = preferred default if installed else largest fitting chat model; fast = preferred default else smallest chat model; embed = preferred default else any embedding model. Overrides from `~/.repopilot/models.json` win. Raise `NoRuntimeError` if no chat model.
- `class ModelClient`: `async chat(role, messages, *, json_schema: dict | None = None, max_tokens=2048, temperature=0.1) -> str`; `async embed(texts: list[str]) -> list[list[float]]`. Ollama: `POST /api/chat` with `options.num_ctx = min(context_length or 8192, 32768)`, `format = json_schema` when given, `stream=false`; OpenAI-compat: `POST /chat/completions` with `response_format={"type":"json_schema","json_schema":{"name":"out","schema":schema}}` when given. Records `tokens_per_second` from response metadata when available.
- `async def structured_call(client, role, schema: type[BaseModel], messages, *, retries: int = 2) -> BaseModel` — validate with `schema.model_validate_json`; on failure append a user message "Your previous output was invalid: <error>. Return only JSON matching the schema." and retry; after retries raise `ModelOutputError(last_output, error)`.
- `class FakeRuntime` (in `runtime/client.py`, used by tests): scripted responses per role, records calls.
- API: `GET /models` → `{runtimes: [...], models: [...], roles: {...}, hardware: {...}}`; `PUT /models/roles` body `{fast?, strong?, embed?}` writes `models.json`. Any model-dependent endpoint raises 503 per Review Focus 4.

- [ ] **Step 1: Failing tests:** `test_assign_roles_prefers_defaults`, `test_assign_roles_excludes_models_too_big`, `test_structured_call_retries_then_succeeds` (fake returns invalid then valid), `test_structured_call_raises_after_retries`, `test_ollama_request_sets_num_ctx_and_format` (httpx `MockTransport` asserts body), `test_no_runtime_returns_503` (API with no models).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** PASS. Commit `feat(runtime): local model detection, roles and schema-validated calls`.

---

### Task 3: Repository memory — files, chunks, symbols, embeddings (incremental, large-repo safe)

**Files:** Create `repopilot/memory/{store.py, files.py, chunker.py, symbols.py, embeddings.py}` (adapt the existing chunker/indexer/retriever logic), tests `tests/test_memory_index.py`.

**Interfaces:**
- `memory.sqlite` tables: `files(path PRIMARY KEY, sha1, language, size, indexed_at)`, `chunks(chunk_id PRIMARY KEY, path, start_line, end_line, kind, symbol, sha1)`, `symbols(name, kind, path, start_line, end_line)`, `meta(key PRIMARY KEY, value)`.
- `def iter_repo_files(root: Path, settings) -> Iterator[RepoFile]` — uses `git ls-files -co --exclude-standard` when a git repo (respects .gitignore), else walk; skips binaries (null byte in first 8 KB), files > `max_file_kb`, and dirs `node_modules, .git, dist, build, .venv, venv, __pycache__, .next, target, vendor`.
- Chunking: Python files → one chunk per top-level function/class (via `ast`, include decorators and docstring; split >150 lines into 120-line windows with 20 overlap); JS/TS → regex function/class boundaries, fallback windows; others → 120-line windows, 20 overlap; Markdown → by heading.
- `symbols.py`: Python `ast` defs + imports; JS/TS regex `export (async )?function|class|const NAME` and `import ... from '...'`.
- `async def index_repo(repo_path: Path, client: ModelClient, progress: Callable[[IndexProgress], None]) -> IndexStats` — incremental: compare file sha1 to `files` table; re-chunk/embed only changed files; delete rows/vectors for removed files; embed in batches of `embed_batch`; Chroma persistent client at `chroma/` with `Settings(anonymized_telemetry=False)`; `IndexProgress{stage: Literal["scanning","chunking","embedding","graph","history","done"], done:int, total:int}`.
- API: `POST /repos` body `{path: str}` (local path; or `{git_url}` which clones to `~/.repopilot/clones/<owner>__<name>`) → `{repo_id}`; `POST /repos/{id}/index` starts background indexing; `GET /repos/{id}/progress` is **SSE** emitting `IndexProgress` JSON; `GET /repos` lists repos with stats.

- [ ] **Step 1: Failing tests:** chunk boundaries for a Python file with two functions and a class; JS export detection; incremental re-index touches only the modified file (assert embed called with 1 file's chunks); deleted file removes its chunks; `.gitignore`d file skipped; a generated 5,000-file repo indexes with `FakeRuntime` embeddings within 120 s.
- [ ] **Step 2:** FAIL → implement → PASS. Commit `feat(memory): incremental code index with symbols and local embeddings`.

---

### Task 4: Repository memory — import graph, git history, co-change, review history

**Files:** Create `repopilot/memory/{codegraph.py, history.py, reviews.py}`, tests `tests/test_memory_history.py`.

**Interfaces:**
- `codegraph.build_graph(repo_path, files) -> Graph{nodes: [{path, language, loc}], edges: [{source, target}]}` — resolve Python `import a.b` / `from .x import y` to repo files; JS/TS relative imports with extension resolution (`.ts,.tsx,.js,.jsx,/index.*`). Saved to `graph.json`. `def dependents(graph, path, depth=2) -> list[(path, depth)]`.
- `history.import_history(repo_path, store, max_commits) -> int` — `git log --no-merges --numstat --date=iso-strict --format=%x1e%H%x1f%an%x1f%ae%x1f%ad%x1f%s%x1f%b` (newest first, capped). Tables: `commits(sha PRIMARY KEY, author, email, date, subject, body, is_fix INTEGER)`, `commit_files(sha, path, added, deleted)`. `is_fix` = regex `(?i)\b(fix|fixes|fixed|bug|hotfix|regression|revert|crash|broken)\b` on subject+body. Incremental: stop at the newest already-imported sha. Record `meta.history_truncated = "1"` when the cap is hit.
- Co-change: `cochange(path, store, min_support=3) -> list[{path, support, confidence}]` where `support` = commits touching both, `confidence = support / commits_touching(path)`; exclude commits touching > 50 files (bulk changes). Sorted by confidence desc, top 15.
- `reviews.py`: table `review_comments(source, pr_number, path, line, body, author, date, verdict)`.
  - Local source: merge commits `Merge pull request #N` → record PR number ↔ commits (`pr_commits(pr_number, sha)`).
  - GitHub import (only if `allow_github_import` and the repo has a github.com remote): `GET /repos/{owner}/{repo}/pulls?state=closed&per_page=100` (max 300 PRs) and `/pulls/{n}/comments` + `/pulls/{n}/reviews`; use `GITHUB_TOKEN` env if set; stop gracefully on rate limit and record `meta.reviews_partial`. Comments and commit subjects are embedded into a Chroma collection `precedents`.
- CLI: `repopilot index PATH --with-reviews` triggers the import.

- [ ] **Step 1: Failing tests:** graph edges for a 3-file Python package with relative imports; `dependents` depth 2; history import counts commits and marks a "fix: crash on empty input" commit as fix; co-change confidence exact for a crafted history (A+B together 4 times, A alone 1 time → B confidence 0.8, support 4); bulk commit (>50 files) excluded; GitHub import uses `httpx.MockTransport` and stops on HTTP 403 rate limit with `reviews_partial`.
- [ ] **Step 2:** FAIL → implement → PASS. Commit `feat(memory): import graph, git history, co-change and review history`.

---

### Task 5: Blast radius engine

**Files:** `repopilot/engines/blast.py`, `repopilot/api/routes/blast.py`, test `tests/test_blast.py`.

**Interfaces:**
- `def blast_radius(repo_id, paths: list[str]) -> BlastReport` with fields: `targets: list[str]`, `cochanged: list[{path, support, confidence}]`, `dependents: list[{path, depth}]`, `past_fixes: list[{sha, date, subject, author}]` (fix commits touching any target, newest first, max 10), `tests: list[str]` (test files that import a target or co-change with it, by naming `test_*`/`*_test.*`/`*.test.*`/`*.spec.*`), `owners: list[{author, commits}]` (top 3 authors of the targets in the last 12 months — "who should review"), `risk: Literal["low","medium","high"]`, `risk_reasons: list[str]`.
- Risk rule: high if ≥ 3 past fixes in 12 months or ≥ 10 dependents; medium if ≥ 1 past fix or ≥ 3 dependents or any co-changed file with confidence ≥ 0.6 not in `paths`; else low. Reasons are human sentences, e.g. "`auth.py` usually changes together with `session.py` (80% of the time) — it is not in this change."
- API: `GET /repos/{id}/blast?path=a&path=b`. CLI: `repopilot blast PATH` prints a rich table.

- [ ] **Step 1: Failing tests** on a crafted repo for each field and each risk rule. **Step 2:** FAIL → implement → PASS. Commit `feat(engine): blast radius from history and import graph`.

---

### Task 6: History-aware review engine

**Files:** `repopilot/engines/{diffparse.py, classify.py, precedents.py, checks.py, review.py}`, `repopilot/worktree.py`, `repopilot/api/routes/review.py`, tests `tests/test_review.py`.

**Interfaces:**
- `diffparse.parse(diff_text) -> list[FileDiff{path, old_path, status, hunks: [Hunk{old_start, old_lines, new_start, new_lines, lines}]}]` (use `unidiff`).
- `diffparse.diff_for(repo_path, *, base: str | None, head: str | None, staged: bool) -> str` — working tree vs HEAD by default; `--staged` → `git diff --cached`; base/head → `git diff base...head`.
- `classify.classify_hunk(file_diff, hunk, repo_path) -> Literal["mechanical","behavior"]` + `reason` — mechanical when: whitespace-only change; comment/docstring-only; import reordering only (same set of import lines); pure rename (old and new lines equal after replacing identifiers that were renamed consistently across the hunk); Python file where `ast.dump(old_file)` == `ast.dump(new_file)` ignoring positions (formatting). Else behavior.
- `precedents.find(repo_id, behavior_hunks, k=3, min_similarity=0.75) -> list[{kind: "review_comment"|"fix_commit", ref: "PR #412"|sha, path, excerpt, similarity}]` — embeds each behavior hunk (+ file path) and queries the `precedents` collection.
- `checks.detect_test_command(repo_path) -> str | None` — order: `repopilot.toml [checks] test` if present; `pytest` if `pytest.ini`/`pyproject [tool.pytest]`/`tests/` with `test_*.py`; `npm test --silent` if `package.json` has `scripts.test` not equal to the npm default error stub; `go test ./...` if `go.mod`; `cargo test` if `Cargo.toml`. Plus optional typecheck (`npx tsc --noEmit` if `tsconfig.json`; `mypy` only if configured).
- `worktree.temp_worktree(repo_path, ref="HEAD") -> ContextManager[Path]` — `git worktree add --detach ~/.repopilot/worktrees/<uuid> ref`; always `git worktree remove --force` on exit.
- `checks.run_checks(repo_path, diff_text, timeout=300) -> ChecksResult{command, status: Literal["passed","failed","skipped","timeout"], output_tail (last 80 lines)}` — applies the diff in a temp worktree (`git apply --3way`) and runs the commands.
- `review.review(repo_id, diff_text, *, run_checks=True) -> ReviewReport`:
  - `summary` (LLM, strong role), `files: [{path, mechanical_hunks, behavior_hunks}]`, `mechanical_count`, `behavior_count`,
  - `findings: [{severity: Literal["high","medium","low"], path, line, title, explanation, evidence: [{kind, ref, excerpt}]}]` from `structured_call` with schema `ReviewFindings` — the prompt includes only behavior hunks, blast radius for touched files, and precedents;
  - **citation verification:** drop findings whose `path` is not in the diff or whose `line` is outside the new-file line range of that file's hunks (±3); count `dropped_unverifiable`;
  - `blast: BlastReport`, `precedents`, `checks: ChecksResult`, `model: {strong, fast}`, `timings_ms`.
- API: `POST /repos/{id}/review` body `{diff?: str, base?: str, head?: str, staged?: bool, run_checks?: bool}`; long-running → returns `{review_id}` and `GET /reviews/{review_id}` (status + report); reports persisted in `memory.sqlite` table `reviews(review_id, created_at, source, report_json)`.
- CLI: `repopilot review` prints summary, mechanical vs behavior counts, findings, blast risk, checks.

- [ ] **Step 1: Failing tests:** classify — whitespace, comment-only, import reorder, consistent rename, black-style reformat → mechanical; changed condition → behavior. Review with `FakeRuntime` returning one valid and one hallucinated finding → one kept, `dropped_unverifiable == 1`. Repo without tests → checks `skipped` with message. Diff that breaks a test in a fixture repo → checks `failed` with output tail containing the assertion. Worktree removed after an exception.
- [ ] **Step 2:** FAIL → implement → PASS. Commit `feat(engine): history-aware review with verified findings`.

---

### Task 7: Grounded Q&A (keep, rebuilt on memory)

**Files:** `repopilot/engines/ask.py`, `repopilot/api/routes/ask.py`, test `tests/test_ask.py`.

**Interfaces:**
- Hybrid retrieval: vector top 20 (Chroma) + lexical top 20 (SQLite FTS5 over chunk text; create `chunks_fts` virtual table in Task 3's store if missing) fused with Reciprocal Rank Fusion `score = Σ 1/(60 + rank)`, keep top 8; add history context when the question contains "why" (top 3 commits whose subject/body match the question or touch the top retrieved files).
- `POST /repos/{id}/ask` → SSE events: `retrieval` (list of `{path,start_line,end_line}`), `token` (text), `citations` (`[{n, path, start_line, end_line, snippet}]`), `done`. The model must cite as `[n]`; after generation, citations whose `n` was not supplied are removed and the answer gets a note "1 unsupported citation removed".
- Refusal: if the top fused score is below the 20th percentile of scores for the repo's own symbol names (store a calibration value at index time), answer "I couldn't find this in the repository." with the closest 3 files.

- [ ] **Step 1: Failing tests:** RRF ordering for crafted rankings; unsupported citation removed; refusal path. **Step 2:** FAIL → implement → PASS. Commit `feat(engine): hybrid retrieval Q&A with checked citations`.

---

### Task 8: Verified edits (coding assistance)

**Files:** `repopilot/engines/edit.py`, `repopilot/api/routes/edit.py`, test `tests/test_edit.py`.

**Interfaces:**
- `async def verified_edit(repo_id, instruction: str, target_paths: list[str] | None, *, max_attempts: int = 3) -> EditResult{status: Literal["verified","failed","no_checks"], diff, attempts: [{n, diff, checks: ChecksResult}], explanation}`.
  - Context: target files (or top retrieved files), their blast radius, conventions sample (2 similar functions from the repo retrieved by embedding).
  - Model output schema `EditProposal{explanation: str, diff: str}` (unified diff against HEAD).
  - Each attempt: `git apply --check` in a temp worktree; if it fails, retry with the apply error; then `run_checks`; if checks fail, retry with the output tail. `no_checks` when no test command detected but the diff applied.
- `POST /repos/{id}/edit` (async job like review). `POST /repos/{id}/edit/{job_id}/apply` applies the verified diff to the **working tree** with `git apply` (only when `status in {"verified","no_checks"}`), returns 409 if the working tree changed the target files since the job started (compare sha1s).

- [ ] **Step 1: Failing tests:** fake model first returns a non-applying diff, then a diff that fails a test, then a passing one → `verified`, 3 attempts; all fail → `failed`, working tree untouched (assert file content unchanged); apply endpoint 409 on concurrent modification.
- [ ] **Step 2:** FAIL → implement → PASS. Commit `feat(engine): verified edits in temporary worktrees`.

---

### Task 9: Night shift

**Files:** `repopilot/engines/nightshift.py`, `repopilot/api/routes/nightshift.py`, CLI `nightshift` subcommands, tests `tests/test_nightshift.py`.

**Interfaces:**
- State file `~/.repopilot/repos/<id>/nightshift.json` `{last_sha, last_run}`.
- `async def run_nightshift(repo_id, *, max_commits: int = 20, write_tests: bool = True) -> NightReport`:
  1. Pull new history (Task 4 incremental). Commits since `last_sha` (first run: last 10).
  2. For each commit: `review(diff of that commit, run_checks=False)` → keep findings with severity ≥ medium.
  3. **Missing tests:** functions/classes added or changed (from `symbols` diff of the commit) that no test file references by name → up to 5 per run: `verified_edit("Write focused unit tests for <symbol> in <path> following the style of <closest existing test file>", target_paths=[test file path])`. Verified test diffs are committed to branch `repopilot/nightshift-YYYY-MM-DD` created in a worktree off HEAD (`git commit -m "test: add tests for <symbol> (RepoPilot night shift)"`). Never touch the current branch.
  4. **Stale docs:** Markdown files that mention a symbol name removed or renamed in these commits (word-boundary match) → list `{doc_path, line, symbol, commit}`.
  5. Report `{date, commits_reviewed, findings: [...with commit sha], tests_written: [{symbol, path, branch, status}], stale_docs: [...], model, duration_s}` saved to `~/.repopilot/repos/<id>/reports/YYYY-MM-DD.json` and `.md`.
- `repopilot nightshift install --repo PATH --at 02:00`: macOS → write `~/Library/LaunchAgents/dev.repopilot.nightshift.<id>.plist` and print the `launchctl load` command (do not run it); Linux → print the crontab line; Windows → print the `schtasks` command.
- API: `GET /repos/{id}/nightshift/reports`, `GET /repos/{id}/nightshift/reports/{date}`, `POST /repos/{id}/nightshift/run`.

- [ ] **Step 1: Failing tests:** first run reviews last 10 commits; second run only new ones; a function without tests gets a verified test on the nightshift branch and the current branch HEAD is unchanged; renamed symbol mentioned in README listed as stale; plist content contains the repo path and `StartCalendarInterval` hour 2 minute 0.
- [ ] **Step 2:** FAIL → implement → PASS. Commit `feat(engine): night shift reviews, verified tests and stale-doc report`.

---

### Task 10: Model bench — "Which model should we run?"

**Files:** `repopilot/engines/bench.py`, `repopilot/api/routes/bench.py`, CLI `bench`, tests `tests/test_bench.py`.

**Interfaces:**
- Task selection `select_tasks(store, n=10, seed=7) -> list[BenchTask{sha, parent, subject, paths, real_diff}]`: non-merge commits in history, 1–2 source files changed (exclude docs/lock/config files), 3–60 changed lines, subject length ≥ 12 chars, not a revert; deterministic sample by seed.
- For each installed chat model that fits hardware (Task 2) and each task: in a worktree at `parent`, give the model the commit subject+body as the instruction, the target files, blast context; single attempt `EditProposal`; measure:
  - `applies` (0/1, `git apply --check`),
  - `tests_pass` (run the repo test command at that worktree after applying, if a test command exists and passes at the real commit; else `null`),
  - `similarity` = `difflib.SequenceMatcher` ratio between changed lines of model diff and real diff (0–1),
  - `latency_s`, `tokens_per_second`.
- Score per task: if `tests_pass` is not null: `0.6*tests_pass + 0.2*applies + 0.2*similarity`; else `0.5*applies + 0.5*similarity`. Model score = mean.
- Recommendation: best score among models with median latency ≤ 60 s; text: "Use <model> for review and code (score 0.71, median 18 s on your machine). <fast model> is good enough for classification." Results saved to `~/.repopilot/repos/<id>/bench/<timestamp>.json`.
- API: `POST /repos/{id}/bench` (job), `GET /repos/{id}/bench/latest`. CLI prints a leaderboard table.

- [ ] **Step 1: Failing tests:** task selection filters (merge, docs-only, too large excluded) and determinism; scoring formula exact values; recommendation respects the latency cap; models too big for hardware are listed as "skipped: needs ~X GB".
- [ ] **Step 2:** FAIL → implement → PASS. Commit `feat(engine): repository-specific model benchmark`.

---

### Task 11: API assembly, job runner, serve command

**Files:** `repopilot/api/main.py`, `repopilot/api/jobs.py`, `repopilot/cli.py serve`, test `tests/test_api_smoke.py`.

- Job runner: in-process `asyncio` task registry `{job_id, kind, status: queued|running|done|failed, progress, result_ref, error}`, persisted to `memory.sqlite` `jobs` table so results survive restarts; `GET /jobs/{id}`.
- `repopilot serve` runs uvicorn on 127.0.0.1:7341 and, if `web/out` exists (built static UI), serves it at `/` so one command gives the whole local app at `http://127.0.0.1:7341`. Print the URL and detected models on start.
- `GET /health` → `{status, version, runtimes_reachable}`.
- [ ] **Step 1:** Smoke test with `TestClient` + `FakeRuntime`: add fixture repo → index → ask → review → blast → bench job lifecycle. **Step 2:** PASS. Commit `feat(api): job runner and single-command local server`.

---

### Task 12: Evaluation harness and published numbers

**Files:** `eval/datasets/flask.yaml`, `eval/datasets/requests.yaml`, `eval/datasets/mechanical_hunks.jsonl`, `eval/run_eval.py`, `eval/results/` (generated), test `tests/test_eval_schema.py`.

- [ ] **Step 1:** Datasets: for `pallets/flask` and `psf/requests` at pinned tags (`3.1.0` and `v2.32.3`): 25 questions each with `gold_files` (hand-written by reading the code; e.g. "Where is the request context pushed?" → `src/flask/ctx.py`), plus 5 unanswerable questions each (e.g. "Where is the GraphQL schema?").
- [ ] **Step 2:** `mechanical_hunks.jsonl`: 60 hunks extracted from those repos' history (30 mechanical, 30 behavior), labelled by hand with a one-line justification.
- [ ] **Step 3:** `run_eval.py --model <strong>` computes: retrieval Recall@5 of gold files (vector-only vs lexical-only vs hybrid), refusal accuracy on unanswerable, mechanical/behavior classifier precision & recall, review citation validity rate (on 20 historical fix commits: fraction of findings that survive verification), and bench results for each installed model on each repo. Writes `eval/results/latest.json` and `eval/results/latest.md`.
- [ ] **Step 4:** Run it with the models the user has installed (if none, install instructions in the report; do not fabricate). Commit `test(eval): evaluation harness and results`.

---

### Task 13: Web UI — scaffold, design system, API client

**Files:** `web/` (Next.js app, `output: "export"` for static serving; dev server on 7342), `web/lib/api.ts`, `web/app/globals.css`, `web/app/layout.tsx`, `web/components/ui/*`.

**Design system (exact):**
- Fonts: Geist (UI), Geist Mono (code, numbers, paths) via the `geist` npm package.
- Tokens (CSS variables on `:root`): `--paper #F6F4EF` (canvas), `--surface #FFFFFF`, `--ink #15171C`, `--muted #5D6270`, `--line #E3DFD6`, `--accent #C2410C` (actions, focus ring), `--accent-soft #FCEBDD`, `--code-bg #0F1216`, `--code-ink #E6E8EE`, `--cite #2457D6` (citation chips), `--ok #1F7A4D`, `--warn #A16207`, `--bad #B42318`, `--mech #6B7280` (mechanical hunks). Radius: panels 12px, controls 8px, chips 999px. Shadows: none except `0 1px 0 var(--line)` dividers.
- Dark mode: `prefers-color-scheme: dark` → paper `#111317`, surface `#171A1F`, ink `#ECEDEF`, muted `#9AA0AA`, line `#2A2E35`, accent `#F97316`, accent-soft `#3A2416`.
- Layout: left rail 232px (repo switcher at top, nav: Overview, Review, Blast radius, Night shift, Ask, Models, Settings), top bar with current repo, branch, model status pill ("strong: qwen2.5-coder:7b · 34 tok/s"), "Local only" lock badge linking to Privacy page.
- Code rendering: shiki (`github-dark-dimmed`) inside `--code-bg` panels; line numbers; highlighted line ranges for citations.
- Motion: 150 ms ease-out state transitions only; respect reduced motion.
- `web/lib/api.ts`: typed client for every endpoint in Tasks 2–11 (types mirror Pydantic models; generate from OpenAPI with `openapi-typescript` into `web/lib/schema.d.ts`), SSE helper, base URL `NEXT_PUBLIC_API_BASE` default `http://127.0.0.1:7341`; `DEMO_MODE` (`NEXT_PUBLIC_DEMO_MODE=1`) reads fixtures from `/demo/*.json` instead.
- [ ] **Step 1:** Scaffold, tokens, shell, API client; vitest for `api.ts` demo-mode switch. Commit `feat(web): scaffold, design system and typed API client`.

---

### Task 14: Web UI — pages

**Files:** `web/app/(app)/{overview,review,blast,nightshift,ask,models,settings,privacy}/page.tsx`, `web/app/page.tsx` (landing), components under `web/components/`.

**Page specs:**
- **Landing (`/`)** — H1 "Review AI-written code like you wrote it." Sub: "AI made code cheap to write and expensive to review. RepoPilot is a private reviewer that knows your repository's history — running on open models on your own machine." Primary CTA "See a live review" (→ `/review` on demo data), secondary "Run it locally" (→ install section). Hero visual: an interactive **blast-radius orbit** built from the real flask demo data (center = file, inner ring = dependents, outer ring = co-changed files, dot size = confidence, red dots = past fixes), slowly rotating, pausable. Sections: "The problem" (the two study numbers with source links), "What it does" (5 features, each with a real screenshot), "Your code never leaves" (runtimes supported, no API keys, no telemetry), "Measured" (table rendered from `eval/results/latest.json` copied into `web/public/demo/eval.json` at build), "In your editor" (VS Code screenshot + .vsix download link to GitHub Releases), footer credits.
- **Overview** — repo cards: files, chunks, commits imported, last index, last night shift; "Add repository" dialog (local path or git URL) → live progress bar per stage via SSE.
- **Review** — source selector (Working changes / Staged / Compare refs / Paste diff) → run → report layout: left column file list with mechanical/behavior counts (mechanical collapsed by default, grey `--mech` badge "Mechanical · 14 hunks — rename, formatting"); main column findings cards (severity colour bar, title, explanation, evidence chips linking to commit/PR, code excerpt); right column "Blast radius" mini-orbit + risk reasons + "Suggested reviewers"; bottom "Checks" panel with command and pass/fail + output tail. Header metrics: "Behavior changes to read: 3 of 17 hunks".
- **Blast radius** — file picker (fuzzy search over indexed files) → full orbit visualization + tables: co-changed (confidence bars), dependents, past fixes timeline, tests, owners.
- **Night shift** — calendar list of reports; report view: commits reviewed, findings by commit, tests written (branch name + "View diff"), stale docs; "Run now" and "Schedule" (shows the install command from CLI output).
- **Ask** — chat with streaming; citation chips `[n]` open a right-side code panel scrolled to and highlighting the lines; "why" answers show commit cards.
- **Models** — detected runtimes and models with size, context, fits/doesn't fit; role assignment dropdowns; bench leaderboard (score bar, applies %, tests pass %, similarity, median latency, tok/s) and the recommendation sentence; "Run benchmark" button.
- **Settings** — test command override, caps, GitHub review import toggle (explains the only network call), data folder path, "Delete repository memory".
- **Privacy** — exactly what is stored where, what network calls exist (model runtime URLs; optional GitHub import), how to verify (`lsof -i -P | grep repopilot`).
- Every page: loading skeletons, empty states with the next action, 503 "No local model runtime" setup card (`ollama pull qwen2.5-coder:7b`, `ollama pull nomic-embed-text`).
- [ ] **Step 1:** Vitest per page for: renders demo fixtures; mechanical hunks collapsed by default; citation chip opens code panel; models page shows "skipped: needs ~X GB". **Step 2:** Implement. **Step 3:** Tests/lint/tsc pass; browser check at 1440×900 and 390×844 against a real local run on `demo_repo/` and on flask. Commit `feat(web): review, blast radius, night shift, ask, models pages and landing`.

---

### Task 15: VS Code extension update

**Files:** `vscode-extension/src/*`, `vscode-extension/package.json`, `vscode-extension/README.md`.

- Settings: `repopilot.serverUrl` (default `http://127.0.0.1:7341`), `repopilot.autoStartServer` (default true: spawns `repopilot serve` if `/health` fails and the CLI is on PATH).
- Commands: `RepoPilot: Review Working Changes`, `RepoPilot: Review Staged Changes`, `RepoPilot: Show Blast Radius for This File`, `RepoPilot: Ask About This Repository` (existing chat panel rewired to `/ask` SSE), `RepoPilot: Edit with Verification` (selection or file + instruction → verified diff shown in VS Code diff editor with Apply/Discard), `RepoPilot: Open Night Shift Report`, `RepoPilot: Pick Models`.
- CodeLens at line 1 of every indexed file: "Blast radius: medium · 3 co-changed · 2 past fixes" → opens blast panel.
- Review results also become VS Code diagnostics (Problems panel) at finding lines, severity mapped high→Error, medium→Warning, low→Information, source "RepoPilot".
- Status bar: "RepoPilot · qwen2.5-coder:7b · local".
- Remove all cloud/key references from extension code and README. `package.json` publisher placeholder stays `repopilot` (user publishes later); `repository.url` → `https://github.com/aahil62/repopilot`.
- [ ] **Step 1:** Compile passes; manual run in Extension Development Host against `demo_repo/`: review, blast CodeLens, verified edit apply. Screenshot to `docs/screenshots/vscode-review.png`. `npx @vscode/vsce package` → `repopilot-2.0.0.vsix` in `vscode-extension/` (gitignored). Commit `feat(vscode): review, blast radius, verified edits and diagnostics`.

---

### Task 16: Demo build and fixtures

- [ ] **Step 1:** `scripts/build_demo.py`: indexes `pallets/flask` at tag `3.1.0` locally, runs review on a chosen real historical commit diff, blast radius for `src/flask/app.py` and `src/flask/ctx.py`, one night-shift report over 5 commits, bench results (whatever models the user has), 3 Ask transcripts; writes JSON fixtures to `web/public/demo/`. All fixture content is real output, never hand-written.
- [ ] **Step 2:** `NEXT_PUBLIC_DEMO_MODE=1 npm --prefix web run build` → static site; banner on every page: "Demo · precomputed on pallets/flask · run RepoPilot locally for your own code". Verify locally with a static server.
- [ ] **Step 3:** The demo build must make **zero** network calls other than to its own static files: add a vitest/Playwright check that loads every page with `NEXT_PUBLIC_DEMO_MODE=1` and fails on any request whose URL is not same-origin.
- [ ] **Step 4:** Commit `feat(demo): static showcase with real precomputed results`. Deployment happens in Task 19.

---

### Task 17: Packaging and install experience

- [ ] `README` install path: `pipx install git+https://github.com/aahil62/repopilot#subdirectory=backend` → `ollama pull qwen2.5-coder:7b && ollama pull nomic-embed-text` → `repopilot serve` → open `http://127.0.0.1:7341`. The web UI static export is bundled into the Python package (`backend/repopilot/static/` copied from `web/out` by `scripts/bundle_web.py`; include via `pyproject` package data).
- [ ] GitHub Actions `ci.yml`: backend tests + ruff, web tests + lint + tsc + build, extension compile. No secrets needed.
- [ ] Verify a clean install in a fresh venv works end-to-end on `demo_repo/`. Commit `build: pipx install with bundled web UI and CI`.

---

### Task 18: Docs, README, screenshots, video, release notes

- [ ] **README.md** order: pitch line; hero GIF (review page); "The problem" (study numbers + verified links); "What it does" (5 features, 1 screenshot each); "Private by design" (runtimes, no keys, no telemetry, link to `docs/PRIVACY.md`); "Quick start"; "VS Code"; "Measured" (table from `eval/results/latest.md`); "How it works" (mermaid: repo → memory [code index, symbols/imports, git history, review history] → engines → web/VS Code; model runtime layer beside it); "Limits" (honest: small models miss subtle bugs, review quality depends on model, GitHub import rate limits); "Credits" (from `CREDITS.md`).
- [ ] `docs/ARCHITECTURE.md`, `docs/PRIVACY.md`, `docs/screenshots/*` (landing, review, blast, night shift, models, ask, vscode).
- [ ] Record a 90-second demo (screen recording of: add repo → review working changes → blast radius → night-shift report → models leaderboard) to `docs/media/demo.mp4`; convert a 20 s GIF for the README if `ffmpeg` exists.
- [ ] `CHANGELOG.md` v2.0.0. Final full check run; record results in `docs/VERIFICATION.md` (commands, counts, models used, what was manually verified, what was not).
- [ ] Commit `docs: v2 README, privacy, architecture and verification`. Report to the user with merge/push/deploy/release commands and wait for approval.

---

### Task 19: Fix the deployments (Vercel + Railway) — needs the user's approval at each marked step

The goal: `https://repopilot-ext.vercel.app` (or a renamed project URL) serves the **v2 static demo from `main`**, no serverless backend, no Gemini key, and the Railway service is retired. Codex prepares everything in the repo; account-level changes are done by the user or with their explicit go-ahead.

**Files:** create `web/vercel.json`; delete any remaining `vercel.json`, `railway.json`, `Dockerfile` files that belong to the old hackathon backend/frontend (keep `backend/Dockerfile` only if Task 17 still uses it for local container runs; otherwise delete).

- [ ] **Step 1 (repo, no approval needed):** `web/vercel.json`:
  ```json
  { "framework": "nextjs", "buildCommand": "npm run build", "outputDirectory": "out",
    "env": { "NEXT_PUBLIC_DEMO_MODE": "1" },
    "headers": [{ "source": "/(.*)", "headers": [
      { "key": "X-Content-Type-Options", "value": "nosniff" },
      { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" } ] }] }
  ```
  `web/next.config.ts` must use `output: "export"` (no rewrites; rewrites don't work with static export, which is intended since there is no backend). Verify locally: `NEXT_PUBLIC_DEMO_MODE=1 npm --prefix web run build && npx serve web/out` → every page loads, no `/api` requests (Task 16 check passes).
- [ ] **Step 2 (repo):** Write `docs/DEPLOYMENT.md` documenting: what is hosted (static demo only), why there is no hosted backend, how to redeploy, and the Vercel project settings below.
- [ ] **Step 3 (user approval — merge and push):** Ask the user to approve: merge `v2` into `main`, push `main`, push the two `archive/*` tags. Only after a clear yes: `git checkout main && git merge --no-ff v2 && git push origin main && git push origin archive/hackathon-main archive/hackathon-website`.
- [ ] **Step 4 (user does this in the Vercel dashboard; Codex gives exact clicks):** Project `repopilot-ext` → Settings → Git → **Production Branch = `main`**; Settings → General → **Root Directory = `web`**, Framework = Next.js; Settings → Environment Variables → **delete `GEMINI_API_KEY`, `BACKEND_URL`, `NEXT_PUBLIC_API_URL`**, add `NEXT_PUBLIC_DEMO_MODE=1`; optionally rename the project to `repopilot` for a cleaner URL if available. Redeploy. If the Vercel CLI is installed and the user asks Codex to do it, use `vercel link` / `vercel env rm` / `vercel --prod` from `web/` — still only with approval.
- [ ] **Step 5 (user does this in Railway):** Project `heroic-determination` → the RepoPilot backend service → Settings → **disconnect the GitHub repo** (or delete the service) so pushes to `main` no longer build a backend. Remove its `GEMINI_API_KEY` / other secrets. Codex cannot verify Railway state without the user's login; ask the user to confirm when done.
- [ ] **Step 6 (verify, no approval needed):** `curl -s -o /dev/null -w '%{http_code}' https://repopilot-ext.vercel.app/` → 200; `curl -s https://repopilot-ext.vercel.app/api/health` → 404 (backend gone); open the site in a browser: demo banner visible, Review/Blast/Night shift/Models/Ask pages render flask results, no console errors, mobile 390px OK. Screenshot to `docs/screenshots/live-demo.png`.
- [ ] **Step 7 (user approval — GitHub metadata):** with approval, `gh repo edit aahil62/repopilot --description "Private, history-aware code review on open models you run yourself" --homepage <live URL> --add-topic code-review,local-llm,ollama,developer-tools,vscode-extension`.
- [ ] **Step 8 (user approval — stale branches):** list `UI_Updates`, `sandbox`, `feature-2`, `feature_2`, `vscode-extension`, `website` with last commit date/author. Recommend deleting them on origin (history is preserved by the archive tags). Delete only the branches the user approves: `git push origin --delete <branch>`.
- [ ] **Step 9 (user approval — release):** with approval, create GitHub release `v2.0.0` with notes from `CHANGELOG.md` and attach `vscode-extension/repopilot-2.0.0.vsix`.
