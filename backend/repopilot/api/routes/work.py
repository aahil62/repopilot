"""Review, blast radius, ask, verified edits, night shift and benchmark endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from repopilot.api.jobs import jobs
from repopilot.api.routes.repos import record_or_404
from repopilot.engines import nightshift as night
from repopilot.engines.ask import ask_stream
from repopilot.engines.bench import latest_bench, run_bench
from repopilot.engines.blast import blast_radius
from repopilot.engines.diffparse import DiffSource, diff_for
from repopilot.engines.edit import ApplyConflict, EditResult, apply_to_working_tree, verified_edit
from repopilot.engines.review import list_reviews, load_review, review
from repopilot.memory.store import MemoryStore
from repopilot.runtime import get_runtime, get_runtime_optional, scan

router = APIRouter(prefix="/api/repos/{repo_id}", tags=["work"])


@router.get("/blast")
def blast(repo_id: str, path: list[str] = Query(...)) -> dict:
    record_or_404(repo_id)
    return blast_radius(repo_id, path).model_dump()


class ReviewRequest(BaseModel):
    diff: str | None = None
    base: str | None = None
    head: str | None = None
    staged: bool = False
    run_checks: bool = True


@router.post("/review")
async def start_review(repo_id: str, body: ReviewRequest) -> dict:
    record = record_or_404(repo_id)
    root = Path(record.path)
    if body.diff:
        diff_text, source = body.diff, DiffSource("paste")
    else:
        try:
            diff_text, source = diff_for(root, base=body.base, head=body.head, staged=body.staged)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    if not diff_text.strip():
        raise HTTPException(400, "There are no changes to review.")
    runtime = await get_runtime_optional()

    async def run(progress):
        progress({"stage": "reviewing"})
        return await review(
            repo_id, root, diff_text, runtime, source=source, run_checks_enabled=body.run_checks
        )

    return {"job_id": jobs().start("review", repo_id, run)}


@router.get("/reviews")
def reviews(repo_id: str) -> list[dict]:
    record_or_404(repo_id)
    return list_reviews(repo_id)


@router.get("/reviews/{review_id}")
def get_review(repo_id: str, review_id: str) -> dict:
    record_or_404(repo_id)
    report = load_review(repo_id, review_id)
    if not report:
        raise HTTPException(404, "Review not found.")
    return report.model_dump()


class AskRequest(BaseModel):
    question: str


@router.post("/ask")
async def ask(repo_id: str, body: AskRequest) -> EventSourceResponse:
    record_or_404(repo_id)
    runtime = await get_runtime()
    store = MemoryStore.open(repo_id)

    async def events():
        async for event in ask_stream(store, runtime, body.question):
            yield {"event": event["event"], "data": json.dumps(event["data"])}

    return EventSourceResponse(events())


class EditRequest(BaseModel):
    instruction: str
    paths: list[str] | None = None


@router.post("/edit")
async def start_edit(repo_id: str, body: EditRequest) -> dict:
    record = record_or_404(repo_id)
    runtime = await get_runtime()

    async def run(progress):
        progress({"stage": "editing"})
        return await verified_edit(repo_id, Path(record.path), runtime, body.instruction, body.paths)

    return {"job_id": jobs().start("edit", repo_id, run)}


@router.post("/edit/{job_id}/apply")
def apply_edit(repo_id: str, job_id: str) -> dict:
    record = record_or_404(repo_id)
    job = jobs().get(job_id)
    if not job or job["kind"] != "edit" or job["status"] != "done":
        raise HTTPException(404, "No finished edit with that id.")
    result = EditResult.model_validate(job["result"])
    try:
        apply_to_working_tree(Path(record.path), result)
    except ApplyConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"applied": True, "paths": result.target_paths}


@router.get("/nightshift/reports")
def night_reports(repo_id: str) -> list[dict]:
    record_or_404(repo_id)
    return night.list_reports(repo_id)


@router.get("/nightshift/reports/{day}")
def night_report(repo_id: str, day: str) -> dict:
    record_or_404(repo_id)
    report = night.load_report(repo_id, day)
    if not report:
        raise HTTPException(404, "No report for that date.")
    return report.model_dump()


@router.post("/nightshift/run")
async def night_run(repo_id: str) -> dict:
    record = record_or_404(repo_id)
    runtime = await get_runtime()

    async def run(progress):
        progress({"stage": "night shift"})
        return await night.run_nightshift(record, runtime)

    return {"job_id": jobs().start("nightshift", repo_id, run)}


@router.get("/nightshift/schedule")
def night_schedule(repo_id: str, at: str = "02:00") -> dict:
    return night.schedule(Path(record_or_404(repo_id).path), at)


class BenchRequest(BaseModel):
    tasks: int = 10


@router.post("/bench")
async def start_bench(repo_id: str, body: BenchRequest | None = None) -> dict:
    record = record_or_404(repo_id)
    runtime = await get_runtime()
    models, _, hw = await scan()

    async def run(progress):
        progress({"stage": "benchmarking", "models": len(models)})
        return await run_bench(
            repo_id,
            Path(record.path),
            models,
            hw,
            n_tasks=(body.tasks if body else 10),
            embed_model=runtime.roles.get("embed"),
        )

    return {"job_id": jobs().start("bench", repo_id, run)}


@router.get("/bench/latest")
def bench_latest(repo_id: str) -> dict:
    record_or_404(repo_id)
    result = latest_bench(repo_id)
    if not result:
        raise HTTPException(404, "No benchmark has been run for this repository yet.")
    return result.model_dump()
