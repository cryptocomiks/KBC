"""More free sources, no key required (The Guardian: free developer key).

* UID register (Swiss Federal Statistical Office): every Swiss legal unit, including
  associations, foundations and sole traders outside the commercial register, with
  VAT status. Public SOAP web service, 20 requests / minute: subject only.
* German Bundestag Lobbyregister: interest representatives (open JSON search).
* ESMA interim MiCA register: authorised crypto-asset service providers (CASPs) and the
  list of **non-compliant** entities providing crypto services without authorisation.
* ASIC Banned and Disqualified Persons (Australia, data.gov.au, CC BY).
* Scam lists: crypto phishing domains (MetaMask eth-phishing-detect, ScamSniffer) and
  scam wallet addresses (ScamSniffer): matched on the websites and wallets of the network.
* The Guardian Open Platform: adverse media, with a free key (GUARDIAN_API_KEY).

Privacy: the Guardian is searched for companies and public figures only; the ASIC
register (a legal register of banned persons, like the UK disqualified directors) is
used for exact-name screening of the people already in the network.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from html import unescape
from typing import Any
from xml.sax.saxutils import escape

from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.crypto_util import detect_chain, normalize_address
from app.connectors.free_sources import _day, _norm
from app.connectors.public_figures import may_query
from app.connectors.wayback import websites
from app.matching.matcher import match_entities
from app.matching.names import name_similarity
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
from app.relevance import named_in, set_aside

log = logging.getLogger(__name__)

REFRESH_SECONDS = 12 * 3600


class _Lazy:
    """A downloaded list kept in memory by a server instance, refreshed twice a day."""

    def __init__(self) -> None:
        self.value: Any = None
        self.loaded_at = 0.0
        self.error = ""
        self.lock = threading.Lock()

    def get(self, load) -> Any:
        with self.lock:
            if self.value is None or time.time() - self.loaded_at > REFRESH_SECONDS:
                try:
                    self.value, self.error = load(), ""
                except (ConnectorError, ValueError, KeyError) as exc:
                    self.error = str(exc)
                    if self.value is None:
                        raise ConnectorError(str(exc)) from exc
                self.loaded_at = time.time()
            return self.value


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node: ET.Element | None, name: str) -> ET.Element | None:
    """First descendant with this local name (namespaces ignored)."""
    if node is None:
        return None
    for el in node.iter():
        if _local(el.tag) == name:
            return el
    return None


def _txt(node: ET.Element | None, name: str) -> str:
    el = _find(node, name)
    return (el.text or "").strip() if el is not None and el.text else ""


# ------------------------------------------------------------------ UID register (CH)
UID_WS = "https://www.uid-wse.admin.ch/V3.0/PublicServices.svc"
UID_UI = "https://www.uid.admin.ch/Detail.aspx?uid_id={uid}"
UID_SOAP = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:uid="http://www.uid.admin.ch/xmlns/uid-wse" '
    'xmlns:ns="http://www.uid.admin.ch/xmlns/uid-wse-shared/2">'
    "<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>"
)
# eCH-0097 legal forms (the most frequent)
UID_LEGAL_FORMS = {
    "0101": "Sole proprietorship",
    "0103": "General partnership",
    "0104": "Limited partnership",
    "0105": "Partnership limited by shares",
    "0106": "Company limited by shares (AG/SA)",
    "0107": "Limited liability company (GmbH/Sàrl)",
    "0108": "Cooperative",
    "0109": "Association",
    "0110": "Foundation",
    "0111": "Branch of a foreign company",
    "0113": "Special legal form",
    "0114": "Limited partnership for collective investment",
    "0115": "SICAV",
    "0116": "SICAF",
    "0117": "Public-law institution",
    "0151": "Swiss branch (commercial register)",
    "0220": "Federal administration",
    "0221": "Cantonal administration",
    "0223": "Municipal administration",
    "0224": "Public-law corporation",
    "0302": "Simple partnership / VAT group",
    "0312": "Foreign branch not in the commercial register",
    "0329": "International organisation",
    "0441": "Foreign company",
}
# eCH-0108 status of the unit in the UID register
UID_STATUS = {
    "1": ("provisional", CompanyStatus.ACTIVE),
    "2": ("being reactivated", CompanyStatus.ACTIVE),
    "3": ("definitive", CompanyStatus.ACTIVE),
    "4": ("being changed", CompanyStatus.ACTIVE),
    "5": ("deleted", CompanyStatus.DISSOLVED),
    "6": ("deleted (provisional)", CompanyStatus.DISSOLVED),
    "7": ("duplicate", CompanyStatus.UNKNOWN),
}
UID_VAT = {
    "1": "not registered for VAT",
    "2": "registered for VAT",
    "3": "VAT registration cancelled",
}


def _uid_fmt(num: str) -> str:
    d = re.sub(r"\D", "", num)
    return f"CHE-{d[0:3]}.{d[3:6]}.{d[6:9]}" if len(d) == 9 else num


class UidRegisterConnector(BaseConnector):
    name = "ch_uid"
    label = "UID register: Swiss legal units incl. associations, foundations, VAT (FSO)"
    kind = "registry"
    homepage = "https://www.uid.admin.ch"
    jurisdictions = {"CH"}
    # 20 requests per minute for the public service: the subject only
    crossref_max_depth = 0
    min_interval_seconds = 3.1
    max_retries = 0
    timeout_seconds = 20.0

    def _call(self, operation: str, body: str) -> ET.Element | None:
        text = self.http_post_text(
            UID_WS,
            UID_SOAP.format(body=body),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f"http://www.uid.admin.ch/xmlns/uid-wse/IPublicServices/{operation}",
            },
        )
        if not text:
            return None
        try:
            return ET.fromstring(text)
        except ET.ParseError as exc:
            raise ConnectorError(f"{self.label}: unreadable answer") from exc

    def _entity(self, org: ET.Element) -> Entity | None:
        num = _txt(org, "uidOrganisationId")
        if not num:
            return None
        uid = _uid_fmt(num)
        street = " ".join(x for x in (_txt(org, "street"), _txt(org, "houseNumber")) if x)
        town = " ".join(x for x in (_txt(org, "swissZipCode"), _txt(org, "town")) if x)
        status_label, status = UID_STATUS.get(
            _txt(org, "uidregStatusEnterpriseDetail"), ("", CompanyStatus.UNKNOWN)
        )
        form_code = _txt(org, "legalForm")
        vat = UID_VAT.get(_txt(org, "vatStatus"), "")
        rid = self.record_id(uid)
        in_hr = _find(org, "commercialRegisterInformation") is not None
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=_txt(org, "organisationName") or uid,
            jurisdiction="CH",
            registration_number=uid,
            legal_form=UID_LEGAL_FORMS.get(form_code, form_code or None),
            status=status,
            address=", ".join(x for x in (street, town) if x) or None,
            identifiers={"UID": uid},
            sources=[self.provenance(rid, UID_UI.format(uid=num))],
            extra={
                k: v
                for k, v in {
                    "uid_status": status_label,
                    "vat_status": vat,
                    "vat_since": _txt(org, "vatEntryDate") or None,
                    "commercial_register": "yes" if in_hr else "no (outside the register)",
                    "accounts_unknown": True,
                }.items()
                if v
            },
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        root = self._call(
            "Search",
            "<uid:Search><uid:searchParameters><ns:uidEntitySearchParameters>"
            f"<ns:organisationName>{escape(name[:100])}</ns:organisationName>"
            "</ns:uidEntitySearchParameters></uid:searchParameters></uid:Search>",
        )
        out = []
        for node in root.iter() if root is not None else []:
            if _local(node.tag) == "organisationType":
                ent = self._entity(node)
                if ent and name_similarity(name, ent.name, "company")[0] >= 80:
                    out.append(ent)
        return out[:8]

    def get_by_identifier(self, ident: Any) -> Entity | None:
        if ident.kind != "ch_uid":
            return None
        num = re.sub(r"\D", "", ident.value)
        root = self._call(
            "GetByUID",
            "<uid:GetByUID><uid:uid>"
            '<uidOrganisationIdCategorie xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2">CHE</uidOrganisationIdCategorie>'
            f'<uidOrganisationId xmlns="http://www.ech.ch/xmlns/eCH-0097-f/2">{num}</uidOrganisationId>'
            "</uid:uid></uid:GetByUID>",
        )
        node = _find(root, "organisationType")
        return self._entity(node) if node is not None else None

    def get_documents(self, entity: Entity) -> list[Document]:
        rid = next((r for r in entity.record_ids if r.startswith(f"{self.name}:")), None)
        if entity.type != EntityType.COMPANY or rid is None:
            return []
        uid = self.native_id(rid)
        parts = [
            f"UID status: {entity.extra['uid_status']}" if entity.extra.get("uid_status") else "",
            entity.extra.get("vat_status", ""),
            f"VAT since {entity.extra['vat_since']}" if entity.extra.get("vat_since") else "",
            f"commercial register: {entity.extra['commercial_register']}"
            if entity.extra.get("commercial_register")
            else "",
        ]
        return [
            Document(
                title=f"UID register: {entity.name} ({uid})",
                kind="register",
                url=UID_UI.format(uid=re.sub(r"\D", "", uid)),
                summary=" · ".join(p for p in parts if p),
                source=self.label,
            )
        ]


# ---------------------------------------------------------- Bundestag Lobbyregister (DE)
LOBBYREGISTER = "https://www.lobbyregister.bundestag.de/sucheJson"


def _eur_range(d: Any) -> str:
    if not isinstance(d, dict):
        return ""
    lo, hi = d.get("from"), d.get("to")
    if lo in (None, "") and hi in (None, ""):
        return ""
    try:
        return f"€{int(lo):,}–{int(hi):,}".replace(",", " ")
    except (TypeError, ValueError):
        return ""


class BundestagLobbyregisterConnector(BaseConnector):
    name = "de_lobbyregister"
    label = "Lobbyregister: German Bundestag and Federal Government (interest representatives)"
    kind = "documents"
    homepage = "https://www.lobbyregister.bundestag.de"
    document_types = {"company"}
    documents_max_depth = 1
    max_retries = 1

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY:
            return []
        data = self.http_get_json(LOBBYREGISTER, params={"q": entity.name[:80]})
        docs = []
        for r in (data or {}).get("results") or []:
            ident = r.get("lobbyistIdentity") or {}
            name = ident.get("name") or ""
            if _norm(name) != _norm(entity.name) and (
                name_similarity(entity.name, name, "company")[0] < 92
            ):
                continue
            details = r.get("registerEntryDetails") or {}
            account = r.get("accountDetails") or {}
            fte = (r.get("employeesInvolvedInLobbying") or {}).get("employeeFTE")
            spend = _eur_range((r.get("financialExpenses") or {}).get("financialExpensesEuro"))
            donations = _eur_range((r.get("donators") or {}).get("totalDonationsEuro"))
            topics = len((r.get("activitiesAndInterests") or {}).get("fieldsOfInterest") or [])
            projects = (r.get("regulatoryProjects") or {}).get("regulatoryProjectsCount")
            parts = [
                "active" if account.get("activeLobbyist") else "no longer active",
                f"{fte} FTE on lobbying" if fte else "",
                f"lobbying spend {spend} (last financial year)" if spend else "",
                f"donations received {donations}" if donations and donations != "€0–0" else "",
                f"{topics} fields of interest" if topics else "",
                f"{projects} regulatory projects" if projects else "",
            ]
            flags = ["lobbying"]
            if account.get("accountHasCodexViolations"):
                parts.insert(0, "CODE OF CONDUCT VIOLATION recorded by the Bundestag")
                flags.append("register_warning")
            docs.append(
                Document(
                    title=f"Registered interest representative: {name} (Lobbyregister {r.get('registerNumber')})",
                    kind="register",
                    date=_day((account.get("firstPublicationDate") or "")[:10]),
                    url=details.get("detailsPageUrl"),
                    summary=" · ".join(p for p in parts if p),
                    source=self.label,
                    flags=flags,
                )
            )
        return docs[:3]


# ------------------------------------------------------- ESMA interim MiCA register (EU)
MICA_PAGE = (
    "https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/"
    "markets-crypto-assets-regulation-mica"
)
MICA_FALLBACK = "https://www.esma.europa.eu/sites/default/files/2024-12/{file}.csv"
_MICA = _Lazy()


def _host(url: str) -> str:
    host = re.sub(r"^[a-z]+://", "", (url or "").strip().lower()).split("/")[0]
    return host.removeprefix("www.")


class MicaRegisterConnector(BaseConnector):
    name = "esma_mica"
    label = (
        "ESMA interim MiCA register: authorised and non-compliant crypto-asset service providers"
    )
    kind = "screening"
    homepage = MICA_PAGE
    timeout_seconds = 40.0

    def _file_url(self, page: str | None, file: str) -> str:
        m = re.search(rf'href="([^"]*/{file}\.csv)"', page or "")
        if not m:
            return MICA_FALLBACK.format(file=file)
        return (
            m.group(1)
            if m.group(1).startswith("http")
            else "https://www.esma.europa.eu" + m.group(1)
        )

    def _load(self) -> dict[str, list[dict[str, str]]]:
        try:
            page = self.http_get_text(MICA_PAGE)
        except ConnectorError:
            page = None
        out: dict[str, list[dict[str, str]]] = {}
        for file in ("CASPS", "NCASP"):
            text = self.http_get_text(self._file_url(page, file)) or ""
            rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
            out[file] = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]
        if not out["CASPS"]:
            raise ValueError("MiCA register downloaded but empty")
        return out

    def prefetch(self) -> None:
        threading.Thread(target=self._safe, daemon=True).start()

    def _safe(self) -> None:
        with contextlib.suppress(ConnectorError):  # reported when screening runs
            _MICA.get(self._load)

    @staticmethod
    def _name(row: dict[str, str]) -> str:
        return next(
            (
                row[k]
                for k in ("ae_lei_name", "ae_commercial_name", "ae_entityName", "ae_name")
                if row.get(k)
            ),
            next((v for k, v in row.items() if "name" in k.lower() and v), ""),
        )

    def _matches(
        self, entity: Entity, rows: list[dict[str, str]]
    ) -> list[tuple[dict[str, str], float, list[str]]]:
        lei = (entity.identifiers.get("LEI") or "").upper()
        sites = set(websites(entity))
        out = []
        for row in rows:
            listed = self._name(row)
            row_sites = {_host(u) for u in re.split(r"[|;, ]+", row.get("ae_website", "")) if u}
            if lei and row.get("ae_lei", "").upper() == lei:
                out.append((row, 100.0, ["same LEI"]))
            elif sites & row_sites:
                out.append((row, 95.0, [f"same website ({', '.join(sorted(sites & row_sites))})"]))
            elif listed:
                aliases = [row["ae_commercial_name"]] if row.get("ae_commercial_name") else []
                cand = Entity(
                    id=f"mica:{listed}", type=EntityType.COMPANY, name=listed, aliases=aliases
                )
                result = match_entities(entity, cand)
                if result.score >= 85:
                    out.append((row, result.score, result.explanation))
        return out

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        """Non-compliant entities (crypto services without authorisation): an alert."""
        if entity.type != EntityType.COMPANY:
            return []
        hits = []
        for row, score, why in self._matches(entity, _MICA.get(self._load).get("NCASP", [])):
            listed = self._name(row)
            details = {
                "competent_authority": row.get("ae_competentAuthority"),
                "member_state": row.get("ae_homeMemberState"),
                "website": row.get("ae_website"),
                "reason": row.get("ae_reason"),
                "decision_date": _au_date(row.get("ae_decision_date", "")),
                "comments": row.get("ae_comments"),
                "source": "ESMA interim MiCA register (CSV)",
            }
            hits.append(
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=ListType.ADVERSE,
                    dataset="ESMA MiCA: non-compliant entity (crypto services without authorisation)",
                    matched_name=listed,
                    score=score,
                    explanation=why,
                    details={k: v for k, v in details.items() if v},
                    provenance=self.provenance(self.record_id(f"NCASP:{listed}"), MICA_PAGE),
                )
            )
        return hits

    def get_documents(self, entity: Entity) -> list[Document]:
        """Authorised crypto-asset service providers: a licence, recorded as a register entry."""
        if entity.type != EntityType.COMPANY:
            return []
        try:
            rows = _MICA.get(self._load).get("CASPS", [])
        except ConnectorError:
            return []
        docs = []
        for row, _score, _why in self._matches(entity, rows)[:3]:
            services = [
                s.split(". ", 1)[-1] for s in row.get("ac_serviceCode", "").split("|") if s.strip()
            ]
            countries = [c for c in row.get("ac_serviceCode_cou", "").split("|") if c]
            parts = [
                f"authorised by {row.get('ae_competentAuthority')}"
                if row.get("ae_competentAuthority")
                else "",
                f"{len(services)} service(s): " + "; ".join(services[:4]) if services else "",
                f"passported to {len(countries)} countries" if countries else "",
                f"authorisation ended {row['ac_authorisationEndDate']}"
                if row.get("ac_authorisationEndDate")
                else "",
            ]
            when = row.get("ac_authorisationNotificationDate", "")
            docs.append(
                Document(
                    title=f"MiCA authorised crypto-asset service provider: {self._name(row)}",
                    kind="register",
                    date=_day(_au_date(when)) if when else None,
                    url=MICA_PAGE,
                    summary=" · ".join(p for p in parts if p),
                    source=self.label,
                )
            )
        return docs


# -------------------------------------------------- ASIC banned & disqualified persons
ASIC_PACKAGE = "https://data.gov.au/data/api/3/action/package_show?id=asic-banned-disqualified-per"
ASIC_UI = "https://moneysmart.gov.au/check-and-report-scams/banned-and-disqualified-persons"
_ASIC = _Lazy()


def _au_date(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


class AsicBannedConnector(BaseConnector):
    name = "asic_banned"
    label = "ASIC: banned and disqualified persons (Australia)"
    kind = "screening"
    homepage = ASIC_UI
    timeout_seconds = 40.0

    def _load(self) -> dict[str, list[dict[str, str]]]:
        pkg = self.http_get_json(ASIC_PACKAGE) or {}
        url = next(
            (
                r.get("url")
                for r in (pkg.get("result") or {}).get("resources") or []
                if (r.get("format") or "").upper() == "CSV"
            ),
            None,
        )
        if not url:
            raise ValueError("ASIC dataset: no CSV resource")
        text = (self.http_get_text(url) or "").lstrip("﻿")
        index: dict[str, list[dict[str, str]]] = {}
        for row in csv.DictReader(io.StringIO(text)):
            raw = (row.get("BD_PER_NAME") or "").strip()
            last, _, first = raw.partition(",")
            name = f"{first.strip()} {last.strip()}".strip().title()
            if name:
                row["name"] = name
                index.setdefault(_norm(last), []).append(row)
        if not index:
            raise ValueError("ASIC dataset downloaded but empty")
        return index

    def prefetch(self) -> None:
        threading.Thread(target=self._safe, daemon=True).start()

    def _safe(self) -> None:
        with contextlib.suppress(ConnectorError):  # reported when screening runs
            _ASIC.get(self._load)

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type != EntityType.PERSON:
            return []
        index = _ASIC.get(self._load)
        hits = []
        tokens = {_norm(t) for t in entity.name.split()}
        seen: set[str] = set()
        for token in tokens:
            for row in index.get(token, []):
                key = row["name"] + row.get("BD_PER_TYPE", "") + row.get("BD_PER_START_DT", "")
                if key in seen:
                    continue
                seen.add(key)
                cand = Entity(id=f"asic:{row['name']}", type=EntityType.PERSON, name=row["name"])
                result = match_entities(entity, cand)
                if result.score < 85:
                    continue
                end = _au_date(row.get("BD_PER_END_DT", ""))
                hits.append(
                    ScreeningHit(
                        entity_id=entity.id,
                        list_type=ListType.ADVERSE,
                        dataset="ASIC banned and disqualified persons (Australia)",
                        matched_name=row["name"],
                        score=result.score,
                        explanation=result.explanation,
                        details={
                            k: v
                            for k, v in {
                                "type": row.get("BD_PER_TYPE"),
                                "from": _au_date(row.get("BD_PER_START_DT", "")),
                                "until": end,
                                "expired": bool(end and end < date.today().isoformat()),
                                "locality": ", ".join(
                                    x
                                    for x in (
                                        row.get("BD_PER_ADD_LOCAL"),
                                        row.get("BD_PER_ADD_STATE"),
                                    )
                                    if x
                                ),
                                "comments": (row.get("BD_PER_COMMENTS") or "")[:300],
                                "source": "ASIC via data.gov.au (CC BY 3.0 AU)",
                            }.items()
                            if v
                        },
                        provenance=self.provenance(
                            self.record_id(row.get("BD_PER_DOC_NUM") or row["name"]), ASIC_UI
                        ),
                    )
                )
        return hits


# ------------------------------------------------------------------------ scam lists
METAMASK = "https://raw.githubusercontent.com/MetaMask/eth-phishing-detect/main/src/config.json"
SCAMSNIFFER_DOMAINS = (
    "https://raw.githubusercontent.com/scamsniffer/scam-database/main/blacklist/domains.json"
)
SCAMSNIFFER_ADDRESSES = (
    "https://raw.githubusercontent.com/scamsniffer/scam-database/main/blacklist/address.json"
)
_SCAM_DOMAINS = _Lazy()
_SCAM_ADDRESSES = _Lazy()


class ScamListsConnector(BaseConnector):
    name = "scam_lists"
    label = (
        "Crypto scam lists: phishing domains (MetaMask, ScamSniffer) and scam wallets (ScamSniffer)"
    )
    kind = "screening"
    homepage = "https://github.com/scamsniffer/scam-database"
    timeout_seconds = 60.0

    def _json(self, url: str) -> Any:
        text = self.http_get_text(url)
        try:
            return json.loads(text or "null")
        except ValueError as exc:
            raise ConnectorError(f"{self.label}: unreadable list") from exc

    def _domains(self) -> dict[str, str]:
        out: dict[str, str] = {}
        mm = self._json(METAMASK) or {}
        allowed = set(mm.get("whitelist") or [])
        for d in mm.get("blacklist") or []:
            if d not in allowed:
                out[d.lower()] = "MetaMask phishing list"
        for d in self._json(SCAMSNIFFER_DOMAINS) or []:
            if isinstance(d, str) and d.lower() not in allowed:
                out.setdefault(d.lower(), "ScamSniffer scam domains")
        if not out:
            raise ValueError("scam domain lists downloaded but empty")
        return out

    def _addresses(self) -> set[str]:
        return {a.lower() for a in self._json(SCAMSNIFFER_ADDRESSES) or [] if isinstance(a, str)}

    def prefetch(self) -> None:
        threading.Thread(target=self._safe, daemon=True).start()

    def _safe(self) -> None:
        with contextlib.suppress(ConnectorError):  # reported when screening runs
            _SCAM_DOMAINS.get(self._domains)
            _SCAM_ADDRESSES.get(self._addresses)

    def domain_hits(self, domain: str) -> str | None:
        """Name of the list flagging the domain (or its parent domain), None when clean."""
        table = _SCAM_DOMAINS.get(self._domains)
        parts = domain.lower().removeprefix("www.").split(".")
        for i in range(len(parts) - 1):
            source = table.get(".".join(parts[i:]))
            if source:
                return source
        return None

    def address_listed(self, address: str) -> bool:
        return address.strip().lower() in _SCAM_ADDRESSES.get(self._addresses)

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        hits = []
        if entity.type == EntityType.WALLET:
            chain = entity.chain or detect_chain(entity.name)
            if chain == "ETH" and self.address_listed(normalize_address(entity.name, chain)):
                hits.append(
                    ScreeningHit(
                        entity_id=entity.id,
                        list_type=ListType.ADVERSE,
                        dataset="ScamSniffer: scam / drainer wallet addresses",
                        matched_name=entity.name,
                        score=100.0,
                        explanation=["address listed verbatim"],
                        details={"source": "ScamSniffer scam-database (GitHub)"},
                        provenance=self.provenance(self.record_id(entity.name), self.homepage),
                    )
                )
        elif entity.type == EntityType.COMPANY:
            for domain in websites(entity):
                source = self.domain_hits(domain)
                if source:
                    hits.append(
                        ScreeningHit(
                            entity_id=entity.id,
                            list_type=ListType.ADVERSE,
                            dataset=f"Crypto phishing / scam domain: {source}",
                            matched_name=domain,
                            score=100.0,
                            explanation=[f"website {domain} is on the list"],
                            details={"domain": domain, "source": source},
                            provenance=self.provenance(self.record_id(domain), self.homepage),
                        )
                    )
        return hits


# ------------------------------------------------------------------------ The Guardian
GUARDIAN = "https://content.guardianapis.com/search"
RISK_TERMS = (
    'fraud OR corruption OR bribery OR sanctions OR "money laundering" OR embezzlement '
    "OR indicted OR convicted OR scandal OR investigation"
)


class GuardianConnector(BaseConnector):
    name = "guardian"
    label = "The Guardian: press archive (adverse media)"
    kind = "documents"
    key_setting = "guardian_api_key"
    homepage = "https://open-platform.theguardian.com"
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 1

    def get_documents(self, entity: Entity) -> list[Document]:
        if not may_query(entity):
            return []
        data = self.http_get_json(
            GUARDIAN,
            params={
                "q": f'"{entity.name}" AND ({RISK_TERMS})',
                "page-size": 10,
                "order-by": "relevance",
                "api-key": self.api_key,
            },
        )
        docs = []
        for r in ((data or {}).get("response") or {}).get("results") or []:
            title = r.get("webTitle") or ""
            doc = Document(
                title=title,
                kind="press",
                date=_day((r.get("webPublicationDate") or "")[:10]),
                url=r.get("webUrl"),
                summary=r.get("sectionName"),
                source=self.label,
                flags=["adverse_media"],
            )
            if not named_in(entity, title):
                set_aside(
                    doc, "the headline does not name the subject (mentioned in the text only)"
                )
            docs.append(doc)
        return docs


# ------------------------------------------------------------------ Lobbywatch (CH)
LOBBYWATCH = "https://cms.lobbywatch.ch/de/data/interface/v1/json"
LW_ORG_UI = "https://lobbywatch.ch/de/daten/organisation/{id}"
LW_PARL_UI = "https://lobbywatch.ch/de/daten/parlamentarier/{id}"
LW_ART = {
    "vorstand": "Board member",
    "geschaeftsfuehrend": "Management",
    "beirat": "Advisory board",
    "beratend": "Adviser",
    "mitglied": "Member",
    "taetig": "Works for",
    "finanziell": "Financial interest",
    "gesellschafter": "Partner / shareholder",
}
LW_FUNCTION = {"praesident": "Chair", "vizepraesident": "Vice-chair", "mitglied": ""}
LW_COUNCIL = {"NR": "National Council", "SR": "Council of States"}


def _lw_role(row: dict[str, Any]) -> str:
    art = LW_ART.get(
        row.get("art") or "", (row.get("art") or "").capitalize() or "Declared interest"
    )
    fn = LW_FUNCTION.get(row.get("funktion_im_gremium") or "", "")
    role = f"{art} ({fn})" if fn else art
    if row.get("verguetung") not in (None, "", "0"):
        role += f", paid CHF {row['verguetung']}"
    return role + ": declared interest (Lobbywatch)"


class LobbywatchConnector(BaseConnector):
    """Swiss federal parliamentarians, their declared interests (boards, advisory roles,
    memberships) and the organisations they are linked to. Public figures only: the
    lobbyists holding Federal Palace access badges are counted, not listed."""

    name = "lobbywatch"
    label = "Lobbywatch.ch: Swiss federal parliamentarians and their declared interests"
    kind = "registry"
    homepage = "https://lobbywatch.ch"
    jurisdictions = {"CH"}
    crossref_max_depth = 2
    max_retries = 1
    document_types = {"company", "person"}
    documents_max_depth = 2

    def _get(self, path: str) -> Any:
        from urllib.parse import quote

        data = self.http_get_json(f"{LOBBYWATCH}/{quote(path, safe='/')}")
        return (data or {}).get("data") if isinstance(data, dict) else None

    # --------------------------------------------------------------- entities
    def _org(self, o: dict[str, Any]) -> Entity:
        rid = self.record_id(f"o:{o.get('id') or o.get('organisation_id')}")
        uid = o.get("uid") or None
        address = ", ".join(
            x
            for x in (
                o.get("adresse_strasse"),
                " ".join(y for y in (o.get("adresse_plz"), o.get("ort")) if y),
            )
            if x
        )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=o.get("name") or o.get("organisation_name") or "?",
            jurisdiction="CH" if str(o.get("land_id") or "191") == "191" else None,
            registration_number=uid,
            legal_form=o.get("rechtsform") or None,
            address=address or None,
            identifiers={"UID": uid} if uid else {},
            sources=[self.provenance(rid, LW_ORG_UI.format(id=self.native_id(rid)[2:]))],
            extra={
                k: v
                for k, v in {
                    "lobbying_influence": o.get("lobbyeinfluss"),
                    "interest_group": o.get("interessengruppe"),
                    "accounts_unknown": True,
                }.items()
                if v
            },
        )

    def _parl(self, p: dict[str, Any]) -> Entity:
        pid = p.get("parlamentarier_id") or p.get("id")
        rid = self.record_id(f"p:{pid}")
        council = LW_COUNCIL.get(p.get("rat") or p.get("ratstyp") or "", p.get("titel") or "")
        position = ": ".join(
            x
            for x in (council or p.get("titel"), p.get("kanton") or p.get("kanton_abkuerzung"))
            if x
        )
        name = p.get("name") or f"{p.get('vorname', '')} {p.get('nachname', '')}".strip()
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON,
            name=name,
            birth_date=p.get("geburtstag") or None,
            nationalities=["CH"],
            identifiers={"Wikidata": p["wikidata_qid"]} if p.get("wikidata_qid") else {},
            sources=[self.provenance(rid, LW_PARL_UI.format(id=pid))],
            extra={
                k: v
                for k, v in {
                    "pep_position": f"Member of the Swiss Federal Assembly ({position})"
                    if position
                    else "Member of the Swiss Federal Assembly",
                    "party": p.get("partei_name") or p.get("partei"),
                    "in_office_since": p.get("im_rat_seit"),
                    "in_office_until": p.get("im_rat_bis"),
                    "committees": p.get("kommissionen_namen") or p.get("kommissionen"),
                }.items()
                if v
            },
        )

    # -------------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        rows = self._get(f"table/organisation/flat/list/{name[:60].replace('/', ' ')}") or []
        out = [self._org(o) for o in rows if isinstance(o, dict)]
        return [e for e in out if name_similarity(name, e.name, "company")[0] >= 85][:5]

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        words = name.split()
        if len(words) < 2:
            return []
        rows = self._get(f"table/parlamentarier/flat/list/{words[-1].replace('/', ' ')}") or []
        out = [self._parl(p) for p in rows if isinstance(p, dict)]
        return [e for e in out if name_similarity(name, e.name, "person")[0] >= 88][:3]

    def get_company_details(self, company_id: str) -> Entity | None:
        data = self._get(f"table/organisation/aggregated/id/{self.native_id(company_id)[2:]}")
        return self._org(data) if isinstance(data, dict) and data.get("id") else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        """Parliamentarians who declared an interest in the organisation."""
        native = self.native_id(company_id)
        if not native.startswith("o:"):
            return []
        data = self._get(f"table/organisation/aggregated/id/{native[2:]}")
        if not isinstance(data, dict):
            return []
        out = []
        for row in data.get("parlamentarier") or []:
            if not isinstance(row, dict) or not row.get("parlamentarier_id"):
                continue
            name = row.get("parlamentarier_name") or ""
            if not name and row.get("anzeige_name"):
                bits = [b.strip() for b in str(row["anzeige_name"]).split(",")]
                name = f"{bits[2]} {bits[1]}" if len(bits) > 2 else ""
            if not name:
                continue
            person = self._parl({**row, "name": name, "id": row["parlamentarier_id"]})
            out.append(self._link(person, company_id, row))
        return out

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        """Declared interests of a parliamentarian (boards, advisory roles, memberships)."""
        native = self.native_id(person_id)
        if not native.startswith("p:"):
            return []
        data = self._get(f"table/parlamentarier/aggregated/id/{native[2:]}")
        if not isinstance(data, dict):
            return []
        out = []
        for row in data.get("interessenbindungen") or []:
            if not isinstance(row, dict) or not row.get("organisation_id"):
                continue
            org = self._org({**row, "id": row["organisation_id"]})
            out.append(self._link(org, person_id, row, person_is_source=True))
        return out[:40]

    def _link(
        self, other: Entity, me: str, row: dict[str, Any], person_is_source: bool = False
    ) -> LinkedEntity:
        src, tgt = (me, other.id) if person_is_source else (other.id, me)
        until = row.get("bis") or None
        return LinkedEntity(
            relationship=Relationship(
                id=f"{self.name}:ib:{row.get('id') or src + tgt}",
                type=RelationType.SHAREHOLDER
                if row.get("art") == "gesellschafter"
                else RelationType.OFFICER,
                source_id=src,
                target_id=tgt,
                role=_lw_role(row),
                start_date=row.get("von") or None,
                end_date=until,
                sources=[self.provenance(me, row.get("quelle_url") or self.homepage)],
            ),
            entity=other,
        )

    def get_documents(self, entity: Entity) -> list[Document]:
        rid = next((r for r in entity.record_ids if r.startswith(f"{self.name}:")), None)
        if rid is None:
            return []
        native = self.native_id(rid)
        if entity.type == EntityType.COMPANY and native.startswith("o:"):
            data = self._get(f"table/organisation/aggregated/id/{native[2:]}") or {}
            if not isinstance(data, dict):
                return []
            parl = len(data.get("parlamentarier") or [])
            badges = len(data.get("zutrittsberechtigte") or [])
            parts = [
                f"{parl} federal parliamentarian(s) with a declared interest" if parl else "",
                f"{badges} lobbyist(s) with a Federal Palace access badge" if badges else "",
                f"lobbying influence: {data['lobbyeinfluss']}" if data.get("lobbyeinfluss") else "",
                f"interest group: {data['interessengruppe']}"
                if data.get("interessengruppe")
                else "",
            ]
            if not any(parts):
                return []
            return [
                Document(
                    title=f"Lobbywatch: links of {entity.name} with the Swiss Parliament",
                    kind="register",
                    url=LW_ORG_UI.format(id=native[2:]),
                    summary=" · ".join(p for p in parts if p),
                    source=self.label,
                    flags=["lobbying"] if parl or badges else [],
                )
            ]
        if entity.type == EntityType.PERSON and native.startswith("p:"):
            parts = [
                entity.extra.get("pep_position", ""),
                f"party: {entity.extra['party']}" if entity.extra.get("party") else "",
                f"in office since {entity.extra['in_office_since']}"
                if entity.extra.get("in_office_since")
                else "",
                f"committees: {entity.extra['committees']}"
                if entity.extra.get("committees")
                else "",
            ]
            return [
                Document(
                    title=f"Lobbywatch: parliamentary mandate and declared interests of {entity.name}",
                    kind="register",
                    url=LW_PARL_UI.format(id=native[2:]),
                    summary=" · ".join(p for p in parts if p),
                    source=self.label,
                )
            ]
        return []


# ------------------------------------------------------------ AfricanLII case law
AFRICANLII = "https://africanlii.org"
# National legal information institutes of the AfricanLII network with an open search API
LIIS = {
    "UG": "https://ulii.org",
    "ZM": "https://zambialii.org",
    "GH": "https://ghalii.org",
    "NG": "https://nigerialii.org",
    "TZ": "https://tanzlii.org",
    "NA": "https://namiblii.org",
    "MW": "https://malawilii.org",
    "ZW": "https://zimlii.org",
}
AKN_COUNTRY = {
    "ke": "Kenya", "ug": "Uganda", "zm": "Zambia", "gh": "Ghana", "ng": "Nigeria",
    "tz": "Tanzania", "na": "Namibia", "mw": "Malawi", "zw": "Zimbabwe", "za": "South Africa",
    "ls": "Lesotho", "sz": "Eswatini", "sc": "Seychelles", "sl": "Sierra Leone", "aa": "African Union",
}  # fmt: skip
_LII_HIT = re.compile(
    r'<a class="h5 text-primary"\s+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.S
)


class AfricanLiiConnector(BaseConnector):
    """Court judgments from the AfricanLII network (Laws.Africa): the regional portal plus the
    national institute of the company's country. Companies and public figures only; a judgment
    counts only when the entity is a party (named in the case name)."""

    name = "africanlii"
    label = "AfricanLII: court judgments (Uganda, Zambia, Ghana, Nigeria, Tanzania, Namibia, Malawi, Zimbabwe, Kenya…)"
    kind = "documents"
    homepage = AFRICANLII
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 1
    timeout_seconds = 20.0

    def _search(self, base: str, query: str) -> list[tuple[str, str]]:
        data = self.http_get_json(
            f"{base}/search/api/documents/", params={"search": f'"{query}"', "page_size": 10}
        )
        html = (data or {}).get("results_html") or "" if isinstance(data, dict) else ""
        return [
            (m.group("href"), " ".join(unescape(re.sub(r"<[^>]+>", "", m.group("title"))).split()))
            for m in _LII_HIT.finditer(html)
        ]

    def get_documents(self, entity: Entity) -> list[Document]:
        if not may_query(entity):
            return []
        from app.connectors.free_sources import core_name

        query = core_name(entity.name) if entity.type == EntityType.COMPANY else entity.name
        if len(query) < 3:
            return []
        bases = [AFRICANLII]
        if (entity.jurisdiction or "").upper() in LIIS:
            bases.insert(0, LIIS[entity.jurisdiction.upper()])
        docs: list[Document] = []
        seen: set[str] = set()
        for base in bases:
            try:
                hits = self._search(base, query)
            except ConnectorError as exc:
                log.info("AfricanLII search failed on %s: %s", base, exc)
                continue
            for href, title in hits:
                m = re.search(r"/akn/(?P<cc>[a-z]{2})/judgment/(?P<court>[a-z0-9-]+)/", href)
                if not m:
                    continue  # legislation, gazettes: not about the entity
                key = href.split("@")[0]
                if key in seen:
                    continue
                seen.add(key)
                when = re.search(r"@(\d{4}-\d{2}-\d{2})", href)
                country = AKN_COUNTRY.get(m.group("cc"), m.group("cc").upper())
                doc = Document(
                    title=title,
                    kind="court",
                    date=_day(when.group(1)) if when else None,
                    url=(base if href.startswith("/") else "") + href,
                    summary=f"{country}: court {m.group('court').upper()}",
                    source=self.label,
                    flags=["court"],
                )
                if not named_in(entity, title):
                    set_aside(doc, "not a party to the case (named in the judgment text only)")
                docs.append(doc)
        return docs[:12]
