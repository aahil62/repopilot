"""Review history: precedent index (fix commits + review comments) and optional GitHub PR comment import.

The GitHub import is the only network call RepoPilot makes besides your model runtime, and it is off
unless REPOPILOT_ALLOW_GITHUB_IMPORT=1. It talks only to api.github.com.
"""

from __future__ import annotations

import os
import re

import httpx

from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import Runtime

PRECEDENTS = "precedents"
GITHUB_REMOTE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$")
MAX_PRS = 300


def github_slug(remote: str | None) -> tuple[str, str] | None:
    if not remote:
        return None
    m = GITHUB_REMOTE.search(remote.strip())
    return (m.group(1), m.group(2)) if m else None


async def import_github_reviews(
    store: MemoryStore, owner: str, repo: str, http: httpx.AsyncClient | None = None
) -> int:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    owned = http is None
    http = http or httpx.AsyncClient(base_url="https://api.github.com", timeout=30)
    rows: list[tuple] = []
    partial = False
    try:
        prs: list[dict] = []
        page = 1
        while len(prs) < MAX_PRS:
            resp = await http.get(
                f"/repos/{owner}/{repo}/pulls",
                params={"state": "closed", "per_page": 100, "page": page},
                headers=headers,
            )
            if resp.status_code in (403, 429):
                partial = True
                break
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            prs += [p for p in batch if p.get("merged_at")]
            page += 1
        for pr in prs[:MAX_PRS]:
            number = pr["number"]
            for kind in ("comments", "reviews"):
                resp = await http.get(
                    f"/repos/{owner}/{repo}/pulls/{number}/{kind}", params={"per_page": 100}, headers=headers
                )
                if resp.status_code in (403, 429):
                    partial = True
                    break
                resp.raise_for_status()
                for item in resp.json():
                    body = (item.get("body") or "").strip()
                    if not body:
                        continue
                    rows.append(
                        (
                            f"gh:{kind}:{item['id']}",
                            "github",
                            number,
                            item.get("path"),
                            item.get("original_line") or item.get("line"),
                            body[:4000],
                            (item.get("user") or {}).get("login"),
                            item.get("created_at") or item.get("submitted_at"),
                            item.get("state"),
                        )
                    )
            if partial:
                break
    finally:
        if owned:
            await http.aclose()
    with store.transaction():
        store.executemany(
            "INSERT OR REPLACE INTO review_comments(id,source,pr_number,path,line,body,author,date,verdict) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            rows,
        )
    store.set_meta("reviews_partial", "1" if partial else "0")
    return len(rows)


def _precedent_texts(store: MemoryStore) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for c in store.query("SELECT sha, subject, body FROM commits WHERE is_fix = 1"):
        files = [
            r["path"] for r in store.query("SELECT path FROM commit_files WHERE sha=? LIMIT 8", (c["sha"],))
        ]
        items.append((f"commit:{c['sha']}", f"{c['subject']}\n{c['body'][:600]}\nfiles: {' '.join(files)}"))
    for r in store.query("SELECT id, path, body FROM review_comments"):
        items.append((f"review:{r['id']}", f"{r['path'] or ''}\n{r['body'][:1200]}"))
    return items


async def index_precedents(store: MemoryStore, runtime: Runtime, batch: int = 64) -> int:
    items = _precedent_texts(store)
    current = {k for k, _ in items}
    stale = [
        r["key"]
        for r in store.query("SELECT key FROM vectors WHERE collection=?", (PRECEDENTS,))
        if r["key"] not in current
    ]
    store.delete_vectors(stale)
    missing = set(store.missing_vector_keys(PRECEDENTS, [k for k, _ in items]))
    todo = [(k, t) for k, t in items if k in missing]
    for start in range(0, len(todo), batch):
        group = todo[start : start + batch]
        vectors = await runtime.embed([t for _, t in group])
        store.put_vectors(PRECEDENTS, [(k, v) for (k, _), v in zip(group, vectors, strict=True)])
    return len(todo)
