"""Registry of repositories RepoPilot knows about (~/.repopilot/repos.json)."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from repopilot.config import get_settings, repo_id_for

GITHUB_URL = re.compile(r"^(?:https://github\.com/|git@github\.com:)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


class RepoError(ValueError):
    pass


@dataclass
class RepoRecord:
    repo_id: str
    name: str
    path: str
    source: str  # "local" | "clone"
    remote: str | None
    added_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _registry_path() -> Path:
    home = get_settings().home
    home.mkdir(parents=True, exist_ok=True)
    return home / "repos.json"


def _load() -> dict[str, dict]:
    path = _registry_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _save(data: dict[str, dict]) -> None:
    _registry_path().write_text(json.dumps(data, indent=2))


def _remote(path: Path) -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout.strip()
            or None
        )
    except (subprocess.SubprocessError, OSError):
        return None


def add_local(path: str | Path) -> RepoRecord:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise RepoError(f"Not a directory: {root}")
    if not (root / ".git").exists():
        raise RepoError(f"Not a git repository: {root}")
    record = RepoRecord(
        repo_id=repo_id_for(root),
        name=root.name,
        path=str(root),
        source="local",
        remote=_remote(root),
        added_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    data = _load()
    data.setdefault(record.repo_id, record.to_dict())
    _save(data)
    return RepoRecord(**data[record.repo_id])


def add_clone(git_url: str) -> RepoRecord:
    match = GITHUB_URL.match(git_url.strip())
    if not match:
        raise RepoError("Only github.com repository URLs can be cloned.")
    owner, name = match.groups()
    target = get_settings().clones_dir / f"{owner}__{name}"
    if not target.exists():
        result = subprocess.run(
            ["git", "clone", "--quiet", f"https://github.com/{owner}/{name}.git", str(target)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            raise RepoError(f"git clone failed: {result.stderr.strip()[:300]}")
    record = add_local(target)
    data = _load()
    data[record.repo_id].update({"source": "clone", "name": f"{owner}/{name}"})
    _save(data)
    return RepoRecord(**data[record.repo_id])


def get_repo(repo_id: str) -> RepoRecord:
    data = _load()
    if repo_id not in data:
        raise KeyError(repo_id)
    return RepoRecord(**data[repo_id])


def find_by_path(path: str | Path) -> RepoRecord | None:
    rid = repo_id_for(Path(path).expanduser())
    data = _load()
    return RepoRecord(**data[rid]) if rid in data else None


def list_repos() -> list[RepoRecord]:
    return [RepoRecord(**v) for v in _load().values()]


def remove_repo(repo_id: str) -> None:
    data = _load()
    data.pop(repo_id, None)
    _save(data)
