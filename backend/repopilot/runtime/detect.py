"""Discover local model runtimes (Ollama, LM Studio, llama.cpp) and the models they serve."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

RuntimeKind = Literal["ollama", "openai_compat"]
EMBED_HINTS = ("embed", "bge", "nomic", "e5-", "gte-", "minilm")


@dataclass(frozen=True)
class ModelInfo:
    id: str
    runtime: RuntimeKind
    base_url: str
    size_bytes: int | None = None
    context_length: int | None = None
    is_embedding: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeStatus:
    base_url: str
    kind: RuntimeKind
    reachable: bool
    error: str | None = None


def runtime_kind(url: str) -> RuntimeKind:
    return "openai_compat" if url.rstrip("/").endswith("/v1") else "ollama"


def looks_like_embedding(name: str, families: list[str] | None = None) -> bool:
    lowered = name.lower()
    if any(hint in lowered for hint in EMBED_HINTS):
        return True
    return bool(families) and "bert" in [f.lower() for f in families] and "coder" not in lowered


async def _ollama_models(http: httpx.AsyncClient, base: str) -> list[ModelInfo]:
    tags = (await http.get(f"{base}/api/tags")).raise_for_status().json()
    models: list[ModelInfo] = []
    for entry in tags.get("models", []):
        name = entry.get("name") or entry.get("model")
        families = (entry.get("details") or {}).get("families") or []
        is_embed = looks_like_embedding(name, families)
        context = None
        if not is_embed:
            try:
                show = (await http.post(f"{base}/api/show", json={"model": name})).raise_for_status().json()
                for key, value in (show.get("model_info") or {}).items():
                    if key.endswith(".context_length") and isinstance(value, int):
                        context = value
                        break
            except httpx.HTTPError:
                context = None
        models.append(
            ModelInfo(
                id=name,
                runtime="ollama",
                base_url=base,
                size_bytes=entry.get("size"),
                context_length=context,
                is_embedding=is_embed,
            )
        )
    return models


async def _openai_models(http: httpx.AsyncClient, base: str) -> list[ModelInfo]:
    payload = (await http.get(f"{base}/models")).raise_for_status().json()
    return [
        ModelInfo(
            id=item["id"],
            runtime="openai_compat",
            base_url=base,
            is_embedding=looks_like_embedding(item["id"]),
        )
        for item in payload.get("data", [])
        if item.get("id")
    ]


async def detect_models(
    urls: list[str], http: httpx.AsyncClient | None = None, timeout: float = 1.5
) -> tuple[list[ModelInfo], list[RuntimeStatus]]:
    """Return every model served by a reachable runtime, plus per-runtime reachability."""
    owned = http is None
    http = http or httpx.AsyncClient(timeout=timeout)
    try:

        async def probe(url: str) -> tuple[list[ModelInfo], RuntimeStatus]:
            base = url.rstrip("/")
            kind = runtime_kind(base)
            try:
                found = await (
                    _openai_models(http, base) if kind == "openai_compat" else _ollama_models(http, base)
                )
                return found, RuntimeStatus(base, kind, True)
            except (httpx.HTTPError, ValueError) as exc:
                return [], RuntimeStatus(base, kind, False, type(exc).__name__)

        results = await asyncio.gather(*(probe(url) for url in urls))
    finally:
        if owned:
            await http.aclose()
    models = [model for found, _ in results for model in found]
    return models, [status for _, status in results]
