"""Links to the official registers where an analyst can view the underlying
documents (deeds, articles of association, filed accounts, filing history).

These are generated from identifiers already known for the entity: no data
is fetched, the analyst opens the primary source.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from app.models import Document, Entity, EntityType

SOURCE = "Official register (link)"


def register_links(entity: Entity) -> list[Document]:
    if entity.type != EntityType.COMPANY or entity.demo:
        return []
    jur = (entity.jurisdiction or "").upper()
    number = re.sub(r"\s", "", entity.registration_number or "")
    docs: list[Document] = []
    if jur == "FR" and re.fullmatch(r"\d{9}", number):
        docs += [
            Document(
                title="Deeds, articles of association & filed accounts (INPI — RNE)",
                kind="deeds",
                url=f"https://data.inpi.fr/entreprises/{number}",
                source=SOURCE,
                summary="Registre national des entreprises: actes, statuts, comptes annuels (PDF)",
            ),
            Document(
                title="Company record & official documents (Annuaire des Entreprises)",
                kind="register",
                url=f"https://annuaire-entreprises.data.gouv.fr/entreprise/{number}",
                source=SOURCE,
            ),
            Document(
                title="All legal announcements (BODACC)",
                kind="legal_notice",
                url=f"https://www.bodacc.fr/pages/annonces-commerciales/?q.registre=registre:{number}",
                source=SOURCE,
            ),
            Document(
                title="Company profile (Pappers)",
                kind="register",
                url=f"https://www.pappers.fr/entreprise/{number}",
                source=SOURCE,
            ),
        ]
    elif jur == "GB" and number:
        docs += [
            Document(
                title="Filing history: accounts, confirmation statements, PDFs (Companies House)",
                kind="filing",
                url=f"https://find-and-update.company-information.service.gov.uk/company/{number}/filing-history",
                source=SOURCE,
            ),
            Document(
                title="Persons with significant control (Companies House)",
                kind="register",
                url=f"https://find-and-update.company-information.service.gov.uk/company/{number}/persons-with-significant-control",
                source=SOURCE,
            ),
        ]
    elif jur == "LU":
        docs.append(
            Document(
                title="Luxembourg Business Registers (RCS / RBE) — search",
                kind="register",
                url="https://www.lbr.lu",
                source=SOURCE,
                summary=f"Search '{entity.name}' ({number or 'number unknown'})",
            )
        )
    elif jur == "CH":
        docs.append(
            Document(
                title="Swiss commercial register (Zefix)",
                kind="register",
                url=f"https://www.zefix.ch/en/search/entity/list?name={quote_plus(entity.name)}",
                source=SOURCE,
            )
        )
    if jur == "GB":
        # The Gazette blocks automated requests: the analyst opens the search.
        docs.append(
            Document(
                title="Insolvency and strike-off notices (The Gazette) — search",
                kind="legal_notice",
                url="https://www.thegazette.co.uk/insolvency/notice?text="
                + quote_plus(f'"{entity.name}"'),
                source=SOURCE,
                summary="Official UK public record: winding-up, liquidation, administration, strike-off",
            )
        )
    # Google News feeds are for personal reading only: a search link, not an automated fetch.
    docs.append(
        Document(
            title="Adverse media search (Google News)",
            kind="press",
            url="https://news.google.com/search?q="
            + quote_plus(
                f'"{entity.name}" (fraud OR "money laundering" OR sanctions OR corruption OR '
                "investigation OR bankruptcy OR lawsuit)"
            ),
            source=SOURCE,
            summary="Opens the search in the browser: read and keep the relevant articles",
        )
    )
    docs.append(
        Document(
            title="Company search (OpenCorporates)",
            kind="register",
            url=f"https://opencorporates.com/companies?q={quote_plus(entity.name)}",
            source=SOURCE,
        )
    )
    return docs
