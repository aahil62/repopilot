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


def _recent_fix_count(store: MemoryStore, paths: list[str], since: str | None) -> int:
    if not paths:
        return 0
    marks = ",".join("?" * len(paths))
    clause = "AND c.date >= ?" if since else ""
    params = (*paths, since) if since else tuple(paths)
    row = store.one(
        f"SELECT count(DISTINCT c.sha) n FROM commits c JOIN commit_files f ON f.sha=c.sha "
        f"WHERE c.is_fix = 1 AND f.path IN ({marks}) {clause}",
        params,
    )
    return row["n"] if row else 0


def _in_degree_percentile(graph, targets: list[str]) -> float:
    """Share of the repository's files that are imported by fewer files than the most-imported target."""
    counts: dict[str, int] = {node["path"]: 0 for node in graph.nodes}
    for edge in graph.edges:
        counts[edge["target"]] = counts.get(edge["target"], 0) + 1
    mine = max((counts.get(t, 0) for t in targets), default=0)
    if mine == 0 or not counts:
        return 0.0
    return sum(1 for v in counts.values() if v < mine) / len(counts)


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

    # Risk is a points score so it stays meaningful in large repositories, where core files always have
    # many dependents: fixes (0-2) + how central the file is relative to this repo (0-2) + a coupled file
    # missing from the change (0 or 2: the most actionable signal). high >= 4, medium >= 2.
    recent_count = _recent_fix_count(store, targets, since)
    centrality = _in_degree_percentile(graph, targets)
    direct = sum(1 for d in deps if d.depth == 1)
    reasons: list[str] = []
    points = 0
    if recent_count >= 3:
        points += 2
        reasons.append(f"{recent_count} bug fixes touched these files in the last 12 months of history.")
    elif recent_count:
        points += 1
        s = "es" if recent_count > 1 else ""
        reasons.append(
            f"{recent_count} bug fix{s} touched these files recently: \u201c{recent_fixes[0].subject}\u201d."
        )
    if direct >= 5 and centrality >= 0.9:
        points += 2
        reasons.append(
            f"Among the most imported files in this repository: {direct} files import it directly, {len(deps)} in total."
        )
    elif direct >= 3 and centrality >= 0.7:
        points += 1
        reasons.append(f"{direct} files import it directly.")
    for c in cochanged:
        if c.confidence >= 0.6 and c.path in existing:
            source = next(
                (t for t in targets if any(r["path"] == c.path for r in cochange(store, t))), targets[0]
            )
            points += 2
            reasons.append(
                f"`{source}` usually changes together with `{c.path}` ({round(c.confidence * 100)}% of the time)"
                " \u2014 it is not in this change."
            )
            break
    risk: Literal["low", "medium", "high"] = "high" if points >= 4 else "medium" if points >= 2 else "low"
    if not reasons:
        reasons.append(
            "No recent fixes, few dependents and no strongly coupled files missing from the change."
        )

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
