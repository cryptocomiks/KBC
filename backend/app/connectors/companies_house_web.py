"""UK Companies House without an API key — the public register website.

find-and-update.company-information.service.gov.uk answers its search pages in
JSON (companies and officers) and publishes officer lists and personal
appointments as stable, id-tagged HTML. That gives the UK register — including
the Register of Overseas Entities (foreign companies owning UK land, numbers
"OE…") — to deployments without a COMPANIES_HOUSE_API_KEY. When the key is set,
the API connector is used instead and this one switches itself off.

Moderate use only (one page per company / officer, cached): it is the same
public website a person would browse.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from app.connectors.companies_house import UI, CompaniesHouseConnector
from app.connectors.util import nationality_iso, parse_date, reorder_surname_first
from app.models import (
    Document,
    Entity,
    EntityType,
    LinkedEntity,
    Relationship,
    RelationType,
)

CORPORATE = re.compile(
    r"\b(limited|ltd|llp|plc|inc|corp|corporation|s\.?a\.?|s\.?à r\.?l|gmbh|ag|b\.?v\.?|n\.?v\.?|trust|nominees|secretaries|holdings|company)\b",
    re.I,
)
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)}  # fmt: skip


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _field(page: str, ident: str) -> str | None:
    m = re.search(rf'id="{re.escape(ident)}"[^>]*>(.*?)</(?:dd|span|h2|a)>', page, re.S)
    return _text(m.group(1)) or None if m else None


def _day(value: str | None) -> str | None:
    """'14 April 2025' -> '2025-04-14'."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def _month(value: Any) -> str | None:
    """'September 1953' (website) or {'month': 9, 'year': 1953} (API) -> '1953-09'."""
    if isinstance(value, dict):
        y, m = value.get("year"), value.get("month")
        return f"{int(y):04d}-{int(m):02d}" if y and m else (f"{int(y):04d}" if y else None)
    m = re.match(r"\s*([A-Za-z]+)\s+(\d{4})", str(value or ""))
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    return None


def _psc_percent(natures: list[str]) -> float | None:
    """Lower bound of the shareholding band: 'ownership-of-shares-25-to-50-percent' -> 25,
    'ownership-of-shares-more-than-25-percent-registered-overseas-entity' -> 25."""
    pct = None
    for n in natures:
        if not n.startswith("ownership-of-shares"):
            continue
        m = re.search(r"(?:more-than-)?(\d+)-(?:to-\d+-)?percent", n)
        if m:
            pct = max(pct or 0.0, float(m.group(1)))
    return pct


