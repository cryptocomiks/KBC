"""GLEIF — Global Legal Entity Identifier (LEI) index.

Open API, no key: https://api.gleif.org/api/v1 (CC0 data). Every entity that
trades financial instruments has an LEI, with its registered address, local
registration number and — "Level 2" data — its direct and ultimate
accounting parents and its children. A worldwide, keyless source of
corporate ownership structures (percentages are not published: consolidation
links only).
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.util import parse_date
from app.models import (
    CompanyStatus,
    Document,
    Entity,
    EntityType,
    LinkedEntity,
    Relationship,
    RelationType,
)

API = "https://api.gleif.org/api/v1"
UI = "https://search.gleif.org/#/record/{lei}"
MAX_CHILDREN = 25


def _address(a: dict[str, Any] | None) -> str | None:
    if not a:
        return None
    parts = [*(a.get("addressLines") or []), a.get("postalCode"), a.get("city"), a.get("country")]
    return ", ".join(p for p in parts if p) or None


class GleifConnector(BaseConnector):
    name = "gleif"
    label = "GLEIF — Legal Entity Identifiers & parent companies"
    kind = "registry"
    homepage = "https://www.gleif.org"

    def _get(self, path: str, **params: Any) -> Any:
        return self.http_get_json(
            f"{API}{path}", params=params or None, headers={"Accept": "application/vnd.api+json"}
        )

    def _company(self, rec: dict[str, Any]) -> Entity:
        attrs = rec.get("attributes") or {}
        ent = attrs.get("entity") or {}
        lei = attrs.get("lei") or rec.get("id", "")
        rid = self.record_id(lei)
        jur = (ent.get("jurisdiction") or (ent.get("legalAddress") or {}).get("country") or "")[
            :2
        ].upper() or None
        status = (ent.get("status") or "").upper()
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=(ent.get("legalName") or {}).get("name") or lei,
            aliases=[n.get("name") for n in ent.get("otherNames") or [] if n.get("name")][:5],
            jurisdiction=jur,
            registration_number=ent.get("registeredAs"),
            legal_form=(ent.get("legalForm") or {}).get("other")
            or (ent.get("legalForm") or {}).get("id"),
            status=CompanyStatus.ACTIVE
            if status == "ACTIVE"
            else CompanyStatus.DISSOLVED
            if status == "INACTIVE"
            else CompanyStatus.UNKNOWN,
            incorporation_date=parse_date(ent.get("creationDate")),
            address=_address(ent.get("legalAddress")),
            identifiers={"LEI": lei},
            sources=[self.provenance(rid, UI.format(lei=lei))],
            extra={"accounts_unknown": True},  # GLEIF does not hold filings
        )

    def _lei(self, company_id: str) -> str:
        return self.native_id(company_id)

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        """Exact legal-name match first, then full-text. Full-text alone ranks a group's
        many subsidiaries ("Danone Hungary", "Fonds Danone"...) above the group head."""
        exact = (
            self._get("/lei-records", **{"filter[entity.legalName]": name.upper(), "page[size]": 5})
            or {}
        )
        fulltext = self._get("/lei-records", **{"filter[fulltext]": name, "page[size]": 10}) or {}
        seen: set[str] = set()
        out = []
        for rec in [*exact.get("data", []), *fulltext.get("data", [])]:
            if rec.get("id") not in seen:
                seen.add(rec.get("id"))
                out.append(self._company(rec))
        return out

    def get_by_identifier(self, ident: Any) -> Entity | None:
        return (
            self.get_company_details(self.record_id(ident.value)) if ident.kind == "lei" else None
        )

    def get_company_details(self, company_id: str) -> Entity | None:
        data = self._get(f"/lei-records/{self._lei(company_id)}") or {}
        return self._company(data["data"]) if data.get("data") else None

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        """Direct and ultimate accounting parents (GLEIF level-2 relationship data)."""
        lei = self._lei(company_id)
        out: list[LinkedEntity] = []
        for kind, role in (
            (
                "direct-parent",
                "Direct parent — accounting consolidation (GLEIF level 2, % not published)",
            ),
            (
                "ultimate-parent",
                "Ultimate parent (group head) — accounting consolidation (GLEIF level 2)",
            ),
        ):
            data = self._get(f"/lei-records/{lei}/{kind}") or {}
            parent = data.get("data")
            if not isinstance(parent, dict) or parent.get("type") != "lei-records":
                continue
            other = self._company(parent)
            if any(o.entity.id == other.id for o in out):
                continue  # the direct parent is also the group head
            rel = Relationship(
                id=f"{self.name}:{kind}:{lei}",
                type=RelationType.SHAREHOLDER if kind == "direct-parent" else RelationType.CONTROLS,
                source_id=other.id,
                target_id=self.record_id(lei),
                role=role,
                sources=[self.provenance(self.record_id(lei), UI.format(lei=lei))],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def get_subsidiaries(self, company_id: str) -> list[LinkedEntity]:
        lei = self._lei(company_id)
        data = (
            self._get(f"/lei-records/{lei}/direct-children", **{"page[size]": MAX_CHILDREN}) or {}
        )
        out = []
        for child in data.get("data", []) or []:
            if child.get("type") != "lei-records":
                continue
            other = self._company(child)
            rel = Relationship(
                id=f"{self.name}:child:{lei}:{other.id}",
                type=RelationType.SHAREHOLDER,
                source_id=self.record_id(lei),
                target_id=other.id,
                role="Direct parent — accounting consolidation (GLEIF level 2, % not published)",
                sources=[self.provenance(self.record_id(lei), UI.format(lei=lei))],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def get_documents(self, entity: Entity) -> list[Document]:
        lei = entity.identifiers.get("LEI")
        if not lei:
            return []
        return [
            Document(
                title="LEI record (GLEIF)",
                kind="register",
                url=UI.format(lei=lei),
                summary=f"LEI {lei}",
                source=self.label,
            )
        ]
