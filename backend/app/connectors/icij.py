"""ICIJ Offshore Leaks Database (Panama, Paradise, Pandora Papers, Bahamas Leaks, Offshore Leaks).

Two connectors:

* ``IcijReconcileConnector`` — the public reconciliation API of
  offshoreleaks.icij.org (no key, works on serverless hosts). One batched
  request per investigation, so each hit is attributed to its leak.
* ``IcijLocalConnector`` — a local SQLite built from the bulk CSV download
  by ``scripts/import_icij.py`` (full dataset, offline, faster; enabled when
  the file exists).

Data: ICIJ Offshore Leaks Database, licensed under the Open Database License
(ODbL) — attribution: "International Consortium of Investigative Journalists".
Appearing in the database does not imply any wrongdoing.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError
from app.matching.names import name_similarity, normalize_company, normalize_person
from app.models import Entity, EntityType, ListType, ScreeningHit

RECONCILE = "https://offshoreleaks.icij.org/api/v1/reconcile"
NODE_URL = "https://offshoreleaks.icij.org/nodes/{id}"
INVESTIGATIONS = {
    "panama-papers": "Panama Papers (ICIJ, 2016)",
    "paradise-papers": "Paradise Papers (ICIJ, 2017)",
    "pandora-papers": "Pandora Papers (ICIJ, 2021)",
    "bahamas-leaks": "Bahamas Leaks (ICIJ, 2016)",
    "offshore-leaks": "Offshore Leaks (ICIJ, 2013)",
}
BATCH_SIZE = 10
MIN_NAME_SCORE = 80
NAME_ONLY_PENALTY = 5
EXTRA_TOKENS_PENALTY = (
    10  # "Mossack Fonseca" vs "Mossack Fonseca Guatemala": a related but distinct node
)
DISCLAIMER = "Appearing in the Offshore Leaks Database does not imply wrongdoing."
ACCEPTED_TYPES = {
    EntityType.PERSON: {"officer", "intermediary"},
    EntityType.COMPANY: {"entity", "officer", "intermediary"},
}


def _leak_score(name_score: float, notes: list[str]) -> tuple[float, list[str]]:
    """Leak records have no date of birth: name-only evidence is discounted, and a
    leaked name with extra/missing words is treated as a related, distinct node."""
    score = name_score - NAME_ONLY_PENALTY
    reasons = [f"name-only match (leak records carry no date of birth) [-{NAME_ONLY_PENALTY}]"]
    if any("token count differs" in n for n in notes):
        score -= EXTRA_TOKENS_PENALTY
        reasons.append(f"the leaked name has extra or missing words [-{EXTRA_TOKENS_PENALTY}]")
    return round(score, 1), reasons


def _type_name(result: dict[str, Any]) -> str:
    # The API returns "types": [{"id": "https://offshoreleaks.icij.org/schema/oldb/entity", "name": "Entity"}]
    types = result.get("types") or result.get("type") or []
    if types and isinstance(types[0], dict):
        return str(types[0].get("name") or types[0].get("id") or "").rsplit("/", 1)[-1].lower()
    return str(types[0]).lower() if types else ""


class IcijReconcileConnector(BaseConnector):
    name = "icij_offshore_leaks"
    label = "ICIJ Offshore Leaks Database (Panama/Paradise/Pandora Papers…)"
    kind = "leaks"
    homepage = "https://offshoreleaks.icij.org"

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        return self.screen_many([entity])

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        targets = [e for e in entities if e.type in ACCEPTED_TYPES]
        hits: list[ScreeningHit] = []
        for slug, dataset in INVESTIGATIONS.items():
            for start in range(0, len(targets), BATCH_SIZE):
                batch = targets[start : start + BATCH_SIZE]
                queries = {f"q{i}": {"query": e.name, "limit": 5} for i, e in enumerate(batch)}
                data = self.http_post_json(
                    f"{RECONCILE}/{slug}", form={"queries": json.dumps(queries)}
                )
                for i, entity in enumerate(batch):
                    for result in ((data or {}).get(f"q{i}") or {}).get("result", []):
                        hit = self._hit(entity, result, dataset, slug)
                        if hit:
                            hits.append(hit)
        return hits

    def _hit(
        self, entity: Entity, result: dict[str, Any], dataset: str, slug: str
    ) -> ScreeningHit | None:
        rtype = _type_name(result)
        if rtype and rtype not in ACCEPTED_TYPES[entity.type]:
            return None
        kind = "company" if entity.type == EntityType.COMPANY else "person"
        score, notes = name_similarity(entity.name, result.get("name", ""), kind)
        if score < MIN_NAME_SCORE:
            return None
        node_id = str(result.get("id", ""))
        rid = self.record_id(f"{slug}:{node_id}")
        return ScreeningHit(
            entity_id=entity.id,
            list_type=ListType.LEAK,
            dataset=dataset,
            matched_name=result.get("name", ""),
            score=_leak_score(score, notes)[0],
            explanation=[f"name {score:.0f}%", *notes, *_leak_score(score, notes)[1]],
            details={
                "node_type": rtype or "unknown",
                "icij_score": result.get("score"),
                "description": result.get("description"),
                "note": DISCLAIMER,
            },
            provenance=self.provenance(rid, NODE_URL.format(id=node_id)),
        )


class IcijLocalConnector(BaseConnector):
    """Offline full-text search over the bulk ICIJ dataset (see scripts/import_icij.py)."""

    name = "icij_local"
    label = "ICIJ Offshore Leaks Database — local bulk import"
    kind = "leaks"
    homepage = "https://offshoreleaks.icij.org/pages/database"

    def status(self) -> tuple[bool, str]:
        if not self.settings.live_sources:
            return False, "Disabled (LIVE_SOURCES=false)"
        if not os.path.exists(self.settings.icij_db_path):
            return False, "Disabled: run scripts/import_icij.py to build the local database"
        return True, "Enabled (local bulk import)"

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.settings.icij_db_path}?mode=ro", uri=True)

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type not in ACCEPTED_TYPES:
            return []
        kind = "company" if entity.type == EntityType.COMPANY else "person"
        tokens = (normalize_company if kind == "company" else normalize_person)(entity.name)
        if not tokens:
            return []
        fts = " AND ".join(f'"{t}"' for t in tokens[:4] if len(t) > 1)
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT n.node_id, n.kind, n.name, n.source, n.jurisdiction, n.countries "
                    "FROM nodes_fts f JOIN nodes n ON n.rowid = f.rowid WHERE nodes_fts MATCH ? LIMIT 50",
                    (fts,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ConnectorError(f"{self.label}: {exc}") from exc
        hits = []
        for node_id, node_kind, name, source, jur, countries in rows:
            if node_kind not in ACCEPTED_TYPES[entity.type]:
                continue
            score, notes = name_similarity(entity.name, name, kind)
            if score < MIN_NAME_SCORE:
                continue
            rid = self.record_id(str(node_id))
            hits.append(
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=ListType.LEAK,
                    dataset=source or "ICIJ Offshore Leaks",
                    matched_name=name,
                    score=_leak_score(score, notes)[0],
                    explanation=[f"name {score:.0f}%", *notes, *_leak_score(score, notes)[1]],
                    details={
                        "node_type": node_kind,
                        "jurisdiction": jur,
                        "countries": countries,
                        "note": DISCLAIMER,
                    },
                    provenance=self.provenance(rid, NODE_URL.format(id=node_id)),
                )
            )
        return hits
