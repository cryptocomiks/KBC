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

# African company registers without an open API (checked 2026-09): official search pages.
AFRICAN_REGISTERS = {
    "NG": ("Corporate Affairs Commission, Nigeria (CAC)", "https://search.cac.gov.ng/"),
    "ZA": (
        "Companies and Intellectual Property Commission, South Africa (CIPC)",
        "https://eservices.cipc.co.za/",
    ),
    "KE": ("Business Registration Service, Kenya (BRS)", "https://brs.go.ke/"),
    "GH": ("Office of the Registrar of Companies, Ghana (ORC)", "https://orc.gov.gh/"),
    "MA": ("Registre du commerce, Morocco (OMPIC — directinfo)", "https://www.directinfo.ma/"),
    "TN": (
        "Registre national des entreprises, Tunisia (RNE)",
        "https://www.registre-entreprises.tn/rne-public/",
    ),
    "DZ": ("Centre national du registre du commerce, Algeria (CNRC)", "https://sidjilcom.cnrc.dz/"),
    "MU": (
        "Corporate and Business Registration Department, Mauritius (CBRD)",
        "https://onlinesearch.mns.mu/",
    ),
    "RW": ("Rwanda Development Board — company registry", "https://org.rdb.rw/"),
    "UG": ("Uganda Registration Services Bureau (URSB)", "https://ursb.go.ug/"),
    "TZ": (
        "Business Registrations and Licensing Agency, Tanzania (BRELA)",
        "https://ors.brela.go.tz/",
    ),
    "ZM": (
        "Patents and Companies Registration Agency, Zambia (PACRA)",
        "https://www.pacra.org.zm/",
    ),
    "NA": ("Business and Intellectual Property Authority, Namibia (BIPA)", "https://www.bipa.na/"),
    "BW": (
        "Companies and Intellectual Property Authority, Botswana (CIPA)",
        "https://www.cipa.co.bw/",
    ),
}


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
    if jur in AFRICAN_REGISTERS:
        # No open API: the analyst opens the official search (paid extracts stay optional).
        label, url = AFRICAN_REGISTERS[jur]
        docs.append(
            Document(
                title=f"{label} — company search",
                kind="register",
                url=url,
                source=SOURCE,
                summary="Official register without an open API: search by name or number, "
                "and ask the client for a certified extract",
            )
        )
    if jur in AFRICAN_REGISTERS or jur in ("CI", "SN", "CM"):
        docs.append(
            Document(
                title="Court judgments (AfricanLII) — search",
                kind="court",
                url="https://africanlii.org/search/?q=" + quote_plus(f'"{entity.name}"'),
                source=SOURCE,
                summary="Judgments from the AfricanLII network, including Kenya and South Africa portals",
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
