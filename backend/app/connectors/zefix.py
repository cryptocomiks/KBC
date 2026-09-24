"""Zefix — Swiss central business name index (Federal Office of Justice).

Public data, no key: the JSON service behind www.zefix.admin.ch. For every
company registered in a Swiss cantonal commercial register it gives the UID,
seat, legal form, purpose, address, auditor, mergers, former names and the
full history of its publications in the Swiss Official Gazette of Commerce
(SOGC/SHAB). Officers are not exposed as structured data: they are read from
the SOGC notices ("registered persons, new or changed" / "persons and
signatures removed"), which gives appointment and departure dates.

Personal data kept to what the register publishes and the analysis needs: name,
role, nationality or place of origin. Residence is not stored.
"""

from __future__ import annotations

import contextlib
import html
import re
from datetime import date
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

API = "https://www.zefix.admin.ch/ZefixREST/api/v1"
UI = "https://www.zefix.admin.ch/en/search/entity/list/firm/{ehraid}"
MAX_NOTICES = 25
MAX_OFFICERS = 60

STATUS = {
    "EXISTIEREND": CompanyStatus.ACTIVE,
    "GELOESCHT": CompanyStatus.DISSOLVED,
    "AUFGELOEST": CompanyStatus.DISSOLVED,
}
# SOGC section headers (DE / FR / IT): persons added or changed, persons removed.
ADDED = (
    "Eingetragene Personen neu oder mutierend:",
    "Personnes inscrites nouvelles ou modifiées:",
    "Persone iscritte nuove o modificate:",
)
REMOVED = (
    "Ausgeschiedene Personen und erloschene Unterschriften:",
    "Personnes et signatures radiées:",
    "Persone dimissionarie e firme cancellate:",
)
SIGNING = ("mit ", "ohne ", "avec ", "sans ", "con ", "senza ")
INSOLVENCY = re.compile(
    r"\b(konkurs|faillite|fallimento|nachlassstundung|sursis concordataire|moratoria concordataria)",
    re.I,
)


