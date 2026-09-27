"""More free registers and enforcement sources (no key).

* RPO — Slovak register of legal entities (Statistical Office): all legal entities,
  statutory bodies and partners with their stakes.
* EGRUL — Russian Unified State Register of Legal Entities (Federal Tax Service): legal
  entities only (individual entrepreneurs are private persons and are skipped), director,
  INN / OGRN, registration and liquidation dates. Searched by name (Latin names are
  transliterated to Cyrillic) or by OGRN / INN.
* BrasilAPI — Brazilian company by CNPJ (Receita Federal open data): partners and
  directors (QSA), legal nature, capital, registration status.
* FINRA BrokerCheck — US broker-dealers and investment advisers: registration status
  and disclosures (regulatory events, arbitrations, civil and criminal matters).
* CourtListener RECAP — US federal court dockets (lawsuits), where the entity is a party.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime
from typing import Any

from unidecode import unidecode

from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.free_sources import _day, core_name
from app.connectors.public_figures import may_query
from app.matching.names import name_similarity
from app.models import (
    CompanyStatus,
    Document,
    Entity,
    EntityType,
    LinkedEntity,
    Relationship,
    RelationType,
)
from app.relevance import named_in

log = logging.getLogger(__name__)


def _mdy(value: str | None) -> date | None:
    try:
        return datetime.strptime((value or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _dmy(value: str | None) -> date | None:
    try:
        return datetime.strptime((value or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


# ------------------------------------------------------------------ RPO (Slovakia)
RPO = "https://api.statistics.sk/rpo/v1"
RPO_UI = "https://rpo.statistics.sk/rpo/#/detail/{id}"


def _current(items: list[dict[str, Any]] | None, key: str = "value") -> Any:
    """The entry without an end date (else the latest one) of an RPO history list."""
    rows = [i for i in items or [] if isinstance(i, dict)]
    live = [i for i in rows if not i.get("validTo")] or rows
    return live[-1].get(key) if live else None


def _rpo_address(a: dict[str, Any] | None) -> str | None:
    if not a:
        return None
    street = " ".join(str(x) for x in (a.get("street"), a.get("buildingNumber")) if x)
    town = " ".join(
        str(x)
        for x in ((a.get("postalCodes") or [None])[0], (a.get("municipality") or {}).get("value"))
        if x
    )
    return ", ".join(x for x in (street, town) if x) or None


class RpoConnector(BaseConnector):
    name = "sk_rpo"
    label = "RPO — Slovak register of legal entities (Statistical Office)"
    kind = "registry"
    homepage = "https://rpo.statistics.sk"
    jurisdictions = {"SK"}
    max_retries = 1
    timeout_seconds = 30.0  # the detail sheet of large companies can take 15-30 s

    def _entity(self, r: dict[str, Any]) -> Entity:
        rid = self.record_id(str(r["id"]))
        ico = _current(r.get("identifiers"))
        term = r.get("termination") or r.get("terminationDate")
        legal_form = _current(r.get("legalForms"))
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=_current(r.get("fullNames")) or str(r["id"]),
            aliases=[n["value"] for n in r.get("fullNames") or [] if n.get("validTo")][:4],
            jurisdiction="SK",
            registration_number=ico,
            legal_form=(legal_form or {}).get("value") if isinstance(legal_form, dict) else None,
            status=CompanyStatus.DISSOLVED if term else CompanyStatus.ACTIVE,
            incorporation_date=r.get("establishment"),
            address=_rpo_address(
                next((a for a in reversed(r.get("addresses") or []) if not a.get("validTo")), None)
            ),
            identifiers={"IČO": ico} if ico else {},
            sources=[self.provenance(rid, RPO_UI.format(id=r["id"]))],
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        data = self.http_get_json(
            f"{RPO}/search", params={"fullName": core_name(name)[:80], "onlyActive": "true"}
        )
        out = [
            self._entity(r)
            for r in (data or {}).get("results") or []
            if isinstance(r, dict) and r.get("id")
        ]
        return [e for e in out if name_similarity(name, e.name, "company")[0] >= 80][:8]

    def _detail(self, company_id: str) -> dict[str, Any] | None:
        data = self.http_get_json(
            f"{RPO}/entity/{self.native_id(company_id)}",
            params={"showHistoricalData": "false", "showOrganizationUnits": "false"},
        )
        return data if isinstance(data, dict) and data.get("id") else None

    def get_company_details(self, company_id: str) -> Entity | None:
        d = self._detail(company_id)
        return self._entity(d) if d else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        d = self._detail(company_id)
        if not d:
            return []
        me = self.record_id(str(d["id"]))
        url = RPO_UI.format(id=d["id"])
        stakes = {}
        for dep in d.get("deposits") or []:
            n = (
                (dep.get("personName") or {}).get("formatedName") or dep.get("fullName") or ""
            ).strip()
            if n:
                stakes[n] = dep.get("amount")
        out = []
        for group, rel_type in (
            ("statutoryBodies", RelationType.OFFICER),
            ("stakeholders", RelationType.SHAREHOLDER),
        ):
            for p in d.get(group) or []:
                if p.get("validTo"):
                    continue
                person = (p.get("personName") or {}).get("formatedName")
                company = p.get("fullName")
                name = (person or company or "").strip()
                if not name:
                    continue
                role = ((p.get("stakeholderType") or {}).get("value") or "").strip() or (
                    "Statutory body" if rel_type == RelationType.OFFICER else "Partner"
                )
                oid = self.record_id(f"{'p' if person else 'c'}:{name}")
                other = Entity(
                    id=oid,
                    record_ids=[oid],
                    type=EntityType.PERSON if person else EntityType.COMPANY,
                    name=name,
                    sources=[self.provenance(oid, url)],
                )
                if stakes.get(name):
                    role += f" — deposit EUR {stakes[name]}"
                out.append(
                    LinkedEntity(
                        relationship=Relationship(
                            id=f"{self.name}:{group}:{oid}>{me}",
                            type=rel_type,
                            source_id=oid,
                            target_id=me,
                            role=role,
                            start_date=p.get("validFrom"),
                            sources=[self.provenance(me, url)],
                        ),
                        entity=other,
                    )
                )
        return out


# ------------------------------------------------------------------ EGRUL (Russia)
EGRUL = "https://egrul.nalog.ru"
EGRUL_POLLS = 4  # the search result is prepared asynchronously
EGRUL_POLL_SECONDS = 0.8
_LAT_CYR = [
    ("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"),
    ("sh", "ш"), ("yu", "ю"), ("ya", "я"), ("yo", "ё"), ("ye", "е"), ("a", "а"), ("b", "б"),
    ("v", "в"), ("g", "г"), ("d", "д"), ("e", "е"), ("z", "з"), ("i", "и"), ("y", "ы"),
    ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"),
    ("s", "с"), ("t", "т"), ("u", "у"), ("f", "ф"), ("h", "х"), ("c", "к"), ("w", "в"),
    ("x", "кс"), ("j", "й"), ("q", "к"),
]  # fmt: skip
RU_LEGAL = re.compile(
    r"\b(pjsc|ojsc|cjsc|jsc|pao|oao|zao|ao|llc|ooo|ltd|limited|company|public joint stock|joint stock)\b",
    re.I,
)
RU_ROLES = {
    "ГЕНЕРАЛЬНЫЙ ДИРЕКТОР": "General director",
    "ПРЕДСЕДАТЕЛЬ ПРАВЛЕНИЯ": "Chairman of the management board",
    "ДИРЕКТОР": "Director",
    "ПРЕЗИДЕНТ": "President",
    "УПРАВЛЯЮЩИЙ": "Managing director",
    "ЛИКВИДАТОР": "Liquidator",
    "КОНКУРСНЫЙ УПРАВЛЯЮЩИЙ": "Bankruptcy administrator",
}


def to_cyrillic(latin: str) -> str:
    """Rough Latin -> Cyrillic transliteration of a Russian company name, for the search."""
    s = RU_LEGAL.sub(" ", latin.lower())
    s = re.sub(r"[^a-z0-9 \-]", " ", s)
    out = []
    i = 0
    while i < len(s):
        for lat, cyr in _LAT_CYR:
            if s.startswith(lat, i):
                out.append(cyr)
                i += len(lat)
                break
        else:
            out.append(s[i])
            i += 1
    return " ".join("".join(out).split())


class EgrulConnector(BaseConnector):
    name = "ru_egrul"
    label = "EGRUL — Russian register of legal entities (Federal Tax Service)"
    kind = "registry"
    homepage = EGRUL
    jurisdictions = {"RU"}
    max_retries = 0
    min_interval_seconds = 1.0
    crossref_max_depth = 1
    timeout_seconds = 10.0

    def _search(self, query: str) -> list[dict[str, Any]]:
        # The token and the result it points to expire: never cached.
        token = self.http_post_json(
            f"{EGRUL}/",
            form={"query": query, "region": "", "PreventChromeAutocomplete": ""},
            cache=False,
        )
        if not isinstance(token, dict) or not token.get("t"):
            if isinstance(token, dict) and token.get("captchaRequired"):
                raise ConnectorError(f"{self.label}: captcha requested, try later")
            return []
        # The result is prepared asynchronously: {"status": "wait"} until it is ready.
        data: Any = None
        for attempt in range(EGRUL_POLLS):
            data = self.http_get_json(f"{EGRUL}/search-result/{token['t']}", cache=False)
            if not (isinstance(data, dict) and data.get("status") == "wait"):
                break
            if attempt < EGRUL_POLLS - 1:
                time.sleep(EGRUL_POLL_SECONDS)
        else:
            raise ConnectorError(f"{self.label}: search result not ready, try later")
        rows = (data or {}).get("rows") if isinstance(data, dict) else None
        # legal entities only: "fl" rows are individual entrepreneurs (private persons)
        return [r for r in rows or [] if isinstance(r, dict) and r.get("k") == "ul"]

    def _entity(self, r: dict[str, Any]) -> Entity:
        ogrn = r.get("o") or ""
        rid = self.record_id(ogrn or r.get("i") or r.get("n", ""))
        full, short = r.get("n") or "", r.get("c") or ""
        liquidated = _dmy(r.get("e"))
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=unidecode(short or full).replace("'", "").strip(),
            aliases=[x for x in {full, short, unidecode(full)} if x][:4],
            jurisdiction="RU",
            registration_number=ogrn or None,
            status=CompanyStatus.DISSOLVED if liquidated else CompanyStatus.ACTIVE,
            incorporation_date=_dmy(r.get("r")),
            dissolution_date=liquidated,
            address=r.get("a") or r.get("rn"),
            identifiers={
                k: v for k, v in {"OGRN": ogrn, "INN": r.get("i"), "KPP": r.get("p")}.items() if v
            },
            sources=[self.provenance(rid, EGRUL)],
            extra={"egrul_director": r.get("g")} if r.get("g") else {},
        )

    def search_company(self, name: str, **filters: Any) -> list[Entity]:
        queries = [name] if re.search(r"[а-яА-Я]", name) else [to_cyrillic(name), name]
        scored: dict[str, tuple[float, Entity]] = {}
        for q in queries:
            if len(q) < 3:
                continue
            for r in self._search(q)[:10]:
                e = self._entity(r)
                score = max(name_similarity(name, a, "company")[0] for a in [e.name, *e.aliases])
                if score >= 88:
                    scored.setdefault(e.id, (score, e))
            if scored:
                break
        # best match first: "Gazprom Neft" before a small "OOO Neft"
        return [e for _, e in sorted(scored.values(), key=lambda x: -x[0])][:6]

    def get_by_identifier(self, ident: Any) -> Entity | None:
        if ident.kind not in ("ru_ogrn", "ru_inn"):
            return None
        rows = self._search(ident.value)
        return self._entity(rows[0]) if rows else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        """The director published in the search record ("TITLE: Surname Name Patronymic")."""
        native = self.native_id(company_id)
        rows = self._search(native)
        if not rows or ":" not in (rows[0].get("g") or ""):
            return []
        title, person = (x.strip() for x in rows[0]["g"].split(":", 1))
        role = RU_ROLES.get(title.upper(), title.capitalize())
        me = self.record_id(native)
        oid = self.record_id(f"p:{person}")
        parts = person.split()
        latin = unidecode(" ".join(parts[1:] + parts[:1]) if len(parts) >= 2 else person).replace(
            "'", ""
        )
        return [
            LinkedEntity(
                relationship=Relationship(
                    id=f"{self.name}:dir:{oid}>{me}",
                    type=RelationType.OFFICER,
                    source_id=oid,
                    target_id=me,
                    role=f"{role} (EGRUL)",
                    sources=[self.provenance(me, EGRUL)],
                ),
                entity=Entity(
                    id=oid,
                    record_ids=[oid],
                    type=EntityType.PERSON,
                    name=latin,
                    aliases=[person],
                    nationalities=["RU"],
                    sources=[self.provenance(oid, EGRUL)],
                ),
            )
        ]


# ---------------------------------------------------------------- BrasilAPI (CNPJ)
BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
CNPJ_UI = (
    "https://solucoes.receita.fazenda.gov.br/Servicos/cnpjreva/Cnpjreva_Solicitacao.asp?cnpj={cnpj}"
)
BR_STATUS = {
    "2": CompanyStatus.ACTIVE,
    "3": CompanyStatus.UNKNOWN,
    "4": CompanyStatus.DISSOLVED,
    "8": CompanyStatus.DISSOLVED,
}
BR_ROLES = {
    "Diretor": "Director",
    "Presidente": "President",
    "Administrador": "Director (administrador)",
    "Conselheiro de Administração": "Board member",
    "Sócio-Administrador": "Managing partner",
    "Sócio": "Partner",
    "Procurador": "Attorney-in-fact",
}


class BrasilApiConnector(BaseConnector):
    name = "br_cnpj"
    label = "Receita Federal — Brazilian companies by CNPJ (via BrasilAPI)"
    kind = "registry"
    homepage = "https://brasilapi.com.br"
    jurisdictions = {"BR"}
    max_retries = 1

    def _get(self, cnpj: str) -> dict[str, Any] | None:
        data = self.http_get_json(BRASILAPI.format(cnpj=re.sub(r"\D", "", cnpj)))
        return data if isinstance(data, dict) and data.get("cnpj") else None

    def _entity(self, d: dict[str, Any]) -> Entity:
        cnpj = d["cnpj"]
        rid = self.record_id(cnpj)
        fmt = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
        street = " ".join(
            str(x)
            for x in (d.get("descricao_tipo_de_logradouro"), d.get("logradouro"), d.get("numero"))
            if x
        )
        return Entity(
            id=rid,
            record_ids=[rid],
            type=EntityType.COMPANY,
            name=d.get("razao_social") or fmt,
            aliases=[d["nome_fantasia"]] if d.get("nome_fantasia") else [],
            jurisdiction="BR",
            registration_number=fmt,
            legal_form=d.get("natureza_juridica"),
            status=BR_STATUS.get(str(d.get("situacao_cadastral")), CompanyStatus.UNKNOWN),
            incorporation_date=d.get("data_inicio_atividade"),
            activity=d.get("cnae_fiscal_descricao"),
            address=", ".join(
                x for x in (street, d.get("bairro"), d.get("municipio"), d.get("uf")) if x
            )
            or None,
            identifiers={"CNPJ": fmt},
            sources=[self.provenance(rid, CNPJ_UI.format(cnpj=cnpj))],
            extra={
                k: v
                for k, v in {"capital_brl": d.get("capital_social"), "size": d.get("porte")}.items()
                if v
            },
        )

    def get_by_identifier(self, ident: Any) -> Entity | None:
        if ident.kind != "br_cnpj":
            return None
        d = self._get(ident.value)
        return self._entity(d) if d else None

    def get_company_details(self, company_id: str) -> Entity | None:
        d = self._get(self.native_id(company_id))
        return self._entity(d) if d else None

    def get_officers(self, company_id: str) -> list[LinkedEntity]:
        d = self._get(self.native_id(company_id))
        if not d:
            return []
        me = self.record_id(d["cnpj"])
        url = CNPJ_UI.format(cnpj=d["cnpj"])
        out = []
        for p in d.get("qsa") or []:
            name = (p.get("nome_socio") or "").strip()
            if not name:
                continue
            is_company = len(re.sub(r"\D", "", p.get("cnpj_cpf_do_socio") or "")) == 14
            q = (p.get("qualificacao_socio") or "").strip()
            role = BR_ROLES.get(q, q or "Partner / director")
            oid = self.record_id(f"{'c' if is_company else 'p'}:{name}")
            partner = "Sócio" in q
            out.append(
                LinkedEntity(
                    relationship=Relationship(
                        id=f"{self.name}:qsa:{oid}>{me}",
                        type=RelationType.SHAREHOLDER if partner else RelationType.OFFICER,
                        source_id=oid,
                        target_id=me,
                        role=role,
                        start_date=p.get("data_entrada_sociedade"),
                        sources=[self.provenance(me, url)],
                    ),
                    entity=Entity(
                        id=oid,
                        record_ids=[oid],
                        type=EntityType.COMPANY if is_company else EntityType.PERSON,
                        name=name.title(),
                        sources=[self.provenance(oid, url)],
                        extra={"age_band": p["faixa_etaria"]}
                        if p.get("faixa_etaria") and not is_company
                        else {},
                    ),
                )
            )
        return out


# ------------------------------------------------------------- FINRA BrokerCheck (US)
BROKERCHECK = "https://api.brokercheck.finra.org/search/firm"
BROKERCHECK_UI = "https://brokercheck.finra.org/firm/summary/{id}"


class BrokerCheckConnector(BaseConnector):
    name = "finra_brokercheck"
    label = (
        "FINRA BrokerCheck — US broker-dealers and investment advisers (registration, disclosures)"
    )
    kind = "documents"
    homepage = "https://brokercheck.finra.org"
    document_types = {"company"}
    documents_max_depth = 1
    max_retries = 1

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY or (entity.jurisdiction or "US") != "US":
            return []
        data = self.http_get_json(
            BROKERCHECK,
            params={
                "query": entity.name[:80],
                "hl": "true",
                "nrows": 5,
                "start": 0,
                "r": 25,
                "wt": "json",
            },
        )
        docs = []
        for h in ((data or {}).get("hits") or {}).get("hits") or []:
            src = h.get("_source") or {}
            name = src.get("firm_name") or ""
            if name_similarity(entity.name, name, "company")[0] < 90:
                continue
            fid = src.get("firm_source_id")
            detail = self.http_get_json(
                f"{BROKERCHECK}/{fid}",
                params={"hl": "true", "nrows": 12, "query": "", "r": 25, "wt": "json"},
            )
            content: dict[str, Any] = {}
            try:
                raw = (
                    (((detail or {}).get("hits") or {}).get("hits") or [{}])[0]
                    .get("_source", {})
                    .get("content")
                )
                content = json.loads(raw) if raw else {}
            except (ValueError, IndexError, AttributeError):
                content = {}
            basic = content.get("basicInformation") or {}
            disclosures = [d for d in content.get("disclosures") or [] if d.get("disclosureCount")]
            parts = [
                f"status {basic.get('firmStatus') or src.get('firm_scope', '').lower()}",
                f"regulator {basic['regulator']}" if basic.get("regulator") else "",
                f"SEC {src['firm_bd_full_sec_number']}"
                if src.get("firm_bd_full_sec_number")
                else "",
                "disclosures: "
                + ", ".join(f"{d['disclosureType']} ×{d['disclosureCount']}" for d in disclosures)
                if disclosures
                else "no disclosure",
            ]
            serious = any(
                d["disclosureType"] in ("Regulatory Event", "Criminal", "Civil Event")
                for d in disclosures
            )
            docs.append(
                Document(
                    title=f"FINRA BrokerCheck — {name} (CRD {fid})",
                    kind="register",
                    date=_mdy(basic.get("finraLastApprovalDate")),
                    url=BROKERCHECK_UI.format(id=fid),
                    summary=" · ".join(p for p in parts if p),
                    source=self.label,
                    flags=["register_warning"] if serious else [],
                )
            )
        return docs[:2]


# ------------------------------------------------------- CourtListener RECAP (dockets)
RECAP = "https://www.courtlistener.com/api/rest/v4/search/"


class RecapDocketsConnector(BaseConnector):
    name = "recap_dockets"
    label = "US federal court dockets — CourtListener RECAP (lawsuits, PACER)"
    kind = "documents"
    homepage = "https://www.courtlistener.com/recap/"
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 0
    timeout_seconds = 15.0
    min_interval_seconds = 1.0  # shared anonymous quota with the opinions search

    def get_documents(self, entity: Entity) -> list[Document]:
        if not may_query(entity):
            return []
        name = entity.name.replace('"', " ").strip()
        data = self.http_get_json(
            RECAP, params={"q": f'caseName:"{name}"', "type": "r", "order_by": "dateFiled desc"}
        )
        docs = []
        for r in ((data or {}).get("results") or [])[:10] if isinstance(data, dict) else []:
            case = (r.get("caseName") or "").strip()
            if not case or not named_in(entity, case):
                continue  # parties only: the search is on the case name
            path = r.get("docket_absolute_url") or ""
            docs.append(
                Document(
                    title=case,
                    kind="court",
                    date=_day(r.get("dateFiled")),
                    url=f"https://www.courtlistener.com{path}" if path else None,
                    summary=" · ".join(
                        x
                        for x in (
                            r.get("court"),
                            r.get("docketNumber"),
                            r.get("suitNature") or r.get("cause"),
                            "closed " + r["dateTerminated"] if r.get("dateTerminated") else "open",
                        )
                        if x
                    ),
                    source=self.label,
                    flags=["court"],
                )
            )
        return docs
