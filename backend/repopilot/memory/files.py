"""Walk a repository's files: respects .gitignore, skips binaries, vendored and oversized files."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from repopilot.config import Settings

SKIP_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    "target",
    "vendor",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "coverage",
    ".gradle",
    ".idea",
}
LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".md": "markdown",
    ".rst": "markdown",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".vue": "vue",
    ".svelte": "svelte",
}
LOCK_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "uv.lock",
    "go.sum",
}


@dataclass(frozen=True)
class RepoFile:
    path: str  # posix, relative to repo root
    abs_path: Path
    size: int
    language: str


def language_for(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if name in LOCK_FILES or name.endswith((".min.js", ".min.css", ".map")):
        return None
    if name in {"Dockerfile", "Makefile"}:
        return "config"
    return LANGUAGES.get(os.path.splitext(name)[1].lower())


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(8192)
    except OSError:
        return True


def _git_listing(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            check=True,
            timeout=120,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def _walk(root: Path) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            yield Path(dirpath, name).relative_to(root).as_posix()


def iter_repo_files(root: Path, settings: Settings) -> Iterator[RepoFile]:
    root = root.resolve()
    listing = _git_listing(root) if (root / ".git").exists() else None
    candidates = listing if listing is not None else _walk(root)
    count = 0
    for rel in candidates:
        if any(part in SKIP_DIRS for part in rel.split("/")[:-1]):
            continue
        language = language_for(rel)
        if language is None:
            continue
        abs_path = root / rel
        try:
            size = abs_path.stat().st_size
        except OSError:
            continue
        if size > settings.max_file_kb * 1024 or size == 0 or is_binary(abs_path):
            continue
        yield RepoFile(rel, abs_path, size, language)
        count += 1
        if count >= settings.max_files:
            return
