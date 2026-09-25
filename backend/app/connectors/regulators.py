"""Financial regulators' registers: is the company authorised, by whom, since when?

* ESMA registers (EU/EEA): investment firms and their national supervisor
  (Solr service behind registers.esma.europa.eu), searched by LEI or by name.
* REGAFI (ACPR, France): credit institutions, payment and e-money institutions,
  passported branches, and the insurance register — open data (Opendatasoft).

Each authorisation found becomes a document of the company, flagged
``regulated`` (or ``authorisation_withdrawn``). Companies only.
"""

from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz
from unidecode import unidecode

from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.util import parse_date
from app.models import Document, Entity, EntityType

ESMA = "https://registers.esma.europa.eu/solr/esma_registers_upreg/select"
ESMA_UI = "https://registers.esma.europa.eu/publication/searchRegister?core=esma_registers_upreg"
REGAFI = "https://www.regafi.fr/api/explore/v2.1/catalog/datasets/{ds}/records"
REGAFI_UI = "https://www.regafi.fr"
NAME_MATCH = 92
LEGAL_FORMS = re.compile(
    r"\b(sa|sas|sarl|ag|gmbh|ltd|limited|plc|uab|bv|nv|spa|srl|as|ab|oy|oyj|se|inc|llc|s\.?a\.?|s\.?à r\.?l\.?)\b\.?",
    re.I,
)


def _norm(name: str) -> str:
    text = unidecode(name or "").lower()
    text = LEGAL_FORMS.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _same_name(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    return bool(na and nb) and (na == nb or fuzz.token_sort_ratio(na, nb) >= NAME_MATCH)


def _solr_phrase(text: str) -> str:
    return '"' + re.sub(r'(["\\])', r"\\\1", text) + '"'


class RegulatorsConnector(BaseConnector):
    name = "regulators"
    label = "Financial regulators — ESMA registers (EU/EEA) and REGAFI (ACPR, France)"
    kind = "documents"
    homepage = "https://registers.esma.europa.eu"
    document_types = {"company"}
    documents_max_depth = 2
    max_retries = 1
    timeout_seconds = 15.0

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY or len(_norm(entity.name)) < 3:
            return []
        docs: list[Document] = []
        for source in (self._esma, self._regafi):
            try:
                docs += source(entity)
            except ConnectorError:
                continue  # one register down never hides the other
        return docs

    # ------------------------------------------------------------ ESMA
    def _esma(self, entity: Entity) -> list[Document]:
        lei = entity.identifiers.get("LEI")
        query = (
            f"ae_lei:{_solr_phrase(lei)}" if lei else f"ae_entityName:{_solr_phrase(entity.name)}"
        )
        data: Any = self.http_get_json(
            ESMA, params={"q": query, "fq": "type_s:parent", "rows": 10, "wt": "json"}
        )
        out = []
        for doc in ((data or {}).get("response") or {}).get("docs", []):
            if not lei and not _same_name(entity.name, doc.get("ae_entityName", "")):
                continue
            status = doc.get("ae_status") or "?"
            withdrawn = status.lower() != "active" or bool(
                doc.get("ae_authorisationWithdrawalEndDateStr")
            )
            since = parse_date((doc.get("ae_authorisationNotificationDate") or "")[:10])
            out.append(
                Document(
                    title=f"{doc.get('ae_entityTypeLabel') or 'Authorised entity'} — "
                    f"{doc.get('ae_competentAuthority') or 'national supervisor'} ({status.lower()})",
                    kind="authorisation",
                    date=since,
                    url=ESMA_UI,
                    summary=" · ".join(
                        p
                        for p in (
                            doc.get("ae_entityName"),
                            doc.get("ae_officeType"),
                            doc.get("ae_homeMemberState", "").title() or None,
                            f"LEI {doc['ae_lei']}" if doc.get("ae_lei") else None,
                            doc.get("ae_headOfficeAddress") or None,
                        )
                        if p
                    ),
                    source="ESMA register of investment firms (MiFID) — national competent authorities",
                    flags=["authorisation_withdrawn"] if withdrawn else ["regulated"],
                )
            )
        return out

    # ----------------------------------------------------------- REGAFI
    def _regafi(self, entity: Entity) -> list[Document]:
        siren = entity.identifiers.get("SIREN") or (
            entity.registration_number
            if (entity.jurisdiction or "").upper() == "FR"
            and re.fullmatch(r"\d{9}", entity.registration_number or "")
            else None
        )
        lei = entity.identifiers.get("LEI")
        out = []
        for ds, sector in (
            ("prd-banque-entites", "banking"),
            ("prd-assurance-entites", "insurance"),
        ):
            where = f'search("{entity.name.replace(chr(34), " ")}")'
            data: Any = self.http_get_json(
                REGAFI.format(ds=ds), params={"where": where, "limit": 10}
            )
            for row in (data or {}).get("results", []):
                same_id = (siren and str(row.get("siren") or "") == siren) or (
                    lei and row.get("lei") == lei
                )
                if not same_id and not _same_name(entity.name, row.get("denomination") or ""):
                    continue
                category = row.get("categorie")
                category = ", ".join(category) if isinstance(category, list) else category
                withdrawn = (
                    bool(row.get("liquidation")) or row.get("approval_withdrawal_process") == "True"
                )
                authority = row.get("libelle_autorite_surveillance") or "ACPR (Banque de France)"
                out.append(
                    Document(
                        title=f"{category or row.get('type_entite') or 'Regulated entity'} — {authority}",
                        kind="authorisation",
                        date=parse_date(row.get("date_creation")),
                        url=REGAFI_UI,
                        summary=" · ".join(
                            str(p)
                            for p in (
                                row.get("denomination"),
                                row.get("type_entite"),
                                row.get("modalite_exercice"),
                                f"parent: {row['denomination_entite_parente']} ({row.get('pays_entite_parente') or '?'})"
                                if row.get("denomination_entite_parente")
                                else None,
                                f"SIREN {row['siren']}" if row.get("siren") else None,
                                f"LEI {row['lei']}" if row.get("lei") else None,
                                row.get("ville"),
                            )
                            if p
                        ),
                        source=f"REGAFI — ACPR register of authorised {sector} entities (France)",
                        flags=["authorisation_withdrawn"] if withdrawn else ["regulated"],
                    )
                )
        return out
