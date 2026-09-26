"""One-off: check candidate sources (removed afterwards)."""

import sys

import httpx

sys.path.insert(0, "backend")
c = httpx.Client(headers={"User-Agent": "KYC1Click research (+https://github.com/cryptocomiks/KBC)"}, timeout=60, follow_redirects=True)


def show(label, url, n=700, **kw):
    try:
        r = c.get(url, **kw)
        print(f"\n== {label}: {r.status_code} {r.headers.get('content-type')} {len(r.content)}B\n{r.text[:n]}")
    except Exception as e:  # noqa: BLE001
        print(f"\n== {label}: ERROR {e!r}")


import re  # noqa: E402

settings = open("backend/app/settings.py").read()
used = set(re.findall(r"[a-z]{2,4}_[a-z0-9_]+", settings.split("open_datasets: str = (")[1].split(")")[0]))
idx = c.get("https://data.opensanctions.org/datasets/latest/index.json").json()
print("== unused OpenSanctions datasets (name | title | count | tags)")
for d in sorted(idx["datasets"], key=lambda d: d["name"]):
    if d.get("type") == "collection" or d["name"] in used:
        continue
    print(d["name"], "|", d.get("title"), "|", (d.get("things") or {}).get("total"), "|", ",".join(d.get("tags") or [])[:70])

# Registers
show("Singapore ACRA (data.gov.sg)", "https://data.gov.sg/api/action/datastore_search", params={"resource_id": "d_3f960c10fed6145404ca7b821f263b87", "q": "DBS BANK", "limit": 2})
show("Singapore ACRA search datasets", "https://api-production.data.gov.sg/v2/public/api/datasets", params={"query": "acra entities"}, n=1500)
show("Israel companies (data.gov.il)", "https://data.gov.il/api/3/action/datastore_search", params={"resource_id": "f004176c-b85f-4542-8901-7b3176f9a054", "q": "Teva", "limit": 2}, n=1200)
show("Canada federal corporations", "https://ised-isde.canada.ca/cc/lgcy/fdrlCrpSrch.html", params={"crpNm": "shopify", "crpNmbr": "", "bsNmbr": ""}, n=300)
show("Canada corporations API", "https://ised-isde.canada.ca/cbr/srch/api/v1/search", params={"fq": "keyword:{shopify}", "lang": "en", "queryaction": "fieldquery", "sortfield": "score", "sortorder": "desc"}, n=1200)
show("Ukraine EDR", "https://data.gov.ua/api/3/action/package_show", params={"id": "1c7f3815-3259-45e0-bdf1-64dca07ddc10"}, n=800)
show("Australia ABN (no key)", "https://abr.business.gov.au/json/MatchingNames.aspx", params={"name": "BHP", "maxResults": 2}, n=300)
show("NZ companies", "https://app.companiesoffice.govt.nz/companies/app/ui/pages/companies/search", params={"q": "fonterra", "type": "entities"}, n=300)
show("France RNA associations", "https://recherche-entreprises.api.gouv.fr/search", params={"q": "croix rouge", "est_association": "true", "per_page": 1}, n=500)

# Justice / official press
show("US DOJ press releases", "https://www.justice.gov/api/v1/press_releases.json", params={"keyword": "Glencore", "pagesize": 2}, n=1500)
show("EUR-Lex SPARQL", "https://publications.europa.eu/webapi/rdf/sparql", params={"query": "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> SELECT ?w ?t WHERE { ?w cdm:work_has_resource-type <http://publications.europa.eu/resource/authority/resource-type/JUDG> . ?e cdm:expression_belongs_to_work ?w ; cdm:expression_title ?t . FILTER(CONTAINS(LCASE(STR(?t)), 'gazprom')) } LIMIT 3", "format": "application/sparql-results+json"}, n=1200, timeout=90)
show("SEC litigation RSS", "https://www.sec.gov/enforcement-litigation/litigation-releases/rss", headers={"User-Agent": "KYC1Click research-contact@kbc-mapping.org"}, n=600)
show("Europol newsroom RSS", "https://www.europol.europa.eu/rss.xml", n=400)
show("FCA final notices search", "https://www.fca.org.uk/api/search", n=200)
show("UK SFO news RSS", "https://www.sfo.gov.uk/feed/", n=400)
# Lobbying / transparency
show("EU transparency register export", "https://data.europa.eu/api/hub/search/search", params={"q": "transparency register", "limit": 2}, n=1200)
show("HATVP representants d'interets", "https://www.hatvp.fr/agora/opendata/agora_repertoire_opendata.json", n=300)
