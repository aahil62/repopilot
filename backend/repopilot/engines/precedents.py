"""Find past review comments and bug fixes that resemble a change."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from repopilot.engines.diffparse import FileDiff, Hunk
from repopilot.memory.history import pr_for_commit
from repopilot.memory.reviews import PRECEDENTS
from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import Runtime

MAX_QUERIES = 12


class Precedent(BaseModel):
    kind: Literal["review_comment", "fix_commit"]
    ref: str  # "PR #412" or short sha
    sha: str | None = None
    path: str | None = None
    excerpt: str
    similarity: float


def _describe(store: MemoryStore, key: str, score: float) -> Precedent | None:
    kind, _, ident = key.partition(":")
    if kind == "commit":
        row = store.one("SELECT sha, subject FROM commits WHERE sha=?", (ident,))
        if not row:
            return None
        pr = pr_for_commit(store, row["sha"])
        path = store.one("SELECT path FROM commit_files WHERE sha=? LIMIT 1", (row["sha"],))
        return Precedent(
            kind="fix_commit",
            ref=f"PR #{pr}" if pr else row["sha"][:8],
            sha=row["sha"],
            path=path["path"] if path else None,
            excerpt=row["subject"],
            similarity=round(score, 3),
        )
    if kind == "review":
        row = store.one("SELECT pr_number, path, body FROM review_comments WHERE id=?", (ident,))
        if not row:
            return None
        return Precedent(
            kind="review_comment",
            ref=f"PR #{row['pr_number']}" if row["pr_number"] else "review",
            path=row["path"],
            excerpt=row["body"][:280],
            similarity=round(score, 3),
        )
    return None


async def find_precedents(
    store: MemoryStore,
    runtime: Runtime,
    hunks: list[tuple[FileDiff, Hunk]],
    *,
    k: int = 3,
    min_similarity: float = 0.7,
) -> list[Precedent]:
    if not hunks or store.one("SELECT count(*) n FROM vectors WHERE collection=?", (PRECEDENTS,))["n"] == 0:
        return []
    queries = [f"{fd.path}\n" + "\n".join(h.added + h.removed)[:1500] for fd, h in hunks[:MAX_QUERIES]]
    vectors = await runtime.embed(queries)
    best: dict[str, float] = {}
    for vec in vectors:
        for key, score in store.search(PRECEDENTS, vec, k=k):
            if score >= min_similarity and score > best.get(key, 0):
                best[key] = score
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[: k * 2]
    return [p for key, score in ranked if (p := _describe(store, key, score))]
