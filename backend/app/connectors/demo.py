"""Connectors serving the fictitious demo dataset (app/demo/data/*.json).

They implement exactly the same interface as the real connectors, which
makes the demo an honest end-to-end run of the pipeline: search,
disambiguation, cross-source deduplication, expansion, screening, scoring.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from app.connectors.base import BaseConnector
from app.matching.matcher import match_entities, match_name
from app.matching.names import tokenize
from app.models import (
    CompanyStatus,
    Document,
    Entity,
    EntityType,
    LinkedEntity,
    ListType,
    Relationship,
    RelationType,
    ScreeningHit,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "demo" / "data"
SEARCH_MIN_SCORE = 60
SCREENING_MIN_SCORE = 45  # hits below 70 are displayed as "weak / likely false positive"


def resolve_date(value: str | None, today: date | None = None) -> str | None:
    """Support relative dates ('@-10m') so the demo stays realistic over time."""
    if not value or not value.startswith("@"):
        return value
    today = today or date.today()
    months = int(value[1:].rstrip("m"))
    total = today.year * 12 + (today.month - 1) + months
    year, month = divmod(total, 12)
    return date(year, month + 1, min(today.day, 28)).isoformat()


@lru_cache
def load_dataset(filename: str) -> dict[str, Any]:
    with open(DATA_DIR / filename, encoding="utf-8") as fh:
        return json.load(fh)


def _norm_address(address: str | None) -> str:
    return " ".join(tokenize(address or ""))


class _DemoBase(BaseConnector):
    is_demo = True
    filename: ClassVar[str]

    @property
    def data(self) -> dict[str, Any]:
        return load_dataset(self.filename)

    @property
    def base_url(self) -> str:
        return self.data["source"]["base_url"]

    def _to_entity(self, rec: dict[str, Any]) -> Entity:
        rid = self.record_id(rec["id"])
        fields = {
            k: resolve_date(v) if k.endswith("_date") else v
            for k, v in rec.items()
            if k not in {"id", "list_type", "dataset", "details"}
        }
        if "status" in fields:
            fields["status"] = CompanyStatus(fields["status"])
        url = f"{self.base_url}/{rec['type']}/{rec['id']}"
        return Entity(
            id=rid,
            record_ids=[rid],
            demo=True,
            sources=[self.provenance(rid, url)],
            **fields,
        )


class DemoRegistryConnector(_DemoBase):
    kind = "registry"

    def _entities(self) -> dict[str, dict[str, Any]]:
        return {e["id"]: e for e in self.data["entities"]}

    def _get(self, native: str) -> Entity | None:
        rec = self._entities().get(native)
        return self._to_entity(rec) if rec else None

    def _relationship(self, idx: int, rel: dict[str, Any]) -> Relationship:
        rid = f"{self.name}:rel:{idx}"
        return Relationship(
            id=rid,
            type=RelationType(rel["type"]),
            source_id=self.record_id(rel["from"]),
            target_id=self.record_id(rel["to"]),
            role=rel.get("role"),
            share_pct=rel.get("share_pct"),
            start_date=resolve_date(rel.get("start_date")),
            end_date=resolve_date(rel.get("end_date")),
            sources=[self.provenance(rid, f"{self.base_url}/company/{rel['to']}#{rel['type']}")],
        )

    def _links(
        self, *, to: str | None = None, frm: str | None = None, types: set[str]
    ) -> list[LinkedEntity]:
        out = []
        for idx, rel in enumerate(self.data["relationships"]):
            if rel["type"] not in types:
                continue
            if to is not None and rel["to"] == to:
                other = self._get(rel["from"])
            elif frm is not None and rel["from"] == frm:
                other = self._get(rel["to"])
            else:
                continue
            if other:
                out.append(LinkedEntity(relationship=self._relationship(idx, rel), entity=other))
        return out

    def _search(self, name: str, etype: EntityType) -> list[Entity]:
        scored = []
        for rec in self.data["entities"]:
            if rec["type"] != etype:
                continue
            ent = self._to_entity(rec)
            score = match_name(name, ent).score
            if score >= SEARCH_MIN_SCORE:
                scored.append((score, ent))
        return [e for _, e in sorted(scored, key=lambda x: -x[0])]

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        return self._search(name, EntityType.PERSON)

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return self._search(name, EntityType.COMPANY)

    def get_company_details(self, company_id: str) -> Entity | None:
        return self._get(self.native_id(company_id))

    def get_person_details(self, person_id: str) -> Entity | None:
        return self._get(self.native_id(person_id))

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        return self._links(to=self.native_id(company_id), types={"officer"})

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        return self._links(to=self.native_id(company_id), types={"shareholder", "beneficial_owner"})

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        return self._links(
            frm=self.native_id(person_id), types={"officer", "shareholder", "beneficial_owner"}
        )

    def get_subsidiaries(self, company_id: str) -> list[LinkedEntity]:
        return self._links(frm=self.native_id(company_id), types={"shareholder"})

    def get_documents(self, entity: Entity) -> list[Document]:
        natives = {self.native_id(r) for r in entity.record_ids if r.startswith(f"{self.name}:")}
        return [
            Document(
                **{k: resolve_date(v) if k == "date" else v for k, v in d.items() if k != "entity"},
                url=f"{self.base_url}/documents/{d['entity']}/{i}",
                source=self.label,
            )
            for i, d in enumerate(self.data.get("documents", []))
            if d["entity"] in natives
        ]

    def search_address(self, address: str) -> list[Entity]:
        key = _norm_address(address)
        return [
            self._to_entity(r)
            for r in self.data["entities"]
            if r["type"] == "company" and key and _norm_address(r.get("address")) == key
        ]


class DemoScreeningConnector(_DemoBase):
    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type == EntityType.ADDRESS:
            return []
        hits = []
        for rec in self.data["entries"]:
            if rec["type"] != entity.type:
                continue
            listed = self._to_entity(rec)
            result = match_entities(entity, listed)
            if result.score < SCREENING_MIN_SCORE:
                continue
            hits.append(
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=ListType(rec["list_type"]),
                    dataset=rec["dataset"],
                    matched_name=rec["name"],
                    score=result.score,
                    explanation=result.explanation,
                    details={
                        **rec.get("details", {}),
                        **({"birth_date": rec["birth_date"]} if rec.get("birth_date") else {}),
                        **(
                            {"nationalities": rec["nationalities"]}
                            if rec.get("nationalities")
                            else {}
                        ),
                    },
                    provenance=listed.sources[0],
                )
            )
        return hits


class DemoFrRegistry(DemoRegistryConnector):
    name = "demo_fr_registry"
    label = "Demo FR Registry (Pappers-like, fictitious)"
    filename = "fr_registry.json"
    jurisdictions = {"FR"}


class DemoIntlRegistry(DemoRegistryConnector):
    name = "demo_intl_registry"
    label = "Demo Global Registry (OpenCorporates-like, fictitious)"
    filename = "intl_registry.json"


class DemoSanctions(DemoScreeningConnector):
    name = "demo_sanctions"
    label = "Demo Sanctions & PEP Lists (OpenSanctions-like, fictitious)"
    kind = "screening"
    filename = "sanctions_pep.json"


class DemoLeaks(DemoScreeningConnector):
    name = "demo_leaks"
    label = "Demo Leaks Archive (ICIJ / Aleph-like, fictitious)"
    kind = "leaks"
    filename = "leaks.json"


DEMO_CONNECTORS: list[type[BaseConnector]] = [
    DemoFrRegistry,
    DemoIntlRegistry,
    DemoSanctions,
    DemoLeaks,
]
