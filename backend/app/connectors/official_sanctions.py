"""Official sanctions lists, downloaded from the issuing authorities (no key).

* OFAC SDN list (US Treasury): sdn.csv + alt.csv (aliases)
  https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists
* UN Security Council Consolidated List: consolidated.xml
  https://www.un.org/securitycouncil/content/un-sc-consolidated-list
* EU consolidated list of financial sanctions (European Commission, FSF)
* UK Sanctions List (Foreign, Commonwealth & Development Office)
* Swiss sanctions list (SECO)

Official lists are freely reusable, commercial use included: in commercial mode they are
the core of the sanctions screening (see app/licences.py).

The lists are downloaded once per server instance (refreshed every 12 h),
indexed by name token, and each network entity is re-scored with KBC's
explainable matcher (name, date of birth, nationality).
"""

from __future__ import annotations

import contextlib
import csv
import io
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET

import httpx

from app.connectors.base import USER_AGENT, BaseConnector, ConnectorError
from app.connectors.crypto_util import (
    OFAC_CURRENCY_CHAIN,
    detect_chain,
    normalize_address,
    wallet_id,
)
from app.connectors.util import nationality_iso
from app.matching.matcher import match_entities
from app.matching.names import canonical, normalize_company, normalize_person, phonetic
from app.models import (
    Entity,
    EntityType,
    LinkedEntity,
    ListType,
    Relationship,
    RelationType,
    ScreeningHit,
)

OFAC_SDN = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_ALT = "https://www.treasury.gov/ofac/downloads/alt.csv"
UN_XML = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
OFAC_UI = "https://sanctionssearch.ofac.treas.gov/Details.aspx?id={id}"
UN_UI = "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list"
US_CSL = "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.json"
US_CSL_UI = "https://www.trade.gov/consolidated-screening-list"
FR_GELS = "https://gels-avoirs.dgtresor.gouv.fr/ApiPublic/api/v1/publication/derniere-publication-fichier-json"
FR_GELS_UI = "https://gels-avoirs.dgtresor.gouv.fr/"
# EU consolidated list of financial sanctions (European Commission, FSF). The token is the
# public one published on data.europa.eu for anonymous downloads.
EU_XML = (
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content"
    "?token=dG9rZW4tMjAxNw"
)
UK_XML = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml"
UK_UI = "https://www.gov.uk/government/publications/the-uk-sanctions-list"
CH_XML = (
    "https://www.sesam.search.admin.ch/sesam-search-web/pages/downloadXmlGesamtliste.xhtml"
    "?lang=en&action=downloadXmlGesamtlisteAction"
)
CH_UI = "https://www.sesam.search.admin.ch/sesam-search-web/pages/search.xhtml?lang=en"
EU_UI = "https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions"
REFRESH_SECONDS = 12 * 3600
MIN_SCORE = 60
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


class ListedEntry:
    """One listed person or company. Stored compactly (a tuple, not a model): the lists hold
    a few hundred thousand entries per server; the Entity is rebuilt only for the candidates
    actually compared with a name."""

    __slots__ = ("_e", "dataset", "url", "program", "details", "list_type")

    def __init__(
        self,
        entity: Entity,
        dataset: str,
        url: str,
        program: str | None = None,
        details: dict | None = None,
        list_type: ListType = ListType.SANCTION,
    ) -> None:
        self._e = (
            sys.intern(entity.id),
            entity.type,
            entity.name,
            tuple(entity.aliases),
            entity.birth_date,
            tuple(entity.nationalities),
            entity.jurisdiction,
            entity.extra or None,
        )
        self.dataset = sys.intern(dataset)
        self.url = url
        self.program = program
        details = {k: v for k, v in (details or {}).items() if v}
        self.details = details or _NO_DETAILS
        self.list_type = list_type

    @property
    def type(self) -> EntityType:
        return self._e[1]

    @property
    def names(self) -> tuple[str, ...]:
        return (self._e[2], *self._e[3])

    @property
    def entity(self) -> Entity:
        eid, etype, name, aliases, dob, nats, jur, extra = self._e
        return Entity(
            id=eid,
            type=etype,
            name=name,
            aliases=list(aliases),
            birth_date=dob,
            nationalities=list(nats),
            jurisdiction=jur,
            extra=dict(extra or {}),
        )


_NO_DETAILS: dict = {}


def _keys(entity_type: EntityType, name: str) -> set[str]:
    norm = normalize_company if entity_type == EntityType.COMPANY else normalize_person
    return {phonetic(canonical(t)) for t in norm(name) if len(t) > 2}


def _ofac_dob(remarks: str) -> str | None:
    m = re.search(r"DOB (?:circa )?(\d{1,2}) ([A-Za-z]{3}) (\d{4})", remarks)
    if m and m.group(2).lower() in _MONTHS:
        return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"DOB (?:circa )?([A-Za-z]{3}) (\d{4})", remarks)
    if m and m.group(1).lower() in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}"
    m = re.search(r"DOB (?:circa )?(\d{4})", remarks)
    return m.group(1) if m else None


