"""Connectors serving the fictitious demo dataset (app/demo/data/*.json).

They implement exactly the same interface as the real connectors, which
makes the demo an honest end-to-end run of the pipeline: search,
disambiguation, cross-source deduplication, expansion, screening, scoring.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from app.connectors.base import BaseConnector
from app.connectors.crypto_util import normalize_address, wallet_id
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
            if k not in {"id", "list_type", "dataset", "details", "addresses"}
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

    def get_by_identifier(self, ident: Any) -> Entity | None:
        want = re.sub(r"[\s.\-/]", "", ident.value).upper()
        for rec in self.data["entities"]:
            if rec["type"] != EntityType.COMPANY:
                continue
            ent = self._to_entity(rec)
            ids = [ent.registration_number or "", *ent.identifiers.values()]
            if any(
                re.sub(r"[\s.\-/]", "", i).upper().removeprefix("LU") == want.removeprefix("LU")
                for i in ids
                if i
            ):
                return ent
        return None

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
        native = self.native_id(person_id)
        return self._links(
            frm=native, types={"officer", "shareholder", "beneficial_owner", "relative"}
        ) + (
            self._links(to=native, types={"relative"})  # family links are symmetric
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
    def _listed_wallet(self, entity: Entity) -> dict[str, Any] | None:
        target = normalize_address(entity.name, entity.chain)
        for rec in self.data["entries"]:
            for a in rec.get("addresses", []):
                if normalize_address(a["address"], a["chain"]) == target:
                    return rec
        return None

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        """A listed wallet is linked to the sanctioned entity it is attributed to."""
        if entity.type != EntityType.WALLET:
            return []
        rec = self._listed_wallet(entity)
        if not rec:
            return []
        owner = self._to_entity({k: v for k, v in rec.items() if k != "addresses"})
        rel = Relationship(
            id=f"{self.name}:ctrl:{rec['id']}",
            type=RelationType.CONTROLS,
            source_id=owner.id,
            target_id=entity.id,
            role="Address attributed by the sanctions list",
            sources=owner.sources,
        )
        return [LinkedEntity(relationship=rel, entity=owner)]

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type == EntityType.WALLET:
            rec = self._listed_wallet(entity)
            if not rec:
                return []
            return [
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=ListType(rec["list_type"]),
                    dataset=rec["dataset"],
                    matched_name=f"{entity.name} ({rec['name']})",
                    score=100.0,
                    explanation=[
                        "address listed verbatim on the sanctions list",
                        f"attributed to {rec['name']}",
                    ],
                    details={**rec.get("details", {}), "listed_owner": rec["name"]},
                    provenance=self.provenance(
                        self.record_id(rec["id"]), f"{self.base_url}/company/{rec['id']}"
                    ),
                )
            ]
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


class DemoChainConnector(_DemoBase):
    """Fictitious wallets and aggregated flows (app/demo/data/chain.json)."""

    name = "demo_chain"
    label = "Demo blockchain explorer (fictitious)"
    kind = "chain"
    filename = "chain.json"

    def _wallet(self, rec: dict[str, Any]) -> Entity:
        rid = wallet_id(rec["chain"], rec["address"])
        extra = {
            k: resolve_date(v) if k in ("first_seen", "last_seen") else v
            for k, v in rec.items()
            if k in ("balance", "tx_count", "first_seen", "last_seen", "label")
        }
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.WALLET,
            name=rec["address"],
            chain=rec["chain"],
            demo=True,
            identifiers={f"{rec['chain']} address": rec["address"]},
            extra=extra,
            sources=[self.provenance(rid, f"{self.base_url}/address/{rec['address']}")],
        )

    def _find(self, address: str) -> dict[str, Any] | None:
        key = normalize_address(address)
        return next(
            (w for w in self.data["wallets"] if normalize_address(w["address"], w["chain"]) == key),
            None,
        )

    def get_wallet(self, address: str) -> Entity | None:
        rec = self._find(address)
        return self._wallet(rec) if rec else None

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        out: list[LinkedEntity] = []
        if entity.type == EntityType.WALLET:
            rec = self._find(entity.name)
            if not rec:
                return []
            me = wallet_id(rec["chain"], rec["address"])
            for owner_rid in rec.get("controlled_by", []):
                owner = self._owner(owner_rid)
                if owner:
                    out.append(
                        LinkedEntity(relationship=self._control(owner.id, me, rec), entity=owner)
                    )
            if include_transfers:
                for i, t in enumerate(self.data["transfers"]):
                    if rec["address"] not in (t["from"], t["to"]):
                        continue
                    other = self._find(t["to"] if t["from"] == rec["address"] else t["from"])
                    if not other:
                        continue
                    rel = Relationship(
                        id=f"{self.name}:flow:{i}",
                        type=RelationType.TRANSFER,
                        source_id=wallet_id(rec["chain"], t["from"]),
                        target_id=wallet_id(rec["chain"], t["to"]),
                        amount=t["amount"],
                        currency=t["currency"],
                        tx_count=t["count"],
                        start_date=resolve_date(t.get("first")),
                        role=f"{t['count']} tx · {t['amount']:,} {t['currency']} · last {resolve_date(t.get('last'))}",
                        sources=[self.provenance(me, f"{self.base_url}/address/{rec['address']}")],
                    )
                    out.append(LinkedEntity(relationship=rel, entity=self._wallet(other)))
            return out
        # Company / person: wallets it controls
        for rec in self.data["wallets"]:
            if set(rec.get("controlled_by", [])) & set(entity.record_ids):
                wallet = self._wallet(rec)
                out.append(
                    LinkedEntity(
                        relationship=self._control(entity.id, wallet.id, rec), entity=wallet
                    )
                )
        return out

    def _control(self, owner_id: str, wallet_rid: str, rec: dict[str, Any]) -> Relationship:
        return Relationship(
            id=f"{self.name}:ctrl:{owner_id}>{rec['address']}",
            type=RelationType.CONTROLS,
            source_id=owner_id,
            target_id=wallet_rid,
            role=rec.get("label") or "Wallet attributed to the entity",
            sources=[self.provenance(wallet_rid, f"{self.base_url}/address/{rec['address']}")],
        )

    @staticmethod
    def _owner(record_id: str) -> Entity | None:
        for cls in (DemoIntlRegistry, DemoFrRegistry):
            if record_id.startswith(f"{cls.name}:"):
                conn = cls()
                native = conn.native_id(record_id)
                return (
                    conn.get_company_details(record_id) or conn.get_person_details(record_id)
                    if native
                    else None
                )
        return None


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
    DemoChainConnector,
]
