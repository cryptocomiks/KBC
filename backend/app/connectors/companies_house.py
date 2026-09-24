"""UK Companies House — companies, officers and persons with significant control (PSC).

API: https://developer.company-information.service.gov.uk (free key:
COMPANIES_HOUSE_API_KEY, sent as HTTP basic-auth user). Rate limit 600
requests / 5 min. Officer ids come from the appointment links, which lets us
list every appointment of a person (their other companies).
"""

from __future__ import annotations

import re
from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.util import nationality_iso, parse_date, partial_date, reorder_surname_first
from app.models import CompanyStatus, Entity, EntityType, LinkedEntity, Relationship, RelationType

API = "https://api.company-information.service.gov.uk"
UI = "https://find-and-update.company-information.service.gov.uk"

# PSC "natures of control" -> lower bound of the ownership band (conservative).
_BANDS = {"25-to-50": 25.0, "50-to-75": 50.0, "75-to-100": 75.0}


def _psc_share(natures: list[str]) -> tuple[float | None, str]:
    pct = None
    for n in natures:
        if n.startswith("ownership-of-shares"):
            for band, low in _BANDS.items():
                if band in n:
                    pct = max(pct or 0, low)
    label = "; ".join(n.replace("-", " ") for n in natures)
    return pct, label


def _address(a: dict[str, Any] | None) -> str | None:
    if not a:
        return None
    parts = [
        a.get(k)
        for k in (
            "premises",
            "address_line_1",
            "address_line_2",
            "locality",
            "postal_code",
            "country",
        )
    ]
    return ", ".join(p for p in parts if p) or None


