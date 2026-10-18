"""Full indexing pipeline: code -> import graph -> git history -> precedents."""

from __future__ import annotations

import json
from pathlib import Path

from repopilot.config import get_settings
from repopilot.memory.codegraph import build_graph
from repopilot.memory.history import import_history
from repopilot.memory.indexer import IndexProgress, IndexStats, ProgressFn, index_code
from repopilot.memory.registry import RepoRecord
from repopilot.memory.reviews import github_slug, import_github_reviews, index_precedents
from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import Runtime


async def index_repo(
    record: RepoRecord,
    runtime: Runtime | None,
    progress: ProgressFn | None = None,
    *,
    with_reviews: bool = False,
) -> IndexStats:
    settings = get_settings()
    report = progress or (lambda _p: None)
    store = MemoryStore.open(record.repo_id)
    repo_path = Path(record.path)

    stats = await index_code(store, repo_path, runtime, report)

    report(IndexProgress("graph", message="Resolving imports"))
    stats.graph_edges = len(build_graph(store).edges)

    report(IndexProgress("history", message="Reading git history"))
    stats.commits_imported = import_history(store, repo_path, settings.history_max_commits)
    if store.get_meta("history_truncated") == "1":
        stats.notes.append(f"History limited to the newest {settings.history_max_commits:,} commits.")

    if with_reviews and settings.allow_github_import and (slug := github_slug(record.remote)):
        report(IndexProgress("history", message="Importing GitHub review comments"))
        await import_github_reviews(store, *slug)
        if store.get_meta("reviews_partial") == "1":
            stats.notes.append("GitHub review import stopped early (rate limit).")
    if runtime is not None:
        await index_precedents(store, runtime)

    store.set_meta("last_index_stats", json.dumps(stats.to_dict()))
    report(IndexProgress("done", message="Ready"))
    return stats


def repo_summary(record: RepoRecord) -> dict:
    store = MemoryStore.open(record.repo_id)
    count = lambda sql: store.one(sql)["n"]  # noqa: E731
    last = store.get_meta("last_index_stats")
    return {
        **record.to_dict(),
        "files": count("SELECT count(*) n FROM files"),
        "chunks": count("SELECT count(*) n FROM chunks"),
        "commits": count("SELECT count(*) n FROM commits"),
        "review_comments": count("SELECT count(*) n FROM review_comments"),
        "indexed_at": store.get_meta("indexed_at"),
        "history_truncated": store.get_meta("history_truncated") == "1",
        "last_index": json.loads(last) if last else None,
    }
