from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from repopilot.config import get_settings
from repopilot.runtime import clear_cache, fits, get_runtime, scan
from repopilot.runtime.roles import NoRuntimeError, assign_roles, load_overrides, save_overrides

router = APIRouter(tags=["models"])


@router.get("/models")
async def list_models() -> dict:
    models, statuses, hw = await scan()
    overrides = load_overrides(get_settings().home / "models.json")
    try:
        roles = {role: m.id for role, m in assign_roles(models, hw, overrides).items()}
    except NoRuntimeError:
        roles = {}
    return {
        "runtimes": [s.__dict__ for s in statuses],
        "models": [{**m.to_dict(), "fits": fits(m, hw)} for m in models],
        "roles": roles,
        "hardware": hw.to_dict(),
    }


class RoleUpdate(BaseModel):
    fast: str | None = None
    strong: str | None = None
    embed: str | None = None


@router.put("/models/roles")
async def update_roles(update: RoleUpdate) -> dict:
    path = get_settings().home / "models.json"
    merged = {**load_overrides(path), **update.model_dump(exclude_none=True)}
    save_overrides(path, merged)
    clear_cache()
    runtime = await get_runtime(refresh=True)
    return {"roles": {role: m.id for role, m in runtime.roles.items()}}
