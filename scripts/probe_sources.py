"""One-off probe of candidate open sources (formats + reachability from a cloud runner)."""

import re

import httpx

SEC_UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept-Encoding": "gzip, deflate"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping/0.1)"}
c = httpx.Client(timeout=30, follow_redirects=True)


def show(label, method, url, n=1500, headers=UA, **kw):
    print(f"\n===== {label}\n{method} {url}")
    try:
        r = c.request(method, url, headers=headers, **kw)
        print("status", r.status_code, r.headers.get("content-type"), "len", len(r.content))
        print(r.text[:n].replace("\n", " "))
        return r
    except Exception as e:  # noqa: BLE001
        print("ERROR", type(e).__name__, e)


# SEC with a declared user agent
show("sec tickers", "GET", "https://www.sec.gov/files/company_tickers.json", 300, headers=SEC_UA)
r = show("sec efts 13G", "GET", "https://efts.sec.gov/LATEST/search-index?q=%22Tesla%22&forms=SC%2013G,SC%2013D,SCHEDULE%2013G,SCHEDULE%2013D", 2500, headers=SEC_UA)
show("sec efts full text", "GET", "https://efts.sec.gov/LATEST/search-index?q=%22Tesla%2C%20Inc.%22&dateRange=custom&forms=SCHEDULE%2013G", 1500, headers=SEC_UA)
r = show("sec companyfacts", "GET", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001318605.json", 200, headers=SEC_UA)
if r is not None and r.status_code == 200:
    f = r.json()["facts"]
    for k in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss", "Assets", "StockholdersEquity"):
        v = f.get("us-gaap", {}).get(k, {}).get("units", {}).get("USD", [])
        print(k, [x for x in v if x.get("form") == "10-K" and x.get("fp") == "FY"][-2:])
    print("dei", {k: list(v["units"].values())[0][-1] for k, v in f.get("dei", {}).items()})
r = show("sec submissions", "GET", "https://data.sec.gov/submissions/CIK0001318605.json", 1200, headers=SEC_UA)
if r is not None and r.status_code == 200:
    j = r.json()
    rec = j["filings"]["recent"]
    print({k: j.get(k) for k in ("name", "sic", "sicDescription", "stateOfIncorporation", "addresses", "formerNames", "ein", "category")})
    print([(rec["form"][i], rec["filingDate"][i], rec["accessionNumber"][i], rec["primaryDocument"][i]) for i in range(8)])

# Zefix detail
for path in ("firm/126286.json", "firm/126286/withoutShabPub.json", "firm/126286/shabPub.json", "sogc/firm/126286/publications.json"):
    show(f"zefix {path}", "GET", f"https://www.zefix.admin.ch/ZefixREST/api/v1/{path}", 3000)
show("zefix legal forms", "GET", "https://www.zefix.admin.ch/ZefixREST/api/v1/legalForm.json", 1200)
show("zefix person search", "POST", "https://www.zefix.admin.ch/ZefixREST/api/v1/firm/search.json", 800,
     json={"name": "Nestlé", "languageKey": "en", "maxEntries": 2, "offset": 0})

# Basel AML Index: look for embedded data
r = show("basel ranking", "GET", "https://index.baselgovernance.org/ranking", 100)
if r is not None:
    t = r.text
    for m in re.finditer(r"Switzerland|Luxembourg|Haiti", t):
        print("ctx:", t[max(0, m.start() - 300): m.start() + 300].replace("\n", " "))
        break
    print("scripts:", re.findall(r'src="([^"]+\.js)"', t)[:10])
    print("api hints:", sorted(set(re.findall(r'https?://[a-z0-9.-]*baselgovernance[^"\' ]*', t)))[:20])
    print("json-ish:", re.findall(r'"(?:score|overall_score|rank)"\s*:\s*[0-9.]+', t)[:10])

# FSI downloads
r = show("fsi", "GET", "https://fsi.taxjustice.net/", 100)
if r is not None:
    print("links:", sorted(set(l for l in re.findall(r'href="([^"]+)"', r.text) if re.search(r"(xlsx|csv|download|data|ranking)", l, re.I)))[:30])
r = show("fsi ranking", "GET", "https://fsi.taxjustice.net/fsi2025/ranking", 100)
r = show("tjn data portal", "GET", "https://data.taxjustice.net/", 600)

# Open Ownership bulk datasets
r = show("oo index", "GET", "https://bods-data.openownership.org/", 100)
if r is not None:
    print("links:", sorted(set(re.findall(r'href="([^"]+)"', r.text)))[:60])
