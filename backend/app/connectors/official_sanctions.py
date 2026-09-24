"""Official sanctions lists, downloaded from the issuing authorities (no key).

* OFAC SDN list (US Treasury) — sdn.csv + alt.csv (aliases)
  https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists
* UN Security Council Consolidated List — consolidated.xml
  https://www.un.org/securitycouncil/content/un-sc-consolidated-list

The lists are downloaded once per server instance (refreshed every 12 h),
indexed by name token, and each network entity is re-scored with KBC's
explainable matcher (name, date of birth, nationality).
"""

from __future__ import annotations

import contextlib
import csv
import io
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

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
REFRESH_SECONDS = 12 * 3600
MIN_SCORE = 60
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


@dataclass
class ListedEntry:
    entity: Entity
    dataset: str
    url: str
    program: str | None = None
    details: dict = field(default_factory=dict)
    list_type: ListType = ListType.SANCTION


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
        for name in [entry.entity.name, *entry.entity.aliases]:
            for key in _keys(entry.entity.type, name):
                self.by_key.setdefault(key, []).append(idx)

    def candidates(self, entity: Entity) -> list[ListedEntry]:
        seen: set[int] = set()
        for name in [entity.name, *entity.aliases]:
            for key in _keys(entity.type, name):
                seen.update(self.by_key.get(key, [])[:500])
        return [self.entries[i] for i in seen if self.entries[i].entity.type == entity.type]


_INDEX = _Index()


def _download(url: str, timeout: float) -> str:
    resp = httpx.get(
        url, timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


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


class OfficialSanctionsConnector(BaseConnector):
    name = "official_sanctions"
    label = "Official sanctions lists — OFAC SDN (US) & UN Security Council"
    kind = "screening"
    homepage = "https://ofac.treasury.gov"

    def _index(self) -> _Index:
        with _INDEX.lock:
            if not _INDEX.entries or time.time() - _INDEX.loaded_at > REFRESH_SECONDS:
                fresh = _Index()
                timeout = max(self.settings.http_timeout_seconds, 30.0)
                for loader in (_load_ofac, _load_un):
                    try:
                        loader(fresh, timeout)
                    except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                        fresh.errors.append(
                            f"{loader.__name__[6:].upper()} list unavailable ({exc})"
                        )
                if not fresh.entries:
                    raise ConnectorError(f"{self.label}: " + "; ".join(fresh.errors))
                _INDEX.entries, _INDEX.by_key, _INDEX.errors = (
                    fresh.entries,
                    fresh.by_key,
                    fresh.errors,
                )
                _INDEX.wallets = fresh.wallets
                _INDEX.loaded_at = time.time()
            return _INDEX

    def prefetch(self) -> None:
        if not _INDEX.entries:
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
                    list_type=ListType.SANCTION,
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
                    f"address listed verbatim on the OFAC SDN list (Digital Currency Address - {currency})",
                    f"attributed to {entry.entity.name}",
                ],
                details={
                    "program": entry.program or None,
                    "listed_owner": entry.entity.name,
                    "currency": currency,
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
