"""Git history memory: commits, touched files, fix detection, PR links and co-change statistics."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from repopilot.memory.store import MemoryStore

FIX_RE = re.compile(r"(?i)\b(fix|fixes|fixed|bug|bugs|hotfix|regression|revert|crash|broken)\b")
# Tooling chores mention "fix" but are not bug fixes.
CHORE_RE = re.compile(
    r"(?i)\b(typos?|lint|linting|mypy|pyright|flake8|ruff|pre-commit|formatting|typing|type hints?|type errors?|"
    r"docs?|documentation|readme|changelog|ci|deprecation warnings?|spelling)\b"
)
FIX_RULE_VERSION = "2"
SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
MERGE_PR_RE = re.compile(r"Merge pull request #(\d+)")
BULK_COMMIT_FILES = 50
RS, US = "\x1e", "\x1f"


def _git(repo: Path, *args: str, timeout: int = 300) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    ).stdout


def is_fix(subject: str, body: str = "") -> bool:
    return bool(FIX_RE.search(f"{subject}\n{body}")) and not CHORE_RE.search(subject)


def rescore_fixes(store: MemoryStore) -> None:
    """Re-apply the fix rule to already-imported commits when the rule changes."""
    if store.get_meta("fix_rule_version") == FIX_RULE_VERSION:
        return
    rows = store.query("SELECT sha, subject, body FROM commits")
    with store.transaction():
        store.executemany(
            "UPDATE commits SET is_fix=? WHERE sha=?",
            [(int(is_fix(r["subject"], r["body"])), r["sha"]) for r in rows],
        )
    store.set_meta("fix_rule_version", FIX_RULE_VERSION)


def parse_log(raw: str) -> list[dict]:
    commits = []
    for record in raw.split(RS):
        if not record.strip():
            continue
        head, _, numstat = record.partition(f"{US}END{US}")
        sha, author, email, date, subject, body = (head.split(US) + [""] * 6)[:6]
        files = []
        for line in numstat.strip().splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            files.append(
                (path, None if added == "-" else int(added), None if deleted == "-" else int(deleted))
            )
        commits.append(
            {
                "sha": sha.strip(),
                "author": author,
                "email": email,
                "date": date,
                "subject": subject,
                "body": body.strip(),
                "files": files,
            }
        )
    return commits


def head_sha(repo: Path) -> str | None:
    try:
        return _git(repo, "rev-parse", "HEAD").strip()
    except subprocess.CalledProcessError:
        return None


def import_history(store: MemoryStore, repo: Path, max_commits: int) -> int:
    """Import non-merge commits newest-first, incrementally, up to `max_commits` in total."""
    if head_sha(repo) is None:
        return 0
    newest = store.get_meta("history_head")
    rev_range = f"{newest}..HEAD" if newest else "HEAD"
    have = store.one("SELECT count(*) n FROM commits")["n"]
    budget = max(0, max_commits - have)
    if budget == 0:
        store.set_meta("history_truncated", "1")
        return 0
    fmt = f"{RS}%H{US}%an{US}%ae{US}%aI{US}%s{US}%b{US}END{US}"
    try:
        raw = _git(
            repo,
            "log",
            "--no-merges",
            "--no-renames",
            "--numstat",
            f"--max-count={budget}",
            f"--format={fmt}",
            rev_range,
        )
    except subprocess.CalledProcessError:
        raw = _git(
            repo,
            "log",
            "--no-merges",
            "--no-renames",
            "--numstat",
            f"--max-count={budget}",
            f"--format={fmt}",
            "HEAD",
        )
    commits = parse_log(raw)
    total_available = int(_git(repo, "rev-list", "--no-merges", "--count", "HEAD").strip() or 0)
    with store.transaction():
        for c in commits:
            try:
                seq = int(datetime.fromisoformat(c["date"]).timestamp())
            except ValueError:
                seq = 0
            inserted = store.execute(
                "INSERT OR IGNORE INTO commits(sha,author,email,date,subject,body,is_fix,seq) VALUES(?,?,?,?,?,?,?,?)",
                (
                    c["sha"],
                    c["author"],
                    c["email"],
                    c["date"],
                    c["subject"],
                    c["body"],
                    int(is_fix(c["subject"], c["body"])),
                    seq,
                ),
            )
            if not inserted.rowcount:
                continue  # already imported (e.g. history rewritten and re-read from HEAD)
            store.executemany(
                "INSERT INTO commit_files(sha,path,added,deleted) VALUES(?,?,?,?)",
                [(c["sha"], p, a, d) for p, a, d in c["files"]],
            )
            if m := SQUASH_PR_RE.search(c["subject"]):
                store.execute(
                    "INSERT INTO pr_commits(pr_number,sha) VALUES(?,?)", (int(m.group(1)), c["sha"])
                )
    _import_merge_prs(store, repo, rev_range)
    rescore_fixes(store)
    store.set_meta("history_head", head_sha(repo) or "")
    imported = store.one("SELECT count(*) n FROM commits")["n"]
    store.set_meta("history_truncated", "1" if total_available > imported else "0")
    return len(commits)


def _import_merge_prs(store: MemoryStore, repo: Path, rev_range: str) -> None:
    try:
        merges = _git(repo, "log", "--merges", f"--format=%H{US}%s", rev_range)
    except subprocess.CalledProcessError:
        return
    rows = []
    for line in merges.splitlines():
        sha, _, subject = line.partition(US)
        m = MERGE_PR_RE.search(subject)
        if not m:
            continue
        try:
            members = _git(repo, "rev-list", "--no-merges", f"{sha}^1..{sha}^2").split()
        except subprocess.CalledProcessError:
            continue
        rows += [(int(m.group(1)), member) for member in members]
    if rows:
        with store.transaction():
            store.executemany("INSERT INTO pr_commits(pr_number,sha) VALUES(?,?)", rows)


def _non_bulk_commits_for(store: MemoryStore, path: str) -> list[str]:
    return [
        r["sha"]
        for r in store.query(
            "SELECT cf.sha FROM commit_files cf WHERE cf.path=? AND "
            "(SELECT count(*) FROM commit_files x WHERE x.sha=cf.sha) <= ?",
            (path, BULK_COMMIT_FILES),
        )
    ]


def cochange(store: MemoryStore, path: str, min_support: int = 3, top: int = 15) -> list[dict]:
    shas = _non_bulk_commits_for(store, path)
    if not shas:
        return []
    marks = ",".join("?" * len(shas))
    rows = store.query(
        f"SELECT path, count(DISTINCT sha) support FROM commit_files WHERE sha IN ({marks}) AND path != ? "
        "GROUP BY path HAVING support >= ? ORDER BY support DESC, path LIMIT ?",
        (*shas, path, min_support, top),
    )
    total = len(set(shas))
    return [
        {"path": r["path"], "support": r["support"], "confidence": round(r["support"] / total, 3)}
        for r in rows
    ]


def commits_touching(
    store: MemoryStore, paths: list[str], *, fixes_only: bool = False, limit: int = 10
) -> list[dict]:
    if not paths:
        return []
    marks = ",".join("?" * len(paths))
    fix_clause = "AND c.is_fix = 1" if fixes_only else ""
    rows = store.query(
        f"SELECT DISTINCT c.sha, c.date, c.subject, c.author FROM commits c JOIN commit_files f ON f.sha = c.sha "
        f"WHERE f.path IN ({marks}) {fix_clause} ORDER BY c.seq DESC LIMIT ?",
        (*paths, limit),
    )
    return [dict(r) for r in rows]


def pr_for_commit(store: MemoryStore, sha: str) -> int | None:
    row = store.one("SELECT pr_number FROM pr_commits WHERE sha=? LIMIT 1", (sha,))
    return row["pr_number"] if row else None
