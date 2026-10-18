"""Blast radius: what usually changes, breaks or needs review together with a set of files."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from repopilot.memory.codegraph import dependents, load_graph
from repopilot.memory.history import cochange, commits_touching
from repopilot.memory.store import MemoryStore

TEST_FILE = re.compile(r"(^|/)(test_[^/]+|[^/]+_test\.[a-z]+|[^/]+\.(test|spec)\.[a-z]+)$|(^|/)tests?/")


class CoChange(BaseModel):
    path: str
    support: int
    confidence: float


class Dependent(BaseModel):
    path: str
    depth: int


class PastFix(BaseModel):
    sha: str
    date: str
    subject: str
    author: str


class Owner(BaseModel):
    author: str
    commits: int


class BlastReport(BaseModel):
    targets: list[str]
    cochanged: list[CoChange]
    dependents: list[Dependent]
    past_fixes: list[PastFix]
    tests: list[str]
    owners: list[Owner]
    risk: Literal["low", "medium", "high"]
    risk_reasons: list[str]


def is_test_file(path: str) -> bool:
    return bool(TEST_FILE.search(path))


def _latest_commit_date(store: MemoryStore) -> datetime | None:
    row = store.one("SELECT date FROM commits ORDER BY seq DESC LIMIT 1")
    return datetime.fromisoformat(row["date"]) if row else None


def _owners(store: MemoryStore, paths: list[str], since: str | None) -> list[Owner]:
    if not paths:
        return []
    marks = ",".join("?" * len(paths))
    clause = "AND c.date >= ?" if since else ""
    params = (*paths, since) if since else tuple(paths)
    rows = store.query(
        f"SELECT c.author, count(DISTINCT c.sha) n FROM commits c JOIN commit_files f ON f.sha=c.sha "
        f"WHERE f.path IN ({marks}) {clause} GROUP BY c.author ORDER BY n DESC, c.author LIMIT 3",
        params,
    )
    return [Owner(author=r["author"], commits=r["n"]) for r in rows]


def blast_radius(repo_id: str, paths: list[str]) -> BlastReport:
    store = MemoryStore.open(repo_id)
    targets = list(dict.fromkeys(p.strip("/") for p in paths if p.strip()))
    target_set = set(targets)
    existing = {r["path"] for r in store.query("SELECT path FROM files")}

    best: dict[str, CoChange] = {}
    for target in targets:
        for row in cochange(store, target):
            if row["path"] in target_set:
                continue
            if row["path"] not in best or row["confidence"] > best[row["path"]].confidence:
                best[row["path"]] = CoChange(**row)
    cochanged = sorted(best.values(), key=lambda c: (-c.confidence, -c.support, c.path))[:15]

    graph = load_graph(store)
    dep_depth: dict[str, int] = {}
    for target in targets:
        for path, depth in dependents(graph, target, depth=2):
            if path not in target_set:
                dep_depth[path] = min(depth, dep_depth.get(path, depth))
    deps = [Dependent(path=p, depth=d) for p, d in sorted(dep_depth.items(), key=lambda x: (x[1], x[0]))]

    latest = _latest_commit_date(store)
    since = (latest - timedelta(days=365)).isoformat() if latest else None
    fixes = [PastFix(**c) for c in commits_touching(store, targets, fixes_only=True, limit=10)]
    recent_fixes = [f for f in fixes if since is None or f.date >= since]

    tests = sorted(
        {d.path for d in deps if is_test_file(d.path)}
        | {c.path for c in cochanged if is_test_file(c.path) and c.path in existing}
        | {t for t in targets if is_test_file(t)}
    )

    reasons: list[str] = []
    if len(recent_fixes) >= 3:
        reasons.append(f"{len(recent_fixes)} bug fixes touched these files in the last 12 months of history.")
    if len(deps) >= 10:
        reasons.append(f"{len(deps)} files depend on these files directly or through one other file.")
    high = bool(reasons)
    if not high:
        if recent_fixes:
            s = "es" if len(recent_fixes) > 1 else ""
            reasons.append(
                f"{len(recent_fixes)} bug fix{s} touched these files recently: “{recent_fixes[0].subject}”."
            )
        if len(deps) >= 3:
            reasons.append(f"{len(deps)} files depend on these files.")
    for c in cochanged:
        if c.confidence >= 0.6 and c.path in existing:
            source = next(
                (t for t in targets if any(r["path"] == c.path for r in cochange(store, t))), targets[0]
            )
            reasons.append(
                f"`{source}` usually changes together with `{c.path}` ({round(c.confidence * 100)}% of the time)"
                " — it is not in this change."
            )
            break
    risk: Literal["low", "medium", "high"] = "high" if high else ("medium" if reasons else "low")
    if risk == "low":
        reasons.append("No past fixes, few dependents and no strongly coupled files missing from the change.")

    return BlastReport(
        targets=targets,
        cochanged=cochanged,
        dependents=deps,
        past_fixes=fixes,
        tests=tests,
        owners=_owners(store, targets, since),
        risk=risk,
        risk_reasons=reasons,
    )
