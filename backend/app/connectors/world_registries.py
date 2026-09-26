"""Keyless company registers outside Europe, and EU Court of Justice case law.

- ACRA (SG): the Singapore register of entities, open data on data.gov.sg.
- Registrar of Companies (IL): the Israeli company register, open data on data.gov.il
  (flags companies marked as "violating" — unpaid annual fees or missing reports).
- Canada's Business Registries (CA): federal and provincial corporations, one search.
- CJEU (EU): judgments of the Court of Justice / General Court naming the company,
  through the EU Publications Office SPARQL endpoint (EUR-Lex / CELLAR).

Companies only (the registers have no officer data in these open datasets); the
court search follows the privacy rule of the other court sources.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.public_figures import may_query
from app.models import CompanyStatus, Document, Entity, EntityType


def _dmy(value: Any) -> date | None:
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(value or "").strip())
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


class _Register(BaseConnector):
    kind = "registry"
    key_setting = None
    country = ""

    def get_by_identifier(self, ident: Any) -> Entity | None:
        value = str(ident.value or "").strip().upper().replace(" ", "")
        return self.get_company_details(self.record_id(value)) if self.valid(value) else None

    def valid(self, value: str) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def get_documents(self, entity: Entity) -> list[Document]:
        own = [r for r in entity.record_ids if r.startswith(f"{self.name}:")]
        if not own:
            return []
        url = entity.sources[0].url if entity.sources else self.homepage
        return [
            Document(
                title=f"Register entry — {self.label.split(' — ')[0]}",
                kind="register",
                url=url,
                summary=f"n° {self.native_id(own[0])}",
                source=self.label,
            )
        ]


# ---------------------------------------------------------------- Singapore
SG_API = "https://data.gov.sg/api/action/datastore_search"
SG_RESOURCE = "d_3f960c10fed6145404ca7b821f263b87"  # ACRA — entities with UEN
SG_UI = "https://www.bizfile.gov.sg/"


class AcraConnector(_Register):
    name = "sg_acra"
    label = "ACRA — Singapore register of business entities"
    jurisdictions = {"SG"}
    country = "SG"
    homepage = "https://www.acra.gov.sg"

    def valid(self, value: str) -> bool:
        return bool(re.fullmatch(r"(\d{8,9}|[STR]\d{2}[A-Z]{2}\d{4})[A-Z]", value))

    def _company(self, r: dict[str, Any]) -> Entity:
        uen = str(r.get("uen") or "").strip()
        rid = self.record_id(uen)
        status = str(r.get("uen_status_desc") or "")
        address = " ".join(
            p for p in (r.get("reg_street_name"), r.get("reg_postal_code")) if p and p != "na"
        )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=str(r.get("entity_name") or uen).strip(),
            jurisdiction="SG",
            registration_number=uen,
            legal_form=r.get("entity_type_desc") or None,
            status=CompanyStatus.ACTIVE
            if status.lower() in ("registered", "live", "live company")
            else CompanyStatus.DISSOLVED
            if status
            else CompanyStatus.UNKNOWN,
            incorporation_date=_dmy(r.get("uen_issue_date")),
            address=(address + ", Singapore") if address else None,
            identifiers={"UEN": uen},
            sources=[self.provenance(rid, SG_UI)],
            extra={"accounts_unknown": True, "register_status": status or None},
        )

    def _query(self, **params: Any) -> list[dict[str, Any]]:
        data = self.http_get_json(SG_API, params={"resource_id": SG_RESOURCE, **params}) or {}
        return [r for r in (data.get("result") or {}).get("records") or [] if r.get("uen")]

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return [self._company(r) for r in self._query(q=name, limit=10)]

    def get_company_details(self, company_id: str) -> Entity | None:
        uen = self.native_id(company_id)
        rows = self._query(filters=f'{{"uen": "{uen}"}}', limit=1) if self.valid(uen) else []
        return self._company(rows[0]) if rows else None


# ------------------------------------------------------------------- Israel
IL_API = "https://data.gov.il/api/3/action/datastore_search"
IL_RESOURCE = "f004176c-b85f-4542-8901-7b3176f9a054"  # Registrar of Companies
IL_UI = "https://ica.justice.gov.il/GenericCorporarionInfo/SearchCorporation?unit=8"
F_NUMBER, F_NAME, F_NAME_EN = "מספר חברה", "שם חברה", "שם באנגלית"
F_TYPE, F_STATUS, F_SUBSTATUS = "סוג תאגיד", "סטטוס חברה", "תת סטטוס"
F_DATE, F_CITY, F_STREET, F_HOUSE = "תאריך התאגדות", "שם עיר", "שם רחוב", "מספר בית"
F_GOV, F_VIOLATING = "חברה ממשלתית", "מפרה"


class IsraelRegistrarConnector(_Register):
    name = "il_companies"
    label = "Israeli Registrar of Companies — company register"
    jurisdictions = {"IL"}
    country = "IL"
    homepage = "https://www.gov.il/en/departments/corporations_authority"

    def valid(self, value: str) -> bool:
        return bool(re.fullmatch(r"5\d{8}", value))

    def _company(self, r: dict[str, Any]) -> Entity:
        number = str(r.get(F_NUMBER) or "").strip()
        rid = self.record_id(number)
        status = str(r.get(F_STATUS) or "")
        english = str(r.get(F_NAME_EN) or "").strip()
        hebrew = str(r.get(F_NAME) or "").strip().replace("~", "״")
        active = "פעיל" in status
        extra: dict[str, Any] = {
            "accounts_unknown": True,
            "register_status": " — ".join(p for p in (status, r.get(F_SUBSTATUS)) if p) or None,
        }
        if str(r.get(F_VIOLATING) or "") == "מפרה":
            extra["register_warning"] = (
                "Marked as a violating company by the Registrar (unpaid annual fee or "
                "missing annual report)"
            )
        if str(r.get(F_GOV) or "") == "כן":
            extra["state_owned"] = True
        address = ", ".join(
            p
            for p in (
                " ".join(str(x) for x in (r.get(F_STREET), r.get(F_HOUSE)) if x),
                r.get(F_CITY),
            )
            if p
        )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=english or hebrew or number,
            aliases=[hebrew] if english and hebrew else [],
            jurisdiction="IL",
            registration_number=number,
            legal_form=r.get(F_TYPE) or None,
            status=CompanyStatus.ACTIVE if active else CompanyStatus.DISSOLVED,
            incorporation_date=_dmy(r.get(F_DATE)),
            address=address or None,
            identifiers={"Company number": number},
            sources=[self.provenance(rid, IL_UI)],
            extra=extra,
        )

    def _query(self, **params: Any) -> list[dict[str, Any]]:
        data = self.http_get_json(IL_API, params={"resource_id": IL_RESOURCE, **params}) or {}
        return [r for r in (data.get("result") or {}).get("records") or [] if r.get(F_NUMBER)]

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return [self._company(r) for r in self._query(q=name, limit=10)]

    def get_company_details(self, company_id: str) -> Entity | None:
        number = self.native_id(company_id)
        if not self.valid(number):
            return None
        rows = self._query(filters=f'{{"{F_NUMBER}": {int(number)}}}', limit=1)
        return self._company(rows[0]) if rows else None


# ------------------------------------------------------------------- Canada
CA_API = "https://ised-isde.canada.ca/cbr/srch/api/v1/search"
CA_UI = "https://ised-isde.canada.ca/cbr/srch/index-eng.html"
CA_PROVINCES = {
    "CC": "federal (Corporations Canada)", "ON": "Ontario", "QC": "Québec", "BC": "British Columbia",
    "AB": "Alberta", "MB": "Manitoba", "SK": "Saskatchewan", "NS": "Nova Scotia",
    "NB": "New Brunswick", "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island",
}  # fmt: skip


class CanadaRegistriesConnector(_Register):
    name = "ca_cbr"
    label = "Canada's Business Registries — federal and provincial corporations"
    jurisdictions = {"CA"}
    country = "CA"
    homepage = "https://ised-isde.canada.ca/cbr/srch/index-eng.html"

    def valid(self, value: str) -> bool:
        return bool(re.fullmatch(r"\d{9}", value))  # business number (BN9)

    def _company(self, d: dict[str, Any]) -> Entity:
        juri = str(d.get("Jurisdiction") or d.get("Registry_Source") or "")
        native = str(d.get("MRAS_ID") or f"{juri}_{d.get('Juri_ID')}")
        rid = self.record_id(native)
        bn = str(d.get("BN") or "")[:9]
        status = str(d.get("Status_State") or "")
        identifiers = {"Corporation number": str(d.get("Juri_ID") or "")}
        if bn:
            identifiers["Business number"] = bn
        city = ", ".join(
            p
            for p in (d.get("Reg_office_city") or d.get("City"), d.get("Reg_office_province"))
            if p
        )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=str(d.get("Company_Name") or native).strip(),
            jurisdiction="CA",
            registration_number=str(d.get("Juri_ID") or "") or None,
            legal_form=d.get("Entity_Type") or None,
            status=CompanyStatus.ACTIVE
            if status.lower() == "active"
            else CompanyStatus.DISSOLVED
            if status
            else CompanyStatus.UNKNOWN,
            incorporation_date=_dmy(d.get("Date_Incorporated")),
            address=(city + ", Canada") if city else None,
            identifiers=identifiers,
            sources=[self.provenance(rid, CA_UI)],
            extra={
                "accounts_unknown": True,
                "register": CA_PROVINCES.get(juri, juri) or None,
                "register_status": status or None,
            },
        )

    def _search(self, text: str) -> list[dict[str, Any]]:
        data = self.http_get_json(
            CA_API,
            params={
                "fq": f"keyword:{{{text}}}",
                "lang": "en",
                "queryaction": "fieldquery",
                "sortfield": "score",
                "sortorder": "desc",
            },
        )
        docs = (data or {}).get("docs") or [] if isinstance(data, dict) else []
        return [d for d in docs if isinstance(d, dict) and d.get("Company_Name")]

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        seen: set[str] = set()
        out = []
        for d in self._search(name.replace("{", " ").replace("}", " "))[:12]:
            e = self._company(d)
            if e.id not in seen:
                seen.add(e.id)
                out.append(e)
        return out

    def get_company_details(self, company_id: str) -> Entity | None:
        native = self.native_id(company_id)
        number = native.split("_", 1)[-1]
        for d in self._search(number):
            if str(d.get("MRAS_ID")) == native or str(d.get("BN") or "")[:9] == number:
                return self._company(d)
        return None


# ------------------------------------------------------------ EU court cases
CELLAR_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EURLEX = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"
MAX_JUDGMENTS = 8


def _sparql_text(value: str) -> str:
    return re.sub(r"[^\w\s.&-]", " ", value.lower()).strip()


class CjeuConnector(BaseConnector):
    name = "cjeu"
    label = "EU Court of Justice and General Court — judgments (EUR-Lex)"
    kind = "documents"
    homepage = "https://curia.europa.eu"
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 0
    timeout_seconds = 25.0

    def get_documents(self, entity: Entity) -> list[Document]:
        name = _sparql_text(entity.name)
        if not may_query(entity) or len(name) < 5:
            return []
        query = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex ?title ?date WHERE {{
  ?w cdm:work_has_resource-type ?type .
  FILTER(?type IN (<http://publications.europa.eu/resource/authority/resource-type/JUDG>,
                   <http://publications.europa.eu/resource/authority/resource-type/ORDER>))
  ?w cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?w cdm:work_date_document ?date }}
  ?e cdm:expression_belongs_to_work ?w ;
     cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> ;
     cdm:expression_title ?title .
  FILTER(CONTAINS(LCASE(STR(?title)), "{name}"))
}} ORDER BY DESC(?date) LIMIT {MAX_JUDGMENTS}"""
        data: Any = self.http_get_json(
            CELLAR_SPARQL,
            params={"query": query, "format": "application/sparql-results+json"},
            # the endpoint answers 406 to a plain "application/json"
            headers={"Accept": "application/sparql-results+json"},
        )
        rows = ((data or {}).get("results") or {}).get("bindings") or []
        docs = []
        for b in rows:
            celex = (b.get("celex") or {}).get("value")
            title = ((b.get("title") or {}).get("value") or "").replace("#", " — ").strip()
            if not celex or not title:
                continue
            docs.append(
                Document(
                    title=title[:220],
                    kind="court_decision",
                    date=_dmy((b.get("date") or {}).get("value")),
                    url=EURLEX.format(celex=celex),
                    summary=f"CELEX {celex}",
                    source="EU Court of Justice / General Court (EUR-Lex) — name in the case title",
                    flags=["court"],
                )
            )
        return docs
