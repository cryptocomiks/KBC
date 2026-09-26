"""One-off: check that candidate public sources answer (removed afterwards)."""

import json
import socket

import httpx

c = httpx.Client(headers={"User-Agent": "KYC1Click research (+https://github.com/cryptocomiks/KBC)"}, timeout=40, follow_redirects=True)


def show(label, url, n=700, **kw):
    try:
        r = c.get(url, **kw)
        print(f"\n== {label}: {r.status_code} {r.headers.get('content-type')} {len(r.content)}B\n{r.text[:n]}")
    except Exception as e:  # noqa: BLE001
        print(f"\n== {label}: ERROR {e!r}")


for host in ("casinosecrets.lol", "www.casinosecrets.lol"):
    try:
        print(host, socket.getaddrinfo(host, 443)[:1])
    except Exception as e:  # noqa: BLE001
        print(host, "DNS ERROR", e)
show("casino search", "https://casinosecrets.lol/api/search.json", params={"q": "stake"})

# OpenSanctions catalogue: datasets not used yet, by topic
have = set("""eu_fsf gb_fcdo_sanctions ch_seco_sanctions ca_dfatd_sema_sanctions au_dfat_sanctions jp_mof_sanctions worldbank_debarred interpol_red_notices ru_acf_bribetakers ua_war_sanctions wd_oligarchs gb_coh_disqualified ch_finma_warnings be_fod_sanctions nz_russia_sanctions lv_magnitsky_list ru_navalny35 afdb_sanctions adb_sanctions iadb_sanctions ebrd_ineligible eu_edes lu_administrative_sanctions ch_finma_rulings fr_amf_regulatory_sanctions fr_illegal_financial_services eu_esma_sanctions us_sec_pause no_nbim_exclusions fr_hatvp_declarations eu_europol_wanted gb_nca_most_wanted gb_nca_press_releases us_fbi_most_wanted de_bka_wanted""".split())
try:
    idx = c.get("https://data.opensanctions.org/datasets/latest/index.json").json()
    rows = []
    for d in idx.get("datasets", []):
        if d.get("type") == "collection" or d["name"] in have:
            continue
        rows.append((d["name"], d.get("title", ""), (d.get("things") or {}).get("total") or d.get("entity_count") or d.get("target_count"), ",".join(d.get("tags") or [])[:60]))
    print("\n== OpenSanctions datasets not used:", len(rows))
    for r in sorted(rows):
        print(" | ".join(str(x) for x in r))
except Exception as e:  # noqa: BLE001
    print("index ERROR", e)

show("EBA register", "https://euclid.eba.europa.eu/register/api/search/entities", params={"q": "Revolut"})
show("EBA register v2", "https://euclid.eba.europa.eu/register/pir/search")
show("KRS Poland", "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000019193", params={"rejestr": "P", "format": "json"}, n=1500)
show("SOGC Swiss gazette", "https://www.amtsblattportal.ch/api/v1/publications", params={"text": "Glencore", "publicationStates": "PUBLISHED", "pageRequest.size": 3})
show("UK disqualified web", "https://find-and-update.company-information.service.gov.uk/search/disqualified-officers", params={"q": "smith"}, n=400)
show("EU transparency register", "https://ec.europa.eu/transparencyregister/public/consultation/searchControllerPager.do", params={"freeTextSearchKeywords": "Glencore"}, n=300)
show("IOSCO i-scan", "https://www.iosco.org/i-scan/", params={"SUBSECTION": "main", "NAME": "binance"}, n=300)
show("Offshore leaks reconcile", "https://offshoreleaks.icij.org/api/v1/reconcile", n=200)
show("GLEIF RR", "https://api.gleif.org/api/v1/lei-records", params={"filter[entity.legalName]": "Glencore plc"}, n=200)
show("Denmark CVR", "https://cvrapi.dk/api", params={"search": "Novo Nordisk", "country": "dk"}, n=600)
show("Latvia UR", "https://data.gov.lv/dati/api/3/action/datastore_search", params={"resource_id": "25e80bf3-f107-4ab4-89ef-251b5b9374e9", "q": "airBaltic", "limit": 2}, n=800)
show("Iceland", "https://api.skatturinn.is/", n=200)
show("Ukraine opendatabot", "https://opendatabot.com/api/v3/public/company/00032945", n=300)
show("Moldova", "https://api.opensanctions.org/", n=100)
show("Wikidata SPARQL", "https://query.wikidata.org/sparql", params={"query": "SELECT ?x WHERE { ?x wdt:P1278 'M8NZEPU0EVW8EFGL1Q06' } LIMIT 1", "format": "json"}, n=300)
