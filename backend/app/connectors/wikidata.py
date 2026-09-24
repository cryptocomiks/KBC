"""Wikidata — public figures, PEPs, their relatives and associates, official contacts.

Open data (CC0), no key: MediaWiki API (wbsearchentities + wbgetentities).

* PEP screening: "position held" (P39) with start/end dates.
* Relatives and close associates (RCA): spouse, children, parents,
  siblings, relatives — the people a PEP screening must also cover.
* Corporate links: chairperson, CEO, director, founder, owner, parent
  organisation, subsidiaries.
* Official contacts — only for companies and public figures (people notable
  enough to have a Wikidata item): website, published e-mail / phone and
  official social accounts. No data is collected about private individuals.
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector
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

SEARCH = "https://www.wikidata.org/w/api.php"
ITEM_URL = "https://www.wikidata.org/wiki/{qid}"
HUMAN = "Q5"
MIN_NAME = 85
NOT_ENTITIES = ("family name", "given name", "disambiguation", "wikimedia", "surname", "name")

RELATIVES = {
    "P26": "Spouse",
    "P40": "Child",
    "P22": "Father",
    "P25": "Mother",
    "P3373": "Sibling",
    "P1038": "Relative",
}
PERSON_TO_ORG = {
    "P108": (RelationType.OFFICER, "Employee / executive"),
    "P3320": (RelationType.OFFICER, "Board member"),
    "P1830": (RelationType.SHAREHOLDER, "Owner"),
}
ORG_FROM = {
    "P488": (RelationType.OFFICER, "Chairperson"),
    "P169": (RelationType.OFFICER, "Chief executive officer"),
    "P1037": (RelationType.OFFICER, "Director / manager"),
    "P112": (RelationType.OFFICER, "Founder"),
    "P127": (RelationType.SHAREHOLDER, "Owner"),
    "P749": (RelationType.SHAREHOLDER, "Parent organisation"),
}
ORG_TO = {
    "P355": (RelationType.SHAREHOLDER, "Parent organisation"),
    "P1830": (RelationType.SHAREHOLDER, "Owner"),
}

CONTACTS = [
    ("website", "Official website", "{v}"),
    ("email", "Published e-mail", "{v}"),
    ("phone", "Published phone", "tel:{v}"),
    ("twitter", "X / Twitter @{v}", "https://x.com/{v}"),
    ("linkedin", "LinkedIn profile", "https://www.linkedin.com/in/{v}"),
    ("linkedin_org", "LinkedIn page", "https://www.linkedin.com/company/{v}"),
    ("facebook", "Facebook", "https://www.facebook.com/{v}"),
    ("instagram", "Instagram @{v}", "https://www.instagram.com/{v}"),
    ("youtube", "YouTube channel", "https://www.youtube.com/channel/{v}"),
]

CONTACT_PROPS = {
    "website": "P856",
    "email": "P968",
    "phone": "P1329",
    "twitter": "P2002",
    "linkedin": "P6634",
    "linkedin_org": "P4264",
    "facebook": "P2013",
    "instagram": "P2003",
    "youtube": "P2397",
}


def _snak_value(claim: dict[str, Any]) -> Any:
    return ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")


def _claim_item(claim: dict[str, Any]) -> str | None:
    value = _snak_value(claim)
    return value.get("id") if isinstance(value, dict) else None


def _item_ids(entity: dict[str, Any] | None, prop: str) -> list[str]:
    return [
        i for i in (_claim_item(c) for c in ((entity or {}).get("claims") or {}).get(prop, [])) if i
    ]


def _strings(entity: dict[str, Any], prop: str) -> list[str]:
    return [
        v
        for v in (_snak_value(c) for c in (entity.get("claims") or {}).get(prop, []))
        if isinstance(v, str)
    ]


def _time(entity: dict[str, Any], prop: str) -> str | None:
    for claim in (entity.get("claims") or {}).get(prop, []):
        value = _snak_value(claim)
        if isinstance(value, dict) and value.get("time"):
            return _date(value["time"].lstrip("+"))
    return None


def _qualifier_date(claim: dict[str, Any], prop: str) -> str | None:
    for q in (claim.get("qualifiers") or {}).get(prop, []):
        value = (q.get("datavalue") or {}).get("value")
        if isinstance(value, dict) and value.get("time"):
            return _date(value["time"].lstrip("+"))
    return None


def _label(entity: dict[str, Any] | None) -> str | None:
    labels = (entity or {}).get("labels") or {}
    return (labels.get("en") or labels.get("fr") or next(iter(labels.values()), {})).get("value")


def _description(entity: dict[str, Any]) -> str | None:
    d = entity.get("descriptions") or {}
    return (d.get("en") or d.get("fr") or {}).get("value")


def _date(value: str | None) -> str | None:
    if not value or value.startswith("-"):
        return None
    value = value[:10]
    return value.replace("-00", "") if "-00" in value else value  # "1952-00-00" -> year precision


class _WikidataClient(BaseConnector):
    """Shared HTTP helpers (MediaWiki API: search + wbgetentities, cached)."""

    def _search(self, name: str, limit: int = 7) -> list[dict[str, Any]]:
        data = (
            self.http_get_json(
                SEARCH,
                params={
                    "action": "wbsearchentities",
                    "search": name,
                    "language": "en",
                    "uselang": "en",
                    "type": "item",
                    "limit": limit,
                    "format": "json",
                },
            )
            or {}
        )
        return [
            r
            for r in data.get("search", [])
            if not any(w in (r.get("description") or "").lower() for w in NOT_ENTITIES[:4])
        ]

    def _entities(
        self, ids: list[str], props: str = "labels|descriptions|claims"
    ) -> dict[str, dict[str, Any]]:
        """wbgetentities, 50 ids per call (the SPARQL endpoint refuses cloud clients)."""
        ids = [i for i in dict.fromkeys(ids) if i and i.startswith("Q")]
        out: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), 50):
            data = (
                self.http_get_json(
                    SEARCH,
                    params={
                        "action": "wbgetentities",
                        "ids": "|".join(ids[start : start + 50]),
                        "props": props,
                        "languages": "en|fr",
                        "languagefallback": "1",
                        "format": "json",
                    },
                )
                or {}
            )
            out.update(
                {k: v for k, v in (data.get("entities") or {}).items() if "missing" not in v}
            )
        return out

    def details(self, qids: list[str]) -> dict[str, dict[str, Any]]:
        items = self._entities(qids)
        # Second call: labels of positions and countries (+ ISO code of countries).
        refs = [i for e in items.values() for p in ("P39", "P27", "P17") for i in _item_ids(e, p)]
        linked = self._entities(refs, props="labels|claims")
        out: dict[str, dict[str, Any]] = {}
        for qid, e in items.items():
            positions = []
            for claim in (e.get("claims") or {}).get("P39", []):
                pos = _claim_item(claim)
                if pos:
                    positions.append(
                        (
                            _label(linked.get(pos)) or pos,
                            _qualifier_date(claim, "P580"),
                            _qualifier_date(claim, "P582"),
                        )
                    )
            countries = []
            for cid in [*_item_ids(e, "P27"), *_item_ids(e, "P17")]:
                iso = (_strings(linked.get(cid) or {}, "P297") or [None])[0]
                if iso and iso not in countries:
                    countries.append(iso)
            out[qid] = {
                "qid": qid,
                "label": _label(e) or qid,
                "description": _description(e),
                "birth": _time(e, "P569"),
                "inception": _time(e, "P571"),
                "dissolution": _time(e, "P576"),
                "countries": countries,
                "types": set(_item_ids(e, "P31")),
                "positions": positions,
                "lei": (_strings(e, "P1278") or [None])[0],
                **{key: (_strings(e, prop) or [None])[0] for key, prop in CONTACT_PROPS.items()},
            }
        return out

    def entity_from(self, d: dict[str, Any]) -> Entity:
        rid = f"wikidata:{d['qid']}"
        human = HUMAN in d["types"]
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON if human else EntityType.COMPANY,
            name=d["label"],
            birth_date=d["birth"] if human else None,
            nationalities=d["countries"] if human else [],
            jurisdiction=None if human or not d["countries"] else d["countries"][0],
            incorporation_date=None if human else d["inception"],
            status=None if human else (CompanyStatus.DISSOLVED if d["dissolution"] else None),
            dissolution_date=None if human else d["dissolution"],
            identifiers={"Wikidata": d["qid"], **({"LEI": d["lei"]} if d.get("lei") else {})},
            extra={
                k: v
                for k, v in {
                    "description": d["description"],
                    "accounts_unknown": None if human else True,
                    "positions_held": "; ".join(_fmt_position(p) for p in d["positions"][:8])
                    or None,
                }.items()
                if v
            },
            sources=[self.provenance(rid, ITEM_URL.format(qid=d["qid"]))],
        )


def _fmt_position(p: tuple[str, str | None, str | None]) -> str:
    label, start, end = p
    span = f" ({(start or '?')[:4]}–{(end or '')[:4]})" if start or end else ""
    return f"{label}{span}"


class WikidataConnector(_WikidataClient):
    name = "wikidata"
    label = "Wikidata — public figures, PEPs, relatives, corporate links, official contacts"
    kind = "registry"
    homepage = "https://www.wikidata.org"
    crossref_max_depth = 1  # SPARQL is slow: only the subject and its direct neighbours
    document_types = {"person", "company"}
    documents_max_depth = 1

    def _search_entities(self, name: str, want_human: bool) -> list[Entity]:
        found = [
            r
            for r in self._search(name)
            if name_similarity(name, r.get("label", ""), "person" if want_human else "company")[0]
            >= MIN_NAME
        ]
        details = self.details([r["id"] for r in found])
        return [
            self.entity_from(d) for d in details.values() if (HUMAN in d["types"]) == want_human
        ]

    def search_person(self, name: str, **filters: Any) -> list[Entity]:
        return self._search_entities(name, want_human=True)

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        return self._search_entities(name, want_human=False)

    def _one(self, record_id: str) -> dict[str, Any] | None:
        return self.details([self.native_id(record_id)]).get(self.native_id(record_id))

    def get_person_details(self, person_id: str) -> Entity | None:
        d = self._one(person_id)
        return self.entity_from(d) if d and HUMAN in d["types"] else None

    def get_company_details(self, company_id: str) -> Entity | None:
        d = self._one(company_id)
        return self.entity_from(d) if d and HUMAN not in d["types"] else None

    def _relations(self, qid: str, props: list[str]) -> list[tuple[str, str, str, bool]]:
        item = self._entities([qid], props="claims").get(qid) or {}
        pairs = [(p, other) for p in props for other in _item_ids(item, p)][:80]
        others = self._entities([o for _, o in pairs], props="labels|claims")
        return [
            (p, o, _label(others.get(o)) or o, HUMAN in _item_ids(others.get(o) or {}, "P31"))
            for p, o in pairs
        ]

    def _stub(self, qid: str, label: str, human: bool) -> Entity:
        rid = f"wikidata:{qid}"
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.PERSON if human else EntityType.COMPANY,
            name=label,
            identifiers={"Wikidata": qid},
            extra={} if human else {"accounts_unknown": True},
            sources=[self.provenance(rid, ITEM_URL.format(qid=qid))],
        )

    def _rel(self, kind: RelationType, src: str, tgt: str, role: str, qid: str) -> Relationship:
        return Relationship(
            id=f"{self.name}:{kind}:{src}>{tgt}:{role}",
            type=kind,
            source_id=src,
            target_id=tgt,
            role=f"{role} (Wikidata)",
            sources=[self.provenance(f"wikidata:{qid}", ITEM_URL.format(qid=qid))],
        )

    def get_person_roles(self, person_id: str) -> list[LinkedEntity]:
        qid = self.native_id(person_id)
        out = []
        for prop, other, label, human in self._relations(qid, [*RELATIVES, *PERSON_TO_ORG]):
            me = f"wikidata:{qid}"
            if prop in RELATIVES and human:
                stub = self._stub(other, label, True)
                out.append(
                    LinkedEntity(
                        relationship=self._rel(
                            RelationType.RELATIVE, me, stub.id, RELATIVES[prop], qid
                        ),
                        entity=stub,
                    )
                )
            elif prop in PERSON_TO_ORG and not human:
                kind, role = PERSON_TO_ORG[prop]
                stub = self._stub(other, label, False)
                out.append(
                    LinkedEntity(relationship=self._rel(kind, me, stub.id, role, qid), entity=stub)
                )
        return out

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        qid = self.native_id(company_id)
        out = []
        for prop, other, label, human in self._relations(qid, [*ORG_FROM, *ORG_TO]):
            me = f"wikidata:{qid}"
            if prop in ORG_FROM:
                kind, role = ORG_FROM[prop]
                if kind == RelationType.OFFICER and not human:
                    continue
                stub = self._stub(other, label, human)
                out.append(
                    LinkedEntity(relationship=self._rel(kind, stub.id, me, role, qid), entity=stub)
                )
            elif prop in ORG_TO and not human:
                kind, role = ORG_TO[prop]
                stub = self._stub(other, label, False)
                out.append(
                    LinkedEntity(relationship=self._rel(kind, me, stub.id, role, qid), entity=stub)
                )
        return out

    def get_documents(self, entity: Entity) -> list[Document]:
        qids = [r.split(":", 1)[1] for r in entity.record_ids if r.startswith("wikidata:")]
        if not qids:
            return []
        docs = []
        for qid, d in self.details(qids).items():
            human = HUMAN in d["types"]
            docs.append(
                Document(
                    title="Wikidata record",
                    kind="register",
                    url=ITEM_URL.format(qid=qid),
                    summary=d.get("description"),
                    source=self.label,
                )
            )
            for key, title, url in CONTACTS:
                value = d.get(key)
                if not value or (human and key in ("email", "phone")):
                    continue  # personal e-mail / phone numbers are never displayed, even if published
                href = value if url == "{v}" else url.format(v=value)
                docs.append(
                    Document(
                        title=title.format(v=value),
                        kind="official_profile",
                        url=href if href.startswith(("http", "mailto:", "tel:")) else None,
                        summary=value if key in ("email", "phone") else None,
                        source="Wikidata (official accounts of companies and public figures)",
                    )
                )
        return docs


class WikidataPepConnector(_WikidataClient):
    """PEP screening: every person of the network is looked up on Wikidata;
    a close namesake holding (or having held) a public position is reported."""

    name = "wikidata_pep"
    label = "Wikidata — politically exposed persons (positions held)"
    kind = "screening"
    homepage = "https://www.wikidata.org/wiki/Property:P39"

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        return self.screen_many([entity])

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        persons = [e for e in entities if e.type == EntityType.PERSON][:40]
        candidates: dict[str, list[str]] = {}
        for person in persons:
            candidates[person.id] = [
                r["id"]
                for r in self._search(person.name, limit=5)
                if name_similarity(person.name, r.get("label", ""))[0] >= MIN_NAME
            ]
        details = self.details([q for qs in candidates.values() for q in qs])
        hits = []
        for person in persons:
            for qid in candidates[person.id]:
                d = details.get(qid)
                if not d or HUMAN not in d["types"] or not d["positions"]:
                    continue
                listed = self.entity_from(d)
                result = match_entities(person, listed)
                if result.score < 45:
                    continue
                current = [p for p in d["positions"] if not p[2]]
                hits.append(
                    ScreeningHit(
                        entity_id=person.id,
                        list_type=ListType.PEP,
                        dataset="Wikidata — positions held",
                        matched_name=d["label"],
                        score=result.score,
                        explanation=result.explanation,
                        details={
                            "positions": "; ".join(_fmt_position(p) for p in d["positions"][:6]),
                            "current_positions": len(current),
                            "description": d.get("description"),
                            "birth_date": d.get("birth"),
                            "nationalities": d.get("countries") or None,
                        },
                        provenance=self.provenance(f"wikidata:{qid}", ITEM_URL.format(qid=qid)),
                    )
                )
        return hits