def _clean(message: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", message or ""))
    if "Ã" in text:  # some notices are double-encoded (UTF-8 read as Latin-1)
        with contextlib.suppress(UnicodeEncodeError, UnicodeDecodeError):
            text = text.encode("latin-1").decode("utf-8")
    return re.sub(r"\s+", " ", text).strip()


def _section(text: str, headers: tuple[str, ...]) -> str | None:
    for h in headers:
        i = text.find(h)
        if i >= 0:
            rest = text[i + len(h) :]
            ends = [rest.find(x) for x in (*ADDED, *REMOVED) if rest.find(x) >= 0]
            return rest[: min(ends)] if ends else rest
    return None


def parse_people(section: str) -> list[dict[str, Any]]:
    """'Mohl, Anna, amerikanische Staatsangehörige, in Lausanne, Generaldirektorin, mit
    Einzelunterschrift; Ernst & Young SA (CHE-294.400.879), in Renens (VD), Revisionsstelle.'"""
    out = []
    for raw in re.sub(r"\[[^\]]*\]", "", section).strip().rstrip(".").split(";"):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if not parts:
            continue
        uid = re.search(r"\(?(CHE-\d{3}\.\d{3}\.\d{3})\)?", parts[0])
        rest = parts[1:]
        if uid:  # a company (auditor, corporate director)
            entry: dict[str, Any] = {
                "company": True,
                "name": parts[0][: uid.start()].strip(),
                "uid": uid.group(1),
            }
        else:
            if not rest:
                continue
            entry = {"company": False, "surname": parts[0], "first": rest[0]}
            rest = rest[1:]
        roles = [
            p
            for p in rest
            if not p.startswith(("in ", "à ", "a ", "genannt ", "dit ", "detto "))
            and not p.startswith(SIGNING)
        ]

        origin = [p for p in roles if p.startswith(("von ", "de ", "da ", "originaire"))]
        nationality = [
            p
            for p in roles
            if re.search(r"staatsangehörig|ressortissant|cittadin|national", p, re.I)
        ]
        entry["origin"] = (origin or nationality or [None])[0]
        role = [p for p in roles if p not in origin and p not in nationality]
        entry["role"] = role[0] if role else None
        out.append(entry)
    return out


# Register wording (DE / FR / IT) -> English. First match wins, so specific terms come first.
ROLES = [
    (
        ("präsident des verwaltungsrates", "président du conseil", "presidente del consiglio"),
        "Chair of the board",
    ),
    (("vizepräsident", "vice-président", "vicepresidente"), "Vice-chair of the board"),
    (
        (
            "mitglied des verwaltungsrates",
            "membre du conseil",
            "membro del consiglio",
            "administrat",
            "amministrat",
        ),
        "Board member",
    ),
    (
        (
            "generaldirektor",
            "directeur général",
            "directrice générale",
            "direttore generale",
            "ceo",
        ),
        "Chief executive",
    ),
    (("vizedirektor", "sous-directeur", "sous-directrice", "vicedirettore"), "Vice director"),
    (("stellvertretende", "directeur adjoint", "directrice adjointe"), "Deputy director"),
    (("direktor", "directeur", "directrice", "direttore", "direttrice"), "Director"),
    (("vorsitzende der geschäftsführung",), "Chair of management"),
    (("geschäftsführer", "gérant", "gerente"), "Managing director"),
    (("gesellschafter", "associé", "associée", "socio", "socia"), "Partner (quota holder)"),
    (("inhaber", "titulaire", "titolare"), "Owner"),
    (("revisionsstelle", "organe de révision", "ufficio di revisione"), "Auditor"),
    (("liquidator", "liquidateur", "liquidatrice", "liquidatore"), "Liquidator"),
    (("prokurist", "fondé de procuration", "procuratore"), "Authorised signatory (Prokura)"),
    (("präsident", "président", "presidente"), "Chair"),
    (("sekretär", "secrétaire", "segretario"), "Secretary"),
    (("aktuar",), "Secretary"),
]
PARTNER = "Partner (quota holder)"


def translate_role(role: str | None) -> str | None:
    if not role:
        return None
    low = role.lower()
    for terms, english in ROLES:
        if any(t in low for t in terms):
            return english if english.lower() == low else f"{english} ({role})"
    return role


class ZefixConnector(BaseConnector):
    name = "zefix"
    label = "Zefix — Swiss commercial register (SOGC publications)"
    kind = "registry"
    jurisdictions = {"CH"}
    crossref_max_depth = 1
    homepage = "https://www.zefix.admin.ch"
    documents_max_depth = 1

    _forms: dict[int, str] | None = None

    def _legal_form(self, form_id: int | None) -> str | None:
        if form_id is None:
            return None
        if ZefixConnector._forms is None:
            forms = self.http_get_json(f"{API}/legalForm.json") or []
            ZefixConnector._forms = {
                f["id"]: (f.get("name") or {}).get("en") or (f.get("name") or {}).get("de")
                for f in forms
                if "id" in f
            }
        return ZefixConnector._forms.get(form_id)

    def _company(self, r: dict[str, Any]) -> Entity:
        ehraid = str(r["ehraid"])
        rid = self.record_id(ehraid)
        addr = r.get("address") or {}
        address = ", ".join(
            p
            for p in (
                " ".join(x for x in (addr.get("street"), addr.get("houseNumber")) if x),
                " ".join(x for x in (addr.get("swissZipCode"), addr.get("town")) if x),
            )
            if p
        ) or r.get("legalSeat")
        extra: dict[str, Any] = {"accounts_unknown": True, "seat": r.get("legalSeat")}
        if r.get("cantonalExcerptWeb"):
            extra["cantonal_excerpt"] = r["cantonalExcerptWeb"]
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=r.get("name") or ehraid,
            aliases=[a for a in (r.get("translation") or []) if a and a != r.get("name")][:4]
            + [
                o.get("name")
                for o in (r.get("oldNames") or [])
                if isinstance(o, dict) and o.get("name")
            ][:4],
            jurisdiction="CH",
            registration_number=r.get("uidFormatted"),
            legal_form=self._legal_form(r.get("legalFormId")),
            status=STATUS.get(r.get("status") or "", CompanyStatus.UNKNOWN),
            dissolution_date=parse_date(r.get("deleteDate")),
            activity=(r.get("purpose") or "")[:300] or None,
            address=address,
            identifiers={
                k: v
                for k, v in {"UID": r.get("uidFormatted"), "CH-ID": r.get("chidFormatted")}.items()
                if v
            },
            sources=[self.provenance(rid, UI.format(ehraid=ehraid))],
            extra=extra,
        )

    def _firm(self, company_id: str) -> dict[str, Any] | None:
        return self.http_get_json(f"{API}/firm/{self.native_id(company_id)}.json")

    # --------------------------------------------------------- interface
    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = self.http_post_json(
            f"{API}/firm/search.json",
            json_body={
                "name": name,
                "languageKey": "en",
                "maxEntries": 10,
                "offset": 0,
                "searchType": "exact",
                "deletedFirms": True,
            },
        )
        return [self._company(r) for r in (data or {}).get("list", []) if r.get("ehraid")]

    def get_company_details(self, company_id: str) -> Entity | None:
        r = self._firm(company_id)
        return self._company(r) if r and r.get("ehraid") else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        r = self._firm(company_id)
        if not r:
            return []
        me = self.record_id(str(r["ehraid"]))
        url = UI.format(ehraid=r["ehraid"])
        people: dict[str, dict[str, Any]] = {}
        # Oldest publication first: the last event wins (appointed, then possibly removed).
        for pub in sorted(r.get("shabPub") or [], key=lambda p: p.get("shabDate") or ""):
            text = _clean(pub.get("message", ""))
            when = parse_date(pub.get("shabDate"))
            for headers, removed in ((ADDED, False), (REMOVED, True)):
                section = _section(text, headers)
                for p in parse_people(section) if section else []:
                    key = p.get("uid") or f"{p['surname']}|{p['first']}|{p.get('origin') or ''}"
                    cur = people.setdefault(key, {**p, "start": None, "end": None})
                    if removed:
                        cur["end"] = when
                    else:
                        cur.update({k: v for k, v in p.items() if v})
                        cur["start"] = cur["start"] or when
                        cur["end"] = None
        for audit in r.get("auditFirms") or []:
            people.setdefault(
                audit.get("uidFormatted") or audit.get("name"),
                {
                    "company": True,
                    "name": audit.get("name"),
                    "uid": audit.get("uidFormatted"),
                    "role": "Auditor",
                    "ehraid": audit.get("ehraid"),
                    "start": None,
                    "end": None,
                },
            )

        out = []
        active_first = sorted(
            people.values(),
            key=lambda p: (p["end"] is not None, -(p["start"] or date.min).toordinal()),
        )
        for p in active_first[:MAX_OFFICERS]:
            if p.get("company"):
                oid = (
                    self.record_id(str(p["ehraid"]))
                    if p.get("ehraid")
                    else self.record_id(f"uid:{p['uid']}")
                )
                other = Entity(
                    id=oid,
                    record_ids=[oid],
                    type=EntityType.COMPANY,
                    name=p.get("name") or p.get("uid"),
                    jurisdiction="CH",
                    registration_number=p.get("uid"),
                    identifiers={"UID": p["uid"]} if p.get("uid") else {},
                    sources=[self.provenance(oid, url)],
                    extra={"accounts_unknown": True},
                )
            else:
                oid = self.record_id(f"p:{p['surname']}|{p['first']}|{p.get('origin') or ''}")
                other = Entity(
                    id=oid,
                    record_ids=[oid],
                    type=EntityType.PERSON,
                    name=f"{p['first']} {p['surname']}",
                    sources=[self.provenance(oid, url)],
                    extra={"origin_or_nationality": p["origin"]} if p.get("origin") else {},
                )
            out.append(
                LinkedEntity(
                    relationship=Relationship(
                        id=f"{self.name}:officer:{oid}>{me}:{p.get('role')}",
                        type=RelationType.SHAREHOLDER
                        if (translate_role(p.get("role")) or "").startswith(PARTNER)
                        else RelationType.OFFICER,
                        source_id=oid,
                        target_id=me,
                        role=translate_role(p.get("role")) or "Registered person",
                        start_date=p["start"],
                        end_date=p["end"],
                        sources=[self.provenance(me, url)],
                    ),
                    entity=other,
                )
            )
        return out

    def get_documents(self, entity: Entity) -> list[Document]:
        rid = next(
            (
                r
                for r in entity.record_ids
                if r.startswith(f"{self.name}:") and ":p:" not in r and ":uid:" not in r
            ),
            None,
        )
        if entity.type != EntityType.COMPANY or rid is None:
            return []
        r = self._firm(rid) or {}
        url = UI.format(ehraid=r.get("ehraid", self.native_id(rid)))
        docs = []
        for pub in sorted(
            r.get("shabPub") or [], key=lambda p: p.get("shabDate") or "", reverse=True
        )[:MAX_NOTICES]:
            text = _clean(pub.get("message", ""))
            kinds = ", ".join(m.get("key", "") for m in pub.get("mutationTypes") or [])
            docs.append(
                Document(
                    title=f"SOGC publication{f' ({kinds})' if kinds else ''}",
                    kind="legal_notice",
                    date=parse_date(pub.get("shabDate")),
                    url=url,
                    summary=text[:500],
                    source=self.label,
                    flags=["insolvency"] if INSOLVENCY.search(text) else [],
                )
            )
        if r.get("cantonalExcerptWeb"):
            docs.append(
                Document(
                    title="Certified cantonal register excerpt",
                    kind="register",
                    url=r["cantonalExcerptWeb"],
                    source=self.label,
                )
            )
        for key, label in (
            ("hasTakenOver", "Has taken over"),
            ("wasTakenOverBy", "Was taken over by"),
        ):
            for other in r.get(key) or []:
                if isinstance(other, dict) and other.get("name"):
                    docs.append(
                        Document(
                            title=f"{label}: {other['name']} ({other.get('uidFormatted', '')})",
                            kind="legal_notice",
                            url=UI.format(ehraid=other["ehraid"]) if other.get("ehraid") else url,
                            source=self.label,
                        )
                    )
        return docs
