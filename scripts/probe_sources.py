"""One-off probe of candidate public sources (removed once the connectors are written)."""

import json

import httpx

UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept": "application/json, */*"}
c = httpx.Client(headers=UA, timeout=40, follow_redirects=True)


def show(label, method, url, **kw):
    print(f"\n===== {label}\n{method} {url}")
    try:
        r = c.request(method, url, **kw)
        print(f"status {r.status_code} · {r.headers.get('content-type')} · {len(r.content)} bytes")
        print(r.text[: kw.pop("n", 1500) if False else 1500].replace("\n", " ")[:1500])
        return r
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))


# --- OpenSanctions dataset catalogue
r = c.get("https://data.opensanctions.org/datasets/latest/index.json")
print("===== OpenSanctions index", r.status_code)
if r.status_code == 200:
    data = r.json()
    keys = ("debar", "ineligib", "sanction", "pep", "warning", "blacklist", "edes", "csl", "exclusion",
            "psc", "ownership", "bods", "fca", "amf", "cssf", "finma", "leak", "icij", "offshore", "oligarch",
            "crime", "wanted", "fatf", "regist", "lei", "gleif", "courts", "procure", "hatvp", "aircraft", "vessel")
    for d in data.get("datasets", []):
        name = d.get("name", "")
        title = d.get("title", "")
        if any(k in (name + " " + title).lower() for k in keys):
            print(f"{name:40} | {d.get('entity_count', d.get('thing_count', '?')):>8} | {d.get('type','')} | {title[:80]}")

# --- Registries
show("Norway search", "GET", "https://data.brreg.no/enhetsregisteret/api/enheter", params={"navn": "Equinor", "size": 3})
show("Norway roles", "GET", "https://data.brreg.no/enhetsregisteret/api/enheter/923609016/roller")
show("Finland search", "GET", "https://avoindata.prh.fi/opendata-ytj-api/v3/companies", params={"name": "Nokia Oyj"})
show("Estonia autocomplete", "GET", "https://ariregister.rik.ee/est/api/autocomplete", params={"q": "Bolt Technology"})
show("Czech ARES search", "POST", "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat", json={"obchodniJmeno": "Škoda Auto", "pocet": 3})
show("Czech ARES VR", "GET", "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty-vr/00177041")
show("Belgium KBO search", "GET", "https://kbopub.economie.fgov.be/kbopub/zoeknaamfonetischform.html", params={"searchWord": "Solvay", "_oudeBenaming": "on", "pstcdeNPRP": "", "postgemeente1": "", "ondNP": "true", "_ondNP": "on", "ondRP": "true", "_ondRP": "on", "rechtsvormFonetic": "ALL", "vest": "true", "_vest": "on", "filterEnkelActieve": "true", "_filterEnkelActieve": "on", "actionNPRP": "Zoek"})
show("Belgium KBO entity", "GET", "https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html", params={"ondernemingsnummer": "0403091220", "lang": "en"})
show("Slovakia RPVS", "GET", "https://rpvs.gov.sk/opendatav2/PartneriVerejnehoSektora", params={"$filter": "contains(ObchodneMeno,'Slovnaft')", "$top": "2"})
show("Latvia UR open data", "GET", "https://data.gov.lv/dati/api/3/action/package_show", params={"id": "uznemumu-registra-patiesie-labuma-guveji"})
show("Poland KRS", "GET", "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000019193", params={"rejestr": "P", "format": "json"})
show("GLEIF children", "GET", "https://api.gleif.org/api/v1/lei-records/529900D6BF99LW9R2E68/direct-children", params={"page[size]": 3})
show("GLEIF ultimate children", "GET", "https://api.gleif.org/api/v1/lei-records/529900D6BF99LW9R2E68/ultimate-children", params={"page[size]": 3})
show("OpenOwnership bods-data", "GET", "https://bods-data.openownership.org/")
show("OpenOwnership register", "GET", "https://register.openownership.org/search", params={"q": "Rosneft"})
show("UK CH overseas (public page)", "GET", "https://find-and-update.company-information.service.gov.uk/search/companies", params={"q": "OE000001"})

# --- Courts / procurement / officials / elites
show("entscheidsuche", "POST", "https://entscheidsuche.ch/_search.php", json={"query": {"simple_query_string": {"query": "\"Glencore\"", "default_operator": "and"}}, "size": 2})
show("CourtListener v4 search (anon)", "GET", "https://www.courtlistener.com/api/rest/v4/search/", params={"q": "\"Glencore\"", "type": "o"})
show("CourtListener v3 search (anon)", "GET", "https://www.courtlistener.com/api/rest/v3/search/", params={"q": "\"Glencore\"", "type": "o"})
show("TED search", "POST", "https://api.ted.europa.eu/v3/notices/search", json={"query": "winner-name = \"Thales\"", "fields": ["notice-title", "winner-name", "buyer-name", "publication-date", "total-value", "links"], "limit": 2})
show("HATVP liste", "GET", "https://www.hatvp.fr/livraison/opendata/liste.csv")
show("LittleSis search", "GET", "https://littlesis.org/api/entities/search", params={"q": "Glencore"})
show("FAA name search", "GET", "https://registry.faa.gov/AircraftInquiry/Search/NameResult", params={"Nametxt": "NETJETS", "sort_option": "1", "PageNo": "1"})
show("FAA bulk head", "HEAD", "https://registry.faa.gov/database/ReleasableAircraft.zip")
show("crt.sh", "GET", "https://crt.sh/", params={"q": "%.glencore.com", "output": "json"})
show("hackertarget analytics", "GET", "https://api.hackertarget.com/analyticslookup/", params={"q": "glencore.com"})
show("Aleph anon search", "GET", "https://aleph.occrp.org/api/2/entities", params={"q": "Glencore", "limit": 1})
