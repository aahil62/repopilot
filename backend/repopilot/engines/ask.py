"""Grounded Q&A: hybrid retrieval (vectors + full-text) fused with RRF; answers cite exact line ranges."""

from __future__ import annotations

import random
import re
from collections.abc import AsyncIterator

from pydantic import BaseModel

from repopilot.memory.indexer import CODE_COLLECTION
from repopilot.memory.store import MemoryStore
from repopilot.runtime.client import Runtime

RRF_K = 60
TOP_K = 8
CANDIDATES = 20
WHY_RE = re.compile(r"(?i)\bwhy\b|\breason\b|\bhistory\b|\bwhen did\b")
CITE_RE = re.compile(r"\[(\d{1,2})\]")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
STOP = {
    "the",
    "and",
    "for",
    "how",
    "what",
    "where",
    "which",
    "does",
    "this",
    "that",
    "with",
    "from",
    "into",
    "are",
    "is",
    "in",
    "of",
    "to",
    "do",
    "we",
    "be",
    "it",
    "a",
    "an",
    "on",
    "by",
    "or",
    "why",
    "when",
    "who",
    "use",
    "used",
}
NOT_FOUND = "I couldn't find this in the repository."
DEFAULT_THRESHOLD = 0.35

SYSTEM = """You answer questions about a code repository using ONLY the numbered context blocks.
Cite every claim with the block number in square brackets, like [2]. Never cite a number that is not listed.
If the context does not contain the answer, reply exactly: "I couldn't find this in the repository."
Be concise and specific; mention function and file names."""


class Citation(BaseModel):
    n: int
    path: str
    start_line: int
    end_line: int
    snippet: str


class CommitRef(BaseModel):
    sha: str
    date: str
    subject: str
    author: str


class AskResult(BaseModel):
    answer: str
    citations: list[Citation]
    commits: list[CommitRef]
    refused: bool
    removed_citations: int


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _terms(question: str) -> list[str]:
    terms: list[str] = []
    for word in WORD_RE.findall(question):
        parts = [word, *re.split(r"_|(?<=[a-z])(?=[A-Z])", word)]
        terms += [p.lower() for p in parts if len(p) > 2 and p.lower() not in STOP]
    return list(dict.fromkeys(terms))


def lexical_search(store: MemoryStore, question: str, k: int = CANDIDATES) -> list[str]:
    terms = _terms(question)
    if not terms:
        return []
    match = " OR ".join(f'"{t}"' for t in terms[:12])
    rows = store.query(
        "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (match, k)
    )
    return [r["chunk_id"] for r in rows]


