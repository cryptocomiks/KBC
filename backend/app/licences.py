"""Reuse terms of every data source, and the commercial-use mode.

A compliance team buying the service must know, for each source, whether its data may be
used in a commercial service. Each connector is classed in one of five categories:

* ``open`` — official or openly licensed data (public domain, CC0, CC BY, ODbL, Etalab,
  OGL…): commercial reuse allowed, with attribution where the licence asks for it;
* ``terms`` — free access under the publisher's terms of use (API fair use, website
  terms, third-party proxy): allowed in principle, to be confirmed with the publisher
  before a commercial deployment;
* ``subscription`` — API key: commercial use depends on the plan behind the key;
* ``non_commercial`` — the licence forbids commercial use without a paid licence
  (CC BY-NC, developer keys for non-commercial use);
* ``demo`` — fictitious dataset.

With ``COMMERCIAL_MODE=true``, non-commercial sources are switched off, unless the firm
holds a commercial licence for them and lists them in ``LICENSED_SOURCES``. This table is
an operational summary, not legal advice: the publisher's own terms prevail.
"""

from __future__ import annotations

from typing import Literal

Category = Literal["open", "terms", "subscription", "non_commercial", "demo"]

CATEGORY_LABELS: dict[str, str] = {
    "open": "Open licence",
    "terms": "Publisher's terms",
    "subscription": "Subscription",
    "non_commercial": "Non-commercial",
    "demo": "Demo",
}

OSN = "CC BY-NC 4.0 (OpenSanctions): free for non-commercial use, a commercial licence is sold by OpenSanctions"

