"""Temporary probe (GitHub Actions): status and a sample of each candidate source."""

import httpx

UA = {"User-Agent": "KYC1CLICK-probe/1.0 (+https://kbc-lemon.vercel.app)"}
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36", "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
PROBES = [
    ("cro package", "https://opendata.cro.ie/api/3/action/package_show?id=companies", {}),
    ("gazette browser json", "https://www.thegazette.co.uk/all-notices/notice/data.json?text=carillion&results-page-size=2", BROWSER),
    ("gazette browser feed", "https://www.thegazette.co.uk/all-notices/notice/data.feed?text=carillion", BROWSER),
    ("gazette plain", "https://www.thegazette.co.uk/all-notices/notice?text=carillion", BROWSER),
    ("tr hub", "https://data.europa.eu/api/hub/search/search?q=%22transparency%20register%22%20lobby&filter=dataset&limit=3&facets=%7B%22publisher%22%3A%5B%5D%7D", {}),
    ("tr hub id", "https://data.europa.eu/api/hub/search/datasets/transparency-register", {}),
    ("tr hub id2", "https://data.europa.eu/api/hub/search/datasets/eu-transparency-register", {}),
    ("tr opendata page", "https://transparency-register.europa.eu/search-register-or-update/open-data_en", {}),
    ("tr api search", "https://ec.europa.eu/transparencyregister/public/api/search?query=google", {}),
    ("shab detail xml", "https://amtsblattportal.ch/api/v1/publications/a24d7dcd-d818-49b9-ada8-8d625e7401a2/xml", {}),
    ("shab search HR", "https://amtsblattportal.ch/api/v1/publications?publicationStates=PUBLISHED&keyword=Swissport&rubrics=HR&pageRequest.page=0&pageRequest.size=3", {"Accept": "application/json"}),
    ("shab search KK", "https://amtsblattportal.ch/api/v1/publications?publicationStates=PUBLISHED&keyword=GmbH&rubrics=KK&pageRequest.page=0&pageRequest.size=2", {"Accept": "application/json"}),
]
with httpx.Client(timeout=40, follow_redirects=True, headers=UA) as c:
    for name, url, h in PROBES:
        try:
            r = c.get(url, headers=h)
            body = r.text
            print(f"\n=== {name} {r.status_code} {r.headers.get('content-type')} len={len(body)} final={r.url}")
            if name == "tr opendata page":
                import re
                print("\n".join(sorted(set(re.findall(r'href="([^"]+(?:xml|csv|xlsx|zip|json)[^"]*)"', body)))[:40]))
            elif name == "cro package":
                import json
                d = json.loads(body)["result"]
                for res in d["resources"]:
                    print(res.get("name"), res.get("format"), res.get("url"), res.get("datastore_active"), res.get("id"), res.get("size"))
            else:
                print(body[:2500])
        except Exception as exc:  # noqa: BLE001
            print(f"\n=== {name} ERROR {exc!r}")
