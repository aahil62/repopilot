"""Per-repository memory: one SQLite file holding code chunks, vectors, symbols, history and reviews."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from repopilot.config import get_settings

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY, sha1 TEXT NOT NULL, language TEXT NOT NULL, size INTEGER NOT NULL,
    lines INTEGER NOT NULL DEFAULT 0, indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY, path TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
    kind TEXT NOT NULL, symbol TEXT, text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, path, symbol, text, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, collection TEXT NOT NULL, vec BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS vectors_collection ON vectors(collection);
CREATE TABLE IF NOT EXISTS symbols (
    name TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS symbols_path ON symbols(path);
CREATE INDEX IF NOT EXISTS symbols_name ON symbols(name);
CREATE TABLE IF NOT EXISTS imports (path TEXT NOT NULL, spec TEXT NOT NULL, names TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS imports_path ON imports(path);
CREATE TABLE IF NOT EXISTS commits (
    sha TEXT PRIMARY KEY, author TEXT NOT NULL, email TEXT NOT NULL, date TEXT NOT NULL,
    subject TEXT NOT NULL, body TEXT NOT NULL, is_fix INTEGER NOT NULL, seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS commit_files (sha TEXT NOT NULL, path TEXT NOT NULL, added INTEGER, deleted INTEGER);
CREATE INDEX IF NOT EXISTS commit_files_path ON commit_files(path);
CREATE INDEX IF NOT EXISTS commit_files_sha ON commit_files(sha);
CREATE TABLE IF NOT EXISTS pr_commits (pr_number INTEGER NOT NULL, sha TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_comments (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, pr_number INTEGER, path TEXT, line INTEGER,
    body TEXT NOT NULL, author TEXT, date TEXT, verdict TEXT
);
CREATE TABLE IF NOT EXISTS reviews (review_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, source TEXT NOT NULL, report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, progress TEXT, result TEXT, error TEXT
);
"""


class MemoryStore:
    """Thread-safe wrapper around a repository's memory.sqlite."""

    _instances: dict[str, MemoryStore] = {}
    _lock = threading.Lock()

    def __init__(self, repo_id: str, path: Path | None = None):
        self.repo_id = repo_id
        self.path = path or get_settings().repo_dir(repo_id) / "memory.sqlite"
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db_lock = threading.RLock()
        self._db.executescript(SCHEMA)
        self._matrix_cache: dict[str, tuple[int, list[str], np.ndarray]] = {}
        self._version = 0

    @classmethod
    def open(cls, repo_id: str) -> MemoryStore:
        key = str(get_settings().repo_dir(repo_id))
        with cls._lock:
            store = cls._instances.get(key)
            if store is None:
                store = cls._instances[key] = cls(repo_id)
            return store

    @classmethod
    def close_all(cls) -> None:
        with cls._lock:
            for store in cls._instances.values():
                store._db.close()
            cls._instances.clear()

    # ------------------------------------------------------------------ sql helpers
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._db_lock:
            return self._db.execute(sql, params)

    def executemany(self, sql: str, rows: list) -> None:
        with self._db_lock:
            self._db.executemany(sql, rows)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._db_lock:
            return self._db.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._db_lock:
            return self._db.execute(sql, params).fetchone()

    @contextmanager
    def transaction(self):
        with self._db_lock:
            self._db.execute("BEGIN")
            try:
                yield self
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            self._version += 1

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ------------------------------------------------------------------ vectors
    def put_vectors(self, collection: str, items: list[tuple[str, list[float]]]) -> None:
        rows = [(key, collection, np.asarray(vec, dtype=np.float16).tobytes()) for key, vec in items]
        with self.transaction():
            self.executemany(
                "INSERT INTO vectors(key,collection,vec) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET vec=excluded.vec, collection=excluded.collection",
                rows,
            )

    def delete_vectors(self, keys: list[str]) -> None:
        if keys:
            with self.transaction():
                self.executemany("DELETE FROM vectors WHERE key=?", [(k,) for k in keys])

    def ensure_embedding_model(self, model_id: str) -> bool:
        """Vectors from different embedding models are incomparable: drop them all when the model changes.

        Returns True when existing vectors were discarded."""
        previous = self.get_meta("embed_model")
        if previous == model_id:
            return False
        had = self.one("SELECT count(*) n FROM vectors")["n"] > 0
        with self.transaction():
            self.execute("DELETE FROM vectors")
        self.set_meta("embed_model", model_id)
        return had

    def missing_vector_keys(self, collection: str, keys: list[str]) -> list[str]:
        have = {r["key"] for r in self.query("SELECT key FROM vectors WHERE collection=?", (collection,))}
        return [k for k in keys if k not in have]

    def _matrix(self, collection: str) -> tuple[list[str], np.ndarray]:
        cached = self._matrix_cache.get(collection)
        if cached and cached[0] == self._version:
            return cached[1], cached[2]
        rows = self.query("SELECT key, vec FROM vectors WHERE collection=?", (collection,))
        keys = [r["key"] for r in rows]
        if rows:
            mat = np.vstack([np.frombuffer(r["vec"], dtype=np.float16) for r in rows]).astype(np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            mat = mat / np.where(norms == 0, 1, norms)
        else:
            mat = np.zeros((0, 1), dtype=np.float32)
        self._matrix_cache[collection] = (self._version, keys, mat)
        return keys, mat

    def search(self, collection: str, query_vec: list[float], k: int = 10) -> list[tuple[str, float]]:
        keys, mat = self._matrix(collection)
        if not keys:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        if q.shape[0] != mat.shape[1]:
            return []
        q = q / (np.linalg.norm(q) or 1.0)
        scores = mat @ q
        top = np.argsort(-scores)[:k]
        return [(keys[i], float(scores[i])) for i in top]
