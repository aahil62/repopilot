# Architecture

RepoPilot is one local Python service plus two clients.

```
backend/repopilot/
  runtime/   detect.py (Ollama /api/tags, OpenAI-compatible /models), hardware.py, roles.py (fast/strong/embed),
             client.py (chat, streaming, embeddings; FakeRuntime for tests), structured.py (schema-validated calls)
  memory/    files.py (git ls-files walk), chunker.py (symbol-aware chunks), symbols.py, indexer.py (incremental),
             codegraph.py (import graph), history.py (commits, numstat, co-change, fix detection, PR links),
             reviews.py (precedent index, optional GitHub review import), store.py (SQLite + vectors), registry.py
  engines/   diffparse.py, classify.py, precedents.py, checks.py, review.py, blast.py, ask.py, edit.py,
             nightshift.py, bench.py
  worktree.py   temporary git worktrees — model-written code is only ever applied and tested here
  api/          FastAPI (+ SSE) under /api, background jobs, serves the bundled web UI
  cli.py        Typer CLI
web/            Next.js static export (local app + public demo)
vscode-extension/
```

## Decisions

**Local runtimes only.** The model client speaks Ollama's API and the OpenAI-compatible API that LM Studio and llama.cpp expose. There is no cloud provider in the codebase, so the privacy promise is enforced by absence rather than configuration.

**Make small models dependable instead of trusting them.** Context size is set explicitly (Ollama's default of a few thousand tokens silently truncates prompts). Every structured output is requested with a JSON schema, validated with Pydantic and retried with the validation error. Review findings must cite a line inside a changed hunk (±3) or they are dropped; answers may only cite context blocks that were supplied. Edits use search/replace blocks rather than unified diffs because small models quote code far more reliably than they compute hunk headers; RepoPilot produces the diff itself.

**Deterministic first.** Mechanical/behavior classification, blast radius, history mining and checks need no model. A Python file whose syntax tree is unchanged is formatting by definition; a rename counts only when the old name disappears from the file and the new name is genuinely new (`return total` → `return subtotal` is a behavior change).

**History is the differentiator.** Co-change uses commits that touch ≤50 files (bulk reformatting is ignored); `confidence = together / commits touching the file`. Fix detection excludes tooling chores ("fix mypy", "fix typo"). Author names honour `.mailmap`. Blast-radius risk is a points score relative to the repository: recent fixes (0–2) + how imported the file is compared with the rest of the repo (0–2) + a strongly coupled file missing from the change (0 or 2).

**Storage.** One SQLite file per repository (WAL) holds files, chunks with an FTS5 index, float16 vectors, symbols, imports, commits, PR links, review comments and saved reviews. Vector search is brute-force cosine in NumPy over a cached matrix — simple, dependency-light and fast enough for hundreds of thousands of chunks. (The original plan named ChromaDB; it was dropped to avoid its dependency weight and telemetry.)

**Never touch the working tree.** Checks, verified edits, night-shift tests and benchmark replays all run in `git worktree`s under `~/.repopilot/worktrees` that are removed afterwards. Applying an edit is an explicit action and fails with a conflict if the target files changed in the meantime.

**Retrieval.** Hybrid: vector top-20 + FTS5 top-20 fused with Reciprocal Rank Fusion (k=60). The refusal threshold is calibrated per repository from "where is <symbol> defined" queries; a question with no keyword hits and a vector score below it is answered with "I couldn't find this in the repository."
