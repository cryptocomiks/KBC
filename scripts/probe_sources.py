"""Temporary probe (GitHub Actions): status and a sample of each candidate source."""

import json

import httpx

UA = {"User-Agent": "KYC1CLICK-probe/1.0 (+https://kbc-lemon.vercel.app)"}
with httpx.Client(timeout=60, follow_redirects=True, headers=UA) as c:
    r = c.get("https://data.europa.eu/api/hub/search/datasets/transparency-register")
    for d in r.json()["result"].get("distributions", []):
        print("DIST", (d.get("title") or {}).get("en"), d.get("format", {}).get("id"), d.get("access_url"), d.get("download_url"))
    r = c.get("https://opendata.cro.ie/api/3/action/datastore_search", params={"resource_id": "3fef41bc-b8f4-4b10-8434-ce51c29b1bba", "q": "Ryanair", "limit": 3})
    print("\n=== cro datastore", r.status_code, r.text[:3000])
    r = c.get("https://opendata.cro.ie/api/3/action/datastore_search", params={"resource_id": "3fef41bc-b8f4-4b10-8434-ce51c29b1bba", "filters": json.dumps({"company_num": 104547}), "limit": 2})
    print("\n=== cro datastore filter", r.status_code, r.text[:1500])
    r = c.get("https://opendata.cro.ie/api/3/action/package_show", params={"id": "financial-statements"})
    for res in r.json()["result"]["resources"]:
        print("FS", res.get("name"), res.get("format"), res.get("url"), res.get("datastore_active"), res.get("id"))
