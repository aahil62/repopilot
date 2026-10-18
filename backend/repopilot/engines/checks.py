"""Detect and run a project's own checks (tests, type checks) in a temporary worktree."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from repopilot.config import get_settings
from repopilot.worktree import WorktreeError, apply_diff, temp_worktree

NO_TEST_MESSAGE = "No test command detected — set one in Settings (repopilot.toml [checks] test)."
NPM_DEFAULT_TEST = 'echo "Error: no test specified" && exit 1'


class ChecksResult(BaseModel):
    command: str | None
    status: Literal["passed", "failed", "skipped", "timeout", "not_applied"]
    output_tail: str = ""
    duration_s: float = 0.0
    message: str = ""


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _python_for(repo: Path) -> str:
    for candidate in (repo / ".venv" / "bin" / "python", repo / "venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return shutil.which("python3") or sys.executable


def detect_test_command(repo: Path) -> str | None:
    config = _read_toml(repo / "repopilot.toml")
    if cmd := config.get("checks", {}).get("test"):
        return cmd
    pyproject = _read_toml(repo / "pyproject.toml")
    has_pytest_cfg = (repo / "pytest.ini").exists() or "pytest" in pyproject.get("tool", {})
    tests_dir = any((repo / d).is_dir() and any((repo / d).rglob("test_*.py")) for d in ("tests", "test"))
    if has_pytest_cfg or tests_dir or any(repo.glob("test_*.py")):
        return f"{shlex.quote(_python_for(repo))} -m pytest -q -x"
    package = repo / "package.json"
    if package.exists():
        try:
            script = json.loads(package.read_text()).get("scripts", {}).get("test")
        except (OSError, json.JSONDecodeError):
            script = None
        if script and script.strip() != NPM_DEFAULT_TEST:
            return "npm test --silent"
    if (repo / "go.mod").exists():
        return "go test ./..."
    if (repo / "Cargo.toml").exists():
        return "cargo test --quiet"
    return None


def detect_typecheck_command(repo: Path) -> str | None:
    config = _read_toml(repo / "repopilot.toml")
    if cmd := config.get("checks", {}).get("typecheck"):
        return cmd
    if (repo / "tsconfig.json").exists() and (repo / "node_modules" / ".bin" / "tsc").exists():
        return "npx tsc --noEmit"
    return None


def _tail(text: str, lines: int = 80) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def run_command(cwd: Path, command: str, timeout: int) -> tuple[str, str, float]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(cwd), str(cwd / "src")]), "CI": "1"}
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return (
            "timeout",
            _tail(out if isinstance(out, str) else out.decode(errors="replace")),
            time.perf_counter() - started,
        )
    status = "passed" if proc.returncode == 0 else "failed"
    return status, _tail(proc.stdout + "\n" + proc.stderr), time.perf_counter() - started


def run_checks(
    repo: Path, diff_text: str | None = None, *, ref: str = "HEAD", timeout: int | None = None
) -> ChecksResult:
    """Apply `diff_text` on top of `ref` in a throwaway worktree and run the project's checks there."""
    timeout = timeout or get_settings().check_timeout_s
    test_cmd = detect_test_command(repo)
    type_cmd = detect_typecheck_command(repo)
    if not test_cmd and not type_cmd:
        return ChecksResult(command=None, status="skipped", message=NO_TEST_MESSAGE)
    try:
        with temp_worktree(repo, ref) as tree:
            ok, err = apply_diff(tree, diff_text or "")
            if not ok:
                return ChecksResult(
                    command=None, status="not_applied", output_tail=_tail(err), message="Diff did not apply."
                )
            command = " && ".join(c for c in (type_cmd, test_cmd) if c)
            status, output, seconds = run_command(tree, command, timeout)
            return ChecksResult(
                command=command, status=status, output_tail=output, duration_s=round(seconds, 2)
            )
    except WorktreeError as exc:
        return ChecksResult(command=test_cmd, status="skipped", message=str(exc))
