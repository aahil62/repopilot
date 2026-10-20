"""Background jobs (index, review, edit, bench, night shift) with progress, persisted across restarts."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from repopilot.config import get_settings

Progress = Callable[[dict], None]
JobFn = Callable[[Progress], Awaitable[Any]]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobRegistry:
    def __init__(self) -> None:
        path = get_settings().home / "jobs.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, kind TEXT, repo_id TEXT, status TEXT, "
            "created_at TEXT, updated_at TEXT, progress TEXT, result TEXT, error TEXT)"
        )
        # Jobs interrupted by a restart can never finish.
        self._db.execute(
            "UPDATE jobs SET status='failed', error='Interrupted by restart' WHERE status IN ('queued','running')"
        )
        self._tasks: dict[str, asyncio.Task] = {}
        self._events: dict[str, list[asyncio.Queue]] = {}

    def _write(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE jobs SET {sets} WHERE job_id=?", (*fields.values(), job_id))

    def _publish(self, job_id: str, event: dict) -> None:
        for queue in self._events.get(job_id, []):
            queue.put_nowait(event)

    def start(self, kind: str, repo_id: str | None, fn: JobFn) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO jobs(job_id,kind,repo_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (job_id, kind, repo_id, "queued", _now(), _now()),
            )

        def progress(data: dict) -> None:
            self._write(job_id, progress=json.dumps(data))
            self._publish(job_id, {"status": "running", "progress": data})

        async def runner() -> None:
            self._write(job_id, status="running")
            try:
                result = await fn(progress)
                payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
                self._write(job_id, status="done", result=json.dumps(payload))
                self._publish(job_id, {"status": "done", "result": payload})
            except Exception as exc:  # noqa: BLE001 - surfaced to the client as a failed job
                message = f"{type(exc).__name__}: {exc}"
                self._write(job_id, status="failed", error=message)
                self._publish(
                    job_id, {"status": "failed", "error": message, "trace": traceback.format_exc()[-1500:]}
                )
            finally:
                self._tasks.pop(job_id, None)

        self._tasks[job_id] = asyncio.get_running_loop().create_task(runner())
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("progress", "result"):
            data[key] = json.loads(data[key]) if data[key] else None
        return data

    def latest(self, repo_id: str, kind: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT job_id FROM jobs WHERE repo_id=? AND kind=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (repo_id, kind),
            ).fetchone()
        return self.get(row["job_id"]) if row else None

    def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._events.setdefault(job_id, []).append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        if queue in self._events.get(job_id, []):
            self._events[job_id].remove(queue)

    async def wait(self, job_id: str) -> dict:
        task = self._tasks.get(job_id)
        if task:
            await task
        return self.get(job_id) or {}


_registry: JobRegistry | None = None


def jobs() -> JobRegistry:
    global _registry
    if _registry is None:
        _registry = JobRegistry()
    return _registry


def reset_jobs() -> None:
    global _registry
    _registry = None