def _ofac_name(raw: str, is_person: bool) -> str:
    """'PUTIN, Vladimir Vladimirovich' -> 'Vladimir Vladimirovich PUTIN'."""
    if is_person and "," in raw:
        last, first = raw.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return raw.strip()


class _Index:
    """In-memory list index shared by all requests of a server instance."""

    def __init__(self) -> None:
        self.entries: list[ListedEntry] = []
        # normalised crypto address -> (entry index, OFAC currency code, network)
        self.wallets: dict[str, tuple[int, str, str | None]] = {}
        self.by_key: dict[str, list[int]] = {}
        self.loaded_at = 0.0
        self.errors: list[str] = []
        self.lock = threading.Lock()

    def add(self, entry: ListedEntry, addresses: list[tuple[str, str]] = ()) -> None:
        idx = len(self.entries)
        self.entries.append(entry)
        for currency, address in addresses:
            chain = detect_chain(address) or OFAC_CURRENCY_CHAIN.get(currency)
            self.wallets[normalize_address(address, chain)] = (idx, currency, chain)
        for name in entry.names:
            for key in _keys(entry.type, name):
                self.by_key.setdefault(key, []).append(idx)

    def candidates(self, entity: Entity) -> list[ListedEntry]:
        seen: set[int] = set()
        for name in [entity.name, *entity.aliases]:
            for key in _keys(entity.type, name):
                seen.update(self.by_key.get(key, [])[:500])
        return [self.entries[i] for i in seen if self.entries[i].type == entity.type]


_INDEX = _Index()


