"""Free public sources, no key and no quota.

- SHAB / FOSC (CH): Swiss Official Gazette of Commerce — commercial-register changes,
  bankruptcies, compositions with creditors, calls to creditors (amtsblattportal.ch).
- VIES (EU): the Commission's VAT number check — active or not, and the name and address
  the tax administration holds.
- CRO (IE): the Irish Companies Registration Office register, open data (daily), with the
  accounts filed each year.
- Find Case Law (UK): judgments of the courts of England and Wales (The National Archives).
- RDAP (worldwide): domain registration data — creation date, registrar, status — of the
  company's websites; a website created a few weeks ago is a shell-company signal.
- EU Transparency Register: organisations registered as interest representatives
  (lobbying) with the EU institutions — compact index rebuilt monthly from the
  Commission's export (scripts/update_transparency_register.py).

Privacy: the gazette and the case law are searched for companies only (the gazette also
lists debt proceedings against private individuals), and for public figures in the case
law, like the other court sources.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import threading
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any
from urllib.parse import quote

from unidecode import unidecode

from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.public_figures import may_query
from app.connectors.wayback import websites
from app.models import CompanyStatus, Document, Entity, EntityType
from app.settings import CONFIG_DIR

log = logging.getLogger(__name__)


LEGAL_WORDS = {
    "ag", "sa", "sarl", "gmbh", "ltd", "limited", "plc", "inc", "llc", "srl", "spa",
    "sas", "bv", "nv", "the", "in", "liquidation", "liq", "dac", "clg", "uc", "co",
    "company", "kg", "se", "oy", "ab", "as", "sagl", "und", "et", "cie",
}  # fmt: skip


def _norm(name: str) -> str:
    """Lower-case, no accents, no punctuation, no legal-form words: for name matching."""
    s = re.sub(r"[^a-z0-9 ]+", " ", unidecode(name or "").lower())
    return " ".join(w for w in s.split() if w not in LEGAL_WORDS)


def core_name(name: str) -> str:
    """The name as written, without the trailing legal form ("Carillion PLC" -> "Carillion")."""
    words = re.sub(r",", " ", name or "").replace(".", "").split()
    while words and unidecode(words[-1]).lower() in LEGAL_WORDS:
        words.pop()
    return " ".join(words) or (name or "").strip()


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


# ------------------------------------------------------------------ SHAB / FOSC
SHAB_API = "https://amtsblattportal.ch/api/v1/publications"
SHAB_UI = "https://www.shab.ch/#!/search/publications/detail/{id}"
SHAB_RUBRICS = {
    "HR": ("Commercial register", []),
    "KK": ("Bankruptcy", ["insolvency"]),
    "NA": ("Composition with creditors (debt restructuring)", ["insolvency"]),
    "SR": ("Call to creditors", []),
    "LS": ("Liquidation / call to creditors", []),
}
HR_SUB = {"HR01": "new registration", "HR02": "change", "HR03": "deletion"}


class ShabConnector(BaseConnector):
    name = "ch_shab"
    label = "SHAB / FOSC — Swiss Official Gazette of Commerce"
    kind = "documents"
    homepage = "https://www.shab.ch"
    jurisdictions = {"CH"}
    document_types = {"company"}
    documents_max_depth = 2
    max_retries = 1
    timeout_seconds = 20.0

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY or len(_norm(entity.name)) < 3:
            return []
        data: Any = self.http_get_json(
            SHAB_API,
            params={
                "publicationStates": "PUBLISHED",
                "keyword": entity.name[:80],
                "pageRequest.page": 0,
                "pageRequest.size": 40,
            },
            headers={"Accept": "application/json"},
        )
        want = _norm(entity.name)
        docs = []
        for item in (data or {}).get("content") or []:
            meta = item.get("meta") or {}
            rubric = meta.get("rubric") or ""
            if rubric not in SHAB_RUBRICS:
                continue  # debt enforcement against individuals, notices from other bodies
            titles = meta.get("title") or {}
            title = next(
                (t for t in (titles.get("en"), titles.get("fr"), titles.get("de")) if t and not t.startswith(("EN_", "FR_"))),
                titles.get("de") or "",
            )  # fmt: skip
            if want not in _norm(title):
                continue  # the keyword search is full-text: keep notices naming the company
            label, flags = SHAB_RUBRICS[rubric]
            sub = HR_SUB.get(meta.get("subRubric") or "")
            docs.append(
                Document(
                    title=title[:220],
                    kind="legal_notice",
                    date=_day(meta.get("publicationDate")),
                    url=SHAB_UI.format(id=meta.get("id")),
                    summary=f"{label}{f' — {sub}' if sub else ''} · n° {meta.get('publicationNumber')}"
                    + (f" · {', '.join(meta.get('cantons') or [])}" if meta.get("cantons") else ""),
                    source=self.label,
                    flags=flags,
                )
            )
        return docs[:25]


# ------------------------------------------------------------------------ VIES
VIES_API = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{cc}/vat/{number}"
VIES_UI = "https://ec.europa.eu/taxation_customs/vies/#/vat-validation"
EU_VAT = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE",
    "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI",
}  # fmt: skip


def vat_numbers(entity: Entity) -> list[tuple[str, str]]:
    """(country prefix, number) of the VAT numbers known or derivable for a company."""
    out: list[tuple[str, str]] = []
    for key, value in entity.identifiers.items():
        if re.search(r"vat|tva|mwst|iva|btw|ust", key, re.I):
            m = re.fullmatch(
                r"([A-Z]{2})([0-9A-Z+*]{2,13})", re.sub(r"[\s.\-]", "", str(value).upper())
            )
            if m and m.group(1).replace("GR", "EL") in EU_VAT:
                out.append((m.group(1).replace("GR", "EL"), m.group(2)))
    jur = (entity.jurisdiction or "").upper()
    reg = re.sub(r"\D", "", entity.registration_number or "")
    if not out and jur == "FR" and len(reg) == 9:
        key = (12 + 3 * (int(reg) % 97)) % 97  # French VAT key from the SIREN
        out.append(("FR", f"{key:02d}{reg}"))
    if not out and jur == "BE" and len(reg) in (9, 10):
        out.append(("BE", reg.zfill(10)))
    return out[:2]


class ViesConnector(BaseConnector):
    name = "eu_vies"
    label = "VIES — EU VAT number validation (European Commission)"
    kind = "documents"
    homepage = VIES_UI
    document_types = {"company"}
    documents_max_depth = 1
    max_retries = 1
    timeout_seconds = 15.0

    def get_documents(self, entity: Entity) -> list[Document]:
        docs = []
        for cc, number in vat_numbers(entity):
            data: Any = self.http_get_json(VIES_API.format(cc=cc, number=quote(number)))
            if not isinstance(data, dict):
                continue
            err = str(data.get("userError") or "")
            if err in ("MS_UNAVAILABLE", "TIMEOUT", "SERVICE_UNAVAILABLE", "MS_MAX_CONCURRENT_REQ"):
                raise ConnectorError(f"{self.label}: {cc} tax administration unavailable ({err})")
            valid = bool(data.get("isValid"))
            name = str(data.get("name") or "").strip()
            address = re.sub(r"\s*\n\s*", ", ", str(data.get("address") or "").strip())
            shown = [x for x in (name, address) if x and x != "---"]
            summary = (
                ("Registered: " + " — ".join(shown))
                if shown
                else "Name and address not disclosed by this member state"
            )
            flags = []
            if not valid:
                flags.append("vat_invalid")
                summary = "Not an active VAT number for intra-EU trade. " + summary
            elif (
                name
                and name != "---"
                and _norm(name)
                and _norm(entity.name) not in _norm(name)
                and _norm(name) not in _norm(entity.name)
            ):
                flags.append("vat_name_mismatch")
                summary += " — the name differs from the register: check the identity"
            docs.append(
                Document(
                    title=f"EU VAT number {cc}{number} — {'valid' if valid else 'NOT VALID'} (VIES)",
                    kind="register",
                    date=_day(data.get("requestDate")),
                    url=VIES_UI,
                    summary=summary[:400],
                    source=self.label,
                    flags=flags,
                )
            )
        return docs


# ---------------------------------------------------------------- CRO (Ireland)
CRO_API = "https://opendata.cro.ie/api/3/action/datastore_search"
CRO_COMPANIES = "3fef41bc-b8f4-4b10-8434-ce51c29b1bba"
CRO_ACCOUNTS = {  # financial statements filed, by year of filing
    2024: "4dc79788-845b-4373-aaf9-77be6feb049b",
    2023: "dd413039-f628-4931-9788-dfc38eaf6b99",
    2022: "508d4f8a-74a1-40c7-8b86-cdf0d54a4929",
}
CRO_UI = "https://core.cro.ie/company/{num}"
CRO_ACTIVE = ("normal",)
CRO_WARNING = ("strike off listed", "liquidation", "receivership", "examinership", "struck off")


class CroConnector(BaseConnector):
    name = "ie_cro"
    label = "CRO — Irish Companies Registration Office (open data)"
    kind = "registry"
    jurisdictions = {"IE"}
    homepage = "https://cro.ie"

    def get_by_identifier(self, ident: Any) -> Entity | None:
        value = re.sub(r"\D", "", str(ident.value or ""))
        if ident.kind != "registration" or not (4 <= len(value) <= 6):
            return None
        return self.get_company_details(self.record_id(value))

    def _query(self, resource: str, **params: Any) -> list[dict[str, Any]]:
        data: Any = self.http_get_json(CRO_API, params={"resource_id": resource, **params}) or {}
        return list(((data.get("result") or {}).get("records")) or [])

    def _company(self, r: dict[str, Any]) -> Entity:
        num = str(r.get("company_num") or "").strip()
        rid = self.record_id(num)
        status = str(r.get("company_status") or "").strip()
        low = status.lower()
        address = ", ".join(
            str(r.get(f"company_address_{i}") or "").strip()
            for i in range(1, 5)
            if r.get(f"company_address_{i}")
        )
        extra: dict[str, Any] = {"register_status": status or None}
        if any(w in low for w in CRO_WARNING):
            extra["register_warning"] = f"Status in the Irish register: {status}"
        dissolved = _day(r.get("comp_dissolved_date"))
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=str(r.get("company_name") or num).strip(),
            jurisdiction="IE",
            registration_number=num,
            legal_form=r.get("company_type") or None,
            status=CompanyStatus.ACTIVE
            if low in CRO_ACTIVE
            else CompanyStatus.DISSOLVED
            if dissolved or "dissolved" in low
            else CompanyStatus.UNKNOWN,
            incorporation_date=_day(r.get("company_reg_date")),
            dissolution_date=dissolved,
            last_accounts_date=_day(r.get("last_accounts_date")),
            address=(address + ", Ireland") if address else None,
            identifiers={"CRO number": num},
            sources=[self.provenance(rid, CRO_UI.format(num=num))],
            extra=extra,
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return [
            self._company(r)
            for r in self._query(CRO_COMPANIES, q=name, limit=10)
            if r.get("company_num")
        ]

    def get_company_details(self, company_id: str) -> Entity | None:
        num = re.sub(r"\D", "", self.native_id(company_id))
        if not num:
            return None
        rows = self._query(CRO_COMPANIES, filters=json.dumps({"company_num": int(num)}), limit=1)
        return self._company(rows[0]) if rows else None

    def get_documents(self, entity: Entity) -> list[Document]:
        own = [r for r in entity.record_ids if r.startswith(f"{self.name}:")]
        if not own:
            return []
        num = re.sub(r"\D", "", self.native_id(own[0]))
        docs = [
            Document(
                title="Company record, filings and documents (CRO CORE)",
                kind="register",
                url=CRO_UI.format(num=num),
                summary=f"CRO n° {num}",
                source=self.label,
            )
        ]
        for year, resource in CRO_ACCOUNTS.items():
            try:
                rows = self._query(resource, filters=json.dumps({"company_num": int(num)}), limit=5)
            except ConnectorError:
                continue
            for r in rows:
                to = _day(r.get("submissions_accounts_to_date"))
                docs.append(
                    Document(
                        title=f"Financial statements filed{f' — accounts to {to}' if to else ''}",
                        kind="accounts",
                        date=_day(r.get("submission_reg_date") or r.get("submission_rec_date")),
                        url=CRO_UI.format(num=num),
                        summary=f"Submission {r.get('submission_num')} ({year} filings)",
                        source=self.label,
                    )
                )
        return docs


# --------------------------------------------------------- UK Find Case Law
CASELAW_ATOM = "https://caselaw.nationalarchives.gov.uk/atom.xml"
ATOM = "{http://www.w3.org/2005/Atom}"


class UkCaseLawConnector(BaseConnector):
    name = "uk_caselaw"
    label = "Find Case Law — UK court judgments (The National Archives)"
    kind = "documents"
    homepage = "https://caselaw.nationalarchives.gov.uk"
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 1
    timeout_seconds = 20.0

    def get_documents(self, entity: Entity) -> list[Document]:
        if not may_query(entity) or len(_norm(entity.name)) < 4:
            return []
        # "party" filters on the parties of the case; it needs the name without legal form.
        xml = self.http_get_text(CASELAW_ATOM, params={"party": core_name(entity.name)})
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise ConnectorError(f"{self.label}: unreadable answer") from exc
        want = _norm(entity.name)
        docs = []
        for e in root.findall(f"{ATOM}entry"):
            title = (e.findtext(f"{ATOM}title") or "").strip()
            if want not in _norm(title):
                continue  # full-text hit: keep the cases where the name is a party
            link = e.find(f"{ATOM}link[@rel='alternate']")
            court = (e.findtext(f"{ATOM}author/{ATOM}name") or "").strip()
            docs.append(
                Document(
                    title=title[:220],
                    kind="court_decision",
                    date=_day(e.findtext(f"{ATOM}published")),
                    url=link.get("href") if link is not None else self.homepage,
                    summary=court or None,
                    source=self.label + " — named as a party",
                    flags=["court"],
                )
            )
        return docs[:15]


# ------------------------------------------------------------------------- RDAP
RDAP = "https://rdap.org/domain/{domain}"
YOUNG_DOMAIN_DAYS = 365


class RdapConnector(BaseConnector):
    name = "rdap"
    label = "RDAP — domain registration data (ICANN registries)"
    kind = "archive"  # website pass: runs once the company's websites are known
    homepage = "https://rdap.org"
    document_types = {"company"}
    documents_max_depth = 1
    max_retries = 1
    timeout_seconds = 15.0

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY:
            return []
        docs = []
        for domain in websites(entity)[:2]:
            try:
                data: Any = self.http_get_json(RDAP.format(domain=domain))
            except ConnectorError as exc:
                log.info("RDAP lookup failed for %s: %s", domain, exc)
                continue
            if not isinstance(data, dict):
                continue
            events = {
                ev.get("eventAction"): ev.get("eventDate")
                for ev in data.get("events") or []
                if isinstance(ev, dict)
            }
            created = _day(events.get("registration"))
            expires = _day(events.get("expiration"))
            registrar = ""
            for ent in data.get("entities") or []:
                if "registrar" in (ent.get("roles") or []):
                    for field in ((ent.get("vcardArray") or [None, []])[1]) or []:
                        if isinstance(field, list) and field and field[0] == "fn":
                            registrar = str(field[3])
            parts = [f"registered {created}" if created else "registration date not published"]
            if expires:
                parts.append(f"expires {expires}")
            if registrar:
                parts.append(f"registrar {registrar}")
            flags = []
            if created and (date.today() - created).days < YOUNG_DOMAIN_DAYS:
                flags.append("young_domain")
                parts.append("website created less than a year ago")
            if (
                created
                and entity.incorporation_date
                and created
                < entity.incorporation_date.replace(year=max(1, entity.incorporation_date.year - 5))
            ):
                parts.append("domain much older than the company: bought or reused")
            docs.append(
                Document(
                    title=f"Domain {domain} — registration data (RDAP)",
                    kind="website",
                    date=created,
                    url=RDAP.format(domain=domain),
                    summary=" · ".join(parts),
                    source=self.label,
                    flags=flags,
                )
            )
        return docs


# ------------------------------------------------------ EU Transparency Register
TR_UI = "https://transparency-register.europa.eu/search-register-or-update/organisation-detail_en?id={id}"
TR_FILE = CONFIG_DIR / "eu_transparency_register.json.gz"
_TR_LOCK = threading.Lock()
_TR_INDEX: dict[str, list[dict[str, Any]]] | None = None
_TR_META: dict[str, Any] = {}


def _tr_index() -> dict[str, list[dict[str, Any]]]:
    global _TR_INDEX
    with _TR_LOCK:
        if _TR_INDEX is None:
            index: dict[str, list[dict[str, Any]]] = {}
            try:
                with gzip.open(TR_FILE, "rt", encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, ValueError):
                payload = {}
            for org in payload.get("organisations") or []:
                for n in {org.get("name"), org.get("acronym")}:
                    key = _norm(n or "")
                    if len(key) >= 3:
                        index.setdefault(key, []).append(org)
            _TR_META.update(count=payload.get("count"), export_date=payload.get("export_date"))
            _TR_INDEX = index
        return _TR_INDEX


class EuTransparencyRegisterConnector(BaseConnector):
    name = "eu_transparency"
    label = "EU Transparency Register — lobbying with the EU institutions"
    kind = "documents"
    homepage = "https://transparency-register.europa.eu"
    document_types = {"company"}
    documents_max_depth = 2

    def status(self) -> tuple[bool, str]:
        enabled, msg = super().status()
        if enabled and not TR_FILE.exists():
            return False, "Index not built yet (workflow “EU Transparency Register index”)"
        return enabled, msg

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY:
            return []
        orgs = _tr_index().get(_norm(entity.name)) or []
        docs = []
        for o in orgs[:3]:
            details = [
                o.get("category"),
                o.get("form"),
                ", ".join(x for x in (o.get("city"), o.get("country")) if x),
            ]
            if o.get("ep"):
                details.append(f"{o['ep']} person(s) accredited to the European Parliament")
            if o.get("fte"):
                details.append(f"{o['fte']:g} FTE on EU lobbying")
            docs.append(
                Document(
                    title=f"Registered interest representative — {o.get('name')} (EU Transparency Register {o.get('id')})",
                    kind="register",
                    date=_day(o.get("since")),
                    url=TR_UI.format(id=o.get("id")),
                    summary=" · ".join(d for d in details if d),
                    source=self.label
                    + (
                        f" — export of {_TR_META['export_date']}"
                        if _TR_META.get("export_date")
                        else ""
                    ),
                    flags=["lobbying"],
                )
            )
        return docs


def transparency_loaded_at() -> str | None:
    """Export date of the loaded index (for the live check)."""
    _tr_index()
    return _TR_META.get("export_date")
