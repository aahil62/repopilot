"""FastAPI application: local-only API for the web UI and the VS Code extension."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from repopilot import __version__
from repopilot.config import get_settings
from repopilot.runtime import NoRuntimeError


def create_app() -> FastAPI:
    from repopilot.api.routes import models as models_routes

    settings = get_settings()
    app = FastAPI(title="RepoPilot", version=__version__, docs_url="/docs", redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://127.0.0.1:{settings.web_port}", f"http://localhost:{settings.web_port}"],
        allow_origin_regex=r"vscode-webview://.*",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NoRuntimeError)
    async def no_runtime(_: Request, exc: NoRuntimeError) -> JSONResponse:
        statuses = getattr(exc, "statuses", [])
        return JSONResponse(
            status_code=503,
            content={
                "detail": "No local model runtime found. Start Ollama or LM Studio.",
                "runtimes_checked": [s.base_url for s in statuses] or get_settings().runtime_urls,
            },
        )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    app.include_router(models_routes.router)
    return app
