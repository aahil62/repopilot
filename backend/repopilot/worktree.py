"""Temporary git worktrees: model-written code is applied and tested here, never in the user's checkout."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from repopilot.config import get_settings


class WorktreeError(RuntimeError):
    pass


def _git(
    repo: Path, *args: str, check: bool = True, input_text: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check, input=input_text, timeout=600
    )


@contextmanager
def temp_worktree(repo: Path, ref: str = "HEAD") -> Iterator[Path]:
    path = get_settings().worktrees_dir / uuid.uuid4().hex[:12]
    result = _git(repo, "worktree", "add", "--detach", str(path), ref, check=False)
    if result.returncode != 0:
        raise WorktreeError(f"git worktree add failed: {result.stderr.strip()[:300]}")
    node_modules = repo / "node_modules"
    if node_modules.is_dir() and not (path / "node_modules").exists():
        (path / "node_modules").symlink_to(node_modules, target_is_directory=True)
    try:
        yield path
    finally:
        _git(repo, "worktree", "remove", "--force", str(path), check=False)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        _git(repo, "worktree", "prune", check=False)


def apply_diff(worktree: Path, diff_text: str) -> tuple[bool, str]:
    """Apply a unified diff inside a worktree. Returns (ok, error output)."""
    if not diff_text.strip():
        return True, ""
    if not diff_text.endswith("\n"):
        diff_text += "\n"
    check = _git(
        worktree,
        "apply",
        "--check",
        "--recount",
        "--whitespace=nowarn",
        "-",
        check=False,
        input_text=diff_text,
    )
    if check.returncode != 0:
        return False, check.stderr.strip()
    applied = _git(
        worktree, "apply", "--recount", "--whitespace=nowarn", "-", check=False, input_text=diff_text
    )
    return applied.returncode == 0, applied.stderr.strip()
