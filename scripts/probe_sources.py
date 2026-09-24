"""One-off probe of candidate public sources (removed once the connectors are written). Round 2."""

import json
import re

import httpx

UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept": "application/json, */*"}
c = httpx.Client(headers=UA, timeout=40, follow_redirects=True)


def show(label, method, url, n=2500, around=None, **kw):
    print(f"\n===== {label}\n{method} {url} {kw.get('params') or ''}")
    try:
        r = c.request(method, url, **kw)
        print(f"status {r.status_code} · {r.headers.get('content-type')} · {len(r.content)} bytes")
        t = r.text
        if around:
            for m in list(re.finditer(around, t))[:3]:
                print("...", t[max(0, m.start() - 300): m.start() + n // 2].replace("\n", " "), "...")
        else:
            print(t[:n].replace("\n", " "))
        return r
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))


CH = "https://find-and-update.company-information.service.gov.uk"
show("CH company", "GET", f"{CH}/company/OE000001", n=1500)
show("CH officers", "GET", f"{CH}/company/OE000001/officers", n=1500)
show("CH PSC / beneficial owners", "GET", f"{CH}/company/OE000001/persons-with-significant-control", n=1500)
show("CH officers search", "GET", f"{CH}/search/officers", params={"q": "Roman Abramovich"}, n=1500)
show("CH company search Tesco", "GET", f"{CH}/search/companies", params={"q": "Tesco PLC"}, n=800)
show("CH API (keyless?)", "GET", "https://api.company-information.service.gov.uk/company/00445790", n=300)

show("RPVS filter", "GET", "https://rpvs.gov.sk/opendatav2/PartneriVerejnehoSektora", params={"$filter": "contains(ObchodneMeno,'Slovnaft')"}, n=1500)
show("RPVS entity", "GET", "https://rpvs.gov.sk/opendatav2/PartneriVerejnehoSektora(1)", params={"$expand": "KonecniUzivateliaVyhod"}, n=1500)
show("RPVS metadata", "GET", "https://rpvs.gov.sk/opendatav2/$metadata", n=3000)

for u in (
    "https://ariregister.rik.ee/est/api/company/12417834",
    "https://ariregister.rik.ee/eng/company/12417834/Bolt-Technology-OU",
    "https://avaandmed.ariregister.rik.ee/en/open-data-api/introduction",
):
    show("Estonia " + u.rsplit("/", 2)[-2], "GET", u, n=1200)

r = show("Belgium search table", "GET", "https://kbopub.economie.fgov.be/kbopub/zoeknaamfonetischform.html", around=r"toonondernemingps", n=900, params={"searchWord": "Solvay", "_oudeBenaming": "on", "ondNP": "true", "_ondNP": "on", "ondRP": "true", "_ondRP": "on", "rechtsvormFonetic": "ALL", "vest": "true", "_vest": "on", "filterEnkelActieve": "true", "_filterEnkelActieve": "on", "actionNPRP": "Zoek", "lang": "en"})
show("Belgium entity functions", "GET", "https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html", around=r"(Functions|Functies|Director|Bestuurder)", n=2400, params={"ondernemingsnummer": "0403091220", "lang": "en"})

show("Czech VR statutory body", "GET", "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty-vr/00177041", around=r"statutarniOrgan", n=2400)
show("Czech VR shareholders", "GET", "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty-vr/00177041", around=r"(spolecnici|akcionar)", n=1600)
show("Finland detail", "GET", "https://avoindata.prh.fi/opendata-ytj-api/v3/companies", params={"businessId": "0112038-9"}, n=3500)
show("Poland board", "GET", "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000019193", params={"rejestr": "P", "format": "json"}, around=r"(reprezentacja|sklad)", n=1800)

r = c.post("https://entscheidsuche.ch/_search.php", json={"query": {"simple_query_string": {"query": "\"Glencore\"", "default_operator": "and"}}, "size": 3, "_source": ["date", "title", "abstract", "reference", "attachment.content_url", "hierarchy"]})
print("\n===== entscheidsuche slim", r.status_code, len(r.content))
print(r.text[:2500])
r = c.post("https://api.ted.europa.eu/v3/notices/search", json={"query": "winner-name = \"Thales\"", "fields": ["notice-title", "winner-name", "buyer-name", "buyer-country", "publication-date", "total-value", "total-value-cur", "notice-type", "contract-conclusion-date"], "limit": 2})
print("\n===== TED fields", r.status_code)
print(r.text[:3000])
show("LittleSis relationships", "GET", "https://littlesis.org/api/entities/93387/relationships", n=2000)
show("LittleSis connections", "GET", "https://littlesis.org/api/entities/93387/connections", n=1500)
show("hackertarget reverse", "GET", "https://api.hackertarget.com/analyticslookup/", params={"q": "GTM-K6F9BXS"})
show("CourtListener RECAP (dockets)", "GET", "https://www.courtlistener.com/api/rest/v4/search/", params={"q": "\"Glencore\"", "type": "r"}, n=1200)
show("Norway persons", "GET", "https://data.brreg.no/enhetsregisteret/api/enheter", params={"navn": "Kistefos", "size": 2}, n=600)
