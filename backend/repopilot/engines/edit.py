"""Verified edits: the model proposes search/replace edits; RepoPilot applies them in a temporary
worktree, runs the project's checks, feeds failures back, and only returns a diff it has verified.

Search/replace blocks are used instead of raw unified diffs because small open models are much
more reliable at quoting existing code than at computing hunk headers.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from repopilot.engines.ask import retrieve
from repopilot.engines.blast import blast_radius
from repopilot.engines.checks import ChecksResult, detect_test_command, detect_typecheck_command, run_command
from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import Runtime
from repopilot.runtime.structured import ModelOutputError, structured_call
from repopilot.worktree import temp_worktree

MAX_FILE_LINES = 600

SYSTEM = """You are editing a code repository. Make the smallest change that fulfils the instruction and
follows the existing style of the files shown. Return JSON with `explanation` and `edits`.
Each edit has `path` (relative to the repository root), `search` (an exact, contiguous excerpt of the
current file, long enough to be unique) and `replace` (the new text for that excerpt). To create a
new file, use an empty `search` and put the whole file in `replace`. Never invent file contents you
were not shown; never edit files that are not needed."""


class EditBlock(BaseModel):
    path: str
    search: str = ""
    replace: str


class EditProposal(BaseModel):
    explanation: str
    edits: list[EditBlock] = Field(min_length=1)


class Attempt(BaseModel):
    n: int
    diff: str
    applied: bool
    apply_error: str | None = None
    checks: ChecksResult | None = None


class EditResult(BaseModel):
    status: Literal["verified", "failed", "no_checks"]
    diff: str
    explanation: str
    attempts: list[Attempt]
    target_paths: list[str]
    base_hashes: dict[str, str | None]


def _sha(path: Path) -> str | None:
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.exists() else None


def apply_edits(root: Path, edits: list[EditBlock]) -> str | None:
    """Apply search/replace blocks under `root`. Returns an error message, or None on success."""
    for edit in edits:
        rel = edit.path.strip().lstrip("./")
        target = (root / rel).resolve()
        if root.resolve() not in target.parents:
            return f"{edit.path}: path is outside the repository."
        if not edit.search:
            if target.exists():
                return f"{rel}: file already exists; quote the code to change in `search`."
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.replace if edit.replace.endswith("\n") else edit.replace + "\n")
            continue
        if not target.exists():
            return f"{rel}: file does not exist."
        text = target.read_text()
        if edit.search in text:
            target.write_text(text.replace(edit.search, edit.replace, 1))
            continue
        # Tolerate trailing-whitespace and indentation drift at line level.
        lines = text.splitlines(keepends=True)
        want = [line.strip() for line in edit.search.strip("\n").splitlines()]
        for i in range(len(lines) - len(want) + 1):
            if [line.strip() for line in lines[i : i + len(want)]] == want:
                replacement = edit.replace if edit.replace.endswith("\n") else edit.replace + "\n"
                target.write_text("".join(lines[:i]) + replacement + "".join(lines[i + len(want) :]))
                break
        else:
            return f"{rel}: the `search` text was not found in the current file. Quote it exactly."
    return None


def _git_diff(tree: Path) -> str:
    subprocess.run(["git", "add", "-A"], cwd=tree, capture_output=True, check=True)
    return subprocess.run(
        ["git", "diff", "--cached", "--no-color", "--no-ext-diff"],
        cwd=tree,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _context(repo_path: Path, store: MemoryStore, targets: list[str], extra_chunks: list[dict]) -> str:
    parts = []
    for rel in targets:
        path = repo_path / rel
        if path.exists():
            lines = path.read_text(errors="replace").splitlines()
            body = "\n".join(lines[:MAX_FILE_LINES])
            note = (
                f"\n... ({len(lines) - MAX_FILE_LINES} more lines not shown)"
                if len(lines) > MAX_FILE_LINES
                else ""
            )
            parts.append(f"=== {rel} (current content)\n{body}{note}")
        else:
            parts.append(f"=== {rel} (does not exist yet)")
    for chunk in extra_chunks:
        parts.append(
            f"=== {chunk['path']} lines {chunk['start_line']}-{chunk['end_line']} (similar code, for style)\n{chunk['text'][:1500]}"
        )
    if targets and store.one("SELECT count(*) n FROM commits")["n"]:
        blast = blast_radius(store.repo_id, [t for t in targets if (repo_path / t).exists()])
        if blast.cochanged:
            parts.append(
                "Files that usually change together with these: "
                + ", ".join(c.path for c in blast.cochanged[:5])
            )
    return "\n\n".join(parts)


async def verified_edit(
    repo_id: str,
    repo_path: Path,
    runtime: Runtime,
    instruction: str,
    target_paths: list[str] | None = None,
    *,
    max_attempts: int = 3,
    ref: str = "HEAD",
) -> EditResult:
    store = MemoryStore.open(repo_id)
    retrieved: list[dict] = []
    if not target_paths:
        retrieved, _ = await retrieve(store, runtime, instruction)
        target_paths = list(dict.fromkeys(c["path"] for c in retrieved))[:2]
    style = [c for c in retrieved if c["path"] not in target_paths][:2]
    if not style:
        style_hits, _ = await retrieve(store, runtime, instruction)
        style = [c for c in style_hits if c["path"] not in target_paths][:2]
    base_hashes = {t: _sha(repo_path / t) for t in target_paths}
    has_checks = bool(detect_test_command(repo_path) or detect_typecheck_command(repo_path))
    command = " && ".join(
        c for c in (detect_typecheck_command(repo_path), detect_test_command(repo_path)) if c
    )

    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": f"{_context(repo_path, store, target_paths, style)}\n\nInstruction: {instruction}",
        },
    ]
    attempts: list[Attempt] = []
    explanation = ""
    for n in range(1, max_attempts + 1):
        try:
            proposal = await structured_call(runtime, "strong", EditProposal, messages, max_tokens=3000)
        except ModelOutputError as exc:
            attempts.append(
                Attempt(n=n, diff="", applied=False, apply_error=f"Invalid model output: {exc.error[:200]}")
            )
            continue
        explanation = proposal.explanation
        with temp_worktree(repo_path, ref) as tree:
            error = apply_edits(tree, proposal.edits)
            diff = "" if error else _git_diff(tree)
            if error or not diff.strip():
                error = error or "The edits did not change anything."
                attempts.append(Attempt(n=n, diff=diff, applied=False, apply_error=error))
                feedback = f"Your edits could not be applied: {error} Try again."
            elif not has_checks:
                attempts.append(Attempt(n=n, diff=diff, applied=True, checks=None))
                return EditResult(
                    status="no_checks",
                    diff=diff,
                    explanation=explanation,
                    attempts=attempts,
                    target_paths=target_paths,
                    base_hashes=base_hashes,
                )
            else:
                status, output, seconds = await asyncio.to_thread(run_command, tree, command, 300)
                checks = ChecksResult(
                    command=command, status=status, output_tail=output, duration_s=round(seconds, 2)
                )
                attempts.append(Attempt(n=n, diff=diff, applied=True, checks=checks))
                if status == "passed":
                    return EditResult(
                        status="verified",
                        diff=diff,
                        explanation=explanation,
                        attempts=attempts,
                        target_paths=target_paths,
                        base_hashes=base_hashes,
                    )
                feedback = (
                    f"The project's checks failed after your edits:\n{output[-2500:]}\nFix the problem."
                )
        messages = [
            *messages,
            {"role": "assistant", "content": proposal.model_dump_json()},
            {"role": "user", "content": feedback},
        ]
    last = attempts[-1] if attempts else None
    return EditResult(
        status="failed",
        diff=last.diff if last else "",
        explanation=explanation,
        attempts=attempts,
        target_paths=target_paths,
        base_hashes=base_hashes,
    )


class ApplyConflict(RuntimeError):
    pass


def apply_to_working_tree(repo_path: Path, result: EditResult) -> None:
    if result.status not in ("verified", "no_checks"):
        raise ValueError("Only verified edits can be applied.")
    for rel, digest in result.base_hashes.items():
        if _sha(repo_path / rel) != digest:
            raise ApplyConflict(f"{rel} changed since the edit was prepared; run it again.")
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=repo_path,
        input=result.diff,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ApplyConflict(proc.stderr.strip()[:300])
