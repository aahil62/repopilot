"""Talk to local model runtimes. Only localhost/LAN URLs configured by the user are ever called."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Protocol

import httpx

from repopilot.runtime.detect import ModelInfo
from repopilot.runtime.roles import Role

Message = dict[str, str]
DEFAULT_CTX = 8192
MAX_CTX = 32768


class Runtime(Protocol):
    roles: dict[Role, ModelInfo]

    async def chat(
        self,
        role: Role,
        messages: list[Message],
        *,
        json_schema: dict | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str: ...

    def stream_chat(
        self, role: Role, messages: list[Message], *, max_tokens: int = 2048
    ) -> AsyncIterator[str]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ModelClient:
    """Calls Ollama (/api/*) or OpenAI-compatible (/v1/*) servers for the assigned roles."""

    def __init__(
        self, roles: dict[Role, ModelInfo], http: httpx.AsyncClient | None = None, timeout: float = 600
    ):
        self.roles = roles
        self._http = http or httpx.AsyncClient(timeout=timeout)
        self.stats: dict[str, dict[str, float]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _num_ctx(model: ModelInfo) -> int:
        return min(model.context_length or DEFAULT_CTX, MAX_CTX)

    def _record(self, role: Role, tokens: int | None, seconds: float) -> None:
        if tokens and seconds > 0:
            self.stats[role] = {
                "tokens": tokens,
                "seconds": round(seconds, 3),
                "tokens_per_second": round(tokens / seconds, 1),
            }

    async def chat(
        self,
        role: Role,
        messages: list[Message],
        *,
        json_schema: dict | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> str:
        model = self.roles[role]
        started = time.perf_counter()
        if model.runtime == "ollama":
            body: dict = {
                "model": model.id,
                "messages": messages,
                "stream": False,
                "options": {
                    "num_ctx": self._num_ctx(model),
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            if json_schema is not None:
                body["format"] = json_schema
            data = (await self._http.post(f"{model.base_url}/api/chat", json=body)).raise_for_status().json()
            eval_ns = data.get("eval_duration") or 0
            self._record(
                role, data.get("eval_count"), eval_ns / 1e9 if eval_ns else time.perf_counter() - started
            )
            return data["message"]["content"]
        body = {"model": model.id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "out", "schema": json_schema},
            }
        data = (
            (await self._http.post(f"{model.base_url}/chat/completions", json=body)).raise_for_status().json()
        )
        self._record(role, (data.get("usage") or {}).get("completion_tokens"), time.perf_counter() - started)
        return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self, role: Role, messages: list[Message], *, max_tokens: int = 2048
    ) -> AsyncIterator[str]:
        model = self.roles[role]
        if model.runtime == "ollama":
            body = {
                "model": model.id,
                "messages": messages,
                "stream": True,
                "options": {"num_ctx": self._num_ctx(model), "temperature": 0.1, "num_predict": max_tokens},
            }
            async with self._http.stream("POST", f"{model.base_url}/api/chat", json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if text := (chunk.get("message") or {}).get("content"):
                        yield text
                    if chunk.get("done"):
                        break
            return
        body = {"model": model.id, "messages": messages, "max_tokens": max_tokens, "stream": True}
        async with self._http.stream("POST", f"{model.base_url}/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                delta = json.loads(payload)["choices"][0].get("delta") or {}
                if text := delta.get("content"):
                    yield text

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self.roles["embed"]
        if model.runtime == "ollama":
            data = (
                (
                    await self._http.post(
                        f"{model.base_url}/api/embed", json={"model": model.id, "input": texts}
                    )
                )
                .raise_for_status()
                .json()
            )
            return data["embeddings"]
        data = (
            (await self._http.post(f"{model.base_url}/embeddings", json={"model": model.id, "input": texts}))
            .raise_for_status()
            .json()
        )
        return [item["embedding"] for item in sorted(data["data"], key=lambda d: d.get("index", 0))]


# --------------------------------------------------------------------------- test double

Responder = str | Callable[[list[Message]], str]
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def hashed_embedding(text: str, dim: int = 256) -> list[float]:
    """Deterministic bag-of-words vector so similarity behaves sensibly in tests and offline demos."""
    vec = [0.0] * dim
    for token in _WORD.findall(text.lower()):
        for part in [token, *token.split("_")]:
            if part:
                vec[int(hashlib.md5(part.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeRuntime:
    """Scripted runtime for tests: responses are consumed in order per role; the last one repeats."""

    def __init__(self, responses: dict[str, list[Responder]] | None = None):
        fake = ModelInfo(id="fake-model", runtime="ollama", base_url="http://fake")
        self.roles: dict[Role, ModelInfo] = {"fast": fake, "strong": fake, "embed": fake}
        self.responses = {k: list(v) for k, v in (responses or {}).items()}
        self.calls: list[dict] = []
        self.embed_calls: list[list[str]] = []
        self.stats: dict[str, dict[str, float]] = {}

    def _next(self, role: str, messages: list[Message]) -> str:
        queue = self.responses.get(role) or self.responses.get("*") or ["{}"]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        return item(messages) if callable(item) else item

    async def chat(self, role, messages, *, json_schema=None, max_tokens=2048, temperature=0.1) -> str:
        self.calls.append({"role": role, "messages": messages, "json_schema": json_schema})
        return self._next(role, messages)

    async def stream_chat(self, role, messages, *, max_tokens=2048) -> AsyncIterator[str]:
        self.calls.append({"role": role, "messages": messages, "stream": True})
        text = self._next(role, messages)
        for piece in re.findall(r"\S+\s*", text):
            yield piece

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [hashed_embedding(t) for t in texts]
