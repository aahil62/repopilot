"""Night shift: while you sleep, review each new commit, write verified tests on a separate branch,
and list documentation that mentions code that no longer exists. Free to run because models are local."""

from __future__ import annotations

import asyncio
import json
import platform
import re
import subprocess
import time
import uuid
from datetime import date as Date
from pathlib import Path

from pydantic import BaseModel, Field

from repopilot import __version__
from repopilot.config import get_settings
from repopilot.engines.blast import is_test_file
from repopilot.engines.checks import run_checks
from repopilot.engines.diffparse import DiffSource, commit_diff, parse
from repopilot.engines.edit import WHOLE_FILE_MAX_LINES, verified_edit
from repopilot.engines.review import Finding, review
from repopilot.memory.codegraph import build_graph
from repopilot.memory.history import import_history
from repopilot.memory.indexer import index_code
from repopilot.memory.registry import RepoRecord
from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import Runtime

FIRST_RUN_COMMITS = 10
MAX_TESTS_PER_RUN = 5
DEF_RE = re.compile(
    r"^\s*(?:async\s+)?(?:def|class|function)\s+([A-Za-z_][\w]*)|^\s*export\s+(?:const|function|class)\s+([A-Za-z_$][\w$]*)"
)


class CommitReview(BaseModel):
    sha: str
    subject: str
    findings: list[Finding]
    behavior_hunks: int


class TestWritten(BaseModel):
    symbol: str
    source_path: str
    test_path: str
    branch: str | None
    status: str
    attempts: int


class StaleDoc(BaseModel):
    doc_path: str
    line: int
    symbol: str
    commit: str


class NightReport(BaseModel):
    date: str
    repo_id: str
    commits_reviewed: list[CommitReview] = Field(default_factory=list)
    tests_written: list[TestWritten] = Field(default_factory=list)
    stale_docs: list[StaleDoc] = Field(default_factory=list)
    model: dict[str, str] = Field(default_factory=dict)
    duration_s: float = 0.0
    notes: list[str] = Field(default_factory=list)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check, timeout=600)


def _reports_dir(repo_id: str) -> Path:
    path = get_settings().repo_dir(repo_id) / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(repo_id: str) -> Path:
    return get_settings().repo_dir(repo_id) / "nightshift.json"


def new_commits(store: MemoryStore, last_sha: str | None) -> list[dict]:
    if last_sha:
        row = store.one("SELECT seq FROM commits WHERE sha=?", (last_sha,))
        if row:
            rows = store.query(
                "SELECT sha, subject FROM commits WHERE seq > ? ORDER BY seq ASC", (row["seq"],)
            )
            return [dict(r) for r in rows if r["sha"] != last_sha]
    rows = store.query("SELECT sha, subject FROM commits ORDER BY seq DESC LIMIT ?", (FIRST_RUN_COMMITS,))
    return [dict(r) for r in reversed(rows)]


def _changed_symbols(store: MemoryStore, repo: Path, shas: list[str]) -> list[tuple[str, str]]:
    """(symbol, source_path) for functions/classes in files changed by these commits that no test mentions."""
    paths: list[str] = []
    for sha in shas:
        paths += [r["path"] for r in store.query("SELECT path FROM commit_files WHERE sha=?", (sha,))]
    paths = [p for p in dict.fromkeys(paths) if p.endswith((".py", ".js", ".ts")) and not is_test_file(p)]
    test_text = ""
    for row in store.query("SELECT path FROM files"):
        if is_test_file(row["path"]) and (repo / row["path"]).exists():
            test_text += (repo / row["path"]).read_text(errors="replace")
    out = []
    for path in paths:
        for sym in store.query(
            "SELECT name FROM symbols WHERE path=? AND kind IN ('function','class') ORDER BY start_line",
            (path,),
        ):
            name = sym["name"]
            if name.startswith("_"):
                continue
            if not re.search(rf"\b{re.escape(name)}\b", test_text):
                out.append((name, path))
    return out


def _test_path_for(repo: Path, source_path: str, symbol: str) -> str:
    """The usual test file for `source_path`; a file of its own when the usual one is too long to rewrite."""
    stem = Path(source_path).stem
    if source_path.endswith(".py"):
        base = "tests" if (repo / "tests").is_dir() else ""
        path = f"{base}/test_{stem}.py".lstrip("/")
        own = f"{base}/test_{stem}_{re.sub(r'[^0-9a-zA-Z_]', '_', symbol).lower()}.py".lstrip("/")
    else:
        suffix = Path(source_path).suffix
        path = str(Path(source_path).with_name(f"{stem}.test{suffix}"))
        own = str(Path(source_path).with_name(f"{stem}.{symbol}.test{suffix}"))
    existing = repo / path
    if existing.is_file() and len(existing.read_text(errors="replace").splitlines()) > WHOLE_FILE_MAX_LINES:
        return own
    return path


