"""List screening and the feed of new designations on the official sanctions lists.

Both work without a case: nothing sent here is stored.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.models import Entity, EntityType
from app.risk.config import get_risk_config

MAX_LIST = 60  # names per call (the page sends a long list in several calls)
_COMPANY = re.compile(
    r"\b(ltd|limited|llc|inc|corp|corporation|co|company|gmbh|ag|sa|sarl|sas|srl|spa|bv|nv|plc|oy"
    r"|ab|as|jsc|pjsc|ooo|llp|lp|fze|fzco|dmcc|holding|holdings|trading|group|foundation|trust"
    r"|bank|s\.a\.|s\.à r\.l\.|stiftung|anstalt)\b",
    re.I,
)


def guess_type(name: str) -> EntityType:
    return EntityType.COMPANY if _COMPANY.search(name) else EntityType.PERSON


def screen_list(rows: list[dict[str, Any]], screen: Any) -> dict[str, Any]:
    """rows: [{name, type?: person|company|auto, country?, reference?}] (at most MAX_LIST).
    `screen(entities)` returns (hits, notes): KbcService.screen_entities."""
    t = get_risk_config().thresholds
    entities: list[Entity] = []
    kept: list[dict[str, Any]] = []
    for row in rows[:MAX_LIST]:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        kind = row.get("type")
        etype = (
            EntityType.PERSON
            if kind == "person"
            else EntityType.COMPANY
            if kind == "company"
            else guess_type(name)
        )
        country = str(row.get("country") or "").strip().upper()[:2] or None
        entities.append(
            Entity(id=f"list:{len(entities)}", type=etype, name=name, jurisdiction=country)
        )
        kept.append(row)
    hits, notes = screen(entities) if entities else ([], [])
    by_id: dict[str, list] = {}
    for h in hits:
        if h.score >= t["possible_match_score"] and h.triage not in ("namesake", "dismissed"):
            by_id.setdefault(h.entity_id, []).append(h)
    # A list still downloading at the deadline was not searched: a name without hits is then
    # "not fully screened", never "no match".
    late = [n for n in notes if n.startswith("Not screened within")]
    results = []
    for ent, row in zip(entities, kept, strict=True):
        found = sorted(by_id.get(ent.id, []), key=lambda h: -h.score)
        strong = any(
            h.score >= t["strong_match_score"] and h.list_type.value == "sanction" for h in found
        )
        results.append(
            {
                "name": ent.name,
                "reference": row.get("reference"),
                "type": ent.type.value,
                "country": ent.jurisdiction,
                "status": "strong"
                if strong
                else "possible"
                if found
                else "incomplete"
                if late
                else "clear",
                "matches": [
                    {
                        "list": h.dataset,
                        "type": h.list_type.value,
                        "listed_as": h.matched_name,
                        "score": h.score,
                        "why": h.explanation[:2],
                        "program": (h.details or {}).get("program"),
                        "source": h.provenance.url,
                    }
                    for h in found[:5]
                ],
            }
        )
    return {"screened": len(results), "results": results, "notes": notes, "complete": not late}


def recent_designations(
    registry: Any, days: int = 90, limit: int = 300, wait: float = 25.0
) -> dict[str, Any]:
    """Entries added to the official lists in the last `days` days, newest first. A list still
    downloading on this server is named in `loading` (its entries come on the next call)."""
    import time

    from app.connectors.official_sanctions import (
        EuropeanSanctionsConnector,
        NationalSanctionsConnector,
        OfficialSanctionsConnector,
    )

    since = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    conns = [
        registry.connectors.get(cls.name)
        for cls in (
            OfficialSanctionsConnector,
            EuropeanSanctionsConnector,
            NationalSanctionsConnector,
        )
    ]
    conns = [c for c in conns if c is not None and c.enabled]
    # On a server that has just started, the lists download while this request waits (a
    # serverless host pauses background work between requests): up to `wait` seconds.
    for c in conns:
        if not c._state.entries:
            c.prefetch()
    deadline = time.monotonic() + wait
    while any(not c._state.entries for c in conns) and time.monotonic() < deadline:
        time.sleep(0.5)
    items: list[dict[str, Any]] = []
    loading: list[str] = []
    seen: set[tuple[str, str]] = set()
    for conn in conns:
        state = conn._state
        if not state.entries:
            loading.append(conn.label)
            continue
        for entry in state.entries:
            listed = (entry.details or {}).get("listed_on")
            if not listed or str(listed)[:10] < since:
                continue
            e = entry.entity
            key = (entry.dataset, e.id)
            if key in seen:  # entries indexed both as person and company
                continue
            seen.add(key)
            items.append(
                {
                    "listed_on": str(listed)[:10],
                    "name": e.name,
                    "type": e.type.value,
                    "list": entry.dataset,
                    "program": entry.program,
                    "nationalities": e.nationalities,
                    "birth_date": e.birth_date,
                    "reference": (entry.details or {}).get("reference"),
                    "source": entry.url,
                }
            )
    items.sort(key=lambda x: (x["listed_on"], x["list"], x["name"]), reverse=True)
    by_list: dict[str, int] = {}
    for x in items:
        by_list[x["list"]] = by_list.get(x["list"], 0) + 1
    return {
        "since": since,
        "until": date.today().isoformat(),
        "total": len(items),
        "by_list": by_list,
        "items": items[:limit],
        "loading": loading,
    }
