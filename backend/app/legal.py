"""Legal basis of the red flags and ready-to-paste justifications (config/legal_basis.yaml).

An operational map to the main texts, not legal advice: the institution checks the current
version of each text and applies its own directives.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.settings import CONFIG_DIR

PATH = CONFIG_DIR / "legal_basis.yaml"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return yaml.safe_load(PATH.read_text(encoding="utf-8")) or {}


def refs_for(signal: str) -> list[dict[str, Any]]:
    d = _data()
    sig = d.get("signals", {}).get(signal) or {}
    return [{"id": r, **d["refs"][r]} for r in sig.get("refs", []) if r in d.get("refs", {})]


def justification(signal: str, evidence: str, lang: str = "en") -> str | None:
    sig = _data().get("signals", {}).get(signal)
    if not sig or lang not in sig:
        return None
    ev = evidence.strip().rstrip(".") or "-"
    if len(ev) > 240:
        ev = ev[:239].rsplit(" ", 1)[0] + "…"
    text = sig[lang].replace("{evidence}", ev)
    basis = ", ".join(r["short"] for r in refs_for(signal))
    label = "Base légale" if lang == "fr" else "Legal basis"
    return f"{text} {label} : {basis}." if lang == "fr" else f"{text} {label}: {basis}."


def for_investigation(risk: Any, ownership: Any = None) -> list[dict[str, Any]]:
    """One item per risk factor present (and the SMO fallback), with refs and texts."""
    out: list[dict[str, Any]] = []
    for f in risk.factors:
        ev = "; ".join(f.evidence[:3])
        out.append(
            {
                "key": f.key,
                "label": f.label,
                "points": f.points,
                "refs": refs_for(f.key),
                "en": justification(f.key, ev, "en"),
                "fr": justification(f.key, ev, "fr"),
            }
        )
    if ownership is not None and getattr(ownership, "smo_reason", None):
        names = ", ".join(s["name"] for s in ownership.smo) or "to be identified"
        out.append(
            {
                "key": "ubo_smo_fallback",
                "label": "No beneficial owner by ownership: senior managing official",
                "points": 0,
                "refs": refs_for("ubo_smo_fallback"),
                "en": justification("ubo_smo_fallback", names, "en"),
                "fr": justification("ubo_smo_fallback", names, "fr"),
            }
        )
    return out


def as_of() -> str:
    return str(_data().get("as_of", ""))
