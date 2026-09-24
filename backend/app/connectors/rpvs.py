"""RPVS — Slovak Register of Public Sector Partners (beneficial owners).

Every company that contracts with the Slovak state must register its
beneficial owners (konečný užívateľ výhod), verified by a lawyer, with their
date of birth and whether they are public officials. The register is open data
(OData v4, no key) and keeps the history (validity dates), so past owners show
as ended relationships.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.util import parse_date, person_name
from app.models import (
    CompanyStatus,
    Document,
    Entity,
    EntityType,
    LinkedEntity,
    Relationship,
    RelationType,
)

API = "https://rpvs.gov.sk/opendatav2"
UI = "https://rpvs.gov.sk/rpvs/Partner/Partner/Detail/{pid}"


def _odata_text(value: str) -> str:
    return value.replace("'", "''")


def _day(value: Any) -> str | None:
    return str(value)[:10] if value else None


class RpvsConnector(BaseConnector):
    name = "rpvs"
    label = "RPVS — Slovak register of public sector partners (beneficial owners)"
    kind = "registry"
    jurisdictions = {"SK"}
    homepage = "https://rpvs.gov.sk"

    def _company(self, row: dict[str, Any]) -> Entity:
        pid = (row.get("Partner") or {}).get("Id") or row.get("PartnerId") or row.get("Id")
        rid = self.record_id(str(pid))
        name = row.get("ObchodneMeno") or person_name(row.get("Meno"), row.get("Priezvisko"))
        ended = row.get("PlatnostDo")
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=name or f"RPVS partner {pid}",
            jurisdiction="SK",
            registration_number=row.get("Ico") or None,
            status=CompanyStatus.UNKNOWN,
            identifiers={"IČO": row["Ico"]} if row.get("Ico") else {},
            sources=[self.provenance(rid, UI.format(pid=pid))],
            extra={
                "accounts_unknown": True,
                "rpvs_registered_since": _day(row.get("PlatnostOd")),
                **({"rpvs_deregistered_on": _day(ended)} if ended else {}),
            },
        )

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = (
            self.http_get_json(
                f"{API}/PartneriVerejnehoSektora",
                params={
                    "$filter": f"contains(ObchodneMeno,'{_odata_text(name)}')",
                    "$expand": "Partner",
                },
            )
            or {}
        )
        seen: set[str] = set()
        out = []
        for row in data.get("value", [])[:15]:
            entity = self._company(row)
            if entity.id not in seen:
                seen.add(entity.id)
                out.append(entity)
        return out

    def get_by_identifier(self, ident: Any) -> Entity | None:
        value = str(ident.value)
        if not (value.isdigit() and len(value) == 8):
            return None
        data = (
            self.http_get_json(
                f"{API}/PartneriVerejnehoSektora",
                params={"$filter": f"Ico eq '{value}'", "$expand": "Partner"},
            )
            or {}
        )
        rows = data.get("value", [])
        return self._company(rows[-1]) if rows else None

    def _partner(self, company_id: str) -> dict[str, Any]:
        pid = self.native_id(company_id)
        if not pid.isdigit():
            return {}
        return (
            self.http_get_json(
                f"{API}/Partneri({pid})",
                params={"$expand": "KonecniUzivateliaVyhod,PartneriVerejnehoSektora"},
            )
            or {}
        )

    def get_company_details(self, company_id: str) -> Entity | None:
        data = self._partner(company_id)
        names = data.get("PartneriVerejnehoSektora") or []
        if not names:
            return None
        current = next((n for n in names if not n.get("PlatnostDo")), names[-1])
        entity = self._company({**current, "Partner": {"Id": data.get("Id")}})
        entity.aliases = sorted(
            {n.get("ObchodneMeno") for n in names if n.get("ObchodneMeno")} - {entity.name}
        )
        return entity

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        data = self._partner(company_id)
        pid = data.get("Id")
        if not pid:
            return []
        url = UI.format(pid=pid)
        out = []
        seen: set[tuple] = set()
        for i, row in enumerate(data.get("KonecniUzivateliaVyhod") or []):
            name = person_name(row.get("Meno"), row.get("Priezvisko"))
            if row.get("ObchodneMeno"):
                name = row["ObchodneMeno"]
            born = _day(row.get("DatumNarodenia"))
            key = (name.lower(), born, _day(row.get("PlatnostOd")), _day(row.get("PlatnostDo")))
            if not name or key in seen:
                continue
            seen.add(key)
            official = bool(row.get("JeVerejnyCinitel"))
            rid = self.record_id(f"person:{name.lower()}:{born or ''}")
            person = Entity(
                id=rid,
                record_ids=[rid],
                type=EntityType.PERSON,
                name=name,
                birth_date=born,
                sources=[self.provenance(rid, url)],
                extra={"public_official": True} if official else {},
            )
            rel = Relationship(
                id=f"{self.name}:kuv:{pid}:{row.get('Id', i)}",
                type=RelationType.BENEFICIAL_OWNER,
                source_id=rid,
                target_id=self.record_id(str(pid)),
                role="Beneficial owner (verified, RPVS)"
                + (" — public official" if official else ""),
                start_date=parse_date(_day(row.get("PlatnostOd"))),
                end_date=parse_date(_day(row.get("PlatnostDo"))),
                sources=[self.provenance(self.record_id(str(pid)), url)],
            )
            out.append(LinkedEntity(relationship=rel, entity=person))
        return out

    def get_documents(self, entity: Entity) -> list[Document]:
        if not any(r.startswith(f"{self.name}:") for r in entity.record_ids):
            return []
        pid = self.native_id(next(r for r in entity.record_ids if r.startswith(f"{self.name}:")))
        return [
            Document(
                title="RPVS entry — verified beneficial owners (Slovakia)",
                kind="register",
                url=UI.format(pid=pid),
                source=self.label,
            )
        ]