class CompaniesHouseWebConnector(CompaniesHouseConnector):
    name = "companies_house_web"
    label = (
        "Companies House (UK) — public register website, incl. overseas entities owning UK property"
    )
    key_setting = None
    max_retries = 1

    def status(self) -> tuple[bool, str]:
        if self.settings.companies_house_api_key:
            return False, "Disabled: COMPANIES_HOUSE_API_KEY is set, the API connector is used"
        return super().status()

    # --------------------------------------------------------- transport
    def _get(self, path: str, **params: Any) -> Any:
        """Search pages answer in JSON on the public website (same shape as the API)."""
        params.pop("items_per_page", None)
        return self.http_get_json(
            f"{UI}{path}", params=params or None, headers={"Accept": "application/json"}
        )

    def _page(self, path: str) -> str:
        return self.http_get_text(f"{UI}{path}", headers={"Accept": "text/html"}) or ""

    # ---------------------------------------------------------- builders
    def _company_from_profile(self, c: dict[str, Any]) -> Entity:
        entity = super()._company_from_profile(c)
        if (c.get("company_type") or c.get("type")) == "registered-overseas-entity" or str(
            c.get("company_number", "")
        ).startswith("OE"):
            entity.extra["uk_overseas_entity"] = True
            entity.jurisdiction = None  # registered abroad: the home country is in its address
            if c.get("external_registration_number"):
                entity.identifiers["Home registration number"] = c["external_registration_number"]
        return entity

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        out = super().search_company(name, **filters)
        return out[:10]

    def get_company_details(self, company_id: str) -> Entity | None:
        number = self.native_id(company_id)
        if ":" in number:
            return None
        data = self._get("/search/companies", q=number) or {}
        for item in data.get("items", []):
            if item.get("company_number") == number:
                return self._company_from_profile(
                    {**item, "company_name": item.get("title"), "type": item.get("company_type")}
                )
        return None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        number = self.native_id(company_id)
        if ":" in number:
            return []
        page = self._page(f"/company/{number}/officers")
        out = []
        for i in sorted({int(n) for n in re.findall(r'id="officer-name-(\d+)"', page)}):
            block = re.search(
                rf'id="officer-name-{i}".*?(?=id="officer-name-{i + 1}"|$)', page, re.S
            )
            chunk = block.group(0) if block else ""
            link = re.search(r'href="/officers/([^/"]+)/appointments"[^>]*>(.*?)</a>', chunk, re.S)
            raw_name = _text(link.group(2)) if link else (_field(page, f"officer-name-{i}") or "")
            officer_id = link.group(1) if link else None
            role = _field(chunk, f"officer-role-{i}")
            if CORPORATE.search(raw_name) and "," not in raw_name:
                rid = self.record_id(f"corp:{raw_name}")
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.COMPANY,
                    name=raw_name,
                    sources=[
                        self.provenance(
                            rid, f"{UI}/officers/{officer_id}/appointments" if officer_id else None
                        )
                    ],
                )
            else:
                native = f"officer:{officer_id}" if officer_id else f"psc:{number}:{i}"
                rid = self.record_id(native)
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.PERSON,
                    name=reorder_surname_first(raw_name),
                    birth_date=_month(_field(chunk, f"officer-date-of-birth-{i}")),
                    nationalities=nationality_iso(_field(chunk, f"officer-nationality-{i}")),
                    sources=[
                        self.provenance(
                            rid, f"{UI}/officers/{officer_id}/appointments" if officer_id else None
                        )
                    ],
                )
            rel = Relationship(
                id=f"{self.name}:off:{number}:{i}",
                type=RelationType.OFFICER,
                source_id=other.id,
                target_id=self.record_id(number),
                role=role,
                start_date=parse_date(_day(_field(chunk, f"officer-appointed-on-{i}"))),
                end_date=parse_date(_day(_field(chunk, f"officer-resigned-on-{i}"))),
                sources=[
                    self.provenance(self.record_id(number), f"{UI}/company/{number}/officers")
                ],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        """Persons with significant control — for overseas entities, the registrable beneficial owners."""
        number = self.native_id(company_id)
        if ":" in number:
            return []
        url = f"{UI}/company/{number}/persons-with-significant-control"
        page = self._page(f"/company/{number}/persons-with-significant-control")
        out = []
        for i in sorted({int(n) for n in re.findall(r'id="psc-name-(\d+)"', page)}):
            block = re.search(rf'id="psc-name-{i}".*?(?=class="appointment-{i + 1}"|$)', page, re.S)
            chunk = block.group(0) if block else ""
            name = _field(chunk, f"psc-name-{i}") or ""
            natures = re.findall(rf'id="psc-noc-{i}-([a-z0-9-]+)"', chunk)
            pct = _psc_percent(natures)
            label = "; ".join(
                _text(v)
                for v in re.findall(rf'id="psc-noc-{i}-[^"]+"[^>]*>(.*?)</dd>', chunk, re.S)
            )
            reg = _field(chunk, f"psc-registration-number-{i}")
            if reg or _field(chunk, f"psc-legal-form-{i}"):
                where = (_field(chunk, f"psc-country-registered-{i}") or "").lower()
                uk = any(
                    w in where
                    for w in ("england", "wales", "scotland", "northern ireland", "united kingdom")
                )
                rid = self.record_id(reg.upper() if reg and uk else f"corp:{name}")
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.COMPANY,
                    name=name,
                    registration_number=reg.upper() if reg else None,
                    jurisdiction="GB" if uk else None,
                    legal_form=_field(chunk, f"psc-legal-form-{i}"),
                    sources=[self.provenance(rid, url)],
                )
            else:
                rid = self.record_id(f"psc:{number}:{i}")
                other = Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.PERSON,
                    name=name,
                    birth_date=_month(_field(chunk, f"psc-date-of-birth-{i}")),
                    nationalities=nationality_iso(_field(chunk, f"psc-nationality-{i}")),
                    sources=[self.provenance(rid, url)],
                )
            overseas = any(n.endswith("registered-overseas-entity") for n in natures)
            rel = Relationship(
                id=f"{self.name}:psc:{number}:{i}",
                type=RelationType.BENEFICIAL_OWNER,
                source_id=other.id,
                target_id=self.record_id(number),
                role=(
                    ("Registrable beneficial owner" if overseas else "PSC")
                    + (f": {label}" if label else "")
                ),
                share_pct=pct,
                start_date=parse_date(_day(_field(chunk, f"psc-notified-on-{i}"))),
                end_date=parse_date(_day(_field(chunk, f"psc-ceased-on-{i}"))),
                sources=[self.provenance(self.record_id(number), url)],
            )
            out.append(LinkedEntity(relationship=rel, entity=other))
        return out

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        data = self._get("/search/officers", q=name) or {}
        out = []
        for item in data.get("items", [])[:15]:
            officer_id = self._officer_id(item.get("links"))
            if not officer_id:
                continue
            rid = self.record_id(f"officer:{officer_id}")
            out.append(
                Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.PERSON,
                    name=reorder_surname_first(item.get("title", "")),
                    birth_date=_month(item.get("date_of_birth")),
                    address=item.get("address_snippet"),
                    sources=[self.provenance(rid, f"{UI}/officers/{officer_id}/appointments")],
                )
            )
        return out

    def get_person_details(self, person_id: str) -> Entity | None:
        native = self.native_id(person_id)
        if not native.startswith("officer:"):
            return None
        officer_id = native.split(":", 1)[1]
        page = self._page(f"/officers/{officer_id}/appointments")
        m = re.search(r"<title[^>]*>(.*?) personal appointments", page, re.S)
        if not m:
            return None
        rid = self.record_id(native)
        dob = re.search(r'id="officer-date-of-birth-value"[^>]*>(.*?)</dd>', page, re.S)
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=reorder_surname_first(_text(m.group(1))),
            birth_date=_month(_text(dob.group(1))) if dob else None,
            nationalities=nationality_iso(_field(page, "nationality-value1")),
            sources=[self.provenance(rid, f"{UI}/officers/{officer_id}/appointments")],
        )

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        native = self.native_id(person_id)
        if not native.startswith("officer:"):
            return []
        officer_id = native.split(":", 1)[1]
        page = self._page(f"/officers/{officer_id}/appointments")
        out = []
        for i in sorted({int(n) for n in re.findall(r'id="company-name-(\d+)"', page)}):
            head = re.search(
                rf'id="company-name-{i}"[^>]*>\s*<a href="/company/([^"]+)">(.*?)</a>', page, re.S
            )
            if not head:
                continue
            number = head.group(1)
            title = re.sub(rf"\s*\({re.escape(number)}\)\s*$", "", _text(head.group(2)))
            company = self._company_from_profile(
                {
                    "company_number": number,
                    "company_name": title,
                    "company_status": (_field(page, f"company-status-value-{i}") or "").lower(),
                }
            )
            rel = Relationship(
                id=f"{self.name}:appt:{officer_id}:{i}",
                type=RelationType.OFFICER,
                source_id=self.record_id(native),
                target_id=company.id,
                role=_field(page, f"appointment-type-value{i}"),
                start_date=parse_date(_day(_field(page, f"appointed-value{i}"))),
                end_date=parse_date(_day(_field(page, f"resigned-value-{i}"))),
                sources=[
                    self.provenance(
                        self.record_id(native), f"{UI}/officers/{officer_id}/appointments"
                    )
                ],
            )
            out.append(LinkedEntity(relationship=rel, entity=company))
        return out

    def get_documents(self, entity: Entity) -> list[Document]:
        number = entity.identifiers.get("UK company number")
        if entity.type != EntityType.COMPANY or not number:
            return []
        docs = [
            Document(
                title="Companies House register page (filing history, officers, PSC)",
                kind="register",
                url=f"{UI}/company/{number}",
                source=self.label,
            )
        ]
        if entity.extra.get("uk_overseas_entity"):
            docs.append(
                Document(
                    title="Registered overseas entity — may own land or property in the UK",
                    kind="register",
                    url=f"{UI}/company/{number}/persons-with-significant-control",
                    summary="Foreign company on the UK Register of Overseas Entities (required to buy, sell or "
                    "lease UK land). Its registrable beneficial owners are listed on the register page; land "
                    "titles are held by HM Land Registry (OCOD dataset).",
                    source=self.label,
                    flags=["uk_property"],
                )
            )
        return docs
