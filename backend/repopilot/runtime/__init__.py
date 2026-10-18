"""Process-wide access to the local model runtime."""

from __future__ import annotations

from repopilot.config import get_settings
from repopilot.runtime.client import FakeRuntime, ModelClient, Runtime
from repopilot.runtime.detect import ModelInfo, RuntimeStatus, detect_models
from repopilot.runtime.hardware import Hardware, hardware
from repopilot.runtime.roles import NoRuntimeError, assign_roles, fits, load_overrides

_override: Runtime | None = None
_cached: ModelClient | None = None


def set_runtime(runtime: Runtime | None) -> None:
    """Install a runtime (tests use FakeRuntime); None restores auto-detection."""
    global _override, _cached
    _override = runtime
    _cached = None


def clear_cache() -> None:
    """Forget the auto-detected runtime (e.g. after role overrides change); keeps any test override."""
    global _cached
    _cached = None


async def scan() -> tuple[list[ModelInfo], list[RuntimeStatus], Hardware]:
    settings = get_settings()
    models, statuses = await detect_models(settings.runtime_urls)
    return models, statuses, hardware()


async def get_runtime(refresh: bool = False) -> Runtime:
    global _cached
    if _override is not None:
        return _override
    if _cached is not None and not refresh:
        return _cached
    models, statuses, hw = await scan()
    try:
        roles = assign_roles(models, hw, load_overrides(get_settings().home / "models.json"))
    except NoRuntimeError as exc:
        exc.statuses = statuses  # type: ignore[attr-defined]
        raise
    _cached = ModelClient(roles)
    return _cached


__all__ = [
    "FakeRuntime",
    "Hardware",
    "clear_cache",
    "ModelClient",
    "ModelInfo",
    "NoRuntimeError",
    "Runtime",
    "RuntimeStatus",
    "fits",
    "get_runtime",
    "scan",
    "set_runtime",
]
