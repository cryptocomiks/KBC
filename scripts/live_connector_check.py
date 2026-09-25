"""Run each real connector against its live API with known reference cases.

    pip install -r requirements.txt
    python scripts/live_connector_check.py

Keyless sources are always checked; keyed ones only when their key is set in
the environment. Prints what each source returned and exits non-zero on the
first failure, so the logs show exactly which parser disagrees with the API.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("CACHE_PATH", ":memory:")

from app.connectors.aleph import AlephConnector  # noqa: E402
from app.connectors.annuaire_fr import AnnuaireEntreprisesConnector  # noqa: E402
from app.connectors.bodacc import BodaccConnector  # noqa: E402
from app.connectors.casino_secrets import (  # noqa: E402
    CasinoSecretsConnector,
    CasinoSecretsLeakConnector,
)
from app.connectors.chains import BitcoinConnector, EthereumConnector, TronConnector  # noqa: E402
from app.connectors.companies_house import CompaniesHouseConnector  # noqa: E402
from app.connectors.gdelt import API as GDELT_API  # noqa: E402
from app.connectors.gdelt import GdeltConnector  # noqa: E402
from app.connectors.gleif import GleifConnector  # noqa: E402
from app.connectors.icij import RECONCILE, IcijReconcileConnector  # noqa: E402
from app.connectors.official_sanctions import OfficialSanctionsConnector  # noqa: E402
from app.connectors.open_datasets import OpenDatasetsConnector  # noqa: E402
from app.connectors.opencorporates import OpenCorporatesConnector  # noqa: E402
from app.connectors.opensanctions import OpenSanctionsConnector  # noqa: E402
from app.connectors.pappers import PappersConnector  # noqa: E402
from app.connectors.sec_edgar import SecEdgarConnector  # noqa: E402
from app.connectors.wikidata import WikidataConnector, WikidataPepConnector  # noqa: E402
from app.connectors.zefix import ZefixConnector  # noqa: E402
from app.models import Entity, EntityType  # noqa: E402
from app.settings import Settings  # noqa: E402

settings = Settings(live_sources=True)
failures: list[str] = []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def expect(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def guarded(title: str, fn) -> None:
    section(title)
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - report and continue with the other sources
        traceback.print_exc()
        expect(f"{title}: no exception", False, f"{type(exc).__name__}: {exc}")


def company(name: str, jur: str | None = None) -> Entity:
    return Entity(id=f"check:{name}", type=EntityType.COMPANY, name=name, jurisdiction=jur)


def person(name: str, dob: str | None = None) -> Entity:
    return Entity(id=f"check:{name}", type=EntityType.PERSON, name=name, birth_date=dob)


def check_annuaire() -> None:
    conn = AnnuaireEntreprisesConnector(settings)
    found = conn.search_company("Danone")
    expect(
        "company search returns results",
        bool(found),
        ", ".join(f"{c.name} ({c.registration_number})" for c in found[:3]),
    )
    top = found[0]
    expect(
        "company fields parsed",
        bool(top.registration_number and top.address and top.status),
        f"status={top.status} created={top.incorporation_date} address={top.address}",
    )
    officers = conn.get_officers(top.id)
    expect(
        "officers returned",
        bool(officers),
        "; ".join(
            f"{o.entity.name} [{o.relationship.role}] dob={o.entity.birth_date}"
            for o in officers[:4]
        ),
    )
    people = conn.search_person(officers[0].entity.name) if officers else []
    expect("person search finds that officer", bool(people), ", ".join(p.name for p in people[:3]))
    if people:
        roles = conn.get_person_roles(people[0].id)
        expect("person roles returned", bool(roles), "; ".join(r.entity.name for r in roles[:4]))


def check_icij() -> None:
    conn = IcijReconcileConnector(settings)
    raw = conn.http_post_json(
        f"{RECONCILE}/panama-papers",
        form={"queries": json.dumps({"q0": {"query": "Mossack Fonseca", "limit": 3}})},
    )
    print("raw reconcile sample:", json.dumps(raw)[:600])
    hits = conn.screen_many([company("Mossack Fonseca"), company("Portcullis TrustNet")])
    for h in hits[:8]:
        print(
            f"      hit: {h.matched_name} | {h.dataset} | score {h.score} | {h.details.get('node_type')} | {h.provenance.url}"
        )
    expect(
        "known Panama Papers name is found",
        any("mossack" in h.matched_name.lower() for h in hits),
        f"{len(hits)} hits",
    )
    expect("hits are attributed to a leak", all(h.dataset.endswith(")") for h in hits))
    expect(
        "node types are parsed",
        all(h.details.get("node_type") not in (None, "unknown") for h in hits),
        ", ".join(sorted({str(h.details.get("node_type")) for h in hits})),
    )
    exact = [h for h in hits if h.matched_name.upper().startswith("MOSSACK FONSECA &")]
    related = [h for h in hits if "GUATEMALA" in h.matched_name.upper()]
    expect(
        "exact name counts as a match (>= 85)",
        bool(exact) and exact[0].score >= 85,
        f"{exact[0].matched_name}: {exact[0].score}" if exact else "",
    )
    expect(
        "name with extra words is only a possible match (< 85)",
        all(h.score < 85 for h in related),
        ", ".join(f"{h.matched_name}: {h.score}" for h in related),
    )


def check_gleif() -> None:
    conn = GleifConnector(settings)
    found = conn.search_company("Danone")
    expect(
        "LEI search returns results",
        bool(found),
        ", ".join(f"{c.name} [{c.jurisdiction}] reg={c.registration_number}" for c in found[:3]),
    )
    expect("exact legal name ranked first", found[0].name.upper() == "DANONE", found[0].name)
    parents = []
    for c in found[1:6]:
        parents = conn.get_shareholders(c.id)
        if parents:
            print(f"      parent of {c.name}: {parents[0].entity.name}")
            break
    expect("a parent company is returned for a Danone subsidiary", bool(parents))
    children = conn.get_subsidiaries(found[0].id)
    expect(
        "children returned for the group head",
        bool(children),
        f"{len(children)}: " + ", ".join(ch.entity.name for ch in children[:4]),
    )


def check_bodacc() -> None:
    danone = Entity(
        id="check:danone",
        type=EntityType.COMPANY,
        name="DANONE",
        jurisdiction="FR",
        registration_number="552032534",
    )
    docs = BodaccConnector(settings).get_documents(danone)
    for d in docs[:4]:
        print(f"      {d.date} | {d.title} | {d.summary} | {d.url}")
    expect("legal notices returned for Danone", bool(docs), f"{len(docs)} notices")
    expect("notices are dated and linked", all(d.date and d.url for d in docs))
    expect(
        "accounts filings recognised",
        any(d.kind == "accounts" for d in docs),
        ", ".join(sorted({d.kind for d in docs})),
    )


def check_official_sanctions() -> None:
    conn = OfficialSanctionsConnector(settings)
    hits = conn.screen(person("Vladimir Putin", "1952-10-07"))
    for h in hits[:3]:
        print(f"      hit: {h.matched_name} | {h.dataset} | {h.score} | {h.details.get('program')}")
    expect(
        "OFAC SDN: sanctioned reference person found",
        any(h.score >= 85 and "OFAC" in h.dataset for h in hits),
    )
    un_hits = conn.screen(person("Ayman al-Zawahiri"))
    expect(
        "UN list: reference person found",
        any("UN" in h.dataset for h in un_hits),
        "; ".join(f"{h.matched_name} ({h.score})" for h in un_hits[:3]),
    )
    from app.connectors.official_sanctions import _INDEX

    print(f"      index: {len(_INDEX.entries)} listed entries; load errors: {_INDEX.errors}")


def check_crypto() -> None:
    from app.connectors.official_sanctions import _INDEX

    sanctions = OfficialSanctionsConnector(settings)
    sanctions._index()
    by_chain: dict[str, str] = {}
    for address, (_, _, chain) in _INDEX.wallets.items():
        by_chain.setdefault(chain or "?", address)
    print(f"      OFAC crypto addresses indexed: {len(_INDEX.wallets)}; sample: {by_chain}")
    # Reference list for manual testing: ETH addresses of North Korea-related designations.
    dprk = [
        (address, _INDEX.entries[idx])
        for address, (idx, _, chain) in _INDEX.wallets.items()
        if chain == "ETH" and "DPRK" in (_INDEX.entries[idx].program or "").upper()
    ]
    print(f"      DPRK-related ETH addresses on the SDN list: {len(dprk)}")
    for address, entry in dprk[:15]:
        print(f"        {address} | {entry.entity.name} | {entry.program}")
    expect("OFAC crypto addresses extracted", len(_INDEX.wallets) > 50)

    for conn, sample in (
        (BitcoinConnector(settings), by_chain.get("BTC")),
        (EthereumConnector(settings), "0xdAC17F958D2ee523a2206206994597C13D831ec7"),
        (TronConnector(settings), by_chain.get("TRON") or "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"),
    ):
        if not sample:
            expect(f"{conn.chain}: sample address available", False)
            continue
        wallet = conn.get_wallet(sample)
        expect(
            f"{conn.chain}: wallet profile",
            wallet is not None,
            f"{sample} {wallet.extra if wallet else ''}",
        )
        links = conn.get_wallet_links(wallet) if wallet else []
        expect(
            f"{conn.chain}: flows aggregated",
            bool(links),
            "; ".join(
                f"{link.relationship.amount} {link.relationship.currency} x{link.relationship.tx_count}"
                for link in links[:3]
            ),
        )
        if conn.chain != "ETH":
            hits = sanctions.screen(wallet)
            expect(
                f"{conn.chain}: OFAC-listed address flagged",
                any(h.score == 100 for h in hits),
                "; ".join(h.matched_name for h in hits),
            )


def check_open_watchlists() -> None:
    from app.connectors import open_datasets

    conn = OpenDatasetsConnector(settings)
    index = conn._index()
    by_dataset: dict[str, int] = {}
    for entry in index.entries:
        by_dataset[entry.dataset] = by_dataset.get(entry.dataset, 0) + 1
    print(f"      entries per list: {by_dataset}; errors: {open_datasets._STATE.errors}")
    expect("all configured lists loaded", not open_datasets._STATE.errors and len(by_dataset) >= 5)
    hits = conn.screen(person("Vladimir Putin", "1952-10-07"))
    for h in hits[:4]:
        print(f"      hit: {h.matched_name} | {h.dataset} | {h.score}")
    expect(
        "EU list: sanctioned reference person found",
        any("EU" in h.dataset and h.score >= 85 for h in hits),
    )
    expect(
        "UK list: sanctioned reference person found",
        any("UK" in h.dataset and h.score >= 85 for h in hits),
    )


def check_wikidata() -> None:
    wd = WikidataConnector(settings)
    people = wd.search_person("Emmanuel Macron")
    expect("person search", bool(people), ", ".join(f"{p.name} {p.birth_date}" for p in people[:3]))
    macron = next((p for p in people if p.birth_date == "1977-12-21"), None)
    expect(
        "positions held parsed",
        bool(macron and "President" in macron.extra.get("positions_held", "")),
        macron.extra.get("positions_held", "")[:200] if macron else "",
    )
    if macron:
        roles = wd.get_person_roles(macron.id)
        expect(
            "relatives / associates",
            any(r.relationship.type.value == "relative" for r in roles),
            "; ".join(f"{r.relationship.role}: {r.entity.name}" for r in roles[:5]),
        )
    hits = WikidataPepConnector(settings).screen_many([person("Emmanuel Macron", "1977-12-21")])
    expect(
        "PEP screening",
        any(h.score >= 85 for h in hits),
        "; ".join(f"{h.matched_name} {h.score}" for h in hits[:2]),
    )
    companies = wd.search_company("TotalEnergies")
    expect(
        "company search",
        bool(companies),
        ", ".join(f"{c.name} [{c.jurisdiction}]" for c in companies[:3]),
    )
    if companies:
        docs = wd.get_documents(companies[0])
        expect(
            "official contacts / accounts",
            any(d.kind == "official_profile" for d in docs),
            "; ".join(f"{d.title} → {d.url}" for d in docs[:5]),
        )
        expect(
            "corporate links",
            bool(wd.get_officers(companies[0].id)),
            "; ".join(
                f"{link.relationship.role}: {link.entity.name}"
                for link in wd.get_officers(companies[0].id)[:4]
            ),
        )


def check_gdelt() -> None:
    import httpx as _httpx

    raw = _httpx.get(
        GDELT_API,
        params={
            "query": '"TotalEnergies" (fraud OR corruption OR sanctions)',
            "mode": "ArtList",
            "format": "json",
            "maxrecords": 5,
            "timespan": "12m",
        },
        timeout=30,
    )
    print(f"      raw status {raw.status_code}: {raw.text[:300]!r}")
    time.sleep(6)  # GDELT allows one request every 5 s: do not rate-limit the connector ourselves
    docs = GdeltConnector(settings).get_documents(company("TotalEnergies"))
    for d in docs[:3]:
        print(f"      {d.date} | {d.title[:90]} | {d.url}")
    # GDELT rate-limits shared cloud IPs (HTTP 429): the connector falls back to Google News.
    expect(
        "adverse media returned (GDELT or Google News fallback)",
        bool(docs),
        f"{len(docs)} articles via {docs[0].source.split(' — ')[0] if docs else '-'}",
    )


def check_zefix() -> None:
    zefix = ZefixConnector(settings)
    found = zefix.search_company("Nestlé")
    expect(
        "company search",
        bool(found),
        ", ".join(f"{c.name} [{c.registration_number}]" for c in found[:4]),
    )
    nestle = next((c for c in found if c.name == "Nestlé AG"), None)
    expect("Nestlé AG found", nestle is not None)
    if not nestle:
        return
    detail = zefix.get_company_details(nestle.id)
    expect(
        "details (address, legal form)",
        bool(detail and detail.address and detail.legal_form),
        f"{detail.legal_form} — {detail.address}" if detail else "",
    )
    officers = zefix.get_officers(nestle.id)
    active = [o for o in officers if o.relationship.end_date is None]
    for o in active[:6]:
        print(f"      {o.entity.name} — {o.relationship.role} (since {o.relationship.start_date})")
    expect(
        "officers parsed from SOGC notices",
        len(active) >= 5,
        f"{len(active)} active, {len(officers)} total",
    )
    expect(
        "board members recognised",
        any((o.relationship.role or "").startswith("Board member") for o in active),
    )
    docs = zefix.get_documents(detail)
    expect(
        "SOGC publications as documents",
        sum(d.kind == "legal_notice" for d in docs) >= 5,
        f"{len(docs)} documents",
    )


def check_sec() -> None:
    sec = SecEdgarConnector(settings)
    found = sec.search_company("Tesla")
    expect(
        "company search",
        bool(found),
        ", ".join(f"{c.name} ({c.identifiers.get('CIK')})" for c in found[:3]),
    )
    tesla = next((c for c in found if c.identifiers.get("CIK") == "1318605"), None)
    expect("Tesla, Inc. found (CIK 1318605)", tesla is not None)
    if not tesla:
        return
    detail = sec.get_company_details(tesla.id)
    expect(
        "financials from XBRL",
        bool(detail and detail.extra.get("revenue_usd")),
        f"revenue {detail.extra.get('revenue_usd')} USD, net income {detail.extra.get('net_income_usd')}, "
        f"assets {detail.extra.get('total_assets_usd')} ({detail.extra.get('financial_year_end')})"
        if detail
        else "",
    )
    owners = sec.get_shareholders(tesla.id)
    for o in owners[:5]:
        print(
            f"      {o.entity.name} ({o.entity.type.value}) {o.relationship.share_pct}% — {o.relationship.role}"
        )
    expect("13D/13G beneficial owners with %", any(o.relationship.share_pct for o in owners))
    docs = sec.get_documents(detail)
    expect(
        "recent filings linked",
        any(d.title.startswith("SEC 10-K") for d in docs),
        f"{len(docs)} filings",
    )


def check_casino_secrets() -> None:
    reg = CasinoSecretsConnector(settings)
    found = reg.search_company("Medium Rare N.V.")
    expect(
        "licence holder found",
        any(c.name == "Medium Rare N.V." for c in found),
        "; ".join(f"{c.name} — {c.extra.get('casino_domains', '')}" for c in found[:3]),
    )
    stake = Entity(id="t:stake", type=EntityType.COMPANY, name="Medium Rare N.V.")
    hits = CasinoSecretsLeakConnector(settings).screen(stake)
    for h in hits[:3]:
        print(f"      hit: {h.matched_name} | {h.score} | {h.provenance.url}")
    expect("screening hit with link", any(h.score >= 85 and h.provenance.url for h in hits))


def check_identifiers() -> None:
    from app.service import KbcService

    svc = KbcService()
    for query, expected in (
        ("552 032 534", "DANONE"),  # SIREN
        ("CHE-105.909.036", "Nestlé AG"),  # Swiss UID
        ("CIK 1318605", "Tesla, Inc."),  # SEC
    ):
        res = svc.search(query)
        names = [c.entity.name for c in res.candidates]
        expect(
            f"exact lookup {query}",
            any(expected.lower() in n.lower() for n in names),
            ", ".join(names[:3]),
        )


def check_sanctioned_official() -> None:
    """End to end, depth 2 as in the app: a sanctioned public official must come out
    screened, with her sanctions listings and PEP status, never as an unchecked score."""
    from app.schemas import InvestigationRequest
    from app.service import KbcService

    svc = KbcService()
    res = svc.search("Elvira Nabiullina", "person")
    person = next((c.entity for c in res.candidates if c.entity.type == EntityType.PERSON), None)
    expect("Elvira Nabiullina found", person is not None)
    if person is None:
        return
    inv = svc.investigate(InvestigationRequest(record_ids=person.record_ids, depth=2, max_nodes=60))
    own = [h for h in inv.hits if h.entity_id == inv.subject_id]
    for h in own:
        print(f"      {h.list_type.value:9} {h.score:5.1f}  {h.dataset}  [{h.triage}]")
    for w in inv.warnings:
        print(f"      warning: {w}")
    expect("subject screened", inv.subject_id not in inv.unscreened, f"level {inv.risk.level}")
    expect(
        "sanctions listings found",
        any(h.list_type.value == "sanction" for h in own),
        ", ".join(sorted({h.dataset for h in own if h.list_type.value == "sanction"})),
    )
    expect("PEP status found", any(h.list_type.value == "pep" for h in own))
    expect(
        "risk level reflects the sanctions",
        inv.risk.level in ("high", "critical"),
        f"{inv.risk.score:.0f} ({inv.risk.level}) — {inv.brief.headline if inv.brief else ''}",
    )


def check_uk_public_register() -> None:
    from app.connectors.companies_house_web import CompaniesHouseWebConnector

    conn = CompaniesHouseWebConnector(Settings(live_sources=True, companies_house_api_key=""))
    found = conn.search_company("Tesco PLC")
    tesco = next((c for c in found if c.registration_number == "00445790"), None)
    expect("company search (public site, JSON)", tesco is not None, ", ".join(c.name for c in found[:3]))
    officers = conn.get_officers("companies_house_web:00445790")
    for o in officers[:3]:
        print(f"      {o.entity.name} — {o.relationship.role} (from {o.relationship.start_date}, born {o.entity.birth_date})")
    expect("officers parsed from the public page", len(officers) >= 5, f"{len(officers)} officers")
    owners = conn.get_shareholders("companies_house_web:OE000001")
    for o in owners[:3]:
        print(f"      {o.entity.name} — {o.relationship.role} ({o.relationship.share_pct}%)")
    expect("overseas entity: registrable beneficial owners", len(owners) >= 1)
    people = conn.search_person("Alisher Usmanov")
    roles = conn.get_person_roles(people[0].id) if people else []
    expect("officer search + appointments", len(roles) >= 1, f"{people[0].name if people else '-'}: {len(roles)} appointments")


def check_european_registers() -> None:
    from app.connectors.europe_registries import (
        AresConnector,
        AriregisterConnector,
        BrregConnector,
        KboConnector,
        PrhConnector,
    )

    for label, conn, query, officers_min in (
        ("Norway (Brønnøysund) — Equinor", BrregConnector(settings), "Equinor", 5),
        ("Czech Republic (ARES) — Škoda Auto", AresConnector(settings), "Škoda Auto", 3),
        ("Belgium (CBE/KBO) — Solvay", KboConnector(settings), "Solvay", 0),
        ("Finland (PRH) — Nokia", PrhConnector(settings), "Nokia Oyj", 0),
        ("Estonia (e-Business Register) — Bolt", AriregisterConnector(settings), "Bolt Technology", 0),
    ):
        found = conn.search_company(query)
        expect(f"{label}: search", bool(found), ", ".join(f"{c.name} ({c.registration_number})" for c in found[:3]))
        if not found or not officers_min:
            continue
        top = found[0]
        links = conn.get_officers(top.id) + conn.get_shareholders(top.id)
        for o in links[:3]:
            print(f"      {o.entity.name} (born {o.entity.birth_date}) — {o.relationship.role}")
        expect(f"{label}: officers / owners", len(links) >= officers_min, f"{len(links)} links")
    kbo = KboConnector(settings)
    solvay = kbo.get_company_details("kbo:0403091220")
    directors = kbo.get_officers("kbo:0403091220")
    expect("Belgium: Solvay SA details and directors", bool(solvay) and len(directors) >= 5, f"{solvay.name if solvay else '-'}: {len(directors)} functions")


def check_rpvs() -> None:
    from app.connectors.rpvs import RpvsConnector

    conn = RpvsConnector(settings)
    found = conn.search_company("Slovnaft")
    expect("partner search", bool(found), ", ".join(f"{c.name} ({c.registration_number})" for c in found[:3]))
    owners = [o for c in found[:3] for o in conn.get_shareholders(c.id)]
    for o in owners[:4]:
        print(f"      {o.entity.name} (born {o.entity.birth_date}) — {o.relationship.role}, until {o.relationship.end_date}")
    expect("verified beneficial owners", len(owners) >= 1)


def check_documents_sources() -> None:
    from app.connectors.courts import CourtListenerConnector, SwissCourtsConnector
    from app.connectors.littlesis import LittleSisConnector
    from app.connectors.ted import TedConnector
    from app.connectors.websites import LinkedWebsitesConnector

    glencore = company("Glencore")
    for label, conn, entity in (
        ("Swiss court decisions (entscheidsuche)", SwissCourtsConnector(settings), glencore),
        ("US court opinions (CourtListener)", CourtListenerConnector(settings), glencore),
        ("EU public contracts (TED)", TedConnector(settings), company("Thales")),
        ("LittleSis relationships", LittleSisConnector(settings), company("Glencore Plc")),
    ):
        docs = conn.get_documents(entity)
        for d in docs[:2]:
            print(f"      {d.date} | {d.title[:90]} | {d.url}")
        expect(label, bool(docs), f"{len(docs)} documents")
    # Glencore's certificates only cover its own domain and its analytics ID only its own site:
    # "no linked website" is the right answer. Check that both sources answer, then the result.
    web = LinkedWebsitesConnector(settings)
    import httpx as _httpx

    raw = _httpx.get("https://crt.sh/", params={"q": "glencore.com", "output": "json"}, timeout=40)
    print(f"      crt.sh raw status {raw.status_code}, {len(raw.content)} bytes")
    certs = raw.json() if raw.status_code == 200 else []
    expect("certificate transparency (crt.sh) answers", len(certs) > 0, f"{len(certs)} certificates")
    ids = web.http_get_text("https://api.hackertarget.com/analyticslookup/", params={"q": "glencore.com"}) or ""
    print(f"      analytics lookup: {ids.strip()[:120]!r}")
    expect("analytics ID lookup answers (or daily quota reached)", "GTM-" in ids or "UA-" in ids or "API count" in ids)
    site = company("Glencore")
    site.extra["website"] = "https://www.glencore.com"
    docs = web.get_documents(site)
    print(f"      linked-website documents for glencore.com: {len(docs)} (none expected: single-brand domain)")


def check_country_risk() -> None:
    from app.risk.config import get_country_risk

    cr = get_country_risk()
    expect(
        "country indicators loaded",
        len(cr.countries) > 150,
        f"{len(cr.countries)} countries, retrieved {cr.retrieved}",
    )
    for code in ("CH", "LU", "PA", "MM"):
        print(f"      {code}: {cr.describe(code)}")
    expect("Switzerland scored", cr.get("CH").get("basel_aml_score") is not None)


def check_opensanctions() -> None:
    conn = OpenSanctionsConnector(settings)
    hits = conn.screen_many([person("Vladimir Putin", "1952-10-07")])
    for h in hits[:3]:
        print(f"      hit: {h.list_type} {h.matched_name} | {h.dataset} | {h.score}")
    expect(
        "sanctioned reference person found", any(h.score >= 85 for h in hits), f"{len(hits)} hits"
    )


def check_companies_house() -> None:
    conn = CompaniesHouseConnector(settings)
    found = conn.search_company("TESCO PLC")
    expect("company search", bool(found), ", ".join(c.name for c in found[:3]))
    detail = conn.get_company_details(found[0].id)
    expect(
        "company profile",
        bool(detail and detail.incorporation_date),
        f"{detail.name if detail else None}",
    )
    expect("officers", bool(conn.get_officers(found[0].id)))


def check_pappers() -> None:
    conn = PappersConnector(settings)
    detail = conn.get_company_details("pappers:552032534")  # Danone
    expect("company profile", bool(detail and detail.name), detail.name if detail else "")
    expect("officers", bool(conn.get_officers("pappers:552032534")))


def check_opencorporates() -> None:
    conn = OpenCorporatesConnector(settings)
    found = conn.search_company("Tesco PLC")
    expect(
        "company search", bool(found), ", ".join(f"{c.name} [{c.jurisdiction}]" for c in found[:3])
    )


def check_aleph() -> None:
    hits = AlephConnector(settings).screen(company("Mossack Fonseca"))
    expect(
        "Aleph search answered",
        True,
        f"{len(hits)} hits: " + "; ".join(h.dataset for h in hits[:3]),
    )


guarded("Annuaire des Entreprises (data.gouv.fr)", check_annuaire)
guarded("ICIJ Offshore Leaks reconcile API", check_icij)
guarded("GLEIF (LEI + parent companies)", check_gleif)
guarded("BODACC legal announcements", check_bodacc)
guarded("Official sanctions lists (OFAC SDN + UN)", check_official_sanctions)
guarded("Crypto: OFAC addresses + BTC/ETH/TRON explorers", check_crypto)
guarded("Open watchlists (EU / UK / CH / World Bank / Interpol)", check_open_watchlists)
guarded("Wikidata (PEP, relatives, contacts)", check_wikidata)
guarded("GDELT adverse media", check_gdelt)
guarded("Zefix (Swiss commercial register)", check_zefix)
guarded("SEC EDGAR (US filings, 13D/13G owners)", check_sec)
guarded("Country risk indicators", check_country_risk)
guarded("Casino Secrets (Curaçao gaming leak)", check_casino_secrets)
guarded("Search by identifier (SIREN, Swiss UID, SEC CIK)", check_identifiers)
guarded("Sanctioned public official, depth 2 (Elvira Nabiullina)", check_sanctioned_official)
guarded("UK register without key (Companies House public site, overseas entities)", check_uk_public_register)
guarded("European registers (NO, CZ, BE, FI, EE)", check_european_registers)
guarded("Slovak beneficial owners (RPVS)", check_rpvs)
guarded("Courts, public contracts, LittleSis, linked websites", check_documents_sources)
for key, title, fn in [
    ("OPENSANCTIONS_API_KEY", "OpenSanctions", check_opensanctions),
    ("COMPANIES_HOUSE_API_KEY", "Companies House", check_companies_house),
    ("PAPPERS_API_KEY", "Pappers", check_pappers),
    ("OPENCORPORATES_API_TOKEN", "OpenCorporates", check_opencorporates),
    ("ALEPH_API_KEY", "OCCRP Aleph", check_aleph),
]:
    if os.environ.get(key):
        guarded(title, fn)
    else:
        section(title)
        print(f"SKIP  {key} not set")

print("\nFAILED: " + ", ".join(failures) if failures else "\nAll live connector checks passed.")
sys.exit(1 if failures else 0)
