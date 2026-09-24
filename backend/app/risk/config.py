"""Loading of the editable YAML risk configuration (config/*.yaml)."""

from __future__ import annotations

from functools import lru_cache

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
        return self.names.get(code.upper(), code.upper())


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