def _download(url: str, timeout: float) -> str:
    resp = httpx.get(
        url, timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF_SECONDS = 2.0


def _download_bytes(url: str, timeout: float) -> bytes:
    """Streamed download, retried: the Swiss server sometimes closes the connection in the
    middle of its 40 MB file ("peer closed connection without sending complete message body")."""
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        buf = bytearray()
        try:
            with httpx.stream(
                "GET",
                url,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
            return bytes(buf)
        except httpx.TransportError:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
            time.sleep(DOWNLOAD_BACKOFF_SECONDS * attempt)
    raise AssertionError("unreachable")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _load_ofac(index: _Index, timeout: float) -> None:
    aliases: dict[str, list[str]] = {}
    for row in csv.reader(io.StringIO(_download(OFAC_ALT, timeout))):
        if len(row) >= 4 and row[3].strip() not in ("", "-0-"):
            aliases.setdefault(row[0].strip(), []).append(row[3].strip())
    for row in csv.reader(io.StringIO(_download(OFAC_SDN, timeout))):
        if len(row) < 12:
            continue
        ent_num, name, sdn_type, program, remarks = (
            row[0].strip(),
            row[1],
            row[2].strip(),
            row[3],
            row[11],
        )
        if sdn_type in ("vessel", "aircraft"):
            continue
        is_person = sdn_type == "individual"
        clean = lambda v: "" if v.strip() == "-0-" else v.strip()  # noqa: E731
        remarks = clean(remarks)
        nats = nationality_iso(" / ".join(re.findall(r"[Nn]ationality ([A-Za-z ]+?)[;.]", remarks)))
        etype = EntityType.PERSON if is_person else EntityType.COMPANY
        wallets = re.findall(r"Digital Currency Address - ([A-Z0-9]+) ([A-Za-z0-9]+)", remarks)
        index.add(
            addresses=wallets,
            entry=ListedEntry(
                entity=Entity(
                    id=f"ofac:{ent_num}",
                    type=etype,
                    name=_ofac_name(name, is_person),
                    aliases=[_ofac_name(a, is_person) for a in aliases.get(ent_num, [])][:30],
                    birth_date=_ofac_dob(remarks) if is_person else None,
                    nationalities=nats,
                ),
                dataset="OFAC SDN list (US Treasury)",
                url=OFAC_UI.format(id=ent_num),
                program=clean(program),
                details={"remarks": remarks[:300] or None},
            ),
        )


def _text(node: ET.Element | None, tag: str) -> str:
    child = node.find(tag) if node is not None else None
    return (child.text or "").strip() if child is not None and child.text else ""


def _load_un(index: _Index, timeout: float) -> None:
    root = ET.fromstring(_download(UN_XML, timeout))
    for ind in root.iter("INDIVIDUAL"):
        name = " ".join(
            p
            for p in (
                _text(ind, t) for t in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")
            )
            if p
        )
        if not name:
            continue
        dob = None
        for d in ind.iter("INDIVIDUAL_DATE_OF_BIRTH"):
            dob = _text(d, "DATE")[:10] or _text(d, "YEAR") or None
            if dob:
                break
        nats = nationality_iso(
            " / ".join(v.text or "" for v in ind.iter("VALUE") if v.text and v.text.strip())
        )
        index.add(
            ListedEntry(
                entity=Entity(
                    id=f"un:{_text(ind, 'REFERENCE_NUMBER')}",
                    type=EntityType.PERSON,
                    name=name,
                    aliases=[
                        a.text.strip() for a in ind.iter("ALIAS_NAME") if a.text and a.text.strip()
                    ][:30],
                    birth_date=dob,
                    nationalities=nats,
                ),
                dataset="UN Security Council Consolidated List",
                url=UN_UI,
                program=_text(ind, "UN_LIST_TYPE"),
                details={
                    "reference": _text(ind, "REFERENCE_NUMBER"),
                    "listed_on": _text(ind, "LISTED_ON"),
                },
            )
        )
    for ent in root.iter("ENTITY"):
        name = _text(ent, "FIRST_NAME")
        if not name:
            continue
        index.add(
            ListedEntry(
                entity=Entity(
                    id=f"un:{_text(ent, 'REFERENCE_NUMBER')}",
                    type=EntityType.COMPANY,
                    name=name,
                    aliases=[
                        a.text.strip() for a in ent.iter("ALIAS_NAME") if a.text and a.text.strip()
                    ][:30],
                ),
                dataset="UN Security Council Consolidated List",
                url=UN_UI,
                program=_text(ent, "UN_LIST_TYPE"),
                details={
                    "reference": _text(ent, "REFERENCE_NUMBER"),
                    "listed_on": _text(ent, "LISTED_ON"),
                },
            )
        )


def _load_eu(index: _Index, timeout: float) -> None:
    """EU consolidated financial sanctions list, from the European Commission (~25 MB XML,
    streamed: each <sanctionEntity> is read, indexed and freed)."""
    data = _download_bytes(EU_XML, timeout)
    added = 0
    for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
        if _local(el.tag) != "sanctionEntity":
            continue
        subject = next((c.get("code") for c in el if _local(c.tag) == "subjectType"), "")
        if subject not in ("person", "enterprise"):
            el.clear()
            continue
        is_person = subject == "person"
        names: list[str] = []
        births: list[str] = []
        nats: list[str] = []
        program, act_url, remark = "", "", ""
        published: list[str] = []
        for c in el:
            tag = _local(c.tag)
            if tag == "nameAlias":
                whole = (c.get("wholeName") or "").strip()
                if whole and whole not in names:
                    names.append(whole)
            elif tag == "birthdate":
                b = (c.get("birthdate") or c.get("year") or "").strip()
                if b:
                    births.append(b)
            elif tag == "citizenship":
                iso = (c.get("countryIso2Code") or "").strip().upper()
                if len(iso) == 2 and iso != "00" and iso not in nats:
                    nats.append(iso)
            elif tag == "regulation" and c.get("publicationDate"):
                published.append(c.get("publicationDate"))
            if tag == "regulation" and not program:
                program = c.get("programme") or ""
                act_url = next(
                    ((u.text or "").strip() for u in c if _local(u.tag) == "publicationUrl"), ""
                )
            elif tag == "remark" and not remark:
                remark = (c.text or "").strip()
        ref = el.get("euReferenceNumber") or el.get("logicalId") or ""
        if names:
            index.add(
                ListedEntry(
                    entity=Entity(
                        id=f"eu_fsf:{el.get('logicalId')}",
                        type=EntityType.PERSON if is_person else EntityType.COMPANY,
                        name=names[0],
                        aliases=names[1:31],
                        birth_date=births[0] if is_person and births else None,
                        nationalities=nats if is_person else [],
                    ),
                    dataset="EU consolidated financial sanctions list (European Commission)",
                    url=act_url or EU_UI,
                    program=program or None,
                    details={
                        "reference": ref or None,
                        "remarks": remark[:300] or None,
                        "listed_on": (el.get("designationDate") or min(published, default=""))
                        or None,
                    },
                )
            )
            added += 1
        el.clear()
    if not added:
        raise ValueError("EU list downloaded but empty")


def _uk_dob(raw: str) -> str | None:
    """'23/03/1980' -> '1980-03-23', 'dd/03/1980' -> '1980-03', 'dd/mm/1945' -> '1945'."""
    m = re.fullmatch(r"(\w{2})/(\w{2})/(\d{4})", raw.strip())
    if not m:
        return None
    day, month, year = m.groups()
    if not month.isdigit():
        return year
    return f"{year}-{month}" + (f"-{day}" if day.isdigit() else "")


def _uk_date(raw: str) -> str | None:
    """'08/09/2026' -> '2026-09-08' (a complete date only)."""
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", raw.strip())
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _load_uk(index: _Index, timeout: float) -> None:
    """UK Sanctions List (FCDO): the single UK list since OFSI's consolidated list closed."""
    data = _download_bytes(UK_XML, timeout)
    added = 0
    for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
        if _local(el.tag) != "Designation":
            continue
        kind = (el.findtext("IndividualEntityShip") or "").strip()
        if kind not in ("Individual", "Entity"):
            el.clear()
            continue
        is_person = kind == "Individual"
        primary: list[str] = []
        aliases: list[str] = []
        for n in el.iter("Name"):
            parts = [(n.findtext(f"Name{i}") or "").strip() for i in range(1, 7)]
            name = " ".join(p for p in parts if p)
            if not name:
                continue
            target = primary if (n.findtext("NameType") or "").startswith("Primary") else aliases
            if name not in primary and name not in aliases:
                target.append(name)
        names = primary + aliases
        dobs = [d for d in (_uk_dob(x.text or "") for x in el.iter("DOB")) if d]
        nats = nationality_iso(" / ".join((x.text or "") for x in el.iter("Nationality")))
        uid = (el.findtext("UniqueID") or "").strip()
        if names:
            index.add(
                ListedEntry(
                    entity=Entity(
                        id=f"uk_fcdo:{uid}",
                        type=EntityType.PERSON if is_person else EntityType.COMPANY,
                        name=names[0],
                        aliases=names[1:31],
                        birth_date=dobs[0] if is_person and dobs else None,
                        nationalities=nats if is_person else [],
                    ),
                    dataset="UK Sanctions List (FCDO)",
                    url=UK_UI,
                    program=(el.findtext("RegimeName") or "").strip() or None,
                    details={
                        "reference": uid or None,
                        "sanctions": (el.findtext("SanctionsImposed") or "").strip() or None,
                        "listed_on": _uk_date(el.findtext("DateDesignated") or ""),
                    },
                )
            )
            added += 1
        el.clear()
    if not added:
        raise ValueError("UK list downloaded but empty")


_CH_PART_RANK = {"given-name": 0, "further-given-name": 1, "father-name": 2, "family-name": 4}


def _ch_names(name: ET.Element) -> list[str]:
    """Given names first, family name last; a second form with the Latin spelling variants
    ('Lukashenka Aliaksandr' -> 'Aliaksandr Lukashenka', 'Alexander Lukashenko')."""
    parts = sorted(
        name.findall("name-part"),
        key=lambda p: (
            _CH_PART_RANK.get(p.get("name-part-type") or "", 3),
            int(p.get("order") or 0),
        ),
    )
    main = [(p.findtext("value") or "").strip() for p in parts]
    variant = [
        next(
            (
                (v.text or "").strip()
                for v in p.findall("spelling-variant")
                if v.get("script") == "LATN" and (v.text or "").strip()
            ),
            m,
        )
        for p, m in zip(parts, main, strict=True)
    ]
    out = [" ".join(v for v in main if v)]
    alt = " ".join(v for v in variant if v)
    if alt and alt != out[0]:
        out.append(alt)
    return [n for n in out if n]


def _load_ch(index: _Index, timeout: float) -> None:
    """Swiss sanctions list (SECO). The file also keeps de-listed targets: a target whose
    latest modification is a de-listing is skipped."""
    data = _download_bytes(CH_XML, timeout)
    programs: dict[str, str] = {}
    added = 0
    for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
        tag = el.tag
        if tag == "sanctions-program":
            key = next(
                (k.text for k in el.findall("program-key") if k.get("lang") == "eng" and k.text),
                "",
            )
            for sset in el.findall("sanctions-set"):
                if sset.get("ssid"):
                    programs[sset.get("ssid")] = key
            continue
        if tag != "target":
            continue
        mods = sorted(
            el.findall("modification"),
            key=lambda m: m.get("effective-date") or m.get("enactment-date") or "",
        )
        subject = el.find("individual")
        is_person = subject is not None
        if subject is None:
            subject = el.find("entity")
        if subject is None or (mods and mods[-1].get("modification-type") == "de-listed"):
            el.clear()
            continue
        names: list[str] = []
        births: list[str] = []
        nats: list[str] = []
        for identity in subject.findall("identity"):
            for name in identity.findall("name"):
                primary = name.get("name-type") == "primary-name" and identity.get("main") == "true"
                for i, n in enumerate(_ch_names(name)):
                    if n in names:
                        continue
                    if primary and i == 0:
                        names.insert(0, n)
                    else:
                        names.append(n)
            for d in identity.findall("day-month-year"):
                y, m, dd = d.get("year"), d.get("month"), d.get("day")
                if y:
                    births.append(
                        y
                        + (f"-{int(m):02d}" if m else "")
                        + (f"-{int(dd):02d}" if m and dd else "")
                    )
            for nat in identity.findall("nationality"):
                iso = (nat.get("iso-code") or "").strip()
                c = nat.find("country")
                if not iso and c is not None:
                    iso = (c.get("iso-code") or "").strip()
                found = (
                    [iso.upper()]
                    if len(iso) == 2
                    else nationality_iso(c.text if c is not None else nat.text)
                )
                nats.extend(x for x in found if x not in nats)
        ssid = el.get("ssid") or ""
        if names:
            index.add(
                ListedEntry(
                    entity=Entity(
                        id=f"ch_seco:{ssid}",
                        type=EntityType.PERSON if is_person else EntityType.COMPANY,
                        name=names[0],
                        aliases=names[1:31],
                        birth_date=births[0] if is_person and births else None,
                        nationalities=nats if is_person else [],
                    ),
                    dataset="Swiss sanctions list (SECO)",
                    url=CH_UI,
                    program=programs.get((el.findtext("sanctions-set-id") or "").strip()) or None,
                    details={
                        "reference": ssid or None,
                        "remarks": (subject.findtext("justification") or "").strip()[:300] or None,
                    },
                )
            )
            added += 1
        el.clear()
    if not added:
        raise ValueError("Swiss list downloaded but empty")


CRYPTO_URL = "https://data.opensanctions.org/datasets/latest/{dataset}/targets.simple.csv"
IL_CRYPTO = CRYPTO_URL.format(dataset="il_mod_crypto")
IL_CRYPTO_LABEL = "Israel NBCTF seized / sanctioned crypto wallets (terror financing)"
# Crypto address lists matched verbatim, like the OFAC addresses: (dataset, label, owner)
CRYPTO_LISTS = (
    ("il_mod_crypto", IL_CRYPTO_LABEL, "Wallet listed by Israel's NBCTF"),
    (
        "us_fbi_lazarus_crypto",
        "US FBI: Lazarus Group (North Korea) crypto wallets",
        "Lazarus Group (DPRK)",
    ),
    ("ransomwhere", "Ransomware payment addresses (ransomwhe.re)", "Ransomware operator"),
)


def _load_crypto_list(index: _Index, timeout: float, dataset: str, label: str, owner: str) -> int:
    added = 0
    for row in csv.DictReader(io.StringIO(_download(CRYPTO_URL.format(dataset=dataset), timeout))):
        candidates = [(row.get("name") or "").strip()] + [
            i.strip() for i in (row.get("identifiers") or "").split(";")
        ]
        address = next((a for a in candidates if a and detect_chain(a)), None)
        if row.get("schema") != "CryptoWallet" or not address:
            continue
        chain = detect_chain(address)
        entry = ListedEntry(
            entity=Entity(id=f"{dataset}:{row.get('id')}", type=EntityType.COMPANY, name=owner),
            dataset=label,
            url=f"https://www.opensanctions.org/entities/{row.get('id')}/",
            program=(row.get("sanctions") or "").strip('"') or None,
        )
        index.entries.append(entry)  # addresses only: not in the name index
        index.wallets.setdefault(
            normalize_address(address, chain), (len(index.entries) - 1, "", chain)
        )
        added += 1
    return added


def _load_il_crypto(index: _Index, timeout: float) -> None:
    """Crypto addresses seized by Israel's NBCTF, the FBI's Lazarus Group (North Korea)
    addresses and ransomware payment addresses: matched verbatim like the OFAC addresses."""
    added, errors = 0, []
    for dataset, label, owner in CRYPTO_LISTS:
        try:
            added += _load_crypto_list(index, timeout, dataset, label, owner)
        except httpx.HTTPError as exc:
            errors.append(f"{dataset}: {exc}")
    if not added:
        raise ValueError("crypto address lists downloaded but empty " + "; ".join(errors))


class OfficialSanctionsConnector(BaseConnector):
    name = "official_sanctions"
    label = "Official sanctions lists: OFAC SDN (US), UN Security Council, crypto wallets"
    kind = "screening"
    homepage = "https://ofac.treasury.gov"

    @property
    def _state(self) -> _Index:
        return _INDEX

    def _loaders(self) -> list:
        loaders = [_load_ofac, _load_un]
        # The crypto address lists come from OpenSanctions exports (CC BY-NC).
        if self.osn_allowed:
            loaders.append(_load_il_crypto)
        return loaders

    def _load_all(self, timeout: float) -> _Index:
        fresh = _Index()
        for loader in self._loaders():
            try:
                loader(fresh, timeout)
            except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                fresh.errors.append(f"{loader.__name__[6:].upper()} list unavailable ({exc})")
        return fresh

    def _index(self) -> _Index:
        state = self._state
        with state.lock:
            if not state.entries or time.time() - state.loaded_at > REFRESH_SECONDS:
                fresh = self._load_all(max(self.settings.http_timeout_seconds, 30.0))
                if not fresh.entries:
                    raise ConnectorError(f"{self.label}: " + "; ".join(fresh.errors))
                state.entries, state.by_key, state.errors = (
                    fresh.entries,
                    fresh.by_key,
                    fresh.errors,
                )
                state.wallets = fresh.wallets
                state.loaded_at = time.time()
            return state

    @property
    def osn_allowed(self) -> bool:
        """OpenSanctions exports may be used: not in commercial mode, or under a licence."""
        from app.licences import licensed_names

        return not self.settings.commercial_mode or "open_watchlists" in licensed_names(
            self.settings.licensed_sources
        )

    def prefetch(self) -> None:
        if not self._state.entries:
            threading.Thread(target=self._safe_index, daemon=True).start()

    def _safe_index(self) -> None:
        with contextlib.suppress(ConnectorError):  # errors are reported when screening runs
            self._index()

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type == EntityType.WALLET:
            return self._screen_wallet(entity)
        if entity.type not in (EntityType.PERSON, EntityType.COMPANY):
            return []
        hits = []
        for entry in self._index().candidates(entity):
            result = match_entities(entity, entry.entity)
            if result.score < MIN_SCORE:
                continue
            listed = entry.entity
            hits.append(
                ScreeningHit(
                    entity_id=entity.id,
                    list_type=entry.list_type,
                    dataset=entry.dataset,
                    matched_name=listed.name,
                    score=result.score,
                    explanation=result.explanation,
                    details={
                        "program": entry.program or None,
                        "birth_date": listed.birth_date,
                        "nationalities": listed.nationalities or None,
                        **entry.details,
                    },
                    provenance=self.provenance(self.record_id(listed.id), entry.url),
                )
            )
        return hits

    def _screen_wallet(self, entity: Entity) -> list[ScreeningHit]:
        index = self._index()
        found = index.wallets.get(normalize_address(entity.name, entity.chain))
        if not found:
            return []
        idx, currency, _ = found
        entry = index.entries[idx]
        return [
            ScreeningHit(
                entity_id=entity.id,
                list_type=ListType.SANCTION,
                dataset=entry.dataset,
                matched_name=f"{entity.name} ({entry.entity.name})",
                score=100.0,
                explanation=[
                    f"address listed verbatim on the OFAC SDN list (Digital Currency Address - {currency})"
                    if currency
                    else f"address listed verbatim: {entry.dataset}",
                    f"attributed to {entry.entity.name}",
                ],
                details={
                    "program": entry.program or None,
                    "listed_owner": entry.entity.name,
                    "currency": currency or None,
                },
                provenance=self.provenance(self.record_id(entry.entity.id), entry.url),
            )
        ]

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        """Wallet -> its sanctioned owner; sanctioned owner -> its other listed addresses."""
        is_listed_owner = any(r.startswith(f"{self.name}:") for r in entity.record_ids)
        if entity.type != EntityType.WALLET and not is_listed_owner:
            return []  # nothing to do: never wait for the list download for ordinary entities
        index = self._index()
        out: list[LinkedEntity] = []
        if entity.type == EntityType.WALLET:
            found = index.wallets.get(normalize_address(entity.name, entity.chain))
            if found:
                owner = self._owner_entity(index.entries[found[0]])
                out.append(self._control(owner, entity, found[1], other=owner))
            return out
        own_ids = {r.split(":", 1)[1] for r in entity.record_ids if r.startswith(f"{self.name}:")}
        for address, (idx, currency, chain) in index.wallets.items():
            entry = index.entries[idx]
            if entry.entity.id in own_ids and chain in ("BTC", "ETH", "TRON"):
                wallet = Entity(
                    id=wallet_id(chain, address),
                    record_ids=[],
                    type=EntityType.WALLET,
                    name=address,
                    chain=chain,
                    sources=[self.provenance(self.record_id(entry.entity.id), entry.url)],
                )
                out.append(self._control(entity, wallet, currency, other=wallet))
        return out[:20]

    def _owner_entity(self, entry: ListedEntry) -> Entity:
        rid = self.record_id(entry.entity.id)
        return entry.entity.model_copy(
            update={"id": rid, "record_ids": [rid], "sources": [self.provenance(rid, entry.url)]}
        )

    def _control(self, owner: Entity, wallet: Entity, currency: str, other: Entity) -> LinkedEntity:
        """CONTROLS edge owner -> wallet; `other` is the end returned to the caller."""
        rel = Relationship(
            id=f"{self.name}:ctrl:{owner.id}>{wallet.name}",
            type=RelationType.CONTROLS,
            source_id=owner.id,
            target_id=wallet.id,
            role=f"Address attributed by OFAC (Digital Currency Address - {currency})",
            sources=[self.provenance(owner.id, OFAC_UI.format(id=owner.id.rsplit(":", 1)[-1]))],
        )
        return LinkedEntity(relationship=rel, entity=other)

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        # The list is in memory: one pass is cheap, and it avoids parallel downloads.
        return [h for e in entities for h in self.screen(e)]


_INDEX_EUROPE = _Index()


class EuropeanSanctionsConnector(OfficialSanctionsConnector):
    """EU, UK and Swiss sanctions lists, from the issuing authorities (~90 MB in all). They
    download in parallel, in the background: until they are ready on a cold server, the
    screening waits a little, then says so instead of blocking the OFAC / UN screening."""

    name = "official_sanctions_europe"
    label = "Official sanctions lists: EU (European Commission), UK (FCDO), Switzerland (SECO)"
    homepage = EU_UI
    #: seconds a screening waits for the lists on a cold server before reporting them as loading
    wait_seconds = 30.0

    @property
    def _state(self) -> _Index:
        return _INDEX_EUROPE

    def _loaders(self) -> list:
        return [_load_eu, _load_uk, _load_ch]

    def _load_all(self, timeout: float) -> _Index:
        from concurrent.futures import ThreadPoolExecutor

        def run(loader) -> _Index | str:
            part = _Index()
            try:
                loader(part, timeout)
            except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                return f"{loader.__name__[6:].upper()} list unavailable ({exc})"
            return part

        # Last good copy of each list: a list that fails to download on a refresh keeps its
        # previous entries instead of silently disappearing from the screening.
        previous: dict[str, tuple[list[ListedEntry], float]] = getattr(self._state, "parts", {})
        parts: dict[str, tuple[list[ListedEntry], float]] = {}
        fresh = _Index()
        loaders = self._loaders()
        with ThreadPoolExecutor(max_workers=3) as pool:
            for loader, result in zip(loaders, pool.map(run, loaders), strict=True):
                key = loader.__name__
                if isinstance(result, str):
                    if key in previous:
                        parts[key] = previous[key]
                        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(previous[key][1]))
                        fresh.errors.append(f"{result}: the copy downloaded on {when} is used")
                    else:
                        fresh.errors.append(result)
                    continue
                parts[key] = (result.entries, time.time())
        for entries, _ in parts.values():
            for entry in entries:
                fresh.add(entry)
        self._state.parts = parts  # type: ignore[attr-defined]
        return fresh

    def prefetch(self) -> None:
        state = self._state
        if not state.entries and not getattr(state, "loading", False):
            state.loading = True  # type: ignore[attr-defined]

            def run() -> None:
                try:
                    self._safe_index()
                finally:
                    state.loading = False  # type: ignore[attr-defined]

            threading.Thread(target=run, daemon=True).start()

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        if entity.type not in (EntityType.PERSON, EntityType.COMPANY):
            return []
        state = self._state
        if not state.entries:
            self.prefetch()
            deadline = time.time() + self.wait_seconds
            while not state.entries and getattr(state, "loading", False) and time.time() < deadline:
                time.sleep(0.5)
            if not state.entries and getattr(state, "loading", False):
                raise ConnectorError(
                    f"{self.label}: still loading on this server, included from the next check"
                )
        return super().screen(entity)

    def get_wallet_links(
        self, entity: Entity, include_transfers: bool = True
    ) -> list[LinkedEntity]:
        return []


# ------------------------------------------------------------ US and French national lists
# Short names of the US Consolidated Screening List sources (the SDN list is read from OFAC).
_CSL_LISTS = {
    "Entity List": "US Entity List (Commerce, BIS): export restrictions",
    "Denied Persons": "US Denied Persons List (Commerce, BIS): export privileges denied",
    "Unverified List": "US Unverified List (Commerce, BIS): end use not verified",
    "Military End User": "US Military End User List (Commerce, BIS)",
    "ITAR Debarred": "US ITAR debarments (State Department): arms exports",
    "Nonproliferation": "US Nonproliferation sanctions (State Department)",
    "Sectoral Sanctions": "US Sectoral Sanctions Identifications (OFAC SSI)",
    "Chinese Military-Industrial": "US Chinese Military-Industrial Complex companies (OFAC CMIC)",
    "Menu-Based": "US Non-SDN Menu-Based Sanctions (OFAC)",
    "Palestinian Legislative Council": "US Palestinian Legislative Council list (OFAC)",
    "Capta": "US CAPTA list (OFAC): correspondent account restrictions",
}
_COMPANY_WORDS = re.compile(
    r"\b(ltd|limited|llc|inc|corp|corporation|co|company|gmbh|ag|sa|sarl|sas|srl|spa|bv|nv|plc"
    r"|jsc|ojsc|pjsc|ooo|oao|zao|llp|lp|group|holding|holdings|trading|industries|industry"
    r"|technology|technologies|institute|university|academy|bureau|center|centre|factory"
    r"|plant|bank|enterprise|enterprises|international|electronics|systems|laboratory|research)\b",
    re.I,
)


def _csl_types(item: dict) -> list[EntityType]:
    kind = (item.get("type") or "").lower()
    if kind == "individual":
        return [EntityType.PERSON]
    if kind == "entity":
        return [EntityType.COMPANY]
    if kind in ("vessel", "aircraft"):
        return []
    # The Commerce lists give no type: a company word decides, a birth date means a person,
    # otherwise the entry is indexed both ways so that neither kind of query misses it.
    if item.get("dates_of_birth"):
        return [EntityType.PERSON]
    if _COMPANY_WORDS.search(item.get("name") or ""):
        return [EntityType.COMPANY]
    return [EntityType.COMPANY, EntityType.PERSON]


def _load_us_csl(index: _Index, timeout: float) -> None:
    """US Consolidated Screening List (trade.gov): the export and trade lists of Commerce,
    State and Treasury. The SDN list is skipped: it is read directly from OFAC."""
    import json

    data = json.loads(_download_bytes(US_CSL, timeout))
    added = 0
    for item in data.get("results") or []:
        source = item.get("source") or ""
        label = next((v for k, v in _CSL_LISTS.items() if k in source), None)
        name = (item.get("name") or "").strip()
        if not label or not name:
            continue
        aliases = [a.strip() for a in item.get("alt_names") or [] if a and a.strip() != name]
        countries = sorted(
            {
                (a.get("country") or "").upper()
                for a in item.get("addresses") or []
                if a.get("country")
            }
        )
        for etype in _csl_types(item):
            is_person = etype == EntityType.PERSON
            index.add(
                ListedEntry(
                    entity=Entity(
                        id=f"us_csl:{item.get('id')}",
                        type=etype,
                        name=name,
                        aliases=aliases[:30],
                        birth_date=(
                            (item.get("dates_of_birth") or [None])[0] if is_person else None
                        ),
                        nationalities=nationality_iso(
                            " / ".join(item.get("nationalities") or item.get("citizenships") or [])
                        )
                        if is_person
                        else [],
                        jurisdiction=None if is_person or len(countries) != 1 else countries[0],
                    ),
                    dataset=label,
                    url=item.get("source_information_url") or US_CSL_UI,
                    program=", ".join(item.get("programs") or []) or None,
                    details={
                        "reference": item.get("id"),
                        "countries": ", ".join(countries) or None,
                        "listed_on": item.get("start_date"),
                        "federal_register": item.get("federal_register_notice"),
                        "license_requirement": item.get("license_requirement"),
                        "remarks": (item.get("remarks") or "")[:300] or None,
                    },
                    list_type=ListType.ADVERSE if "Unverified" in source else ListType.SANCTION,
                )
            )
            added += 1
    if not added:
        raise ValueError("US screening list downloaded but empty")


def _fr_field(record: dict, field: str) -> list[dict]:
    return [
        v
        for d in record.get("RegistreDetail") or []
        if d.get("TypeChamp") == field
        for v in d.get("Valeur") or []
    ]


def _load_fr_gels(index: _Index, timeout: float) -> None:
    """France: Registre national des gels (DG Trésor), every asset freeze applicable in France,
    EU, UN and national measures alike."""
    import json

    data = json.loads(_download_bytes(FR_GELS, timeout))
    records = (data.get("Publications") or {}).get("PublicationDetail") or []
    added = 0
    for rec in records:
        nature = rec.get("Nature") or ""
        if nature not in ("Personne physique", "Personne morale"):
            continue  # ships
        is_person = nature == "Personne physique"
        last = (rec.get("Nom") or "").strip()
        first = " ".join((v.get("Prenom") or "").strip() for v in _fr_field(rec, "PRENOM")).strip()
        name = f"{first} {last}".strip() if is_person else last
        if not name:
            continue
        aliases = [(v.get("Alias") or "").strip() for v in _fr_field(rec, "ALIAS")]
        dob = None
        for v in _fr_field(rec, "DATE_DE_NAISSANCE"):
            y, m, d = (
                (v.get("Annee") or "").strip(),
                (v.get("Mois") or "").strip(),
                (v.get("Jour") or "").strip(),
            )
            if y:
                dob = "-".join(
                    x for x in (y, m.zfill(2) if m else "", d.zfill(2) if m and d else "") if x
                )
                break
        bases = [
            (v.get("FondementJuridiqueLabel") or "").strip()
            for v in _fr_field(rec, "FONDEMENT_JURIDIQUE")
        ]
        national = any(
            b and "(UE)" not in b and "comité des sanctions" not in b.lower() for b in bases
        )
        index.add(
            ListedEntry(
                entity=Entity(
                    id=f"fr_gels:{rec.get('IdRegistre')}",
                    type=EntityType.PERSON if is_person else EntityType.COMPANY,
                    name=name,
                    aliases=[a for a in aliases if a and a != name][:30],
                    birth_date=dob if is_person else None,
                    nationalities=nationality_iso(
                        " / ".join((v.get("Pays") or "") for v in _fr_field(rec, "NATIONALITE"))
                    )
                    if is_person
                    else [],
                ),
                dataset="France asset freezes register (DG Trésor)",
                url=FR_GELS_UI,
                program="; ".join(b for b in bases if b)[:300] or None,
                details={
                    "reference": str(rec.get("IdRegistre")),
                    "national_measure": "yes" if national else None,
                    "grounds": ((_fr_field(rec, "MOTIFS") or [{}])[0].get("Motifs") or "")[:300]
                    or None,
                },
            )
        )
        added += 1
    if not added:
        raise ValueError("French register downloaded but empty")


_INDEX_NATIONAL = _Index()


class NationalSanctionsConnector(EuropeanSanctionsConnector):
    """US export and trade restriction lists (Commerce, State, Treasury beyond the SDN list)
    and the French national asset freezes register, downloaded from the authorities. Both are
    open government data: they stay on in commercial mode."""

    name = "official_sanctions_national"
    label = "Official lists: US export and trade restrictions (Commerce, State, Treasury), France asset freezes (DG Trésor)"
    homepage = US_CSL_UI
    wait_seconds = 20.0

    @property
    def _state(self) -> _Index:
        return _INDEX_NATIONAL

    def _loaders(self) -> list:
        return [_load_us_csl, _load_fr_gels]
