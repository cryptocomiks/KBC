"""One-off probe of candidate open sources (formats + reachability from a cloud runner)."""

import json

import httpx

UA = {"User-Agent": "KBC-corporate-mapping research (github.com/cryptocomiks/KBC)", "Accept": "*/*"}
c = httpx.Client(headers=UA, timeout=30, follow_redirects=True)


def show(label, method, url, n=1500, **kw):
    print(f"\n===== {label}\n{method} {url}")
    try:
        r = c.request(method, url, **kw)
        print("status", r.status_code, r.headers.get("content-type"), "len", len(r.content))
        print(r.text[:n].replace("\n", " "))
        return r
    except Exception as e:  # noqa: BLE001
        print("ERROR", type(e).__name__, e)


# France: finances + beneficial owners flags in recherche-entreprises
r = show("annuaire finances", "GET", "https://recherche-entreprises.api.gouv.fr/search?q=danone&per_page=1", 300)
if r is not None and r.status_code == 200:
    res = r.json()["results"][0]
    print("keys", sorted(res))
    print("finances", res.get("finances"))
    print("complements", res.get("complements"))
    print("dirigeants sample", res.get("dirigeants", [])[:2])

# SEC EDGAR
show("sec tickers", "GET", "https://www.sec.gov/files/company_tickers.json", 300)
show("sec full-text 13G", "GET", "https://efts.sec.gov/LATEST/search-index?q=%22TotalEnergies%22&forms=SC%2013G,SC%2013D", 1500)
show("sec efts search", "GET", "https://efts.sec.gov/LATEST/search-index?keysTyped=Tesla", 800)
show("sec submissions", "GET", "https://data.sec.gov/submissions/CIK0001318605.json", 1500)
r = show("sec companyfacts", "GET", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001318605.json", 200)
if r is not None and r.status_code == 200:
    f = r.json()["facts"]
    print("taxonomies", list(f))
    for k in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss", "Assets"):
        v = f.get("us-gaap", {}).get(k, {}).get("units", {}).get("USD", [])
        print(k, [x for x in v if x.get("form") == "10-K" and x.get("fp") == "FY"][-2:])
    print("dei", {k: v.get("units") and list(v["units"].values())[0][-1] for k, v in f.get("dei", {}).items()})
show("sec browse company", "GET", "https://www.sec.gov/cgi-bin/browse-edgar?company=tesla&type=&dateb=&owner=include&count=10&action=getcompany&output=atom", 1500)

# Zefix (Switzerland)
show("zefix web search", "POST", "https://www.zefix.admin.ch/ZefixREST/api/v1/firm/search.json",
     3000, json={"name": "Nestlé", "languageKey": "en", "maxEntries": 5, "searchType": "exact", "deletedFirms": True})
show("zefix public rest (no auth)", "POST", "https://www.zefix.admin.ch/ZefixPublicREST/api/v1/company/search",
     500, json={"name": "Nestlé", "activeOnly": False})
show("zefix firm detail", "GET", "https://www.zefix.admin.ch/ZefixREST/api/v1/firm/CHE-105.909.036.json", 3000)
show("zefix sogc", "GET", "https://www.zefix.admin.ch/ZefixREST/api/v1/firm/CHE105909036/withoutShabPub.json", 800)

# Open Ownership
show("oo bods data", "GET", "https://bods-data.openownership.org/", 1500)
show("oo register api", "GET", "https://register.openownership.org/entities.json?q=tesco", 800)
show("oo bods index json", "GET", "https://bods-data.openownership.org/source/index.json", 1500)
show("oo datasets", "GET", "https://bods-data.openownership.org/source/", 1500)

# Country risk
show("owid cpi", "GET", "https://ourworldindata.org/grapher/ti-corruption-perception-index.csv?v=1&csvType=full&useColumnShortNames=true", 600)
show("wb wgi cc", "GET", "https://api.worldbank.org/v2/country/all/indicator/CC.EST?format=json&date=2023&per_page=5", 1200)
show("wb wgi cc 2022", "GET", "https://api.worldbank.org/v2/country/all/indicator/GOV_WGI_CC.EST?format=json&date=2023&per_page=3&source=3", 1200)
show("basel ranking", "GET", "https://index.baselgovernance.org/ranking", 1500)
show("basel api", "GET", "https://index.baselgovernance.org/api/v1/ranking", 1500)
show("fsi", "GET", "https://fsi.taxjustice.net/", 1500)
show("fsi data", "GET", "https://fsi.taxjustice.net/fsi2022/data/FSI-2022-DATA.csv", 800)
show("cpi ti xlsx page", "GET", "https://www.transparency.org/en/cpi/2024", 600)

# Lux
show("lbr", "GET", "https://www.lbr.lu/mjrcs/jsp/webapp/static/mjrcs/en/mjrcs/pdf/index.html", 300)
print(json.dumps({"done": True}))
