"""Temporary probe of candidate sources (removed after use)."""

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 (compliance research)", "Accept": "*/*"}
LW = "https://cms.lobbywatch.ch/de/data/interface/v1/json"

with httpx.Client(headers=H, timeout=60, follow_redirects=True) as c:
    orgs = c.get(f"{LW}/table/organisation/flat/list/Raiffeisen").json().get("data") or []
    print("orgs:", [(o["id"], o["name"], o.get("uid")) for o in orgs])
    for o in orgs[:4]:
        d = c.get(f"{LW}/table/organisation/aggregated/id/{o['id']}").json().get("data") or {}
        for k in ("parlamentarier", "zutrittsberechtigte"):
            rows = d.get(k) or []
            print(f"\n## {o['name']} {k}: {len(rows)}")
            if rows:
                print({kk: (str(v)[:60] if v is not None else None) for kk, v in rows[0].items()})
    t = c.get("https://www.esma.europa.eu/sites/default/files/2024-12/NCASP.csv").text
    print("\n## NCASP", len(t))
    print("\n".join(t.splitlines()[:4]))
    for path in ("pir-api/search?name=Revolut", "pir-api/entities?name=Revolut", "pir-api/institutions?searchText=Revolut",
                 "api/search?name=Revolut", "pir-api/search/entities?name=Revolut", "pir-api/"):
        r = c.get("https://euclid.eba.europa.eu/register/" + path)
        print(f"\n## eba {path}: {r.status_code} {r.headers.get('content-type')} {r.text[:200]!r}")