def _removed_names(repo: Path, shas: list[str], store: MemoryStore) -> list[tuple[str, str]]:
    existing = {r["name"].split(".")[-1] for r in store.query("SELECT name FROM symbols")}
    removed: list[tuple[str, str]] = []
    for sha in shas:
        for fd in parse(commit_diff(repo, sha)):
            for h in fd.hunks:
                for line in h.removed:
                    m = DEF_RE.match(line)
                    name = m and (m.group(1) or m.group(2))
                    if name and name not in existing and len(name) > 3:
                        removed.append((name, sha))
    return list(dict.fromkeys(removed))


def _stale_docs(store: MemoryStore, repo: Path, removed: list[tuple[str, str]]) -> list[StaleDoc]:
    docs = [r["path"] for r in store.query("SELECT path FROM files WHERE language='markdown'")]
    out = []
    for doc in docs:
        target = repo / doc
        if not target.exists():
            continue
        for number, line in enumerate(target.read_text(errors="replace").splitlines(), start=1):
            for name, sha in removed:
                if re.search(rf"\b{re.escape(name)}\b", line):
                    out.append(StaleDoc(doc_path=doc, line=number, symbol=name, commit=sha[:8]))
    return out


def _commit_to_branch(repo: Path, branch: str, diff: str, message: str) -> None:
    path = get_settings().worktrees_dir / f"nightshift-{uuid.uuid4().hex[:10]}"
    exists = (
        _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
    )
    args = (
        ["worktree", "add", str(path), branch]
        if exists
        else ["worktree", "add", "-b", branch, str(path), "HEAD"]
    )
    _git(repo, *args)
    try:
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=path,
            input=diff,
            text=True,
            capture_output=True,
            check=True,
        )
        _git(path, "add", "-A")
        _git(
            path,
            "-c",
            "user.name=RepoPilot",
            "-c",
            "user.email=repopilot@localhost",
            "commit",
            "-q",
            "-m",
            message,
        )
    finally:
        _git(repo, "worktree", "remove", "--force", str(path), check=False)


def _markdown(report: NightReport) -> str:
    lines = [f"# RepoPilot night shift — {report.date}", ""]
    lines.append(
        f"Reviewed {len(report.commits_reviewed)} commit(s); wrote {sum(t.status == 'verified' for t in report.tests_written)} verified test(s); "
        f"found {len(report.stale_docs)} stale doc reference(s)."
    )
    for c in report.commits_reviewed:
        lines += ["", f"## {c.sha[:8]} {c.subject}"]
        lines += [f"- **{f.severity}** `{f.path}:{f.line}` {f.title}" for f in c.findings] or [
            "- No findings."
        ]
    if report.tests_written:
        lines += ["", "## Tests"]
        lines += [
            f"- `{t.symbol}` → `{t.test_path}` ({t.status}{', branch ' + t.branch if t.branch else ''})"
            for t in report.tests_written
        ]
    if report.stale_docs:
        lines += ["", "## Stale docs"]
        lines += [
            f"- `{d.doc_path}:{d.line}` mentions `{d.symbol}` (removed in {d.commit})"
            for d in report.stale_docs
        ]
    return "\n".join(lines) + "\n"


