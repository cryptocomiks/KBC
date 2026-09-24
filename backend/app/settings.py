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
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # An empty variable (e.g. DEMO_MODE= copied from .env.example) means "use the default".
        env_ignore_empty=True,
    )

    # Fictitious demo dataset (always separate from real data)
    demo_mode: bool = True
    # Real sources: keyless public APIs are on by default, keyed ones need their key
    live_sources: bool = True
    cache_path: str = _default_cache_path()
    cache_ttl_hours: int = 72

    pappers_api_key: str = ""
    opencorporates_api_token: str = ""
    companies_house_api_key: str = ""
    aleph_api_key: str = ""
    opensanctions_api_key: str = ""
    # Open watchlists downloaded as bulk files (OpenSanctions dataset names, comma-separated)
    open_datasets: str = (
        "eu_fsf,gb_fcdo_sanctions,ch_seco_sanctions,worldbank_debarred,interpol_red_notices"
    )
    icij_db_path: str = str(REPO_ROOT / "data" / "icij_offshore_leaks.db")

    risk_config_path: str = str(CONFIG_DIR / "risk.yaml")
    jurisdictions_config_path: str = str(CONFIG_DIR / "jurisdictions.yaml")
    country_risk_path: str = str(CONFIG_DIR / "country_risk.json")
    # The SEC blocks automated requests whose User-Agent does not name a contact.
    sec_user_agent: str = "KBC Corporate Mapping research-contact@kbc-mapping.org"

    # Guard rails for network expansion
    max_depth: int = 3
    max_nodes_limit: int = 250
    http_timeout_seconds: float = 15.0
    # Wall-clock budget for one investigation over live APIs (serverless time limits)
    expansion_time_budget_seconds: float = 30.0
    screening_workers: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
