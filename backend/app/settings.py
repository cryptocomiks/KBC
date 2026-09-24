"""Application settings, read from environment variables and the `.env` file."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def _default_cache_path() -> str:
    # Vercel's filesystem is read-only except /tmp (ephemeral, which is fine for a cache).
    if os.environ.get("VERCEL"):
        return "/tmp/kbc_cache.db"
    return str(REPO_ROOT / "data" / "kbc_cache.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    demo_mode: bool = True
    cache_path: str = _default_cache_path()
    cache_ttl_hours: int = 72

    pappers_api_key: str = ""
    opencorporates_api_token: str = ""
    companies_house_api_key: str = ""
    aleph_api_key: str = ""
    opensanctions_api_key: str = ""
    icij_db_path: str = str(REPO_ROOT / "data" / "icij_offshore_leaks.db")

    risk_config_path: str = str(CONFIG_DIR / "risk.yaml")
    jurisdictions_config_path: str = str(CONFIG_DIR / "jurisdictions.yaml")

    # Guard rails for network expansion
    max_depth: int = 3
    max_nodes_limit: int = 250
    http_timeout_seconds: float = 15.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
