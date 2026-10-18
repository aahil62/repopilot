import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from repopilot.api.main import create_app
from repopilot.runtime import FakeRuntime
from repopilot.runtime.client import ModelClient
from repopilot.runtime.detect import ModelInfo, detect_models
from repopilot.runtime.hardware import Hardware
from repopilot.runtime.roles import NoRuntimeError, assign_roles
from repopilot.runtime.structured import ModelOutputError, structured_call

GB = 1024**3
HW16 = Hardware(total_ram_bytes=16 * GB, gpu="Apple M4", vram_bytes=12 * GB, unified_memory=True)


def model(name, size_gb=None, embed=False):
    return ModelInfo(name, "ollama", "http://x", int(size_gb * GB) if size_gb else None, None, embed)


def test_assign_roles_prefers_defaults():
    models = [
        model("llama3:8b", 4.7),
        model("qwen2.5-coder:7b", 4.7),
        model("qwen2.5-coder:1.5b", 1.0),
        model("nomic-embed-text", 0.3, embed=True),
    ]
    roles = assign_roles(models, HW16)
    assert roles["strong"].id == "qwen2.5-coder:7b"
    assert roles["fast"].id == "qwen2.5-coder:1.5b"
    assert roles["embed"].id == "nomic-embed-text"


def test_assign_roles_excludes_models_too_big():
    models = [model("qwen3-coder:30b", 19), model("mistral:7b", 4.1), model("phi3:mini", 2.2)]
    roles = assign_roles(models, HW16)  # budget = 0.8 * 12 GB = 9.6 GB
    assert roles["strong"].id == "mistral:7b"
    assert roles["fast"].id == "phi3:mini"
    assert roles["embed"].id == "phi3:mini"  # no embedding model installed -> fast model embeds


def test_assign_roles_overrides_win():
    models = [model("qwen2.5-coder:7b", 4.7), model("mistral:7b", 4.1)]
    assert assign_roles(models, HW16, {"strong": "mistral:7b"})["strong"].id == "mistral:7b"


def test_assign_roles_without_chat_model_raises():
    with pytest.raises(NoRuntimeError):
        assign_roles([model("nomic-embed-text", 0.3, embed=True)], HW16)


class Answer(BaseModel):
    verdict: str
    score: int


async def test_structured_call_retries_then_succeeds():
    fake = FakeRuntime({"strong": ["not json", '```json\n{"verdict": "ok", "score": 3}\n```']})
    result = await structured_call(fake, "strong", Answer, [{"role": "user", "content": "go"}])
    assert result == Answer(verdict="ok", score=3)
    assert len(fake.calls) == 2
    assert "invalid" in fake.calls[1]["messages"][-1]["content"]
    assert fake.calls[0]["json_schema"]["title"] == "Answer"


async def test_structured_call_raises_after_retries():
    fake = FakeRuntime({"strong": ['{"verdict": 1}']})
    with pytest.raises(ModelOutputError):
        await structured_call(fake, "strong", Answer, [{"role": "user", "content": "go"}], retries=2)
    assert len(fake.calls) == 3


async def test_ollama_request_sets_num_ctx_and_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"message": {"content": "{}"}, "eval_count": 50, "eval_duration": 1_000_000_000}
        )

    m = ModelInfo("qwen2.5-coder:7b", "ollama", "http://127.0.0.1:11434", context_length=131072)
    client = ModelClient(
        {"strong": m, "fast": m, "embed": m}, http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await client.chat("strong", [{"role": "user", "content": "hi"}], json_schema={"type": "object"})
    assert seen["url"].endswith("/api/chat")
    assert seen["body"]["options"]["num_ctx"] == 32768
    assert seen["body"]["format"] == {"type": "object"}
    assert client.stats["strong"]["tokens_per_second"] == 50.0


async def test_openai_compat_request_uses_json_schema_response_format():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{}"}}], "usage": {"completion_tokens": 3}}
        )

    m = ModelInfo("local-model", "openai_compat", "http://127.0.0.1:1234/v1")
    client = ModelClient(
        {"strong": m, "fast": m, "embed": m}, http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await client.chat("strong", [{"role": "user", "content": "hi"}], json_schema={"type": "object"})
    assert seen["body"]["response_format"]["type"] == "json_schema"


async def test_detect_models_marks_embeddings_and_unreachable():
    def handler(request):
        if request.url.host == "down":
            raise httpx.ConnectError("refused")
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen2.5-coder:7b",
                            "size": 4_700_000_000,
                            "details": {"families": ["qwen2"]},
                        },
                        {
                            "name": "nomic-embed-text:latest",
                            "size": 274_000_000,
                            "details": {"families": ["nomic-bert"]},
                        },
                    ]
                },
            )
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"qwen2.context_length": 32768}})
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    models, statuses = await detect_models(["http://up:11434", "http://down:1234/v1"], http=http)
    by_id = {m.id: m for m in models}
    assert by_id["qwen2.5-coder:7b"].context_length == 32768
    assert by_id["nomic-embed-text:latest"].is_embedding
    assert [s.reachable for s in statuses] == [True, False]


def test_no_runtime_returns_503(monkeypatch):
    from repopilot.config import reset_settings

    monkeypatch.setenv("REPOPILOT_RUNTIME_URLS", '["http://127.0.0.1:9"]')
    reset_settings()
    client = TestClient(create_app())
    resp = client.put("/models/roles", json={"strong": "x"})
    assert resp.status_code == 503
    assert resp.json()["detail"].startswith("No local model runtime found")
    listing = client.get("/models").json()
    assert listing["roles"] == {} and listing["runtimes"][0]["reachable"] is False
