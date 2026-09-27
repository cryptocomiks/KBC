"""Temporary probe (GitHub Actions): transparency register latest XML structure."""

import httpx

UA = {"User-Agent": "KYC1CLICK-probe/1.0 (+https://kbc-lemon.vercel.app)"}
with httpx.Client(timeout=120, follow_redirects=True, headers=UA) as c:
    for url in ("https://transparency-register.europa.eu/odplastorganisationxml_en", "https://transparency-register.europa.eu/odplastorganisationxls_en"):
        r = c.get(url)
        print("\n===", url, r.status_code, r.headers.get("content-type"), len(r.content), r.url)
        if "xml" in (r.headers.get("content-type") or "") or r.content[:5] == b"<?xml":
            t = r.text
            print(t[:6000])
            print("...COUNT interestRepresentative:", t.count("<interestRepresentative"), t.count("<identificationCode>"))
    r = c.get("https://opendata.cro.ie/api/3/action/datastore_search", params={"resource_id": "4dc79788-845b-4373-aaf9-77be6feb049b", "q": "Ryanair", "limit": 2})
    print("\n=== cro fs", r.status_code, r.text[:2500])
