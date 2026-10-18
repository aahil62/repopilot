from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, model_validator
from sse_starlette.sse import EventSourceResponse

from repopilot.api.jobs import jobs
from repopilot.config import get_settings
from repopilot.engines.ask import calibrate_refusal
from repopilot.engines.checks import detect_test_command, load_repo_settings, repo_settings_path
from repopilot.memory import registry
from repopilot.memory.pipeline import index_repo, repo_summary
from repopilot.memory.store import MemoryStore
from repopilot.runtime import get_runtime_optional

router = APIRouter(prefix="/api/repos", tags=["repos"])


def record_or_404(repo_id: str) -> registry.RepoRecord:
    try:
        return registry.get_repo(repo_id)
    except KeyError:
        raise HTTPException(404, f"Unknown repository {repo_id}") from None


class AddRepo(BaseModel):
    path: str | None = None
    git_url: str | None = None

    @model_validator(mode="after")
    def one_source(self) -> AddRepo:
        if bool(self.path) == bool(self.git_url):
            raise ValueError("Provide exactly one of `path` or `git_url`.")
        return self


@router.get("")
def list_repos() -> list[dict]:
    return [repo_summary(r) for r in registry.list_repos()]


@router.post("")
async def add_repo(body: AddRepo) -> dict:
    try:
        if body.path:
            record = registry.add_local(body.path)
        else:
            record = await asyncio.to_thread(registry.add_clone, body.git_url)
    except registry.RepoError as exc:
        raise HTTPException(400, str(exc)) from None
    return repo_summary(record)


@router.get("/{repo_id}")
def get_repo(repo_id: str) -> dict:
    return repo_summary(record_or_404(repo_id))


@router.delete("/{repo_id}")
def delete_repo(repo_id: str) -> dict:
    record_or_404(repo_id)
    MemoryStore.close_all()
    shutil.rmtree(get_settings().home / "repos" / repo_id, ignore_errors=True)
    registry.remove_repo(repo_id)
    return {"deleted": repo_id}


class IndexRequest(BaseModel):
    with_reviews: bool = False


@router.post("/{repo_id}/index")
async def start_index(repo_id: str, body: IndexRequest | None = None) -> dict:
    record = record_or_404(repo_id)
    runtime = await get_runtime_optional()

    async def run(progress):
        stats = await index_repo(
            record, runtime, lambda p: progress(p.to_dict()), with_reviews=bool(body and body.with_reviews)
        )
        if runtime is not None:
            await calibrate_refusal(MemoryStore.open(repo_id), runtime)
        return stats.to_dict()

    return {"job_id": jobs().start("index", repo_id, run)}


@router.get("/{repo_id}/progress")
async def index_progress(repo_id: str) -> EventSourceResponse:
    record_or_404(repo_id)
    job = jobs().latest(repo_id, "index")

    async def events():
        if not job:
            yield {"event": "status", "data": json.dumps({"status": "idle"})}
            return
        if job["status"] in ("done", "failed"):
            yield {
                "event": "status",
                "data": json.dumps({k: job[k] for k in ("status", "progress", "result", "error")}),
            }
            return
        queue = jobs().subscribe(job["job_id"])
        try:
            while True:
                event = await queue.get()
                yield {"event": "status", "data": json.dumps(event)}
                if event["status"] in ("done", "failed"):
                    return
        finally:
            jobs().unsubscribe(job["job_id"], queue)

    return EventSourceResponse(events())


@router.get("/{repo_id}/files")
def list_files(repo_id: str, q: str = "", limit: int = Query(50, le=500)) -> list[dict]:
    record_or_404(repo_id)
    rows = MemoryStore.open(repo_id).query("SELECT path, language, lines FROM files ORDER BY path")
    needle = q.lower()

    def score(path: str) -> int:
        if not needle:
            return 0
        if needle in path.lower():
            return 0 if path.lower().endswith(needle) else 1
        it = iter(path.lower())
        return 2 if all(ch in it for ch in needle) else 99

    ranked = sorted(
        (r for r in rows if score(r["path"]) < 99), key=lambda r: (score(r["path"]), len(r["path"]))
    )
    return [dict(r) for r in ranked[:limit]]


@router.get("/{repo_id}/file")
def read_file(repo_id: str, path: str, start: int = 1, end: int | None = None) -> dict:
    record = record_or_404(repo_id)
    root = Path(record.path).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404, "File not found in repository.")
    lines = target.read_text(errors="replace").splitlines()
    end = min(end or len(lines), len(lines))
    return {
        "path": path,
        "start": start,
        "end": end,
        "total_lines": len(lines),
        "lines": lines[start - 1 : end],
    }


class RepoSettings(BaseModel):
    test_command: str | None = None


@router.get("/{repo_id}/settings")
def get_repo_settings(repo_id: str) -> dict:
    root = Path(record_or_404(repo_id).path)
    return {**load_repo_settings(root), "detected_test_command": detect_test_command(root)}


@router.put("/{repo_id}/settings")
def put_repo_settings(repo_id: str, body: RepoSettings) -> dict:
    root = Path(record_or_404(repo_id).path)
    data = {**load_repo_settings(root), **body.model_dump()}
    repo_settings_path(root).write_text(json.dumps(data, indent=2))
    return {**data, "detected_test_command": detect_test_command(root)}
