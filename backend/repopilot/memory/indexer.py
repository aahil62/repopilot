"""Incremental indexing: only files whose content changed are re-chunked and re-embedded."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from repopilot.config import get_settings
from repopilot.memory.chunker import chunk_file
from repopilot.memory.files import iter_repo_files
from repopilot.memory.store import MemoryStore
from repopilot.memory.symbols import extract
from repopilot.runtime.client import Runtime

Stage = Literal["scanning", "chunking", "embedding", "graph", "history", "done"]
CODE_COLLECTION = "code"
EMBED_CHARS = 2000


@dataclass
class IndexProgress:
    stage: Stage
    done: int = 0
    total: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IndexStats:
    files_total: int = 0
    files_changed: int = 0
    files_removed: int = 0
    chunks_total: int = 0
    chunks_embedded: int = 0
    commits_imported: int = 0
    graph_edges: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


ProgressFn = Callable[[IndexProgress], None]


def chunk_id(path: str, start: int, end: int, digest: str) -> str:
    return hashlib.sha1(f"{path}:{start}:{end}:{digest}".encode()).hexdigest()[:16]


def embed_text(path: str, symbol: str | None, text: str) -> str:
    return f"{path}\n{symbol or ''}\n{text[:EMBED_CHARS]}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _remove_file(store: MemoryStore, path: str) -> list[str]:
    ids = [r["chunk_id"] for r in store.query("SELECT chunk_id FROM chunks WHERE path=?", (path,))]
    store.execute("DELETE FROM chunks WHERE path=?", (path,))
    store.execute("DELETE FROM chunks_fts WHERE path=?", (path,))
    store.execute("DELETE FROM symbols WHERE path=?", (path,))
    store.execute("DELETE FROM imports WHERE path=?", (path,))
    store.execute("DELETE FROM files WHERE path=?", (path,))
    return ids


async def index_code(
    store: MemoryStore, repo_path: Path, runtime: Runtime, progress: ProgressFn | None = None
) -> IndexStats:
    settings = get_settings()
    report = progress or (lambda _p: None)
    stats = IndexStats()

    report(IndexProgress("scanning", message="Listing files"))
    known = {r["path"]: r["sha1"] for r in store.query("SELECT path, sha1 FROM files")}
    seen: set[str] = set()
    changed: list[tuple[str, str, str, str]] = []  # path, language, sha1, text
    for repo_file in iter_repo_files(repo_path, settings):
        seen.add(repo_file.path)
        data = repo_file.abs_path.read_bytes()
        digest = hashlib.sha1(data).hexdigest()
        if known.get(repo_file.path) != digest:
            changed.append((repo_file.path, repo_file.language, digest, data.decode("utf-8", "replace")))
    stats.files_total = len(seen)
    if len(seen) >= settings.max_files:
        stats.notes.append(f"Stopped at the {settings.max_files:,}-file cap (REPOPILOT_MAX_FILES).")

    removed = [p for p in known if p not in seen]
    stale_vectors: list[str] = []
    with store.transaction():
        for path in removed:
            stale_vectors += _remove_file(store, path)
    stats.files_removed = len(removed)

    report(IndexProgress("chunking", 0, len(changed)))
    for i, (path, language, digest, text) in enumerate(changed, start=1):
        chunks = chunk_file(path, text, language)
        symbols, imports = extract(path, text, language)
        with store.transaction():
            stale_vectors += _remove_file(store, path)
            store.execute(
                "INSERT INTO files(path,sha1,language,size,lines,indexed_at) VALUES(?,?,?,?,?,?)",
                (path, digest, language, len(text.encode()), text.count("\n") + 1, _now()),
            )
            rows = [
                (
                    chunk_id(path, c.start_line, c.end_line, digest),
                    path,
                    c.start_line,
                    c.end_line,
                    c.kind,
                    c.symbol,
                    c.text,
                )
                for c in chunks
            ]
            store.executemany(
                "INSERT OR REPLACE INTO chunks(chunk_id,path,start_line,end_line,kind,symbol,text) VALUES(?,?,?,?,?,?,?)",
                rows,
            )
            store.executemany(
                "INSERT INTO chunks_fts(chunk_id,path,symbol,text) VALUES(?,?,?,?)",
                [(r[0], r[1], r[5] or "", r[6]) for r in rows],
            )
            store.executemany(
                "INSERT INTO symbols(name,kind,path,start_line,end_line) VALUES(?,?,?,?,?)",
                [(s.name, s.kind, s.path, s.start_line, s.end_line) for s in symbols],
            )
            store.executemany(
                "INSERT INTO imports(path,spec,names) VALUES(?,?,?)",
                [(m.path, m.spec, m.names) for m in imports],
            )
        if i % 50 == 0 or i == len(changed):
            report(IndexProgress("chunking", i, len(changed)))
    stats.files_changed = len(changed)
    store.delete_vectors(stale_vectors)

    all_chunks = store.query("SELECT chunk_id, path, symbol, text FROM chunks")
    stats.chunks_total = len(all_chunks)
    missing = set(store.missing_vector_keys(CODE_COLLECTION, [r["chunk_id"] for r in all_chunks]))
    pending = [r for r in all_chunks if r["chunk_id"] in missing]
    batch = settings.embed_batch
    report(IndexProgress("embedding", 0, len(pending)))
    for start in range(0, len(pending), batch):
        group = pending[start : start + batch]
        vectors = await runtime.embed([embed_text(r["path"], r["symbol"], r["text"]) for r in group])
        store.put_vectors(CODE_COLLECTION, [(r["chunk_id"], v) for r, v in zip(group, vectors, strict=True)])
        stats.chunks_embedded += len(group)
        report(IndexProgress("embedding", stats.chunks_embedded, len(pending)))

    store.set_meta("indexed_at", _now())
    return stats
