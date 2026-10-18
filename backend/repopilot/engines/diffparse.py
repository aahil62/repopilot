"""Produce and parse unified diffs."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

Status = Literal["added", "modified", "deleted", "renamed"]


@dataclass
class Hunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str]  # each line keeps its ' ', '+' or '-' prefix
    header: str = ""

    @property
    def added(self) -> list[str]:
        return [line[1:] for line in self.lines if line.startswith("+")]

    @property
    def removed(self) -> list[str]:
        return [line[1:] for line in self.lines if line.startswith("-")]

    @property
    def new_range(self) -> tuple[int, int]:
        return self.new_start, self.new_start + max(self.new_lines, 1) - 1

    @property
    def old_range(self) -> tuple[int, int]:
        return self.old_start, self.old_start + max(self.old_lines, 1) - 1

    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class FileDiff:
    path: str
    old_path: str
    status: Status
    hunks: list[Hunk] = field(default_factory=list)
    binary: bool = False


@dataclass
class DiffSource:
    kind: Literal["working", "staged", "refs", "paste", "commit"]
    base: str | None = None
    head: str | None = None


def _strip(path: str | None) -> str:
    if not path or path == "/dev/null":
        return ""
    return path[2:] if path.startswith(("a/", "b/")) else path


def parse(diff_text: str) -> list[FileDiff]:
    try:
        patch = PatchSet(diff_text)
    except UnidiffParseError as exc:
        raise ValueError(f"Could not parse diff: {exc}") from exc
    files: list[FileDiff] = []
    for pf in patch:
        source, target = _strip(pf.source_file), _strip(pf.target_file)
        if pf.is_added_file:
            status: Status = "added"
        elif pf.is_removed_file:
            status = "deleted"
        elif pf.is_rename or (source and target and source != target):
            status = "renamed"
        else:
            status = "modified"
        path = target or source
        hunks = [
            Hunk(
                old_start=h.source_start,
                old_lines=h.source_length,
                new_start=h.target_start,
                new_lines=h.target_length,
                lines=[
                    f"{line.line_type}{line.value.rstrip(chr(10))}" for line in h if line.line_type in " +-"
                ],
                header=h.section_header or "",
            )
            for h in pf
        ]
        files.append(
            FileDiff(path=path, old_path=source or path, status=status, hunks=hunks, binary=pf.is_binary_file)
        )
    return files


def _git(repo: Path, *args: str, ok_codes: tuple[int, ...] = (0,)) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=300,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode not in ok_codes:
        raise ValueError(result.stderr.strip()[:300] or f"git {' '.join(args)} failed")
    return result.stdout


def diff_for(
    repo: Path, *, base: str | None = None, head: str | None = None, staged: bool = False
) -> tuple[str, DiffSource]:
    if base and head:
        return _git(repo, "diff", "--no-color", "--no-ext-diff", f"{base}...{head}"), DiffSource(
            "refs", base, head
        )
    if base:
        return _git(repo, "diff", "--no-color", "--no-ext-diff", base), DiffSource("refs", base, None)
    if staged:
        return _git(repo, "diff", "--no-color", "--no-ext-diff", "--cached"), DiffSource(
            "staged", "HEAD", None
        )
    text = _git(repo, "diff", "--no-color", "--no-ext-diff", "HEAD")
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    for path in filter(None, untracked):
        text += _git(repo, "diff", "--no-color", "--no-index", "--", "/dev/null", path, ok_codes=(0, 1))
    return text, DiffSource("working", "HEAD", None)


def commit_diff(repo: Path, sha: str) -> str:
    return _git(repo, "show", "--no-color", "--format=", "--no-ext-diff", sha)


def file_versions(repo: Path, source: DiffSource, fd: FileDiff) -> tuple[str | None, str | None]:
    """Old and new full text of a changed file, when they can be recovered."""

    def show(ref: str, path: str) -> str | None:
        try:
            return _git(repo, "show", f"{ref}:{path}")
        except ValueError:
            return None

    old_ref = source.base or "HEAD"
    if source.kind == "refs" and source.base and source.head:
        try:
            old_ref = _git(repo, "merge-base", source.base, source.head).strip()
        except ValueError:
            old_ref = source.base
    if source.kind == "commit" and source.head:
        old_ref = f"{source.head}^"
    old = None if fd.status == "added" else show(old_ref, fd.old_path)
    if fd.status == "deleted":
        return old, None
    if source.kind == "working":
        target = repo / fd.path
        new = target.read_text(errors="replace") if target.exists() else None
    elif source.kind == "staged":
        new = show("", fd.path)
    elif source.head:
        new = show(source.head, fd.path)
    else:
        new = None
    return old, new
