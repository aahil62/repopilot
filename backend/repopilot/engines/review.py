"""History-aware review of a diff: mechanical vs behavior, blast radius, precedents, checks, verified findings."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
Judge the change against its INTENT: code that correctly does what the intent says is not a bug,
and new tests that exercise the intended behavior are not bugs.
Only report a problem if you can name a concrete input or call that now misbehaves (`failing_input`):
a wrong condition, missing case, broken contract, unsafe input handling, resource leak, race, or a change
that contradicts a past fix or review comment listed under HISTORY. Never comment on style or naming.
Every finding must name the file path exactly as shown and a line number from the new version
(the numbers printed at the start of each line). Most correct changes have no findings: an empty
`findings` list is the expected answer when nothing is clearly wrong.
`evidence` may only contain refs that appear under HISTORY (for example "PR #412" or a commit sha)."""

CRITIC_PROMPT = """You are checking another reviewer's claim about a code change. Be skeptical.
Lines starting with - were removed and lines with + were added. Trace the failing input through the
new code step by step in `reason`, then decide. Judge only behavior: ignore whether the claim's title
or history reference is accurate. confirmed=true if the new code really misbehaves for that input.
confirmed=false if it behaves correctly, or if the change does exactly what its INTENT says.
If TESTS FAILED output is shown, it is real output from running the project's tests on the new code:
a test failure that matches the claim confirms it."""


class ModelFinding(BaseModel):
    # `failing_input` is required in the schema sent to the runtime, so constrained decoding always fills it,
    # but optional when validating, so one vague finding is dropped instead of failing the whole review.
    model_config = ConfigDict(
        json_schema_extra=lambda s: s.setdefault("required", []).append("failing_input")
    )

    severity: Literal["high", "medium", "low"]
    path: str = Field(max_length=300)
    line: int
    title: str = Field(max_length=160)
    explanation: str = Field(max_length=600)
    failing_input: str = Field(default="", max_length=300)
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
    corroborated: bool = False  # a failing test or a past fix/review supports it


class CriticVerdict(BaseModel):
    # `reason` first: models generate fields in schema order, so this makes it reason before deciding.
    reason: str = Field(max_length=600)
    confirmed: bool


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
    dropped_unconfirmed: int = 0
    intent: str | None = None
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


def change_intent(repo_path: Path, source: DiffSource) -> str | None:
    """What the change is meant to do: commit messages for commits and branch comparisons."""
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo_path, capture_output=True, text=True, timeout=30
        ).stdout.strip()

    if source.kind == "commit" and source.head:
        return git("log", "-1", "--format=%s%n%n%b", source.head)[:1200] or None
    if source.kind == "refs" and source.base:
        rng = f"{source.base}..{source.head or 'HEAD'}"
        return git("log", "--format=- %s", "-20", rng)[:1200] or None
    return None


def _prompt(
    behavior: list[tuple[FileDiff, Hunk]],
    blast: BlastReport | None,
    precedents: list[Precedent],
    checks: ChecksResult,
    intent: str | None = None,
) -> tuple[str, bool]:
    parts, used, truncated = [f"INTENT\n{intent or 'Not stated.'}\n", "BEHAVIOR HUNKS"], 0, False
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


