"""Assign installed models to the three jobs RepoPilot needs: fast, strong and embed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from repopilot.runtime.detect import ModelInfo
from repopilot.runtime.hardware import Hardware

Role = Literal["fast", "strong", "embed"]
ROLES: tuple[Role, ...] = ("fast", "strong", "embed")
PREFERRED: dict[Role, tuple[str, ...]] = {
    "strong": ("qwen2.5-coder:7b", "qwen2.5-coder:14b", "qwen3-coder:30b", "gpt-oss:20b"),
    "fast": ("qwen2.5-coder:1.5b", "qwen2.5-coder:3b", "llama3.2:3b"),
    "embed": ("nomic-embed-text", "nomic-embed-text:latest", "mxbai-embed-large"),
}


class NoRuntimeError(RuntimeError):
    """No reachable runtime serves a usable chat model."""


def fits(model: ModelInfo, hw: Hardware) -> bool:
    return model.size_bytes is None or model.size_bytes <= hw.model_budget_bytes


def _match(models: list[ModelInfo], name: str) -> ModelInfo | None:
    for model in models:
        if model.id == name or model.id == f"{name}:latest" or model.id.split(":latest")[0] == name:
            return model
    return None


def load_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if k in ROLES and isinstance(v, str)}


def save_overrides(path: Path, overrides: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: v for k, v in overrides.items() if k in ROLES}, indent=2))


def assign_roles(
    models: list[ModelInfo], hw: Hardware, overrides: dict[str, str] | None = None
) -> dict[Role, ModelInfo]:
    overrides = overrides or {}
    chat = [m for m in models if not m.is_embedding and fits(m, hw)]
    embeds = [m for m in models if m.is_embedding]
    if not chat:
        raise NoRuntimeError("No local chat model found that fits this machine.")

    def size(model: ModelInfo) -> int:
        return model.size_bytes or 0

    def pick(role: Role, pool: list[ModelInfo], fallback: ModelInfo | None) -> ModelInfo | None:
        if role in overrides:
            chosen = _match(models, overrides[role])
            if chosen:
                return chosen
        for name in PREFERRED[role]:
            chosen = _match(pool, name)
            if chosen:
                return chosen
        return fallback

    roles: dict[Role, ModelInfo] = {
        "strong": pick("strong", chat, max(chat, key=size)),
        "fast": pick("fast", chat, min(chat, key=size)),
    }
    embed = pick("embed", embeds, embeds[0] if embeds else None)
    # Without a dedicated embedding model, fall back to embedding with the fast chat model.
    roles["embed"] = embed or roles["fast"]
    return roles
