"""Keyless national business registers of Norway, Finland, Estonia, Czechia and Belgium.

- Brønnøysund (NO): data.brreg.no Enhetsregisteret JSON API, companies + roles.
- PRH / YTJ (FI): avoindata.prh.fi open data API v3, companies only.
- e-Äriregister (EE): the public autocomplete JSON service, companies only.
- ARES (CZ): the Ministry of Finance REST API, companies + the commercial
  register extract (statutory bodies, supervisory board, prokura, shareholders).
- KBO / BCE / CBE (BE): the public search HTML pages, companies + functions.

None of them publishes filings as structured data, so companies carry
``extra["accounts_unknown"] = True``. Personal data is kept to what the analysis
needs: name, role, date of birth (NO/CZ) and nationality (CZ). Addresses of
natural persons are never stored.
"""

from __future__ import annotations

import html as htmllib
import re
from datetime import date, datetime
from typing import Any, ClassVar

from unidecode import unidecode

from app.connectors.base import BaseConnector
from app.connectors.util import parse_date, reorder_surname_first
from app.models import (
    CompanyStatus,
    Document,
    Entity,
    EntityType,
    LinkedEntity,
    Relationship,
    RelationType,
)

MAX_LINKS = 80


# ----------------------------------------------------------------- helpers
def _slug(value: str) -> str:
    return re.sub(r"\s+", " ", unidecode(value or "").strip().lower())


def _full_name(first: str | None, last: str | None) -> str:
    """Like util.person_name() but also fixes hyphenated all-caps names ('KLAUS-DIETER')."""

    def fix(part: str | None) -> str:
        return " ".join(
            "-".join(p.capitalize() for p in w.split("-")) if w.isupper() else w
            for w in (part or "").split()
        )

    return " ".join(x for x in (fix(first), fix(last)) if x)


def _translate(role: str | None, table: list[tuple[tuple[str, ...], str]]) -> str | None:
    """Register wording -> 'English (original)'. First matching term wins."""
    if not role or not role.strip():
        return None
    role = re.sub(r"\s+", " ", role).strip()
    low = role.lower()
    for terms, english in table:
        if any(t in low for t in terms):
            return english if english.lower() == low else f"{english} ({role})"
    return role


