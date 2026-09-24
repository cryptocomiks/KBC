"""OpenCorporates — the largest open database of companies (140+ registries).

API: https://api.opencorporates.com/documentation/API-Reference
(token: OPENCORPORATES_API_TOKEN). Officers are returned per appointment, so
a person is identified here by name + date of birth when available.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.util import nationality_iso, parse_date, reorder_surname_first
from app.matching.names import name_similarity, normalize_person
from app.models import CompanyStatus, Entity, EntityType, LinkedEntity, Relationship, RelationType

API = "https://api.opencorporates.com/v0.4"
PERSON_MATCH_MIN = 85


def _country(jurisdiction_code: str | None) -> str | None:
    return (jurisdiction_code or "")[:2].upper() or None


class OpenCorporatesConnector(BaseConnector):
    name = "opencorporates"
    label = "OpenCorporates (international company registries)"
    kind = "registry"
    key_setting = "opencorporates_api_token"
    homepage = "https://opencorporates.com"

    def _get(self, path: str, **params: Any) -> Any:
        data = (
            self.http_get_json(f"{API}{path}", params={"api_token": self.api_key, **params}) or {}
        )
        return data.get("results") or {}

    def _company(self, c: dict[str, Any]) -> Entity:
        jur, num = c.get("jurisdiction_code", ""), c.get("company_number", "")
        rid = self.record_id(f"{jur}/{num}")
        status = (c.get("current_status") or "").lower()
        dissolved = (
            bool(c.get("dissolution_date"))
            or c.get("inactive")
            or any(w in status for w in ("dissolved", "struck", "closed", "inactive", "liquidat"))
        )
        address = c.get("registered_address_in_full")
        if not address and isinstance(c.get("registered_address"), dict):
            address = ", ".join(
                v for v in c["registered_address"].values() if isinstance(v, str) and v
            )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=c.get("name", num),
            aliases=[
                p.get("company_name")
                for p in c.get("previous_names") or []
                if p.get("company_name")
            ][:5],
            jurisdiction=_country(jur),
            registration_number=num,
            legal_form=c.get("company_type"),
            status=CompanyStatus.DISSOLVED
            if dissolved
            else CompanyStatus.ACTIVE
            if status
            else CompanyStatus.UNKNOWN,
            incorporation_date=parse_date(c.get("incorporation_date")),
            dissolution_date=parse_date(c.get("dissolution_date")),
            address=address,
            identifiers={"OpenCorporates": f"{jur}/{num}"},
            sources=[
                self.provenance(
                    rid,
                    c.get("opencorporates_url")
                    or f"https://opencorporates.com/companies/{jur}/{num}",
                )
            ],
            # OpenCorporates rarely carries filing data: never infer "no accounts" from it.
            extra={"accounts_unknown": True, "registry_status": c.get("current_status")}
            if c.get("current_status")
            else {"accounts_unknown": True},
        )

    @staticmethod
    def _person_key(name: str, dob: str | None) -> str:
        return f"p:{' '.join(normalize_person(name))}|{dob or ''}"

    def _person(self, o: dict[str, Any]) -> Entity:
        name = (
            reorder_surname_first(o.get("name", ""))
            if "," in o.get("name", "")
            else o.get("name", "")
        )
        dob = o.get("date_of_birth")
        rid = self.record_id(self._person_key(name, dob))
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=name,
            birth_date=dob,
            nationalities=nationality_iso(o.get("nationality")),
            sources=[self.provenance(rid, o.get("opencorporates_url"))],
        )

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        res = self._get("/companies/search", q=name, per_page=10)
        return [self._company(item["company"]) for item in res.get("companies", [])]

    def get_company_details(self, company_id: str) -> Entity | None:
        native = self.native_id(company_id)
        if native.startswith("p:"):
            return None
        res = self._get(f"/companies/{native}")
        return self._company(res["company"]) if res.get("company") else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        native = self.native_id(company_id)
        company = self._get(f"/companies/{native}").get("company") or {}
        out = []
        for i, item in enumerate(company.get("officers") or []):
            o = item.get("officer") or {}
            other = self._person(o)
            rel = Relationship(
                id=f"{self.name}:off:{native}:{i}",
                type=RelationType.OFFICER,
                source_id=other.id,
                target_id=self.record_id(native),
                role=o.get("position"),
                start_date=parse_date(o.get("start_date")),
                end_date=parse_date(o.get("end_date")),
                sources=[self.provenance(self.record_id(native), o.get("opencorporates_url"))],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def _officer_search(self, name: str) -> list[dict[str, Any]]:
        res = self._get("/officers/search", q=name, per_page=30)
        return [item.get("officer") or {} for item in res.get("officers", [])]

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        out: dict[str, Entity] = {}
        for o in self._officer_search(name):
            person = self._person(o)
            if name_similarity(name, person.name)[0] >= PERSON_MATCH_MIN:
                out.setdefault(person.id, person)
        return list(out.values())

    def get_person_details(self, person_id: str) -> Entity | None:
        native = self.native_id(person_id)
        if not native.startswith("p:"):
            return None
        name, dob = (native[2:].split("|") + [""])[:2]
        rid = self.record_id(native)
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=name.title(),
            birth_date=dob or None,
            sources=[self.provenance(rid, None)],
        )

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        native = self.native_id(person_id)
        if not native.startswith("p:"):
            return []
        name = native[2:].split("|")[0]
        out = []
        for i, o in enumerate(self._officer_search(name)):
            if self._person(o).id != self.record_id(native) or not o.get("company"):
                continue
            company = self._company(o["company"])
            rel = Relationship(
                id=f"{self.name}:role:{native}:{i}",
                type=RelationType.OFFICER,
                source_id=self.record_id(native),
                target_id=company.id,
                role=o.get("position"),
                start_date=parse_date(o.get("start_date")),
                end_date=parse_date(o.get("end_date")),
                sources=[self.provenance(company.id, o.get("opencorporates_url"))],
            )
            out.append(LinkedEntity(relationship=rel, entity=company))
        return out
