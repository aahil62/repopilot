# Changelog

## 2.0.0 — rebuild

- Local-only model runtime layer: Ollama, LM Studio, llama.cpp; hardware-aware role assignment; schema-validated outputs with retries. All cloud providers removed.
- Repository memory: incremental symbol-aware index (SQLite + FTS5 + vectors), import graph, git history with co-change, fix detection and PR links, optional GitHub review-comment import.
- History-aware review: mechanical vs behavior hunks, blast radius, precedents, tests in temporary worktrees, findings verified against changed lines.
- Blast radius, night shift, repository-specific model benchmark, verified edits, grounded Q&A with checked citations.
- Works without a model for indexing, blast radius, classification and checks.
- New web app (local + static demo), new VS Code extension, CLI, evaluation harness, CI.
- GitHub Action (`aahil62/repopilot@v2.0.0`), pre-push hook, Markdown report and `--fail-on` gate.
- JavaScript/TypeScript mechanical detection on tree-sitter syntax trees; multi-file verified edits guarded against concurrent changes.
- Measured on real local models (qwen2.5-coder 7B/1.5B): planted bugs caught 70%, correct fixes flagged high 0%, hybrid retrieval 88–96%, Django-scale indexing. See `docs/VERIFICATION.md`.

## 1.x — AlphaByte 3.0 hackathon

Preserved in tags `archive/hackathon-main` and `archive/hackathon-website`.