async def _criticise(
    runtime: Runtime,
    findings: list[Finding],
    behavior: list[tuple[FileDiff, Hunk]],
    intent: str | None,
    checks: ChecksResult,
) -> tuple[list[Finding], int]:
    """Second, skeptical pass: keep a finding only if the model confirms its failing input.
    Uncorroborated findings (no failing test, no past fix or review) are capped at medium."""
    kept, dropped = [], 0
    for f in findings:
        if not f.failing_input.strip():
            dropped += 1
            continue
        hunk_text = "\n\n".join(_numbered(h) for fd, h in behavior if fd.path == f.path)[:6000]
        tests = (
            f"\n\nTESTS FAILED AFTER THIS CHANGE ({checks.command})\n{checks.output_tail[-2000:]}"
            if checks.status == "failed"
            else ""
        )
        claim = (
            f"INTENT\n{intent or 'Not stated.'}\n\nCODE ({f.path})\n{hunk_text}{tests}\n\nCLAIM\n"
            f"line {f.line}: {f.title}. {f.explanation}\nFailing input: {f.failing_input}\n\nVERDICT?"
        )
        try:
            verdict = await structured_call(
                runtime,
                "strong",
                CriticVerdict,
                [{"role": "system", "content": CRITIC_PROMPT}, {"role": "user", "content": claim}],
                max_tokens=400,
            )
        except ModelOutputError:
            dropped += 1
            continue
        if not verdict.confirmed:
            dropped += 1
            continue
        corroborated = checks.status == "failed" or bool(f.evidence_detail)
        severity = f.severity if corroborated or f.severity != "high" else "medium"
        kept.append(f.model_copy(update={"corroborated": corroborated, "severity": severity}))
    return kept, dropped


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
    intent: str | None = None,
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
    unconfirmed = 0
    if intent is None and source.kind in ("commit", "refs"):
        intent = change_intent(repo_path, source)
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
        prompt, truncated = _prompt(behavior, blast, precedents, checks, intent)
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
            findings, unconfirmed = await _criticise(runtime, findings, behavior, intent, checks)
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
        dropped_unconfirmed=unconfirmed,
        intent=intent,
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


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def should_fail(report: ReviewReport, fail_on: str) -> bool:
    """CI gate: fail on findings at or above `fail_on` ("high" or "medium"), or on failing checks."""
    if fail_on == "never":
        return False
    threshold = SEVERITY_RANK[fail_on]
    return report.checks.status == "failed" or any(
        SEVERITY_RANK[f.severity] >= threshold for f in report.findings
    )


def report_markdown(report: ReviewReport) -> str:
    """A compact Markdown report for pull-request summaries ($GITHUB_STEP_SUMMARY) and comments."""
    total = report.mechanical_count + report.behavior_count
    lines = [
        "## RepoPilot review",
        "",
        f"**{report.behavior_count} of {total} hunks change behavior.** "
        f"{report.mechanical_count} mechanical hunks (formatting, comments, docs, imports, renames) were set aside.",
    ]
    summary = report.summary.split(" Behavior changes to read:")[0].strip()
    if summary and not summary.startswith("Behavior changes to read"):
        lines += ["", summary]
    if report.findings:
        lines += ["", "### Findings", ""]
        for f in report.findings:
            lines.append(f"- **{f.severity}** `{f.path}:{f.line}` {f.title}. {f.explanation}")
            lines += [f"  - {e.ref}: {e.excerpt[:140]}" for e in f.evidence_detail]
    behavior_files = [f for f in report.files if f.behavior_hunks]
    if behavior_files:
        lines += ["", "### Read these", ""]
        lines += [
            f"- `{f.path}`: {f.behavior_hunks} behavior hunk{'s' if f.behavior_hunks > 1 else ''}"
            for f in behavior_files
        ]
    if report.blast:
        lines += ["", f"### Blast radius: {report.blast.risk}", ""]
        lines += [f"- {r}" for r in report.blast.risk_reasons]
        if report.blast.owners:
            lines.append("- Who knows this code: " + ", ".join(o.author for o in report.blast.owners))
    c = report.checks
    lines += ["", f"### Checks: {c.status.replace('_', ' ')}"]
    if c.command:
        lines.append(f"`{c.command}`")
    if c.message:
        lines.append(c.message)
    if c.status == "failed":
        lines += ["", "```", c.output_tail[-2000:], "```"]
    if report.model_error:
        lines += ["", f"_{report.model_error}_"]
    model = report.model.get("strong")
    lines += [
        "",
        f"<sub>Generated locally by RepoPilot{f' with {model}' if model else ''}. No code left the runner.</sub>",
    ]
    return "\n".join(lines) + "\n"