def _mod11(digits: str, weights: list[int]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11


def valid_orgnr(value: str) -> bool:
    """Norwegian organisation number (9 digits, mod 11)."""
    if not re.fullmatch(r"\d{9}", value or ""):
        return False
    r = _mod11(value[:8], [3, 2, 7, 6, 5, 4, 3, 2])
    check = 0 if r == 0 else 11 - r
    return check != 10 and check == int(value[8])


def valid_business_id(value: str) -> bool:
    """Finnish Y-tunnus '1234567-8' (mod 11)."""
    if not re.fullmatch(r"\d{7}-\d", value or ""):
        return False
    r = _mod11(value[:7], [7, 9, 10, 5, 8, 4, 2])
    if r == 1:
        return False
    return (0 if r == 0 else 11 - r) == int(value[8])


def valid_ee_code(value: str) -> bool:
    """Estonian registry code (8 digits, two-pass mod 11)."""
    if not re.fullmatch(r"\d{8}", value or ""):
        return False
    r = _mod11(value[:7], [1, 2, 3, 4, 5, 6, 7])
    if r == 10:
        r = _mod11(value[:7], [3, 4, 5, 6, 7, 8, 9]) % 10
    return r == int(value[7])


def valid_ico(value: str) -> bool:
    """Czech IČO (8 digits, mod 11)."""
    if not re.fullmatch(r"\d{8}", value or ""):
        return False
    s = sum(int(d) * w for d, w in zip(value[:7], range(8, 1, -1), strict=True))
    return (11 - s % 11) % 10 == int(value[7])


def normalise_be(value: str) -> str | None:
    """'BE 0403.091.220', '403091220' -> '0403091220' when the mod-97 check holds."""
    digits = re.sub(r"\D", "", re.sub(r"^\s*BE", "", (value or "").upper()))
    if len(digits) == 9:
        digits = "0" + digits
    if not re.fullmatch(r"[01]\d{9}", digits):
        return None
    return digits if 97 - int(digits[:8]) % 97 == int(digits[8:]) else None


def _be_dotted(num: str) -> str:
    return f"{num[:4]}.{num[4:7]}.{num[7:]}"


def _website(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else f"https://{url}"


# ---------------------------------------------------------- shared base
class _EuropeanRegistry(BaseConnector):
    """Shared plumbing: record ids, person ids, register document."""

    kind = "registry"
    key_setting = None
    document_types: ClassVar[set[str]] = {"company"}
    #: ISO-2 country of the register
    country: ClassVar[str] = ""
    #: shown in the register-entry document title
    register_name: ClassVar[str] = ""

    def ui_url(self, native: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def valid_number(self, native: str) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def _own_number(self, entity: Entity) -> str | None:
        for rid in entity.record_ids:
            if rid.startswith(f"{self.name}:"):
                native = self.native_id(rid)
                if self.valid_number(native):
                    return native
        if (
            (entity.jurisdiction or "").upper() == self.country
            and entity.registration_number
            and self.valid_number(entity.registration_number)
        ):
            return entity.registration_number
        return None

    def _person(
        self,
        name: str,
        birth: str | None,
        url: str,
        nationalities: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Entity:
        pid = self.record_id(f"person:{_slug(name)}:{birth or ''}")
        return Entity(
            id=pid,
            record_ids=[pid],
            type=EntityType.PERSON,
            name=name,
            birth_date=birth,
            nationalities=nationalities or [],
            sources=[self.provenance(pid, url)],
            extra=extra or {},
        )

    def _link(
        self,
        other: Entity,
        company_rid: str,
        role: str | None,
        url: str,
        rel_type: RelationType = RelationType.OFFICER,
        start: date | None = None,
        end: date | None = None,
        share_pct: float | None = None,
    ) -> LinkedEntity:
        kind = "shareholder" if rel_type == RelationType.SHAREHOLDER else "officer"
        return LinkedEntity(
            relationship=Relationship(
                id=f"{self.name}:{kind}:{other.id}>{company_rid}:{role or ''}",
                type=rel_type,
                source_id=other.id,
                target_id=company_rid,
                role=role,
                share_pct=share_pct,
                start_date=start,
                end_date=end,
                sources=[self.provenance(company_rid, url)],
            ),
            entity=other,
        )

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY:
            return []
        native = self._own_number(entity)
        if not native:
            return []
        docs = [
            Document(
                title=f"Register entry ({self.register_name})",
                kind="register",
                url=self.ui_url(native),
                summary=f"{entity.name} — {native}",
                source=self.label,
            )
        ]
        insolvency = entity.extra.get("insolvency")
        if insolvency:
            docs.append(
                Document(
                    title=f"Insolvency recorded in the register: {insolvency}",
                    kind="register",
                    date=parse_date(entity.extra.get("insolvency_date")),
                    url=self.ui_url(native),
                    summary=str(insolvency),
                    source=self.label,
                    flags=["insolvency"],
                )
            )
        return docs


# ================================================================ Norway
BRREG_API = "https://data.brreg.no/enhetsregisteret/api"
BRREG_UI = "https://virksomhet.brreg.no/nb/oppslag/enheter/{orgnr}"

NO_ROLES: list[tuple[tuple[str, ...], str]] = [
    (("daglig leder",), "Chief executive"),
    (("styrets leder",), "Chair of the board"),
    (("nestleder",), "Deputy chair"),
    (("varamedlem",), "Deputy board member"),
    (("styremedlem",), "Board member"),
    (("observatør",), "Board observer"),
    (("regnskapsfører",), "Accountant"),
    (("revisor",), "Auditor"),
    (("kontaktperson",), "Contact person"),
    (("innehaver",), "Owner"),
    (("komplementar",), "General partner"),
    (("deltaker",), "Partner"),
    (("forretningsfører",), "Business manager"),
    (("bestyrende reder",), "Managing owner"),
    (("norsk representant",), "Norwegian representative"),
    (("prokura",), "Authorised signatory (prokura)"),
    (("signatur",), "Signatory"),
]


def translate_no_role(role: str | None) -> str | None:
    return _translate(role, NO_ROLES)


def _brreg_address(a: dict[str, Any] | None) -> str | None:
    if not a:
        return None
    parts = [
        *(a.get("adresse") or []),
        " ".join(p for p in (a.get("postnummer"), a.get("poststed")) if p),
        a.get("land"),
    ]
    return ", ".join(p for p in parts if p) or None


class BrregConnector(_EuropeanRegistry):
    name = "brreg"
    label = "Brønnøysund Register Centre — Norwegian business register"
    jurisdictions = {"NO"}
    country = "NO"
    register_name = "Brønnøysund Enhetsregisteret"
    homepage = "https://www.brreg.no"

    def ui_url(self, native: str) -> str:
        return BRREG_UI.format(orgnr=native)

    def valid_number(self, native: str) -> bool:
        return valid_orgnr(native)

    def _company(self, r: dict[str, Any]) -> Entity:
        orgnr = str(r.get("organisasjonsnummer") or "")
        rid = self.record_id(orgnr)
        name = r.get("navn") or orgnr
        bankrupt = bool(r.get("konkurs"))
        winding_up = bool(
            r.get("underAvvikling") or r.get("underTvangsavviklingEllerTvangsopplosning")
        )
        deleted = parse_date(r.get("slettedato"))
        extra: dict[str, Any] = {"accounts_unknown": True}
        if r.get("hjemmeside"):
            extra["website"] = _website(r["hjemmeside"])
        if bankrupt:
            extra["insolvency"] = "Bankruptcy (konkurs)"
            extra["insolvency_date"] = r.get("konkursdato")
        elif winding_up:
            extra["winding_up"] = True
        if r.get("antallAnsatte") is not None:
            extra["employees"] = r.get("antallAnsatte")
        aliases: list[str] = []
        for h in r.get("historiskeNavn") or []:
            old = (h or {}).get("navn")
            if old and old != name and old not in aliases:
                aliases.append(old)
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=name,
            aliases=aliases[:8],
            jurisdiction="NO",
            registration_number=orgnr,
            legal_form=(r.get("organisasjonsform") or {}).get("beskrivelse"),
            status=CompanyStatus.DISSOLVED
            if deleted or bankrupt or winding_up
            else CompanyStatus.ACTIVE,
            incorporation_date=parse_date(r.get("stiftelsesdato"))
            or parse_date(r.get("registreringsdatoEnhetsregisteret")),
            dissolution_date=deleted,
            address=_brreg_address(r.get("forretningsadresse"))
            or _brreg_address(r.get("postadresse")),
            activity=(r.get("naeringskode1") or {}).get("beskrivelse"),
            identifiers={"Orgnr": orgnr},
            sources=[self.provenance(rid, self.ui_url(orgnr))],
            extra=extra,
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = self.http_get_json(f"{BRREG_API}/enheter", params={"navn": name, "size": 10}) or {}
        rows = (data.get("_embedded") or {}).get("enheter") or []
        return [self._company(r) for r in rows if r.get("organisasjonsnummer")]

    def get_company_details(self, company_id: str) -> Entity | None:
        orgnr = self.native_id(company_id)
        if not valid_orgnr(orgnr):
            return None
        data = self.http_get_json(f"{BRREG_API}/enheter/{orgnr}")
        return self._company(data) if isinstance(data, dict) and data else None

    def get_by_identifier(self, ident: Any) -> Entity | None:
        value = re.sub(r"\D", "", ident.value or "")
        return self.get_company_details(self.record_id(value)) if valid_orgnr(value) else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        orgnr = self.native_id(company_id)
        if not valid_orgnr(orgnr):
            return []
        me = self.record_id(orgnr)
        url = self.ui_url(orgnr)
        data = self.http_get_json(f"{BRREG_API}/enheter/{orgnr}/roller") or {}
        out: list[LinkedEntity] = []
        seen: set[str] = set()
        for group in data.get("rollegrupper") or []:
            for role in (group or {}).get("roller") or []:
                if not role or role.get("fratraadt"):
                    continue  # resigned: the API gives no departure date
                label = translate_no_role((role.get("type") or {}).get("beskrivelse"))
                other = self._holder(role, url)
                if other is None:
                    continue
                link = self._link(
                    other,
                    me,
                    label,
                    url,
                    rel_type=RelationType.SHAREHOLDER
                    if (label or "").startswith(("Owner", "Partner", "General partner"))
                    else RelationType.OFFICER,
                    share_pct=100.0 if (label or "").startswith("Owner") else None,
                )
                if link.relationship.id in seen:
                    continue
                seen.add(link.relationship.id)
                out.append(link)
        return out[:MAX_LINKS]

    def _holder(self, role: dict[str, Any], url: str) -> Entity | None:
        person = role.get("person")
        if isinstance(person, dict):
            n = person.get("navn") or {}
            name = _full_name(
                " ".join(p for p in (n.get("fornavn"), n.get("mellomnavn")) if p),
                n.get("etternavn"),
            )
            if not name:
                return None
            extra = {"deceased": True} if person.get("erDoed") else {}
            return self._person(name, person.get("fodselsdato"), url, extra=extra)
        unit = role.get("enhet")
        if isinstance(unit, dict) and unit.get("organisasjonsnummer"):
            orgnr = str(unit["organisasjonsnummer"])
            names = unit.get("navn")
            name = " ".join(names) if isinstance(names, list) else (names or orgnr)
            oid = self.record_id(orgnr)
            return Entity(
                id=oid,
                record_ids=[oid],
                type=EntityType.COMPANY,
                name=name,
                jurisdiction="NO",
                registration_number=orgnr,
                legal_form=(unit.get("organisasjonsform") or {}).get("beskrivelse"),
                identifiers={"Orgnr": orgnr},
                sources=[self.provenance(oid, self.ui_url(orgnr))],
                extra={"accounts_unknown": True},
            )
        return None


# ================================================================ Finland
PRH_API = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
PRH_UI = "https://tietopalvelu.ytj.fi/yritys/{bid}"
# companySituations codes (restructuring, liquidation, bankruptcy)
FI_SITUATIONS = {
    "SANE": "Restructuring proceedings",
    "SELTILA": "Liquidation",
    "KONK": "Bankruptcy",
}
FI_ADDRESS_VISITING = 1


def _en(descriptions: list[dict[str, Any]] | None) -> str | None:
    descs = [d for d in descriptions or [] if isinstance(d, dict)]
    for code in ("3", "1", "2"):  # English, Finnish, Swedish
        for d in descs:
            if str(d.get("languageCode")) == code and d.get("description"):
                return d["description"]
    return None


def _prh_address(addresses: list[dict[str, Any]] | None) -> str | None:
    addrs = [a for a in addresses or [] if isinstance(a, dict) and not a.get("endDate")]
    if not addrs:
        return None
    a = next((x for x in addrs if str(x.get("type")) == str(FI_ADDRESS_VISITING)), addrs[0])
    street = " ".join(
        str(p)
        for p in (a.get("street"), a.get("buildingNumber"), a.get("entrance"))
        if p not in (None, "")
    )
    if a.get("apartmentNumber"):
        street += f" {a.get('apartmentIdSuffix') or ''}{a['apartmentNumber']}".rstrip()
    if not street and a.get("postOfficeBox"):
        street = f"PL {a['postOfficeBox']}"
    offices = a.get("postOffices") or []
    city = next(
        (o.get("city") for o in offices if str(o.get("languageCode")) == "1" and o.get("city")),
        next((o.get("city") for o in offices if o.get("city")), None),
    )
    parts = [
        a.get("co") and f"c/o {a['co']}",
        street,
        " ".join(p for p in (a.get("postCode"), city) if p),
    ]
    return ", ".join(p for p in parts if p) or None


class PrhConnector(_EuropeanRegistry):
    name = "prh"
    label = "PRH / YTJ — Finnish Trade Register (open data)"
    jurisdictions = {"FI"}
    country = "FI"
    register_name = "Finnish Trade Register (PRH/YTJ)"
    homepage = "https://avoindata.prh.fi"

    def ui_url(self, native: str) -> str:
        return PRH_UI.format(bid=native)

    def valid_number(self, native: str) -> bool:
        return valid_business_id(native)

    def _company(self, c: dict[str, Any]) -> Entity:
        bid_obj = c.get("businessId") or {}
        bid = str(bid_obj.get("value") or "")
        rid = self.record_id(bid)
        names = [n for n in c.get("names") or [] if isinstance(n, dict) and n.get("name")]
        current = [n for n in names if str(n.get("type")) == "1" and not n.get("endDate")]
        name = current[0]["name"] if current else (names[0]["name"] if names else bid)
        aliases: list[str] = []
        for n in names:
            if n["name"] != name and n["name"] not in aliases:
                aliases.append(n["name"])
        forms = [f for f in c.get("companyForms") or [] if isinstance(f, dict)]
        form = next((f for f in forms if not f.get("endDate")), forms[0] if forms else None)

        extra: dict[str, Any] = {"accounts_unknown": True}
        website = (c.get("website") or {}).get("url")
        if website:
            extra["website"] = _website(website)
        dissolved = bool(c.get("endDate"))
        for s in c.get("companySituations") or []:
            if not isinstance(s, dict) or s.get("endDate"):
                continue
            code = str(s.get("type") or "").upper()
            text = FI_SITUATIONS.get(code) or _en(s.get("descriptions")) or code
            low = text.lower()
            if code == "KONK" or "bankrupt" in low or "konkurs" in low:
                extra["insolvency"] = text
                extra["insolvency_date"] = s.get("registrationDate")
                dissolved = True
            elif code in ("SELTILA", "SANE") or "liquidat" in low or "restructur" in low:
                extra.setdefault("situations", []).append(text)
                dissolved = dissolved or code == "SELTILA" or "liquidat" in low
        trade = str(c.get("tradeRegisterStatus") or "")
        if trade:
            extra["trade_register_status"] = trade
        for entry in c.get("registeredEntries") or []:
            if not isinstance(entry, dict) or str(entry.get("register")) != "1":
                continue
            desc = (_en(entry.get("descriptions")) or "").lower()
            if "unregistered" in desc or "deregistered" in desc or "removed" in desc:
                dissolved = True
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=name,
            aliases=aliases[:10],
            jurisdiction="FI",
            registration_number=bid,
            legal_form=_en(form.get("descriptions")) if form else None,
            status=CompanyStatus.DISSOLVED if dissolved else CompanyStatus.ACTIVE,
            incorporation_date=parse_date(bid_obj.get("registrationDate")),
            dissolution_date=parse_date(c.get("endDate")),
            address=_prh_address(c.get("addresses")),
            activity=_en((c.get("mainBusinessLine") or {}).get("descriptions")),
            identifiers={"Business ID": bid}
            | ({"EUID": c["euId"]["value"]} if (c.get("euId") or {}).get("value") else {}),
            sources=[self.provenance(rid, self.ui_url(bid))],
            extra=extra,
        )

    def _query(self, **params: Any) -> list[dict[str, Any]]:
        data = self.http_get_json(PRH_API, params=params) or {}
        return [c for c in data.get("companies") or [] if (c.get("businessId") or {}).get("value")]

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return [self._company(c) for c in self._query(name=name)[:10]]

    def get_company_details(self, company_id: str) -> Entity | None:
        bid = self.native_id(company_id)
        if not valid_business_id(bid):
            return None
        found = [c for c in self._query(businessId=bid) if c["businessId"]["value"] == bid]
        return self._company(found[0]) if found else None

    def get_by_identifier(self, ident: Any) -> Entity | None:
        value = (ident.value or "").strip()
        if not re.fullmatch(r"\d{7}-\d", value):
            digits = re.sub(r"\D", "", value)
            if ident.kind not in ("registration", "uk_company") or len(digits) != 8:
                return None
            value = f"{digits[:7]}-{digits[7]}"
        return self.get_company_details(self.record_id(value)) if valid_business_id(value) else None


# ================================================================ Estonia
EE_API = "https://ariregister.rik.ee/est/api/autocomplete"
EE_UI = "https://ariregister.rik.ee/eng/company/{code}"
EE_STATUS = {
    "R": ("Registered", CompanyStatus.ACTIVE),
    "L": ("In liquidation", CompanyStatus.DISSOLVED),
    "N": ("Bankrupt", CompanyStatus.DISSOLVED),
    "K": ("Deleted", CompanyStatus.DISSOLVED),
}
# Legal forms inferred from the name suffix (the autocomplete only gives a numeric code).
EE_FORMS = [
    ("MTÜ", "Non-profit association (MTÜ)"),
    ("OÜ", "Private limited company (OÜ)"),
    ("AS", "Public limited company (AS)"),
    ("SA", "Foundation (SA)"),
    ("TÜ", "General partnership (TÜ)"),
    ("UÜ", "Limited partnership (UÜ)"),
    ("FIE", "Sole proprietor (FIE)"),
]


def _ee_form(name: str) -> str | None:
    tokens = name.replace(",", " ").split()
    for suffix, label in EE_FORMS:
        if suffix in (tokens[-1:] + tokens[:1]):
            return label
    return None


class AriregisterConnector(_EuropeanRegistry):
    name = "ariregister"
    label = "e-Äriregister — Estonian business register"
    jurisdictions = {"EE"}
    country = "EE"
    register_name = "Estonian e-Business Register"
    homepage = "https://ariregister.rik.ee"

    def ui_url(self, native: str) -> str:
        return EE_UI.format(code=native)

    def valid_number(self, native: str) -> bool:
        return valid_ee_code(native)

    def _company(self, r: dict[str, Any]) -> Entity:
        code = str(r.get("reg_code") or "")
        rid = self.record_id(code)
        name = r.get("name") or code
        status_label, status = EE_STATUS.get(
            str(r.get("status") or "").upper(), (None, CompanyStatus.UNKNOWN)
        )
        extra: dict[str, Any] = {"accounts_unknown": True}
        if status_label:
            extra["register_status"] = status_label
        if r.get("legal_form") not in (None, ""):
            extra["legal_form_code"] = str(r["legal_form"])
        if str(r.get("status") or "").upper() == "N":
            extra["insolvency"] = "Bankrupt (pankrotis)"
        address = ", ".join(p for p in (r.get("legal_address"), r.get("zip_code")) if p) or None
        url = r.get("url") or self.ui_url(code)
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=name,
            aliases=[h for h in r.get("historical_names") or [] if h and h != name][:8],
            jurisdiction="EE",
            registration_number=code,
            legal_form=_ee_form(name),
            status=status,
            address=address,
            identifiers={"Registry code": code},
            sources=[self.provenance(rid, url)],
            extra=extra | {"register_url": url},
        )

    def _autocomplete(self, q: str) -> list[dict[str, Any]]:
        data = self.http_get_json(EE_API, params={"q": q}) or {}
        rows = data.get("data") if isinstance(data, dict) else None
        return [r for r in rows or [] if isinstance(r, dict) and r.get("reg_code")]

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return [self._company(r) for r in self._autocomplete(name)[:10]]

    def get_company_details(self, company_id: str) -> Entity | None:
        code = self.native_id(company_id)
        if not valid_ee_code(code):
            return None
        match = [r for r in self._autocomplete(code) if str(r.get("reg_code")) == code]
        return self._company(match[0]) if match else None

    def get_by_identifier(self, ident: Any) -> Entity | None:
        value = re.sub(r"\D", "", ident.value or "")
        return self.get_company_details(self.record_id(value)) if valid_ee_code(value) else None

    def get_documents(self, entity: Entity) -> list[Document]:
        docs = super().get_documents(entity)
        url = entity.extra.get("register_url")
        if docs and url:
            docs[0] = docs[0].model_copy(update={"url": url})
        return docs


# ================================================================ Czechia
ARES_API = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest"
ARES_UI = "https://ares.gov.cz/ekonomicke-subjekty?ico={ico}"
CZ_FORMS = {
    "101": "Sole trader",
    "111": "General partnership (v.o.s.)",
    "112": "Limited liability company (s.r.o.)",
    "113": "Limited partnership (k.s.)",
    "117": "Foundation (nadace)",
    "118": "Endowment fund (nadační fond)",
    "121": "Joint-stock company (a.s.)",
    "141": "Public benefit company (o.p.s.)",
    "205": "Cooperative (družstvo)",
    "706": "Association (spolek)",
    "931": "Branch of a foreign company",
    "932": "Branch of a European company",
}
CZ_ROLES: list[tuple[tuple[str, ...], str]] = [
    (("místopředseda dozorčí rady",), "Vice-chair of the supervisory board"),
    (("předseda dozorčí rady", "předsedkyně dozorčí rady"), "Chair of the supervisory board"),
    (("člen dozorčí rady", "členka dozorčí rady"), "Supervisory board member"),
    (("místopředseda představenstva",), "Vice-chair of the board"),
    (("předseda představenstva", "předsedkyně představenstva"), "Chair of the board"),
    (("člen představenstva", "členka představenstva"), "Board member"),
    (("předseda správní rady",), "Chair of the administrative board"),
    (("člen správní rady",), "Administrative board member"),
    (("statutární ředitel",), "Statutory director"),
    (("místopředseda",), "Vice-chair"),
    (("jednatel",), "Managing director"),
    (("prokurist", "prokura"), "Authorised signatory (prokura)"),
    (("likvidátor",), "Liquidator"),
    (("insolvenční správce",), "Insolvency administrator"),
    (("společník",), "Partner"),
    (("akcionář",), "Shareholder"),
    (("předseda", "předsedkyně"), "Chair"),
    (("člen statutárního orgánu",), "Member of the statutory body"),
    (("člen",), "Member"),
]
CZ_ORGANS = {
    "DOZORCI_RADA": "Supervisory board member",
    "PROKURA": "Authorised signatory (prokura)",
    "SPRAVNI_RADA": "Administrative board member",
    "LIKVIDATOR": "Liquidator",
}


def translate_cz_role(role: str | None) -> str | None:
    return _translate(role, CZ_ROLES)


def _cz_number(text: Any) -> float | None:
    if text is None:
        return None
    s = str(text).strip().replace(" ", "").replace("\xa0", "")
    if m := re.fullmatch(r"(\d+)/(\d+)", s):
        num, den = int(m.group(1)), int(m.group(2))
        return round(100.0 * num / den, 4) if den else None
    s = s.replace("%", "").replace(";", ".").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _cz_share(podil: Any) -> float | None:
    """Percentage of a spolecnik's podil ('PROCENTA' amount, '50 %' text or fraction)."""
    items = podil if isinstance(podil, list) else [podil] if isinstance(podil, dict) else []
    items = [p for p in items if isinstance(p, dict)]
    current = [p for p in items if not p.get("datumVymazu")] or items
    for p in current:
        size = p.get("velikostPodilu")
        if isinstance(size, dict):
            kind = str(size.get("typObnos") or "").upper()
            value = size.get("hodnota")
            if kind == "PROCENTA" or "%" in str(value or ""):
                return _cz_number(value)
            if kind in ("ZLOMEK", "TEXT") and "/" in str(value or ""):
                return _cz_number(value)
        elif isinstance(size, str) and ("%" in size or "/" in size):
            return _cz_number(size.split("%")[0])
    return None


class AresConnector(_EuropeanRegistry):
    name = "ares"
    label = "ARES — Czech business register (Ministry of Finance)"
    jurisdictions = {"CZ"}
    country = "CZ"
    register_name = "Czech ARES / commercial register"
    homepage = "https://ares.gov.cz"

    def ui_url(self, native: str) -> str:
        return ARES_UI.format(ico=native)

    def valid_number(self, native: str) -> bool:
        return valid_ico(native)

    def _company(self, r: dict[str, Any]) -> Entity:
        ico = str(r.get("ico") or r.get("icoId") or "").zfill(8)
        rid = self.record_id(ico)
        seat = r.get("sidlo") or {}
        form = str(r.get("pravniForma") or "")
        ended = parse_date(r.get("datumZaniku"))
        regs = r.get("seznamRegistraci") or {}
        extra: dict[str, Any] = {"accounts_unknown": True}
        if form:
            extra["legal_form_code"] = form
        if str(regs.get("stavZdrojeIr") or "").upper() == "AKTIVNI":
            extra["insolvency"] = "Listed in the insolvency register (ISIR)"
        identifiers = {"IČO": ico}
        if r.get("dic"):
            identifiers["DIČ"] = r["dic"]
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=r.get("obchodniJmeno") or ico,
            jurisdiction="CZ",
            registration_number=ico,
            legal_form=CZ_FORMS.get(form) or (f"Legal form code {form}" if form else None),
            status=CompanyStatus.DISSOLVED if ended else CompanyStatus.ACTIVE,
            incorporation_date=parse_date(r.get("datumVzniku")),
            dissolution_date=ended,
            address=seat.get("textovaAdresa")
            or ", ".join(
                v for v in (r.get("adresaDorucovaci") or {}).values() if isinstance(v, str) and v
            )
            or None,
            identifiers=identifiers,
            sources=[self.provenance(rid, self.ui_url(ico))],
            extra=extra,
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = (
            self.http_post_json(
                f"{ARES_API}/ekonomicke-subjekty/vyhledat",
                json_body={"obchodniJmeno": name, "pocet": 10},
            )
            or {}
        )
        return [self._company(r) for r in data.get("ekonomickeSubjekty") or [] if r.get("ico")]

    def get_company_details(self, company_id: str) -> Entity | None:
        ico = self.native_id(company_id)
        if not valid_ico(ico):
            return None
        data = self.http_get_json(f"{ARES_API}/ekonomicke-subjekty/{ico}")
        if not isinstance(data, dict) or not data:
            return None
        company = self._company(data)
        rec = self._vr(ico)
        if rec:
            old = [
                n.get("hodnota")
                for n in rec.get("obchodniJmeno") or []
                if isinstance(n, dict) and n.get("hodnota") and n.get("hodnota") != company.name
            ]
            company.aliases = list(dict.fromkeys(old))[:10]
        return company

    def get_by_identifier(self, ident: Any) -> Entity | None:
        value = re.sub(r"\D", "", ident.value or "")
        if re.fullmatch(r"CZ\d{8}", re.sub(r"\s", "", (ident.value or "").upper())):
            value = value[-8:]
        return self.get_company_details(self.record_id(value)) if valid_ico(value) else None

    # ------------------------------------------------ commercial register (VR)
    def _vr(self, ico: str) -> dict[str, Any] | None:
        data = self.http_get_json(f"{ARES_API}/ekonomicke-subjekty-vr/{ico}") or {}
        records = [z for z in data.get("zaznamy") or [] if isinstance(z, dict)]
        if not records:
            return None
        return next((z for z in records if z.get("primarniZaznam")), records[0])

    def _holder(self, member: dict[str, Any], url: str) -> Entity | None:
        osoba = member.get("osoba") if isinstance(member.get("osoba"), dict) else {}
        fo = member.get("fyzickaOsoba") or osoba.get("fyzickaOsoba")
        po = member.get("pravnickaOsoba") or osoba.get("pravnickaOsoba")
        if isinstance(fo, dict):
            name = _full_name(fo.get("jmeno"), fo.get("prijmeni"))
            if not name:
                return None
            nat = str(fo.get("statniObcanstvi") or "").upper()
            return self._person(
                name,
                fo.get("datumNarozeni"),
                url,
                nationalities=[nat] if re.fullmatch(r"[A-Z]{2}", nat) else [],
            )
        if isinstance(po, dict):
            name = (po.get("obchodniJmeno") or "").strip()
            ico = re.sub(r"\D", "", str(po.get("ico") or ""))
            country = str((po.get("adresa") or {}).get("kodStatu") or "").upper() or None
            if ico and valid_ico(ico.zfill(8)) and country in (None, "CZ"):
                ico = ico.zfill(8)
                oid = self.record_id(ico)
                return Entity(
                    id=oid,
                    record_ids=[oid],
                    type=EntityType.COMPANY,
                    name=name or ico,
                    jurisdiction="CZ",
                    registration_number=ico,
                    identifiers={"IČO": ico},
                    sources=[self.provenance(oid, self.ui_url(ico))],
                    extra={"accounts_unknown": True},
                )
            if not name:
                return None
            oid = self.record_id(f"company:{_slug(name)}:{country or ''}")
            return Entity(
                id=oid,
                record_ids=[oid],
                type=EntityType.COMPANY,
                name=name,
                jurisdiction=country,
                registration_number=ico or None,
                sources=[self.provenance(oid, url)],
                extra={"accounts_unknown": True},
            )
        return None

    @staticmethod
    def _members(organs: list[Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        out = []
        for organ in organs or []:
            if not isinstance(organ, dict):
                continue
            members = organ.get("clenoveOrganu") or organ.get("spolecnik")
            if members is None and (organ.get("fyzickaOsoba") or organ.get("pravnickaOsoba")):
                members = [organ]
            for m in members or []:
                if isinstance(m, dict):
                    out.append((organ, m))
        return out

    def _collect(
        self, pairs: list[tuple[dict[str, Any], dict[str, Any]]], url: str, share: bool
    ) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for organ, m in pairs:
            other = self._holder(m, url)
            if other is None:
                continue
            clenstvi = m.get("clenstvi") or {}
            funkce = clenstvi.get("funkce") or {}
            membership = clenstvi.get("clenstvi") or {}
            raw_role = funkce.get("nazev") or m.get("nazevAngazma")
            if share:
                role = "Shareholder" if organ.get("typOrganu") == "AKCIONAR" else "Partner"
                if raw_role:
                    role = translate_cz_role(raw_role) or role
            else:
                role = (
                    translate_cz_role(raw_role)
                    or CZ_ORGANS.get(str(organ.get("typOrganu") or ""))
                    or translate_cz_role(organ.get("nazevOrganu"))
                    or "Registered officer"
                )
            start = (
                parse_date(funkce.get("vznikFunkce"))
                or parse_date(membership.get("vznikClenstvi"))
                or parse_date(m.get("datumZapisu"))
            )
            erased = m.get("datumVymazu") or organ.get("datumVymazu")
            end = (
                (
                    parse_date(funkce.get("zanikFunkce"))
                    or parse_date(membership.get("zanikClenstvi"))
                    or parse_date(erased)
                )
                if erased
                else None
            )
            pct = (
                _cz_share(m.get("podil") or (m.get("osoba") or {}).get("podil")) if share else None
            )
            key = f"{other.id}|{role}"
            cur = merged.get(key)
            if cur is None:
                merged[key] = {
                    "entity": other,
                    "role": role,
                    "start": start,
                    "end": end,
                    "active": end is None,
                    "pct": pct,
                }
                continue
            # The register rewrites entries on every change (address, function...):
            # one relation per holder and role, earliest start, open if any entry is open.
            if start and (cur["start"] is None or start < cur["start"]):
                cur["start"] = start
            if end is None:
                cur["active"] = True
                cur["end"] = None
                if pct is not None:
                    cur["pct"] = pct
            elif not cur["active"] and (cur["end"] is None or end > cur["end"]):
                cur["end"] = end
                if pct is not None and cur["pct"] is None:
                    cur["pct"] = pct
        return merged

    def _links(self, company_id: str, share: bool) -> list[LinkedEntity]:
        ico = self.native_id(company_id)
        if not valid_ico(ico):
            return []
        rec = self._vr(ico)
        if not rec:
            return []
        me = self.record_id(ico)
        url = self.ui_url(ico)
        if share:
            pairs = self._members(rec.get("akcionari") or [])
            pairs += self._members(rec.get("spolecnici") or [])
        else:
            pairs = self._members(rec.get("statutarniOrgany") or [])
            pairs += self._members(rec.get("ostatniOrgany") or [])
        merged = self._collect(pairs, url, share)
        ordered = sorted(
            merged.values(),
            key=lambda p: (not p["active"], -(p["start"] or date.min).toordinal()),
        )
        return [
            self._link(
                p["entity"],
                me,
                p["role"],
                url,
                rel_type=RelationType.SHAREHOLDER if share else RelationType.OFFICER,
                start=p["start"],
                end=p["end"],
                share_pct=p["pct"],
            )
            for p in ordered[:MAX_LINKS]
        ]

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        return self._links(company_id, share=False)

    def get_shareholders(self, company_id: str) -> list[LinkedEntity]:
        return self._links(company_id, share=True)


# ================================================================ Belgium
KBO_BASE = "https://kbopub.economie.fgov.be/kbopub"
KBO_SEARCH = f"{KBO_BASE}/zoeknaamfonetischform.html"
KBO_DETAIL = f"{KBO_BASE}/toonondernemingps.html"
KBO_UI = KBO_DETAIL + "?ondernemingsnummer={num}&lang=en"
BE_NUMBER = re.compile(r"\b([01]\d{3})\.(\d{3})\.(\d{3})\b")
BE_ROLES: list[tuple[tuple[str, ...], str]] = [
    (
        ("managing director", "gedelegeerd bestuurder", "administrateur délégué"),
        "Managing director",
    ),
    (("chairman", "chair", "voorzitter", "président"), "Chair of the board"),
    (("daily management", "dagelijks bestuur", "gestion journalière"), "Daily management"),
    (
        ("permanent representative", "vaste vertegenwoordiger", "représentant permanent"),
        "Permanent representative",
    ),
    (("auditor", "commissaris", "commissaire", "réviseur"), "Auditor"),
    (("liquidator", "vereffenaar", "liquidateur"), "Liquidator"),
    (("director", "bestuurder", "administrateur"), "Director"),
    (("manager", "zaakvoerder", "gérant"), "Manager"),
    (("partner", "vennoot", "associé"), "Partner"),
]


def _text(fragment: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", fragment or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s).replace("\xa0", " ")).strip()


def _lines(fragment: str) -> list[str]:
    s = re.sub(r'<span class="upd">.*?</span>', "", fragment or "", flags=re.S | re.I)
    return [t for t in (_text(x) for x in re.split(r"<br\s*/?>", s, flags=re.I)) if t]


def _en_date(text: str | None) -> date | None:
    """'Since December 8, 2023' / 'January 26, 1863' -> date."""
    if not text:
        return None
    m = re.search(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", text)
    if not m:
        return None
    try:
        return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date()
    except ValueError:
        return None


def _kbo_field(page: str, label: str) -> str | None:
    m = re.search(rf"<td[^>]*>\s*{label}\s*</td>\s*<td[^>]*>(.*?)</td>", page, flags=re.S | re.I)
    return m.group(1) if m else None


def translate_be_role(role: str | None) -> str | None:
    if not role:
        return None
    role = _text(role)
    low = role.lower()
    for terms, english in BE_ROLES:
        if any(t in low for t in terms):
            return role if english.lower() == low else f"{english} ({role})"
    return role


class KboConnector(_EuropeanRegistry):
    name = "kbo"
    label = "KBO / BCE — Belgian Crossroads Bank for Enterprises"
    jurisdictions = {"BE"}
    country = "BE"
    register_name = "Belgian Crossroads Bank for Enterprises (KBO/BCE)"
    homepage = "https://kbopub.economie.fgov.be"

    def ui_url(self, native: str) -> str:
        return KBO_UI.format(num=native)

    def valid_number(self, native: str) -> bool:
        return normalise_be(native) == native

    def _stub(
        self,
        num: str,
        name: str,
        status_text: str | None = None,
        address: str | None = None,
        start: date | None = None,
    ) -> Entity:
        rid = self.record_id(num)
        low = (status_text or "").lower()
        status = (
            CompanyStatus.ACTIVE
            if "active" in low or "actief" in low or "actif" in low
            else CompanyStatus.DISSOLVED
            if "stopped" in low or "gestopt" in low or "arrêté" in low
            else CompanyStatus.UNKNOWN
        )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=name or _be_dotted(num),
            jurisdiction="BE",
            registration_number=num,
            status=status,
            incorporation_date=start,
            address=address,
            identifiers={"Enterprise number": _be_dotted(num)},
            sources=[self.provenance(rid, self.ui_url(num))],
            extra={"accounts_unknown": True},
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        page = self.http_get_text(
            KBO_SEARCH,
            params={
                "searchWord": name,
                "_oudeBenaming": "on",
                "ondNP": "true",
                "_ondNP": "on",
                "ondRP": "true",
                "_ondRP": "on",
                "rechtsvormFonetic": "ALL",
                "vest": "true",
                "_vest": "on",
                "filterEnkelActieve": "true",
                "_filterEnkelActieve": "on",
                "actionNPRP": "Zoek",
                "lang": "en",
            },
        )
        out: list[Entity] = []
        seen: set[str] = set()
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page or "", flags=re.S | re.I):
            m = re.search(r"toonondernemingps\.html\?ondernemingsnummer=(\d+)", row)
            if not m:
                continue
            num = normalise_be(m.group(1)) or m.group(1).zfill(10)
            if num in seen:
                continue
            seen.add(num)
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)
            benaming = re.search(
                r'<td class="benaming">(.*?)</td>\s*<td[^>]*>(.*?)</td>', row, flags=re.S | re.I
            )
            status_cell = next(
                (c for c in cells if "<br" in c and "ondernemingsnummer" not in c), ""
            )
            since = re.search(r'<span class="upd">(.*?)</span>', row, flags=re.S)
            out.append(
                self._stub(
                    num,
                    _text(benaming.group(1)) if benaming else "",
                    status_text=_text(status_cell),
                    address=", ".join(_lines(benaming.group(2))) or None if benaming else None,
                    start=_en_date(_text(since.group(1))) if since else None,
                )
            )
            if len(out) >= 10:
                break
        return out

    def _page(self, num: str) -> str | None:
        return self.http_get_text(KBO_DETAIL, params={"ondernemingsnummer": num, "lang": "en"})

    def get_company_details(self, company_id: str) -> Entity | None:
        num = normalise_be(self.native_id(company_id))
        if not num:
            return None
        page = self._page(num)
        if not page or not _kbo_field(page, "Name:"):
            return None
        name_lines = _lines(_kbo_field(page, "Name:") or "")
        status = _text(_kbo_field(page, "Status:") or "")
        situation = _lines(_kbo_field(page, "Legal situation:") or "")
        address = _lines(_kbo_field(page, r"Registered seat(?:'|&#0?39;|’)s address:") or "")
        company = self._stub(
            num,
            name_lines[0] if name_lines else "",
            status_text=status,
            address=", ".join(address) or None,
            start=_en_date(_text(_kbo_field(page, "Start date:") or "")),
        )
        form = _lines(_kbo_field(page, "Legal form:") or "")
        company.legal_form = form[0] if form else None
        abbreviation = _lines(_kbo_field(page, "Abbreviation:") or "")
        company.aliases = [a for a in abbreviation[:1] if a != company.name]
        website = _text(_kbo_field(page, "Web Address:") or "")
        if website and website.lower() not in ("no data included in the cbe.", "-"):
            company.extra["website"] = _website(website.split()[0])
        if situation:
            company.extra["legal_situation"] = situation[0]
            if re.search(r"bankrupt|faillissement|faillite|reorgani[sz]ation", situation[0], re.I):
                company.extra["insolvency"] = situation[0]
                company.status = (
                    CompanyStatus.DISSOLVED
                    if "bankrupt" in situation[0].lower()
                    else company.status
                )
            elif re.search(r"liquidation|dissolution|closure", situation[0], re.I):
                company.status = CompanyStatus.DISSOLVED
        return company

    def get_by_identifier(self, ident: Any) -> Entity | None:
        num = normalise_be(ident.value or "")
        return self.get_company_details(self.record_id(num)) if num else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        num = normalise_be(self.native_id(company_id))
        if not num:
            return []
        page = self._page(num) or ""
        me = self.record_id(num)
        url = self.ui_url(num)
        m = re.search(r'<table[^>]*id="toonfctie"[^>]*>(.*?)</table>', page, flags=re.S | re.I)
        if m:
            section = m.group(1)
        else:
            m = re.search(r"<h2>\s*Functions\s*</h2>(.*?)(?:<h2>|$)", page, flags=re.S | re.I)
            section = m.group(1) if m else ""
        out: list[LinkedEntity] = []
        seen: set[str] = set()
        rows = re.findall(
            r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>",
            section,
            flags=re.S | re.I,
        )
        for role_cell, holder_cell, since_cell in rows:
            role = translate_be_role(role_cell)
            holder = _text(holder_cell)
            if not role or not holder:
                continue
            number = re.search(r"ondernemingsnummer=(\d+)", holder_cell)
            dotted = BE_NUMBER.search(holder)
            if number or dotted:
                onum = normalise_be(number.group(1) if number else "".join(dotted.groups()))
                if not onum:
                    continue
                cname = BE_NUMBER.sub("", holder).strip(" -,") or _be_dotted(onum)
                other = self._stub(onum, cname)
                other.status = None
            else:
                other = self._person(reorder_surname_first(holder), None, url)
            link = self._link(other, me, role, url, start=_en_date(_text(since_cell)))
            if link.relationship.id in seen:
                continue
            seen.add(link.relationship.id)
            out.append(link)
        return out[:MAX_LINKS]
