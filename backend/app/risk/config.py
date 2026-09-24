"""Loading of the editable YAML risk configuration (config/*.yaml)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.settings import get_settings


class JurisdictionLists(BaseModel):
    as_of: str = ""
    fatf_blacklist: set[str] = Field(default_factory=set)
    fatf_greylist: set[str] = Field(default_factory=set)
    eu_tax_blacklist: set[str] = Field(default_factory=set)
    offshore_centres: set[str] = Field(default_factory=set)
    names: dict[str, str] = Field(default_factory=dict)

    def name(self, code: str | None) -> str:
        if not code:
            return "Unknown"
        code = code.upper()
        return self.names.get(code) or get_country_risk().name(code) or code


class CountryRisk(BaseModel):
    """Country indicators (config/country_risk.json, refreshed by scripts/update_country_risk.py)."""

    retrieved: str = ""
    sources: dict[str, dict[str, str]] = Field(default_factory=dict)
    countries: dict[str, dict] = Field(default_factory=dict)

    def get(self, code: str | None) -> dict:
        return self.countries.get((code or "").upper(), {})

    def name(self, code: str | None) -> str | None:
        return self.get(code).get("name")

    def code_for(self, name: str | None) -> str | None:
        """ISO code from a country name as written by a source ("Cayman Islands")."""
        key = (name or "").strip().lower()
        if not key:
            return None
        for code, c in self.countries.items():
            if c.get("name", "").lower() == key:
                return code
        return None

    def describe(self, code: str | None) -> str | None:
        c = self.get(code)
        bits = []
        if c.get("basel_aml_score") is not None:
            bits.append(
                f"Basel AML Index {c['basel_aml_score']:.2f}/10 (rank {c['basel_aml_rank']})"
            )
        if c.get("cpi_score") is not None:
            bits.append(f"CPI {c['cpi_score']:.0f}/100 ({c['cpi_year']})")
        if c.get("wgi_control_of_corruption") is not None:
            bits.append(f"WGI control of corruption {c['wgi_control_of_corruption']:+.2f}")
        return ", ".join(bits) or None


class RiskConfig(BaseModel):
    weights: dict[str, float]
    proximity_multiplier: dict[str, float]
    thresholds: dict[str, float]
    levels: dict[str, float]

    def multiplier(self, distance: int) -> float:
        return self.proximity_multiplier.get(
            str(distance), self.proximity_multiplier.get("default", 0.35)
        )

    def level(self, score: float) -> str:
        current = "low"
        for name, lower in sorted(self.levels.items(), key=lambda kv: kv[1]):
            if score >= lower:
                current = name
        return current


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache
def get_risk_config() -> RiskConfig:
    data = _load(get_settings().risk_config_path)
    data["proximity_multiplier"] = {str(k): v for k, v in data["proximity_multiplier"].items()}
    return RiskConfig(**data)


@lru_cache
def get_jurisdictions() -> JurisdictionLists:
    data = _load(get_settings().jurisdictions_config_path)
    for key in ("fatf_blacklist", "fatf_greylist", "eu_tax_blacklist", "offshore_centres"):
        data[key] = {c.upper() for c in data.get(key) or []}
    return JurisdictionLists(**data)


@lru_cache
def get_country_risk() -> CountryRisk:
    path = Path(get_settings().country_risk_path)
    if not path.exists():
        return CountryRisk()
    return CountryRisk(**json.loads(path.read_text(encoding="utf-8")))
