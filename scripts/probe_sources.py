"""Temporary probe of candidate sources (removed after use)."""

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 (compliance research)", "Accept": "*/*"}
UID_SOAP = """<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:uid="http://www.uid.admin.ch/xmlns/uid-wse" xmlns:ns="http://www.uid.admin.ch/xmlns/uid-wse-shared/2">
<soapenv:Body><uid:Search><uid:searchParameters><ns:uidEntitySearchParameters><ns:organisationName>Nestlé</ns:organisationName></ns:uidEntitySearchParameters></uid:searchParameters></uid:Search></soapenv:Body></soapenv:Envelope>"""

GETS = [
    ("lobbywatch search", "https://cms.lobbywatch.ch/de/data/interface/v1/json/search/default/Ruag"),
    ("lobbywatch parl list", "https://cms.lobbywatch.ch/de/data/interface/v1/json/table/parlamentarier/flat/list"),
    ("lobbywatch org", "https://cms.lobbywatch.ch/de/data/interface/v1/json/table/organisation/flat/list/Ruag"),
    ("lobbyregister sucheJson", "https://www.lobbyregister.bundestag.de/sucheJson?q=Siemens"),
    ("lobbyregister api", "https://api.lobbyregister.bundestag.de/rest/v2/registerentries?q=Siemens&apikey=5bHB2zrUuHR6YdPoZygQhWfg2CBrjUOi"),
    ("lobbyregister api v1", "https://api.lobbyregister.bundestag.de/rest/v1/sucheDetailJson?q=Siemens&apikey=5bHB2zrUuHR6YdPoZygQhWfg2CBrjUOi"),
    ("esma mica casp", "https://registers.esma.europa.eu/solr/esma_registers_mica_casp/select?q=*:*&rows=2&wt=json"),
    ("esma cores", "https://registers.esma.europa.eu/solr/admin/cores?wt=json"),
    ("esma mica csv page", "https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica"),
    ("eba euclid", "https://euclid.eba.europa.eu/register/api/search/entities?t=Revolut"),
    ("eba pir", "https://euclid.eba.europa.eu/register/pir/search"),
    ("metamask config", "https://raw.githubusercontent.com/MetaMask/eth-phishing-detect/main/src/config.json"),
    ("scamsniffer domains", "https://raw.githubusercontent.com/scamsniffer/scam-database/main/blacklist/domains.json"),
    ("scamsniffer address", "https://raw.githubusercontent.com/scamsniffer/scam-database/main/blacklist/address.json"),
    ("six bankmaster", "https://api.six-group.com/api/epcd/bankmaster/v3/bankmaster_V3.json"),
    ("six bankmaster v2", "https://api.six-group.com/api/epcd/bankmaster/v2/public"),
    ("doh cloudflare", "https://cloudflare-dns.com/dns-query?name=nestle.com&type=MX"),
    ("doh google", "https://dns.google/resolve?name=_dmarc.nestle.com&type=TXT"),
    ("fr address search", "https://recherche-entreprises.api.gouv.fr/search?q=60%20rue%20francois%201er%2075008&per_page=5"),
    ("zefix address", "https://www.zefix.admin.ch/ZefixREST/api/v1/firm/search.json"),
    ("comp cases api", "https://competition-cases.ec.europa.eu/api/search?text=Google&page=0&size=3"),
    ("comp cases api2", "https://competition-cases.ec.europa.eu/api/cases?searchText=Google"),
    ("comp cases search", "https://competition-cases.ec.europa.eu/search?text=Google"),
    ("asic ckan", "https://data.gov.au/data/api/3/action/package_search?q=banned%20disqualified%20ASIC&rows=3"),
    ("guardian test", "https://content.guardianapis.com/search?q=%22Glencore%22%20AND%20bribery&api-key=test&page-size=2"),
]


def show(name, r):
    ct = r.headers.get("content-type", "")
    print(f"\n### {name}: {r.status_code} {ct} {len(r.content)}B final={r.url}")
    print(r.text[:700].replace("\n", " "))


with httpx.Client(headers=H, timeout=40, follow_redirects=True) as c:
    for name, url in GETS:
        try:
            if name == "zefix address":
                r = c.post(url, json={"name": "Bahnhofstrasse 1", "languageKey": "en", "maxEntries": 3})
            elif name == "doh cloudflare":
                r = c.get(url, headers={"accept": "application/dns-json"})
            else:
                r = c.get(url)
            show(name, r)
        except Exception as e:  # noqa: BLE001
            print(f"\n### {name}: ERROR {type(e).__name__}: {e}")
    for ver in ("V5.0", "V3.0"):
        try:
            r = c.post(
                f"https://www.uid-wse.admin.ch/{ver}/PublicServices.svc",
                content=UID_SOAP.encode(),
                headers={"Content-Type": "text/xml; charset=utf-8",
                         "SOAPAction": "http://www.uid.admin.ch/xmlns/uid-wse/IPublicServices/Search"},
            )
            show(f"uid soap {ver}", r)
        except Exception as e:  # noqa: BLE001
            print(f"uid {ver} ERROR {e}")
