"""One-off: check the Swiss official gazette (SOGC) API format (removed afterwards)."""

import json

import httpx

c = httpx.Client(headers={"User-Agent": "KYC1Click research (+https://github.com/cryptocomiks/KBC)"}, timeout=40, follow_redirects=True)
API = "https://www.amtsblattportal.ch/api/v1/publications"
for params in (
    {"text": "Glencore International AG", "rubrics": "HR", "publicationStates": "PUBLISHED", "pageRequest.size": 3, "pageRequest.sortOrders": "publicationDate:DESC"},
    {"text": "Credit Suisse", "rubrics": "KK", "publicationStates": "PUBLISHED", "pageRequest.size": 2},
    {"uid": "CHE-105.909.036", "publicationStates": "PUBLISHED", "pageRequest.size": 2},
    {"text": "Nestlé", "tenant": "shab", "publicationStates": "PUBLISHED", "pageRequest.size": 2},
):
    r = c.get(API, params=params)
    print("\n==", params, r.status_code)
    try:
        d = r.json()
        print("keys", list(d), "total", d.get("total") or d.get("totalElements"))
        for item in d.get("content", [])[:2]:
            print(json.dumps(item, ensure_ascii=False)[:2500])
    except Exception as e:  # noqa: BLE001
        print(r.text[:500], e)
r = c.get(API + "/HR02-1006123456/xml")
print("\n== xml", r.status_code, r.text[:300])
r = c.get("https://www.amtsblattportal.ch/api/v1/rubrics")
print("\n== rubrics", r.status_code, r.text[:1500])
