# Changelog

## 2.0.0 — rebuild

- Local-only model runtime layer: Ollama, LM Studio, llama.cpp; hardware-aware role assignment; schema-validated outputs with retries. All cloud providers removed.
- Repository memory: incremental symbol-aware index (SQLite + FTS5 + vectors), import graph, git history with co-change, fix detection and PR links, optional GitHub review-comment import.
- History-aware review: mechanical vs behavior hunks, blast radius, precedents, tests in temporary worktrees, findings verified against changed lines.
- Blast radius, night shift, repository-specific model benchmark, verified edits, grounded Q&A with checked citations.
- Works without a model for indexing, blast radius, classification and checks.
- New web app (local + static demo), new VS Code extension, CLI, evaluation harness, CI.

## 1.x — AlphaByte 3.0 hackathon

Preserved in tags `archive/hackathon-main` and `archive/hackathon-website`.