class CompaniesHouseConnector(BaseConnector):
    name = "companies_house"
    label = "Companies House (UK)"
    kind = "registry"
    key_setting = "companies_house_api_key"
    jurisdictions = {"GB"}
    homepage = UI

    def _get(self, path: str, **params: Any) -> Any:
        return self.http_get_json(f"{API}{path}", params=params or None, auth=(self.api_key, ""))

    # ---------------------------------------------------------- builders
    def _company_from_profile(self, c: dict[str, Any]) -> Entity:
        number = c.get("company_number", "")
        rid = self.record_id(number)
        status = (c.get("company_status") or "").lower()
        accounts = (c.get("accounts") or {}).get("last_accounts") or {}
        extra: dict[str, Any] = {}
        if "accounts" not in c:
            extra["accounts_unknown"] = True  # partial record (search / appointment)
        if (c.get("accounts") or {}).get("overdue"):
            extra["accounts_overdue"] = True
        if c.get("sic_codes"):
            extra["sic_codes"] = ", ".join(c["sic_codes"])
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=c.get("company_name") or c.get("title") or number,
            jurisdiction="GB",
            registration_number=number,
            legal_form=c.get("type") or c.get("company_type"),
            status=CompanyStatus.ACTIVE
            if status == "active"
            else CompanyStatus.DISSOLVED
            if status in ("dissolved", "liquidation", "converted-closed", "removed")
            else CompanyStatus.UNKNOWN,
            incorporation_date=parse_date(c.get("date_of_creation")),
            dissolution_date=parse_date(c.get("date_of_cessation")),
            last_accounts_date=parse_date(accounts.get("made_up_to")),
            address=_address(c.get("registered_office_address")) or c.get("address_snippet"),
            identifiers={"UK company number": number},
            sources=[self.provenance(rid, f"{UI}/company/{number}")],
            extra=extra,
        )

    def _officer_id(self, links: dict[str, Any] | None) -> str | None:
        path = (
            ((links or {}).get("officer") or {}).get("appointments")
            or (links or {}).get("self")
            or ""
        )
        m = re.search(r"/officers/([^/]+)/appointments", path)
        return m.group(1) if m else None

    def _person(
        self,
        name: str,
        officer_id: str | None,
        dob: dict[str, Any] | None,
        nationality: str | None,
        fallback_key: str,
    ) -> Entity:
        native = f"officer:{officer_id}" if officer_id else f"psc:{fallback_key}"
        rid = self.record_id(native)
        url = f"{UI}/officers/{officer_id}/appointments" if officer_id else None
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=reorder_surname_first(name),
            birth_date=partial_date((dob or {}).get("year"), (dob or {}).get("month")),
            nationalities=nationality_iso(nationality),
            sources=[self.provenance(rid, url)],
        )

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = self._get("/search/companies", q=name, items_per_page=10) or {}
        out = []
        for item in data.get("items", []):
            item = {
                **item,
                "company_name": item.get("title"),
                "company_status": item.get("company_status"),
                "date_of_creation": item.get("date_of_creation"),
                "date_of_cessation": item.get("date_of_cessation"),
                "type": item.get("company_type"),
            }
            out.append(self._company_from_profile(item))
        return out

    def get_company_details(self, company_id: str) -> Entity | None:
        number = self.native_id(company_id)
        if ":" in number:
            return None
        data = self._get(f"/company/{number}")
        return self._company_from_profile(data) if data else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        number = self.native_id(company_id)
        data = self._get(f"/company/{number}/officers", items_per_page=100) or {}
        out = []
        for i, o in enumerate(data.get("items", [])):
            officer_id = self._officer_id(o.get("links"))
            if o.get("officer_role", "").startswith("corporate"):
                corp_num = (o.get("identification") or {}).get("registration_number")
                rid = self.record_id(corp_num or f"corp:{o.get('name')}")
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.COMPANY,
                    name=o.get("name", ""),
                    registration_number=corp_num,
                    sources=[self.provenance(rid, None)],
                )
            else:
                other = self._person(
                    o.get("name", ""),
                    officer_id,
                    o.get("date_of_birth"),
                    o.get("nationality"),
                    f"{number}:{i}",
                )
            rel = Relationship(
                id=f"{self.name}:off:{number}:{i}",
                type=RelationType.OFFICER,
                source_id=other.id,
                target_id=self.record_id(number),
                role=(o.get("officer_role") or "").replace("-", " ").capitalize() or None,
                start_date=parse_date(o.get("appointed_on")),
                end_date=parse_date(o.get("resigned_on")),
                sources=[
                    self.provenance(self.record_id(number), f"{UI}/company/{number}/officers")
                ],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        number = self.native_id(company_id)
        data = (
            self._get(f"/company/{number}/persons-with-significant-control", items_per_page=100)
            or {}
        )
        out = []
        for i, p in enumerate(data.get("items", [])):
            pct, natures = _psc_share(p.get("natures_of_control") or [])
            kind = p.get("kind", "")
            if "corporate" in kind or "legal-person" in kind:
                ident = p.get("identification") or {}
                reg = ident.get("registration_number")
                country = (ident.get("country_registered") or "").strip()
                rid = self.record_id(reg or f"corp:{p.get('name')}")
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.COMPANY,
                    name=p.get("name", ""),
                    registration_number=reg,
                    jurisdiction="GB"
                    if country.lower()
                    in ("england", "wales", "scotland", "united kingdom", "england and wales")
                    else None,
                    sources=[self.provenance(rid, None)],
                )
            else:
                other = self._person(
                    p.get("name", ""),
                    None,
                    p.get("date_of_birth"),
                    p.get("nationality"),
                    f"{number}:{i}",
                )
            rel = Relationship(
                id=f"{self.name}:psc:{number}:{i}",
                type=RelationType.BENEFICIAL_OWNER,
                source_id=other.id,
                target_id=self.record_id(number),
                role=f"PSC: {natures}" if natures else "Person with significant control",
                share_pct=pct,
                start_date=parse_date(p.get("notified_on")),
                end_date=parse_date(p.get("ceased_on")),
                sources=[
                    self.provenance(
                        self.record_id(number),
                        f"{UI}/company/{number}/persons-with-significant-control",
                    )
                ],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        data = self._get("/search/officers", q=name, items_per_page=15) or {}
        out = []
        for item in data.get("items", []):
            officer_id = self._officer_id(item.get("links"))
            if not officer_id:
                continue
            person = self._person(
                item.get("title", ""), officer_id, item.get("date_of_birth"), None, officer_id
            )
            person.address = item.get("address_snippet")
            out.append(person)
        return out

    def get_person_details(self, person_id: str) -> Entity | None:
        native = self.native_id(person_id)
        if not native.startswith("officer:"):
            return None
        data = self._get(f"/officers/{native.split(':', 1)[1]}/appointments") or {}
        if not data:
            return None
        return self._person(
            data.get("name", ""), native.split(":", 1)[1], data.get("date_of_birth"), None, native
        )

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        native = self.native_id(person_id)
        if not native.startswith("officer:"):
            return []
        officer_id = native.split(":", 1)[1]
        data = self._get(f"/officers/{officer_id}/appointments", items_per_page=50) or {}
        out = []
        for i, a in enumerate(data.get("items", [])):
            co = a.get("appointed_to") or {}
            number = co.get("company_number")
            if not number:
                continue
            company = self._company_from_profile(
                {
                    "company_number": number,
                    "company_name": co.get("company_name"),
                    "company_status": co.get("company_status"),
                }
            )
            rel = Relationship(
                id=f"{self.name}:appt:{officer_id}:{i}",
                type=RelationType.OFFICER,
                source_id=self.record_id(native),
                target_id=company.id,
                role=(a.get("officer_role") or "").replace("-", " ").capitalize() or None,
                start_date=parse_date(a.get("appointed_on")),
                end_date=parse_date(a.get("resigned_on")),
                sources=[
                    self.provenance(
                        self.record_id(native), f"{UI}/officers/{officer_id}/appointments"
                    )
                ],
            )
            out.append(LinkedEntity(relationship=rel, entity=company))
        return out

    def search_address(self, address: str) -> list[Entity]:
        return []