# connector name -> (category, licence, note)
LICENCES: dict[str, tuple[Category, str, str]] = {
    # Registries
    "annuaire_fr": ("open", "Licence Ouverte / Etalab 2.0", ""),
    "bodacc": ("open", "Licence Ouverte / Etalab 2.0", ""),
    "gleif": ("open", "CC0 1.0", ""),
    "pappers": (
        "subscription",
        "Pappers API terms",
        "Commercial use covered by a paid Pappers plan",
    ),
    "companies_house": ("open", "Open Government Licence v3.0", ""),
    "companies_house_web": (
        "terms",
        "Open Government Licence v3.0 (data); website terms",
        "Reads the public register website: fair use of the site",
    ),
    "zefix": ("terms", "Zefix PublicREST terms (Federal Office of Justice)", ""),
    "ch_uid": ("terms", "UID public services terms (Federal Statistical Office)", ""),
    "lobbywatch": ("terms", "Lobbywatch.ch data interface terms", "Attribution to Lobbywatch.ch"),
    "brreg": ("open", "Norwegian Licence for Open Government Data (NLOD)", ""),
    "ares": ("open", "Czech open data (Ministry of Finance)", ""),
    "kbo": ("terms", "KBO public search terms (FPS Economy)", "Reads the public search website"),
    "prh": ("open", "CC BY 4.0", ""),
    "ariregister": ("open", "CC BY 4.0 (Estonian open data)", ""),
    "lv_ur": ("open", "Latvian open data (CC0 / CC BY 4.0)", ""),
    "krs": ("open", "Polish public information, free reuse", ""),
    "sk_rpo": ("open", "Slovak open data (Statistical Office)", ""),
    "ru_egrul": (
        "terms",
        "Federal Tax Service public service terms",
        "Check sanctions-related restrictions on dealings with Russian state services",
    ),
    "br_cnpj": ("terms", "Receita Federal open data via BrasilAPI (community API)", ""),
    "sg_acra": ("open", "Singapore Open Data Licence", ""),
    "il_companies": ("open", "Israel government open data (data.gov.il)", ""),
    "ca_cbr": ("terms", "Canada's Business Registries search terms", ""),
    "ie_cro": ("open", "CC BY 4.0", ""),
    "rpvs": ("open", "Slovak open data", ""),
    "sec_edgar": ("open", "US public domain (SEC fair access policy)", ""),
    "opencorporates": (
        "subscription",
        "ODbL; OpenCorporates API plans",
        "Free keys are for public-benefit projects; commercial use needs a paid plan",
    ),
    # Sanctions, PEPs, watchlists
    "opensanctions": (
        "subscription",
        "OpenSanctions API plans",
        "Commercial use needs a paid licence",
    ),
    "official_sanctions": (
        "open",
        "US public domain (OFAC); UN public data",
        "The crypto address lists (Israel NBCTF, FBI, ransomware) come from OpenSanctions "
        "exports: off in commercial mode unless open_watchlists is licensed",
    ),
    "official_sanctions_europe": (
        "open",
        "EU (Commission reuse policy), UK (Open Government Licence v3.0), Switzerland (SECO, free reuse)",
        "",
    ),
    "open_watchlists": ("non_commercial", OSN, ""),
    "open_watchlists_extended": ("non_commercial", OSN, ""),
    "wikidata": ("open", "CC0 1.0", ""),
    "wikidata_pep": ("open", "CC0 1.0", ""),
    "esma_mica": ("open", "ESMA public registers, free reuse", ""),
    "asic_banned": ("open", "CC BY 3.0 AU (data.gov.au)", ""),
    "scam_lists": ("terms", "MetaMask and ScamSniffer repository licences", ""),
    # Media, archives, internet
    "gdelt_media": ("open", "GDELT: free and open use with attribution", ""),
    "guardian": (
        "non_commercial",
        "Guardian Open Platform developer key",
        "Developer keys are for non-commercial use; a commercial agreement is available",
    ),
    "wayback": ("terms", "Internet Archive terms of use", ""),
    "websites": (
        "terms",
        "crt.sh and HackerTarget terms",
        "HackerTarget's free API is rate-limited",
    ),
    "rdap": ("terms", "Registry RDAP terms (vary by registry)", ""),
    # Official gazettes, courts, public registers
    "ch_shab": ("terms", "SHAB / FOSC terms of use (SECO)", ""),
    "eu_vies": ("terms", "European Commission VIES terms", "Validation of individual numbers only"),
    "entscheidsuche": ("open", "Swiss court decisions (not protected by copyright)", ""),
    "courtlistener": ("open", "Free Law Project: public domain court records", ""),
    "recap_dockets": ("open", "Free Law Project: public domain court records", ""),
    "cjeu": ("open", "EUR-Lex reuse policy (Commission Decision 2011/833/EU)", ""),
    "uk_caselaw": (
        "terms",
        "Open Justice Licence",
        "Computational analysis of the judgments needs a transactional licence from The National Archives",
    ),
    "africanlii": ("terms", "AfricanLII / LII terms of use", ""),
    "ted": ("open", "EU open data (TED)", ""),
    "regulators": ("open", "ESMA registers and REGAFI, free reuse", ""),
    "finra_brokercheck": (
        "terms",
        "FINRA BrokerCheck terms of use",
        "Check reuse limits with FINRA",
    ),
    "littlesis": ("open", "CC BY-SA 4.0", ""),
    "eu_transparency": ("open", "EU open data", ""),
    "de_lobbyregister": ("open", "Bundestag open data", ""),
    # Leaks
    "icij_offshore_leaks": ("open", "ODbL 1.0 (database) and CC BY-SA (contents), ICIJ", ""),
    "icij_local": ("open", "ODbL 1.0 (database) and CC BY-SA (contents), ICIJ", ""),
    "casino_secrets": ("terms", "Leaked documents", "Legal review before any commercial use"),
    "casino_secrets_screening": (
        "terms",
        "Leaked documents",
        "Legal review before any commercial use",
    ),
    "aleph": ("terms", "OCCRP Aleph terms of use", "Access is granted for investigative work"),
    # Blockchains
    "chain_btc": ("terms", "mempool.space API terms", ""),
    "chain_eth": ("terms", "Blockscout API terms", ""),
    "chain_tron": ("terms", "TronGrid API terms", ""),
}

DEFAULT: tuple[Category, str, str] = ("terms", "Publisher's terms of use", "")


def licence_of(name: str, is_demo: bool = False) -> tuple[Category, str, str]:
    if is_demo:
        return ("demo", "Fictitious dataset", "")
    return LICENCES.get(name, DEFAULT)


def licensed_names(value: str) -> set[str]:
    return {n.strip().lower() for n in value.split(",") if n.strip()}
