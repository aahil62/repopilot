"""Which model should we run? Replay real past commits from this repository and score every installed model."""

from __future__ import annotations

import asyncio
import difflib
import random
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from repopilot.config import get_settings
from repopilot.engines.blast import is_test_file
from repopilot.engines.checks import detect_test_command, run_command
from repopilot.engines.diffparse import commit_diff
from repopilot.engines.edit import SYSTEM as EDIT_SYSTEM
from repopilot.engines.edit import EditProposal, _git_diff, apply_edits
from repopilot.memory.files import language_for
from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import ModelClient, Runtime
from repopilot.runtime.detect import ModelInfo
from repopilot.runtime.hardware import Hardware
from repopilot.runtime.roles import fits
from repopilot.runtime.structured import ModelOutputError, structured_call
from repopilot.worktree import temp_worktree

CODE_LANGS = {
    "python",
    "javascript",
    "typescript",
    "go",
    "rust",
    "java",
    "kotlin",
    "ruby",
    "php",
    "c",
    "cpp",
    "csharp",
    "swift",
    "scala",
    "shell",
}
LATENCY_CAP_S = 60
RECENT_COMMITS = 300  # tasks are sampled from this many newest commits
CLOSE_ENOUGH = 0.75  # a model under the cap must reach this share of the best score


class BenchTask(BaseModel):
    sha: str
    parent: str
    subject: str
    body: str
    paths: list[str]
    real_diff: str


class TaskScore(BaseModel):
    sha: str
    applies: bool
    tests_pass: bool | None
    similarity: float
    latency_s: float
    tokens_per_second: float | None
    score: float
    error: str | None = None


class ModelScore(BaseModel):
    model: str
    size_bytes: int | None
    score: float
    applies_rate: float
    tests_pass_rate: float | None
    similarity: float
    median_latency_s: float
    tokens_per_second: float | None
    tasks: list[TaskScore]


class SkippedModel(BaseModel):
    model: str
    reason: str


class BenchResult(BaseModel):
    created_at: str
    repo_id: str
    tasks: list[BenchTask]
    models: list[ModelScore]
    skipped: list[SkippedModel] = Field(default_factory=list)
    recommendation: str
    recommended_strong: str | None = None
    recommended_fast: str | None = None


def _changed_lines(diff: str) -> list[str]:
    return [
        line
        for line in diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]


def similarity(model_diff: str, real_diff: str) -> float:
    a, b = _changed_lines(model_diff), _changed_lines(real_diff)
    if not a and not b:
        return 1.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def task_score(applies: bool, tests_pass: bool | None, sim: float) -> float:
    if tests_pass is not None:
        return round(0.6 * tests_pass + 0.2 * applies + 0.2 * sim, 3)
    return round(0.5 * applies + 0.5 * sim, 3)


def select_tasks(
    store: MemoryStore, repo: Path, n: int = 10, seed: int = 7, recent: int = RECENT_COMMITS
) -> list[BenchTask]:
    """Sample commits to replay from recent history: old code often no longer builds or tests."""
    candidates = []
    rows = store.query("SELECT sha, subject, body FROM commits ORDER BY seq DESC LIMIT ?", (recent,))
    for c in sorted(rows, key=lambda r: r["sha"]):
        subject = c["subject"]
        if len(subject) < 12 or subject.lower().startswith(("revert", "merge")):
            continue
        files = store.query("SELECT path, added, deleted FROM commit_files WHERE sha=?", (c["sha"],))
        if not files or any(f["added"] is None for f in files):
            continue
        code = [f for f in files if language_for(f["path"]) in CODE_LANGS and not is_test_file(f["path"])]
        if len(code) != len(files) or not 1 <= len(code) <= 2:
            continue
        changed = sum(f["added"] + f["deleted"] for f in files)
        if not 3 <= changed <= 60:
            continue
        candidates.append((c, [f["path"] for f in files]))
    picked = random.Random(seed).sample(candidates, min(n, len(candidates)))
    tasks = []
    for c, paths in picked:
        parent = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{c['sha']}^"],
            cwd=repo,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not parent:  # root commit: nothing to replay from
            continue
        diff = commit_diff(repo, c["sha"])
        tasks.append(
            BenchTask(
                sha=c["sha"], parent=parent, subject=c["subject"], body=c["body"], paths=paths, real_diff=diff
            )
        )
    return tasks


def _context(tree: Path, paths: list[str]) -> str:
    parts = []
    for rel in paths:
        target = tree / rel
        if target.exists():
            parts.append(f"=== {rel} (current content)\n{target.read_text(errors='replace')[:20000]}")
        else:
            parts.append(f"=== {rel} (does not exist yet)")
    return "\n\n".join(parts)


