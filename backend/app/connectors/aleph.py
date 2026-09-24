"""OCCRP Aleph — investigative data: leaks, registries, court records, gazettes.

API: https://aleph.occrp.org/api/2 (key: ALEPH_API_KEY, free account).
Used as a screening source: each network entity is searched by name and the
hits are reported with the collection they come from. Sanctions collections
are skipped (covered by OpenSanctions), private case files are ignored.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.matching.matcher import match_entities
from app.models import Entity, EntityType, ListType, ScreeningHit

API = "https://aleph.occrp.org/api/2/entities"
MIN_SCORE = 75
SKIPPED_CATEGORIES = {"sanctions", "casefile"}
LEAK_CATEGORIES = {"leak"}


def _first(props: dict[str, list[Any]], key: str) -> Any:
    values = props.get(key) or []
    return values[0] if values else None


class AlephConnector(BaseConnector):
    name = "aleph"
    label = "OCCRP Aleph (leaks, registries, court records)"
    kind = "leaks"
    key_setting = "aleph_api_key"
    homepage = "https://aleph.occrp.org"

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type not in (EntityType.PERSON, EntityType.COMPANY):
            return []
        schema = "Person" if entity.type == EntityType.PERSON else "LegalEntity"
        data = (
            self.http_get_json(
                API,
                params={"q": f'"{entity.name}"', "filter:schemata": schema, "limit": 15},
                headers={"Authorization": f"ApiKey {self.api_key}"},
            )
            or {}
        )
        hits = []
        for r in data.get("results", []):
            collection = r.get("collection") or {}
            category = collection.get("category") or "other"
            if category in SKIPPED_CATEGORIES:
                continue
            props = r.get("properties") or {}
            listed = Entity(
                id=r.get("id", ""),
                type=entity.type,
                name=_first(props, "name") or r.get("caption") or "",
                aliases=(props.get("name") or [])[1:10] + (props.get("alias") or [])[:10],
                birth_date=_first(props, "birthDate"),
                nationalities=sorted(
                    {c.upper() for c in props.get("nationality", []) if len(c) == 2}
                ),
                jurisdiction=(
                    _first(props, "jurisdiction") or _first(props, "country") or ""
                ).upper()
                or None,
            )
            result = match_entities(entity, listed)
            if result.score < MIN_SCORE:
                continue
            rid = self.record_id(r.get("id", ""))
            hits.append(
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=ListType.LEAK if category in LEAK_CATEGORIES else ListType.ADVERSE,
                    dataset=f"{collection.get('label', 'Aleph')} (Aleph · {category})",
                    matched_name=listed.name,
                    score=result.score,
                    explanation=result.explanation,
                    details={
                        "schema": r.get("schema"),
                        "collection_category": category,
                        "countries": ", ".join(props.get("country", [])[:5]) or None,
                    },
                    provenance=self.provenance(
                        rid,
                        (r.get("links") or {}).get("ui")
                        or f"https://aleph.occrp.org/entities/{r.get('id', '')}",
                    ),
                )
            )
        return hits
