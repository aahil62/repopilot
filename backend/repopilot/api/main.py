"""FastAPI application: local-only API for the web UI and the VS Code extension."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from repopilot import __version__
from repopilot.config import get_settings
from repopilot.runtime import NoRuntimeError

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(static_dir: Path | None = STATIC_DIR) -> FastAPI:
    from repopilot.api.jobs import jobs
    from repopilot.api.routes import models as models_routes
    from repopilot.api.routes import repos as repo_routes
    from repopilot.api.routes import work as work_routes

    settings = get_settings()
    app = FastAPI(
        title="RepoPilot",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
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
                "setup": [
                    "ollama pull qwen2.5-coder:7b",
                    "ollama pull qwen2.5-coder:1.5b",
                    "ollama pull nomic-embed-text",
                ],
            },
        )

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict:
        data = jobs().get(job_id)
        if not data:
            raise HTTPException(404, "Unknown job.")
        return data

    @app.get("/api/privacy")
    def privacy() -> dict:
        s = get_settings()
        return {
            "data_dir": str(s.home),
            "model_runtime_urls": s.runtime_urls,
            "github_review_import": s.allow_github_import,
            "telemetry": False,
            "network_calls": [
                "Your local model runtime(s) listed above.",
                *(["api.github.com, only when you import review history."] if s.allow_github_import else []),
            ],
        }

    app.include_router(models_routes.router)
    app.include_router(repo_routes.router)
    app.include_router(work_routes.router)

    if static_dir and static_dir.is_dir():
        root = static_dir.resolve()
        if (root / "_next").is_dir():
            app.mount("/_next", StaticFiles(directory=root / "_next"), name="next-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def web(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(404)
            for candidate in (root / full_path, root / full_path / "index.html", root / f"{full_path}.html"):
                resolved = candidate.resolve()
                if resolved.is_file() and resolved.is_relative_to(root):
                    return FileResponse(resolved)
            return FileResponse(root / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        def no_ui() -> HTMLResponse:
            return HTMLResponse(
                "<h1>RepoPilot is running</h1><p>The web UI isn't bundled in this install. "
                "Build it with <code>python scripts/bundle_web.py</code>, use the VS Code extension, "
                "or browse the API at <a href='/api/docs'>/api/docs</a>.</p>"
            )

    return app