async def _run_task(
    runtime: Runtime, repo: Path, task: BenchTask, test_cmd: str | None, passes_at_commit: bool
) -> TaskScore:
    with temp_worktree(repo, task.parent) as tree:
        messages = [
            {"role": "system", "content": EDIT_SYSTEM},
            {
                "role": "user",
                "content": f"{_context(tree, task.paths)}\n\nInstruction: {task.subject}\n{task.body}",
            },
        ]
        started = time.perf_counter()
        try:
            proposal = await structured_call(
                runtime, "strong", EditProposal, messages, retries=1, max_tokens=3000
            )
            error = apply_edits(tree, proposal.edits)
            if error:  # one more try with the reason, as verified edits do, from a clean tree
                subprocess.run(["git", "checkout", "--", "."], cwd=tree, capture_output=True)
                subprocess.run(["git", "clean", "-fdq"], cwd=tree, capture_output=True)
                messages += [
                    {"role": "assistant", "content": proposal.model_dump_json()},
                    {"role": "user", "content": f"Your edits could not be applied: {error} Try again."},
                ]
                proposal = await structured_call(
                    runtime, "strong", EditProposal, messages, retries=1, max_tokens=3000
                )
                error = apply_edits(tree, proposal.edits)
        except ModelOutputError as exc:
            error = f"invalid output: {exc.error[:120]}"
        except httpx.HTTPError as exc:  # one failing call is a failed task, not a failed benchmark
            detail = exc.response.text[:120] if isinstance(exc, httpx.HTTPStatusError) else str(exc)[:120]
            error = f"runtime error: {detail}"
        latency = round(time.perf_counter() - started, 2)
        diff = "" if error else _git_diff(tree)
        applies = error is None and bool(diff.strip())
        tests_pass: bool | None = None
        if test_cmd and passes_at_commit:
            if applies:
                status, _, _ = await asyncio.to_thread(run_command, tree, test_cmd, 300)
                tests_pass = status == "passed"
            else:
                tests_pass = False
    sim = similarity(diff, task.real_diff) if applies else 0.0
    tps = (getattr(runtime, "stats", {}) or {}).get("strong", {}).get("tokens_per_second")
    return TaskScore(
        sha=task.sha,
        applies=applies,
        tests_pass=tests_pass,
        similarity=sim,
        latency_s=latency,
        tokens_per_second=tps,
        score=task_score(applies, tests_pass, sim),
        error=error,
    )


async def _passes_at(repo: Path, sha: str, test_cmd: str) -> bool:
    with temp_worktree(repo, sha) as tree:
        status, _, _ = await asyncio.to_thread(run_command, tree, test_cmd, 300)
    return status == "passed"


def recommend(scores: list[ModelScore]) -> tuple[str, str | None, str | None]:
    if not scores:
        return "No chat models could be benchmarked.", None, None
    top = max(scores, key=lambda s: (s.score, -s.median_latency_s))
    # Prefer a model under the latency cap only if it is nearly as good; never trade away most of the quality.
    quick = [s for s in scores if s.median_latency_s <= LATENCY_CAP_S and s.score >= CLOSE_ENOUGH * top.score]
    best = max(quick, key=lambda s: (s.score, -s.median_latency_s)) if quick else top
    fast = min(scores, key=lambda s: (s.size_bytes or 0, -s.score))
    text = (
        f"Use {best.model} for review and code (score {best.score:.2f}, median {best.median_latency_s:.0f} s "
        "on your machine)."
    )
    if best.median_latency_s > LATENCY_CAP_S:
        text += " It is slow on this hardware, but the faster models scored much lower."
    if fast.model != best.model:
        text += f" {fast.model} is good enough for classification."
    return text, best.model, fast.model


async def run_bench(
    repo_id: str,
    repo: Path,
    models: list[ModelInfo],
    hw: Hardware,
    *,
    n_tasks: int = 10,
    seed: int = 7,
    runtimes: dict[str, Runtime] | None = None,
    embed_model: ModelInfo | None = None,
) -> BenchResult:
    store = MemoryStore.open(repo_id)
    tasks = select_tasks(store, repo, n_tasks, seed)
    test_cmd = detect_test_command(repo)
    passes = {t.sha: (await _passes_at(repo, t.sha, test_cmd)) if test_cmd else False for t in tasks}
    scores: list[ModelScore] = []
    skipped: list[SkippedModel] = []
    for model in [m for m in models if not m.is_embedding]:
        if not fits(model, hw):
            gb = (model.size_bytes or 0) / 1024**3
            skipped.append(SkippedModel(model=model.id, reason=f"needs ~{gb:.1f} GB"))
            continue
        runtime = (runtimes or {}).get(model.id) or ModelClient(
            {"strong": model, "fast": model, "embed": embed_model or model}
        )
        results = [await _run_task(runtime, repo, t, test_cmd, passes[t.sha]) for t in tasks]
        if not results:
            continue
        tests = [r.tests_pass for r in results if r.tests_pass is not None]
        tps = [r.tokens_per_second for r in results if r.tokens_per_second]
        scores.append(
            ModelScore(
                model=model.id,
                size_bytes=model.size_bytes,
                score=round(statistics.mean(r.score for r in results), 3),
                applies_rate=round(sum(r.applies for r in results) / len(results), 3),
                tests_pass_rate=round(sum(tests) / len(tests), 3) if tests else None,
                similarity=round(statistics.mean(r.similarity for r in results), 3),
                median_latency_s=round(statistics.median(r.latency_s for r in results), 2),
                tokens_per_second=round(statistics.mean(tps), 1) if tps else None,
                tasks=results,
            )
        )
    scores.sort(key=lambda s: -s.score)
    text, strong, fast = recommend(scores)
    result = BenchResult(
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        repo_id=repo_id,
        tasks=tasks,
        models=scores,
        skipped=skipped,
        recommendation=text,
        recommended_strong=strong,
        recommended_fast=fast,
    )
    out = get_settings().repo_dir(repo_id) / "bench"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{result.created_at.replace(':', '-')}.json").write_text(result.model_dump_json(indent=2))
    return result


def latest_bench(repo_id: str) -> BenchResult | None:
    out = get_settings().repo_dir(repo_id) / "bench"
    files = sorted(out.glob("*.json")) if out.exists() else []
    return BenchResult.model_validate_json(files[-1].read_text()) if files else None
