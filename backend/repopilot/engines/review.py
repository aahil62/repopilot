"""History-aware review of a diff: mechanical vs behavior, blast radius, precedents, checks, verified findings."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from repopilot.engines.blast import BlastReport, blast_radius
from repopilot.engines.checks import ChecksResult, run_checks
from repopilot.engines.classify import classify_hunk, identifiers, python_same_tree
from repopilot.engines.diffparse import DiffSource, FileDiff, Hunk, file_versions, parse
from repopilot.engines.precedents import Precedent, find_precedents
from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import Runtime
from repopilot.runtime.structured import ModelOutputError, structured_call

MAX_PROMPT_LINES = 600
LINE_TOLERANCE = 3

SYSTEM_PROMPT = """You are a careful senior engineer reviewing a code change for real bugs.
Only report problems you can point to in the BEHAVIOR HUNKS below: a wrong condition, missing case,
broken contract, unsafe input handling, resource leak, race, or a change that contradicts a past fix
or review comment listed under HISTORY. Do not comment on style, naming or formatting.
Every finding must name the file path exactly as shown and a line number from the new version
(the numbers printed at the start of each line). If you are not confident, report fewer findings.
`evidence` may only contain refs that appear under HISTORY (for example "PR #412" or a commit sha)."""


class ModelFinding(BaseModel):
    severity: Literal["high", "medium", "low"]
    path: str = Field(max_length=300)
    line: int
    title: str = Field(max_length=160)
    explanation: str = Field(max_length=600)
    evidence: list[str] = Field(default_factory=list, max_length=3)


class ModelReview(BaseModel):
    # Length limits are part of the JSON schema, so Ollama/llama.cpp enforce them while generating:
    # small models otherwise ramble until the token limit and the JSON is cut off.
    summary: str = Field(max_length=400)
    findings: list[ModelFinding] = Field(default_factory=list, max_length=6)


class HunkView(BaseModel):
    old_start: int
    new_start: int
    new_end: int
    label: Literal["mechanical", "behavior"]
    reason: str
    text: str


class FileView(BaseModel):
    path: str
    status: str
    mechanical_hunks: int
    behavior_hunks: int
    hunks: list[HunkView]


class Finding(ModelFinding):
    evidence_detail: list[Precedent] = Field(default_factory=list)


class ReviewReport(BaseModel):
    review_id: str
    created_at: str
    source: dict
    summary: str
    files: list[FileView]
    mechanical_count: int
    behavior_count: int
    findings: list[Finding]
    dropped_unverifiable: int
    blast: BlastReport | None
    precedents: list[Precedent]
    checks: ChecksResult
    model: dict[str, str]
    model_error: str | None = None
    truncated: bool = False
    timings_ms: dict[str, int]


def _numbered(h: Hunk) -> str:
    """Render a hunk with new-file line numbers so the model can cite exact lines."""
    out, new_no, old_no = [], h.new_start, h.old_start
    for line in h.lines:
        tag, body = line[0], line[1:]
        if tag == "-":
            out.append(f"     -{old_no:>5} | {body}")
            old_no += 1
        else:
            out.append(f"{new_no:>5} {tag}      | {body}")
            new_no += 1
            if tag == " ":
                old_no += 1
    return "\n".join(out)


def _prompt(
    behavior: list[tuple[FileDiff, Hunk]],
    blast: BlastReport | None,
    precedents: list[Precedent],
    checks: ChecksResult,
) -> tuple[str, bool]:
    parts, used, truncated = ["BEHAVIOR HUNKS"], 0, False
    for fd, h in behavior:
        size = len(h.lines)
        if used + size > MAX_PROMPT_LINES:
            truncated = True
            break
        parts.append(
            f"\n--- {fd.path} ({fd.status}) @@ new lines {h.new_range[0]}-{h.new_range[1]}\n{_numbered(h)}"
        )
        used += size
    parts.append("\nHISTORY")
    if blast:
        parts += [f"- past fix {f.sha[:8]}: {f.subject}" for f in blast.past_fixes[:5]]
        parts += [
            f"- usually changes with {c.path} ({round(c.confidence * 100)}%)" for c in blast.cochanged[:5]
        ]
    parts += [
        f"- {p.ref} ({p.kind.replace('_', ' ')}{', ' + p.path if p.path else ''}): {p.excerpt}"
        for p in precedents
    ]
    if len(parts) and parts[-1] == "\nHISTORY":
        parts.append("- none")
    parts.append(
        f"\nCHECKS: {checks.status}"
        + (f"\n{checks.output_tail[-1500:]}" if checks.status == "failed" else "")
    )
    return "\n".join(parts), truncated


def _verify(
    findings: list[ModelFinding], files: list[FileDiff], known_refs: dict[str, Precedent], fix_refs: set[str]
) -> tuple[list[Finding], int]:
    ranges: dict[str, list[tuple[int, int]]] = {}
    for fd in files:
        for h in fd.hunks:
            lo, hi = h.old_range if fd.status == "deleted" else h.new_range
            ranges.setdefault(fd.path, []).append((lo - LINE_TOLERANCE, hi + LINE_TOLERANCE))
    kept, dropped = [], 0
    for f in findings:
        path = f.path.strip().removeprefix("./")
        if path not in ranges or not any(lo <= f.line <= hi for lo, hi in ranges[path]):
            dropped += 1
            continue
        evidence = [e for e in f.evidence if e in known_refs or e[:8] in fix_refs]
        kept.append(
            Finding(
                **{**f.model_dump(), "path": path, "evidence": evidence},
                evidence_detail=[known_refs[e] for e in evidence if e in known_refs],
            )
        )
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(kept, key=lambda x: (order[x.severity], x.path, x.line)), dropped


async def review(
    repo_id: str,
    repo_path: Path,
    diff_text: str,
    runtime: Runtime | None,
    *,
    source: DiffSource | None = None,
    run_checks_enabled: bool = True,
    use_model: bool = True,
    checks_ref: str = "HEAD",
    persist: bool = True,
) -> ReviewReport:
    started = time.perf_counter()
    timings: dict[str, int] = {}
    source = source or DiffSource("paste")
    files = [f for f in parse(diff_text) if not f.binary]

    def tick(name: str, t0: float) -> None:
        timings[name] = int((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    views: list[FileView] = []
    behavior: list[tuple[FileDiff, Hunk]] = []
    for fd in files:
        old, new = (None, None) if source.kind == "paste" else file_versions(repo_path, source, fd)
        same_tree = fd.path.endswith(".py") and fd.status == "modified" and python_same_tree(old, new)
        old_ids, new_ids = identifiers(old), identifiers(new)
        hunk_views = []
        for h in fd.hunks:
            label, reason = classify_hunk(
                fd, h, same_tree=same_tree, old_idents=old_ids, new_idents=new_ids, old_text=old
            )
            if label == "behavior":
                behavior.append((fd, h))
            hunk_views.append(
                HunkView(
                    old_start=h.old_start,
                    new_start=h.new_range[0],
                    new_end=h.new_range[1],
                    label=label,
                    reason=reason,
                    text=h.text(),
                )
            )
        views.append(
            FileView(
                path=fd.path,
                status=fd.status,
                hunks=hunk_views,
                mechanical_hunks=sum(v.label == "mechanical" for v in hunk_views),
                behavior_hunks=sum(v.label == "behavior" for v in hunk_views),
            )
        )
    tick("classify", t0)

    store = MemoryStore.open(repo_id)
    t0 = time.perf_counter()
    touched = [fd.old_path if fd.status == "deleted" else fd.path for fd in files]
    blast = blast_radius(repo_id, touched) if touched else None
    tick("blast", t0)

    t0 = time.perf_counter()
    precedents = await find_precedents(store, runtime, behavior) if runtime is not None else []
    tick("precedents", t0)

    t0 = time.perf_counter()
    if run_checks_enabled and behavior:
        if source.kind in ("refs", "commit") and source.head:
            # The change already exists at `head`; test that commit as-is.
            checks = await asyncio.to_thread(run_checks, repo_path, None, ref=source.head)
        else:
            checks = await asyncio.to_thread(run_checks, repo_path, diff_text, ref=checks_ref)
    elif not behavior:
        checks = ChecksResult(
            command=None, status="skipped", message="Only mechanical changes; checks not needed."
        )
    else:
        checks = ChecksResult(command=None, status="skipped", message="Checks were not requested.")
    tick("checks", t0)

    findings: list[Finding] = []
    dropped = 0
    model_error = None
    truncated = False
    mech = sum(v.mechanical_hunks for v in views)
    beh = len(behavior)
    summary = f"Behavior changes to read: {beh} of {mech + beh} hunks."
    if runtime is None and behavior:
        model_error = (
            "No local model runtime, so only deterministic checks ran (classification, blast radius, tests)."
        )
    if behavior and use_model and runtime is not None:
        t0 = time.perf_counter()
        prompt, truncated = _prompt(behavior, blast, precedents, checks)
        try:
            result = await structured_call(
                runtime,
                "strong",
                ModelReview,
                [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                max_tokens=1800,
            )
            known = {p.ref: p for p in precedents}
            fix_refs = {f.sha[:8] for f in (blast.past_fixes if blast else [])}
            findings, dropped = _verify(result.findings, files, known, fix_refs)
            summary = f"{result.summary.strip()} {summary}".strip()
        except ModelOutputError as exc:
            model_error = f"Model output could not be validated after retries: {exc.error[:200]}"
        tick("model", t0)

    report = ReviewReport(
        review_id=uuid.uuid4().hex[:12],
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source={"kind": source.kind, "base": source.base, "head": source.head},
        summary=summary,
        files=views,
        mechanical_count=mech,
        behavior_count=beh,
        findings=findings,
        dropped_unverifiable=dropped,
        blast=blast,
        precedents=precedents,
        checks=checks,
        model={role: info.id for role, info in runtime.roles.items()} if runtime is not None else {},
        model_error=model_error,
        truncated=truncated,
        timings_ms={**timings, "total": int((time.perf_counter() - started) * 1000)},
    )
    if persist:
        store.execute(
            "INSERT INTO reviews(review_id, created_at, source, report) VALUES(?,?,?,?)",
            (report.review_id, report.created_at, json.dumps(report.source), report.model_dump_json()),
        )
    return report


def load_review(repo_id: str, review_id: str) -> ReviewReport | None:
    row = MemoryStore.open(repo_id).one("SELECT report FROM reviews WHERE review_id=?", (review_id,))
    return ReviewReport.model_validate_json(row["report"]) if row else None


def list_reviews(repo_id: str, limit: int = 20) -> list[dict]:
    rows = MemoryStore.open(repo_id).query(
        "SELECT review_id, created_at, source, json_extract(report,'$.summary') summary, "
        "json_extract(report,'$.behavior_count') behavior, json_extract(report,'$.mechanical_count') mechanical "
        "FROM reviews ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [{**dict(r), "source": json.loads(r["source"])} for r in rows]