async def run_nightshift(
    record: RepoRecord,
    runtime: Runtime,
    *,
    max_commits: int = 20,
    write_tests: bool = True,
    max_tests: int = MAX_TESTS_PER_RUN,
    today: str | None = None,
) -> NightReport:
    started = time.perf_counter()
    repo = Path(record.path)
    store = MemoryStore.open(record.repo_id)
    await index_code(store, repo, runtime)
    build_graph(store)
    import_history(store, repo, get_settings().history_max_commits)

    state_path = _state_path(record.repo_id)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    commits = new_commits(store, state.get("last_sha"))[-max_commits:]
    report = NightReport(
        date=today or Date.today().isoformat(),
        repo_id=record.repo_id,
        model={k: v.id for k, v in runtime.roles.items()},
    )
    if not commits:
        report.notes.append("No new commits since the last run.")

    for c in commits:
        diff = commit_diff(repo, c["sha"])
        if not diff.strip():
            continue
        result = await review(
            record.repo_id,
            repo,
            diff,
            runtime,
            source=DiffSource("commit", head=c["sha"]),
            run_checks_enabled=False,
            persist=False,
        )
        report.commits_reviewed.append(
            CommitReview(
                sha=c["sha"],
                subject=c["subject"],
                behavior_hunks=result.behavior_count,
                findings=[f for f in result.findings if f.severity in ("high", "medium")],
            )
        )

    if write_tests and commits:
        # New tests are judged by the whole suite passing, so a suite that is already red would
        # reject correct tests. Say so instead of spending model attempts.
        baseline = await asyncio.to_thread(run_checks, repo, None, ref="HEAD")
        if baseline.status == "failed":
            write_tests = False
            report.notes.append(
                f"Tests already fail on HEAD (`{baseline.command}`), so no tests were written. "
                "Fix the failing tests and the next run will write tests for new code."
            )
    if write_tests and commits:
        branch = f"repopilot/nightshift-{report.date}"
        for symbol, source_path in _changed_symbols(store, repo, [c["sha"] for c in commits])[:max_tests]:
            test_path = _test_path_for(repo, source_path, symbol)
            result = await verified_edit(
                record.repo_id,
                repo,
                runtime,
                f"Write focused unit tests for `{symbol}` in `{source_path}`. Put them in `{test_path}`, following the "
                "style of the existing tests. Do not change the source file.",
                [test_path],
                context_paths=[source_path],
                restrict_to_targets=True,
            )
            committed = result.status == "verified"
            if committed:
                _commit_to_branch(
                    repo, branch, result.diff, f"test: add tests for {symbol} (RepoPilot night shift)"
                )
            report.tests_written.append(
                TestWritten(
                    symbol=symbol,
                    source_path=source_path,
                    test_path=test_path,
                    branch=branch if committed else None,
                    status=result.status,
                    attempts=len(result.attempts),
                )
            )

    report.stale_docs = _stale_docs(store, repo, _removed_names(repo, [c["sha"] for c in commits], store))
    report.duration_s = round(time.perf_counter() - started, 2)
    out = _reports_dir(record.repo_id)
    (out / f"{report.date}.json").write_text(report.model_dump_json(indent=2))
    (out / f"{report.date}.md").write_text(_markdown(report))
    if commits:
        state_path.write_text(json.dumps({"last_sha": commits[-1]["sha"], "last_run": report.date}))
    return report


def list_reports(repo_id: str) -> list[dict]:
    out = []
    for path in sorted(_reports_dir(repo_id).glob("*.json"), reverse=True):
        data = json.loads(path.read_text())
        out.append(
            {
                "date": data["date"],
                "commits": len(data["commits_reviewed"]),
                "findings": sum(len(c["findings"]) for c in data["commits_reviewed"]),
                "tests_verified": sum(t["status"] == "verified" for t in data["tests_written"]),
                "stale_docs": len(data["stale_docs"]),
            }
        )
    return out


def load_report(repo_id: str, day: str) -> NightReport | None:
    path = _reports_dir(repo_id) / f"{day}.json"
    return NightReport.model_validate_json(path.read_text()) if path.exists() else None


def schedule(repo_path: Path, at: str = "02:00", system: str | None = None) -> dict:
    """Describe (and on macOS write) the daily schedule; never activates it on the user's behalf."""
    hour, minute = (int(x) for x in at.split(":"))
    system = system or platform.system()
    repo_path = repo_path.resolve()
    command = f"repopilot nightshift run --repo {repo_path}"
    if system == "Darwin":
        from repopilot.config import repo_id_for

        label = f"dev.repopilot.nightshift.{repo_id_for(repo_path)}"
        plist = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>-lc</string><string>{command}</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>{minute}</integer></dict>
  <key>StandardOutPath</key><string>/tmp/{label}.log</string>
  <key>StandardErrorPath</key><string>/tmp/{label}.log</string>
</dict></plist>
"""
        return {
            "kind": "launchd",
            "path": str(plist),
            "content": content,
            "activate": f"launchctl load {plist}",
            "version": __version__,
        }
    if system == "Windows":
        return {
            "kind": "schtasks",
            "activate": f'schtasks /Create /SC DAILY /ST {at} /TN RepoPilotNightShift /TR "{command}"',
        }
    return {
        "kind": "cron",
        "content": f"{minute} {hour} * * * {command}",
        "activate": "crontab -e  # add the line above",
    }
