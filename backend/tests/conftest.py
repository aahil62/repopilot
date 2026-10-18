from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from repopilot.config import reset_settings


@pytest.fixture(autouse=True)
def tmp_home(tmp_path_factory, monkeypatch) -> Path:
    home = tmp_path_factory.mktemp("rp-home")
    monkeypatch.setenv("REPOPILOT_HOME", str(home))
    reset_settings()
    yield home
    reset_settings()
    from repopilot.runtime import set_runtime

    set_runtime(None)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


Commit = tuple[str, dict[str, str | None]]


@pytest.fixture
def git_repo(tmp_path) -> Callable[..., Path]:
    """Factory: git_repo([("message", {"path": "content" or None-to-delete}), ...]) -> repo path."""

    def make(commits: list[Commit], name: str = "repo", author: str = "Dev One") -> Path:
        root = tmp_path / name
        root.mkdir()
        _git(root, "init", "-q", "-b", "main")
        _git(root, "config", "user.name", author)
        _git(root, "config", "user.email", f"{author.split()[0].lower()}@example.com")
        _git(root, "config", "commit.gpgsign", "false")
        for i, (message, files) in enumerate(commits):
            for rel, content in files.items():
                target = root / rel
                if content is None:
                    target.unlink()
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            _git(root, "add", "-A")
            date = f"2026-01-{(i % 28) + 1:02d}T10:00:00+00:00"
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", message],
                cwd=root,
                check=True,
                capture_output=True,
                env={**_env(), "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
            )
        return root

    return make


def _env() -> dict[str, str]:
    import os

    return dict(os.environ)


@pytest.fixture
def git() -> Callable[..., str]:
    return _git
