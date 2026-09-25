"""SEC EDGAR — US Securities and Exchange Commission filings.

Public data, no key (the SEC only asks for a User-Agent naming a contact).
For every US-registered filer (listed companies, funds, many foreign issuers):

* company profile — legal name, former names, state of incorporation,
  industry (SIC), business address, exchanges and tickers;
* financials — revenue, net income, total assets and equity from the XBRL
  data of the annual reports (10-K / 20-F);
* significant shareholders — Schedule 13D / 13G: anyone holding more than 5 %
  of a listed class must file one. Since December 2024 these filings are
  structured XML with the exact percentage, the holder type and citizenship;
* recent filings as linked documents (annual / quarterly reports, 8-K,
  ownership filings, proxy statements).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
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
from app.risk.config import get_country_risk

SEARCH = "https://efts.sec.gov/LATEST/search-index"
DATA = "https://data.sec.gov"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{doc}"
UI = "https://www.sec.gov/edgar/browse/?CIK={cik}"
OWNERSHIP_FORMS = ("SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G")
DOCUMENT_FORMS = {
    "10-K": "accounts",
    "20-F": "accounts",
    "40-F": "accounts",
    "10-Q": "filing",
    "8-K": "filing",
    "6-K": "filing",
    "DEF 14A": "filing",
}
MAX_OWNERSHIP_FILINGS = 8
MAX_DOCUMENTS = 15
# (label, us-gaap concepts in order of preference)
FINANCIALS = [
    (
        "revenue",
        ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
    ),
    ("net_income", ("NetIncomeLoss", "ProfitLoss")),
    ("total_assets", ("Assets",)),
]
PERSON_TYPES = {"IN"}  # Schedule 13 "type of reporting person": IN = individual


def _cik(value: str) -> str:
    return str(int(re.sub(r"\D", "", value) or 0))


def _money(v: float | None) -> str | None:
    return f"{v:,.0f}" if v is not None else None


class SecEdgarConnector(BaseConnector):
    name = "sec_edgar"
    label = "SEC EDGAR — US filings, financials and 5 % shareholders (13D/13G)"
    kind = "registry"
    jurisdictions = {"US"}
    crossref_max_depth = 1
    homepage = "https://www.sec.gov/edgar"
    documents_max_depth = 1
    min_interval_seconds = 0.12  # SEC fair access: 10 requests per second

    @property
    def _headers(self) -> dict[str, str]:
        # The SEC blocks requests without a declared contact in the User-Agent.
        return {"User-Agent": self.settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}

    def _get(self, url: str, **params: Any) -> Any:
        return self.http_get_json(url, params=params or None, headers=self._headers)

    def _submissions(self, cik: str) -> dict[str, Any]:
        return self._get(f"{DATA}/submissions/CIK{int(cik):010d}.json") or {}

    def _recent(self, sub: dict[str, Any]) -> list[dict[str, Any]]:
        rec = (sub.get("filings") or {}).get("recent") or {}
        keys = ("form", "filingDate", "accessionNumber", "primaryDocument", "reportDate")
        n = len(rec.get("form", []))
        return [{k: (rec.get(k) or [None] * n)[i] for k in keys} for i in range(n)]

    def _url(self, cik: str, f: dict[str, Any]) -> str:
        return ARCHIVES.format(
            cik=cik,
            adsh=(f.get("accessionNumber") or "").replace("-", ""),
            doc=f.get("primaryDocument") or "",
        )

    def _financials(self, cik: str) -> dict[str, Any]:
        """Latest annual values from the XBRL company concepts."""
        out: dict[str, Any] = {}
        history: dict[str, dict[str, float]] = {}
        for label, concepts in FINANCIALS:
            for concept in concepts:
                data = self._get(
                    f"{DATA}/api/xbrl/companyconcept/CIK{int(cik):010d}/us-gaap/{concept}.json"
                )
                facts = [
                    f
                    for f in ((data or {}).get("units") or {}).get("USD", [])
                    if f.get("form") in ("10-K", "20-F", "40-F")
                    and f.get("fp") == "FY"
                    and f.get("end")
                ]
                if not facts:
                    continue
                for f in facts:
                    history.setdefault(f["end"][:4], {})[label] = f["val"]
                latest = max(facts, key=lambda f: (f["end"], f.get("filed", "")))
                out[f"{label}_usd"] = _money(latest["val"])
                out.setdefault("financial_year_end", latest["end"])
                break
        if history:
            out["financials"] = [
                {
                    "year": y,
                    **{k: _money(v) for k, v in vals.items()},
                    "currency": "USD",
                    "source": "SEC XBRL",
                }
                for y, vals in sorted(history.items(), reverse=True)[:5]
            ]
        return out

    def _company(self, cik: str, sub: dict[str, Any], with_financials: bool = False) -> Entity:
        rid = self.record_id(cik)
        addr = (sub.get("addresses") or {}).get("business") or {}
        address = ", ".join(
            p
            for p in (
                addr.get("street1"),
                addr.get("street2"),
                addr.get("city"),
                addr.get("stateOrCountry"),
                addr.get("zipCode"),
            )
            if p
        )
        filings = self._recent(sub)
        annual = next((f for f in filings if f["form"] in ("10-K", "20-F", "40-F")), None)
        state = sub.get("stateOfIncorporation") or ""
        # Incorporated in a US state -> US; otherwise EDGAR gives a country name ("Cayman Islands").
        if state in _US_STATES:
            jurisdiction: str | None = "US"
        else:
            jurisdiction = get_country_risk().code_for(sub.get("stateOfIncorporationDescription"))
        extra: dict[str, Any] = {
            k: v
            for k, v in {
                "state_of_incorporation": sub.get("stateOfIncorporationDescription")
                or state
                or None,
                "tickers": ", ".join(sub.get("tickers") or []) or None,
                "exchanges": ", ".join(e for e in sub.get("exchanges") or [] if e) or None,
                "filer_category": sub.get("category") or None,
                "fiscal_year_end": sub.get("fiscalYearEnd") or None,
            }.items()
            if v
        }
        if with_financials:
            extra.update(self._financials(cik))
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=sub.get("name") or cik,
            aliases=[n["name"] for n in sub.get("formerNames") or [] if n.get("name")][:5],
            jurisdiction=jurisdiction,
            registration_number=f"CIK {cik}",
            legal_form=sub.get("entityType") or None,
            status=CompanyStatus.ACTIVE if filings else CompanyStatus.UNKNOWN,
            last_accounts_date=parse_date(annual["filingDate"]) if annual else None,
            activity=sub.get("sicDescription") or None,
            address=address or None,
            identifiers={
                k: v
                for k, v in {
                    "CIK": cik,
                    "LEI": sub.get("lei"),
                    "Ticker": (sub.get("tickers") or [None])[0],
                }.items()
                if v
            },
            sources=[self.provenance(rid, UI.format(cik=cik))],
            extra=extra if annual or not with_financials else {**extra, "accounts_unknown": True},
        )

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = self._get(SEARCH, keysTyped=name) or {}
        out = []
        for hit in ((data.get("hits") or {}).get("hits") or [])[:6]:
            cik = _cik(hit.get("_id", ""))
            label = ((hit.get("_source") or {}).get("entity") or "").strip()
            clean = re.sub(r"\s*\([A-Z0-9.\-, ]+\)\s*$", "", label) or label
            rid = self.record_id(cik)
            out.append(
                Entity(
                    id=rid,
                    record_ids=[rid],
                    type=EntityType.COMPANY,
                    name=clean,
                    registration_number=f"CIK {cik}",
                    identifiers={"CIK": cik},
                    sources=[self.provenance(rid, UI.format(cik=cik))],
                    extra={"accounts_unknown": True},
                )
            )
        return out

    def get_by_identifier(self, ident: Any) -> Entity | None:
        return (
            self.get_company_details(self.record_id(ident.value)) if ident.kind == "cik" else None
        )

    def get_company_details(self, company_id: str) -> Entity | None:
        cik = _cik(self.native_id(company_id))
        sub = self._submissions(cik)
        return self._company(cik, sub, with_financials=True) if sub.get("name") else None

    def _ownership(self, cik: str, f: dict[str, Any]) -> list[dict[str, Any]]:
        """Reporting persons of a structured Schedule 13D/G (XML since December 2024)."""
        if not (f.get("primaryDocument") or "").endswith(".xml"):
            return []
        adsh = (f.get("accessionNumber") or "").replace("-", "")
        text = self.http_get_text(
            ARCHIVES.format(cik=cik, adsh=adsh, doc="primary_doc.xml"), headers=self._headers
        )
        if not text:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        event = root.findtext(".//{*}eventDateRequiresFilingThisStatement") or root.findtext(
            ".//{*}dateOfEvent"
        )
        out = []
        for rp in root.iter():
            if not rp.tag.endswith(
                ("coverPageHeaderReportingPersonDetails", "reportingPersonInfo")
            ):
                continue
            name = rp.findtext(".//{*}reportingPersonName")
            pct = rp.findtext(".//{*}classPercent") or rp.findtext(".//{*}percentOfClass")
            if not name:
                continue
            try:
                share = float(pct) if pct else None
            except ValueError:
                share = None
            out.append(
                {
                    "name": name.strip(),
                    "pct": share,
                    "type": (rp.findtext(".//{*}typeOfReportingPerson") or "").strip(),
                    "citizenship": (rp.findtext(".//{*}citizenshipOrOrganization") or "").strip(),
                    "event": parse_date(_us_date(event)) if event else None,
                    "form": f.get("form"),
                    "filed": f.get("filingDate"),
                    "url": self._url(cik, f),
                }
            )
        return out

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        cik = _cik(self.native_id(company_id))
        sub = self._submissions(cik)
        me = self.record_id(cik)
        filings = [f for f in self._recent(sub) if (f["form"] or "").startswith(OWNERSHIP_FORMS)]
        holders: dict[str, dict[str, Any]] = {}
        for f in filings[:MAX_OWNERSHIP_FILINGS]:  # newest first: keep each holder's latest filing
            for h in self._ownership(cik, f):
                holders.setdefault(h["name"].upper(), h)
        out = []
        for h in holders.values():
            person = h["type"] in PERSON_TYPES
            oid = self.record_id(f"holder:{h['name'].upper()}")
            ended = h["pct"] is not None and h["pct"] < 5
            out.append(
                LinkedEntity(
                    relationship=Relationship(
                        id=f"{self.name}:13dg:{oid}>{me}",
                        type=RelationType.SHAREHOLDER,
                        source_id=oid,
                        target_id=me,
                        share_pct=h["pct"],
                        role=f"Beneficial owner — {h['form']} filed {h['filed']}"
                        + (" (below 5 %: exit filing)" if ended else ""),
                        start_date=h["event"] if not ended else None,
                        end_date=h["event"] if ended else None,
                        sources=[self.provenance(me, h["url"])],
                    ),
                    entity=Entity(
                        id=oid,
                        record_ids=[oid],
                        type=EntityType.PERSON if person else EntityType.COMPANY,
                        name=h["name"],
                        sources=[self.provenance(oid, h["url"])],
                        extra={"accounts_unknown": True} if not person else {},
                    ),
                )
            )
        return out

    def get_documents(self, entity: Entity) -> list[Document]:
        rid = next(
            (r for r in entity.record_ids if r.startswith(f"{self.name}:") and ":holder:" not in r),
            None,
        )
        if entity.type != EntityType.COMPANY or rid is None:
            return []
        cik = _cik(self.native_id(rid))
        docs = []
        for f in self._recent(self._submissions(cik)):
            form = f["form"] or ""
            kind = DOCUMENT_FORMS.get(form) or (
                "filing" if form.startswith(OWNERSHIP_FORMS) else None
            )
            if kind is None:
                continue
            docs.append(
                Document(
                    title=f"SEC {form}"
                    + (f" — period {f['reportDate']}" if f.get("reportDate") else ""),
                    kind=kind,
                    date=parse_date(f["filingDate"]),
                    url=self._url(cik, f),
                    source=self.label,
                )
            )
            if len(docs) >= MAX_DOCUMENTS:
                break
        return docs


def _us_date(value: str) -> str:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", value or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else value


_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
    "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR",
}  # fmt: skip
