"""BODACC — French official bulletin of civil and commercial announcements.

Open data, no key: https://bodacc-datadila.opendatasoft.com (DILA).
Every legal event of a French company is published there: registration,
changes (officers, address, capital), filing of annual accounts, collective
insolvency proceedings (safeguard, receivership, liquidation) and
deregistration. Each announcement becomes a linked document; insolvency
proceedings also raise a red flag.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.util import parse_date
from app.models import Document, Entity, EntityType

API = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
MAX_NOTICES = 30

FAMILY_KIND = {
    "dépôts des comptes": "accounts",
    "procédures collectives": "insolvency",
    "procédures de conciliation": "insolvency",
    "procédures de rétablissement professionnel": "insolvency",
    "immatriculations": "legal_notice",
    "créations": "legal_notice",
    "modifications diverses": "legal_notice",
    "ventes et cessions": "legal_notice",
    "radiations": "deregistration",
}


def _siren(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}


class BodaccConnector(BaseConnector):
    name = "bodacc"
    label = "BODACC — French legal announcements (DILA)"
    kind = "documents"
    jurisdictions = {"FR"}
    homepage = "https://www.bodacc.fr"

    def get_documents(self, entity: Entity) -> list[Document]:
        siren = _siren(entity.registration_number)
        if (
            entity.type != EntityType.COMPANY
            or len(siren) != 9
            or not self.covers(entity.jurisdiction)
        ):
            return []
        data = (
            self.http_get_json(
                API,
                params={
                    "where": f'"{siren}"',
                    "order_by": "dateparution desc",
                    "limit": MAX_NOTICES,
                },
            )
            or {}
        )
        docs = []
        for r in data.get("results", []):
            registre = r.get("registre") or []
            if isinstance(registre, str):
                registre = [registre]
            if siren not in {_siren(x) for x in registre}:
                continue  # full-text hit on another company
            family = (r.get("familleavis_lib") or r.get("familleavis") or "Announcement").strip()
            kind = FAMILY_KIND.get(family.lower(), "legal_notice")
            summary = self._summary(r, kind)
            docs.append(
                Document(
                    title=f"BODACC — {family}"
                    + (f" ({r['typeavis_lib']})" if r.get("typeavis_lib") else ""),
                    kind="legal_notice" if kind == "deregistration" else kind,
                    date=parse_date(r.get("dateparution")),
                    url=r.get("url_complete")
                    or f"https://www.bodacc.fr/pages/annonces-commerciales-detail/?q.id=id:{r.get('id')}",
                    summary=summary,
                    source=self.label,
                    flags=["insolvency"]
                    if kind == "insolvency"
                    else ["deregistration"]
                    if kind == "deregistration"
                    else [],
                )
            )
        return docs

    @staticmethod
    def _summary(r: dict[str, Any], kind: str) -> str | None:
        parts = []
        if kind == "insolvency":
            jugement = _loads(r.get("jugement"))
            parts += [jugement.get("nature"), jugement.get("complementJugement")]
        elif kind == "accounts":
            depot = _loads(r.get("depot"))
            if depot.get("dateCloture"):
                parts.append(f"Financial year closed {depot['dateCloture']}")
            parts.append(depot.get("typeDepot"))
        else:
            modif = _loads(r.get("modificationsgenerales"))
            parts.append(modif.get("descriptif"))
            acte = _loads(r.get("acte"))
            creation = acte.get("creation") or {}
            if isinstance(creation, dict) and creation.get("categorieCreation"):
                parts.append(creation["categorieCreation"])
        parts.append(r.get("tribunal"))
        text = " — ".join(str(p).strip() for p in parts if p and str(p).strip())
        return text[:400] or None
