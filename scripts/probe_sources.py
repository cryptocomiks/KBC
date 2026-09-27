"""Temporary probe of candidate sources (removed after use)."""

import re

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 (compliance research)", "Accept": "*/*"}
LW = "https://cms.lobbywatch.ch/de/data/interface/v1/json"
GETS = [
    ("lw org aggregated", f"{LW}/table/organisation/aggregated/id/8765"),
    ("lw parl by name", f"{LW}/table/parlamentarier/flat/list/Pfister"),
    ("lw zutrittsberechtigung", f"{LW}/table/zutrittsberechtigung/flat/list/Meier"),
    ("lw person", f"{LW}/table/person/flat/list/Meier"),
    ("lw parl aggregated", f"{LW}/table/parlamentarier/aggregated/id/1"),
    ("six v3 json", "https://api.six-group.com/api/epcd/bankmaster/v3/bankmaster.json"),
    ("six v3 csv", "https://api.six-group.com/api/epcd/bankmaster/v3/bankmaster.csv"),
    ("six v2 json", "https://api.six-group.com/api/epcd/bankmaster/v2/bankmaster.json"),
    ("asic banned pkg", "https://data.gov.au/data/api/3/action/package_search?q=ASIC%20banned%20disqualified%20persons&rows=5"),
]


def show(name, r, n=900):
    print(f"\n### {name}: {r.status_code} {r.headers.get('content-type','')} {len(r.content)}B final={r.url}")
    print(r.text[:n].replace("\n", " "))


with httpx.Client(headers=H, timeout=60, follow_redirects=True) as c:
    for name, url in GETS:
        try:
            r = c.get(url)
            if name == "asic banned pkg" and r.status_code == 200:
                for p in r.json()["result"]["results"]:
                    print("\nPKG", p["name"], "|", p["title"])
                    for res in p.get("resources", []):
                        print("   RES", res.get("format"), res.get("url"))
            else:
                show(name, r)
        except Exception as e:  # noqa: BLE001
            print(f"\n### {name}: ERROR {type(e).__name__}: {e}")
    # ESMA MiCA interim register: CSV links on the MiCA page
    try:
        page = c.get("https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica").text
        links = sorted(set(re.findall(r'href="([^"]+\.(?:csv|xlsx)[^"]*)"', page)))
        print("\n### esma mica links:", links[:20])
        for l in links:
            if "casp" in l.lower():
                u = l if l.startswith("http") else "https://www.esma.europa.eu" + l
                show("esma casp csv", c.get(u), 1200)
                break
    except Exception as e:  # noqa: BLE001
        print("esma ERROR", e)
    # SPA apps: find the API base in the JS bundles
    for name, base, page in (
        ("eba", "https://euclid.eba.europa.eu/register/", "https://euclid.eba.europa.eu/register/pir/search"),
        ("comp", "https://competition-cases.ec.europa.eu/", "https://competition-cases.ec.europa.eu/search"),
    ):
        try:
            html = c.get(page).text
            for js in re.findall(r'src="([^"]*main[^"]*\.js)"', html):
                src = c.get(base + js).text
                hits = sorted(set(re.findall(r'["\'`]((?:https?://[^"\'`]*)?/?(?:api|rest|service|register/api)[^"\'`\s]{0,90})["\'`]', src)))
                print(f"\n### {name} js {js} {len(src)}B api strings:", hits[:60])
        except Exception as e:  # noqa: BLE001
            print(name, "ERROR", e)