async def calibrate_refusal(store: MemoryStore, runtime: Runtime, sample: int = 40) -> float:
    names = [
        r["name"] for r in store.query("SELECT DISTINCT name FROM symbols WHERE kind IN ('function','class')")
    ]
    if len(names) < 5:
        store.set_meta("refusal_threshold", str(DEFAULT_THRESHOLD))
        return DEFAULT_THRESHOLD
    random.Random(7).shuffle(names)
    queries = [f"where is {n.replace('_', ' ')} defined" for n in names[:sample]]
    vectors = await runtime.embed(queries)
    tops = sorted(hits[0][1] for v in vectors if (hits := store.search(CODE_COLLECTION, v, k=1)))
    # A real question about the repo should score at least ~60% of a typical "where is <symbol>" match.
    threshold = round(tops[len(tops) // 2] * 0.6, 4) if tops else DEFAULT_THRESHOLD
    store.set_meta("refusal_threshold", str(threshold))
    return threshold


def _why_commits(store: MemoryStore, question: str, paths: list[str]) -> list[CommitRef]:
    terms = _terms(question)
    if not terms and not paths:
        return []
    clauses, params = [], []
    for t in terms[:6]:
        clauses.append("(lower(c.subject) LIKE ? OR lower(c.body) LIKE ?)")
        params += [f"%{t}%", f"%{t}%"]
    if paths:
        clauses.append(
            f"c.sha IN (SELECT sha FROM commit_files WHERE path IN ({','.join('?' * len(paths))}))"
        )
        params += paths
    rows = store.query(
        f"SELECT DISTINCT c.sha, c.date, c.subject, c.author FROM commits c WHERE {' OR '.join(clauses)} "
        "ORDER BY c.seq DESC LIMIT 3",
        tuple(params),
    )
    return [CommitRef(**dict(r)) for r in rows]


async def retrieve(store: MemoryStore, runtime: Runtime, question: str) -> tuple[list[dict], bool]:
    [qvec] = await runtime.embed([question])
    vector_hits = store.search(CODE_COLLECTION, qvec, k=CANDIDATES)
    lexical = lexical_search(store, question)
    fused = rrf([[key for key, _ in vector_hits], lexical])[:TOP_K]
    best_vec = vector_hits[0][1] if vector_hits else 0.0
    threshold = float(store.get_meta("refusal_threshold") or DEFAULT_THRESHOLD)
    refuse = not fused or (best_vec < threshold and not lexical)
    chunks = []
    for key, _ in fused:
        row = store.one(
            "SELECT chunk_id, path, start_line, end_line, symbol, text FROM chunks WHERE chunk_id=?", (key,)
        )
        if row:
            chunks.append(dict(row))
    return chunks, refuse


def _context(chunks: list[dict], commits: list[CommitRef]) -> str:
    blocks = [
        f"[{i}] {c['path']} lines {c['start_line']}-{c['end_line']}\n{c['text'][:1800]}"
        for i, c in enumerate(chunks, 1)
    ]
    if commits:
        blocks.append(
            "Relevant commits:\n" + "\n".join(f"- {c.sha[:8]} {c.date[:10]} {c.subject}" for c in commits)
        )
    return "\n\n".join(blocks)


def clean_citations(answer: str, valid: set[int]) -> tuple[str, list[int], int]:
    used, removed = [], 0

    def keep(match: re.Match) -> str:
        nonlocal removed
        n = int(match.group(1))
        if n in valid:
            if n not in used:
                used.append(n)
            return match.group(0)
        removed += 1
        return ""

    cleaned = CITE_RE.sub(keep, answer)
    if removed:
        s = "s" if removed > 1 else ""
        cleaned = cleaned.rstrip() + f"\n\n_{removed} unsupported citation{s} removed._"
    return cleaned, used, removed


async def ask_stream(store: MemoryStore, runtime: Runtime, question: str) -> AsyncIterator[dict]:
    chunks, refuse = await retrieve(store, runtime, question)
    yield {
        "event": "retrieval",
        "data": [
            {"path": c["path"], "start_line": c["start_line"], "end_line": c["end_line"]} for c in chunks
        ],
    }
    commits = (
        _why_commits(store, question, list(dict.fromkeys(c["path"] for c in chunks[:3])))
        if WHY_RE.search(question)
        else []
    )
    if refuse:
        closest = ", ".join(dict.fromkeys(c["path"] for c in chunks[:3])) or "none"
        text = f"{NOT_FOUND} Closest files: {closest}."
        yield {"event": "token", "data": text}
        yield {"event": "citations", "data": []}
        yield {"event": "done", "data": {"refused": True, "removed_citations": 0, "commits": []}}
        return
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{_context(chunks, commits)}\n\nQuestion: {question}"},
    ]
    answer = ""
    async for piece in runtime.stream_chat("strong", messages, max_tokens=900):
        answer += piece
        yield {"event": "token", "data": piece}
    _, used, removed = clean_citations(answer, set(range(1, len(chunks) + 1)))
    cites = [
        Citation(
            n=n,
            path=chunks[n - 1]["path"],
            start_line=chunks[n - 1]["start_line"],
            end_line=chunks[n - 1]["end_line"],
            snippet=chunks[n - 1]["text"][:400],
        ).model_dump()
        for n in used
    ]
    yield {"event": "citations", "data": cites}
    yield {
        "event": "done",
        "data": {
            "refused": NOT_FOUND in answer,
            "removed_citations": removed,
            "commits": [c.model_dump() for c in commits],
        },
    }


async def ask(store: MemoryStore, runtime: Runtime, question: str) -> AskResult:
    answer, citations, commits, refused, removed = "", [], [], False, 0
    async for event in ask_stream(store, runtime, question):
        if event["event"] == "token":
            answer += event["data"]
        elif event["event"] == "citations":
            citations = [Citation(**c) for c in event["data"]]
        elif event["event"] == "done":
            refused, removed = event["data"]["refused"], event["data"]["removed_citations"]
            commits = [CommitRef(**c) for c in event["data"]["commits"]]
    cleaned, _, _ = clean_citations(answer, {c.n for c in citations} | set(range(1, TOP_K + 1)))
    if removed:
        cleaned, _, _ = clean_citations(answer, {c.n for c in citations})
    return AskResult(
        answer=cleaned, citations=citations, commits=commits, refused=refused, removed_citations=removed
    )
