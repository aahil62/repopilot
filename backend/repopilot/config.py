"""Runtime settings. Every value can be overridden with a REPOPILOT_* environment variable."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REPOPILOT_", extra="ignore")

    home: Path = Field(default_factory=lambda: Path.home() / ".repopilot")
    host: str = "127.0.0.1"
    port: int = 7341
    web_port: int = 7342
    max_file_kb: int = 512
    max_files: int = 100_000
    history_max_commits: int = 5_000
    embed_batch: int = 64
    runtime_urls: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:11434",
            "http://127.0.0.1:1234/v1",
            "http://127.0.0.1:8080/v1",
        ]
    )
    allow_github_import: bool = False
    check_timeout_s: int = 300

    def repo_dir(self, repo_id: str) -> Path:
        path = self.home / "repos" / repo_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def worktrees_dir(self) -> Path:
        path = self.home / "worktrees"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def clones_dir(self) -> Path:
        path = self.home / "clones"
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Clear the cached settings (used by tests after changing the environment)."""
    get_settings.cache_clear()


def repo_id_for(path: Path) -> str:
    """Stable 12-hex id for a local repository path."""
    return hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:12]
