"""Temporary probe (GitHub Actions): status and a sample of each candidate source."""

import httpx

UA = {"User-Agent": "KYC1CLICK-probe/1.0 (+https://kbc-lemon.vercel.app)"}
PROBES = [
    ("shab search json", "https://amtsblattportal.ch/api/v1/publications?keyword=Swissair&pageRequest.page=0&pageRequest.size=3", {"Accept": "application/json"}),
    ("shab search json 2", "https://amtsblattportal.ch/api/v1/publications?publicationStates=PUBLISHED&keyword=Konkurs&pageRequest.page=0&pageRequest.size=2", {"Accept": "application/json"}),
    ("shab uid", "https://amtsblattportal.ch/api/v1/publications?uid=CHE-105.815.381&pageRequest.page=0&pageRequest.size=3", {"Accept": "application/json"}),
    ("vies get", "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/FR/vat/40303265045", {}),
    ("vies get DE", "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/IE/vat/6388047V", {}),
    ("gazette json", "https://www.thegazette.co.uk/all-notices/notice/data.json?text=carillion&results-page-size=2", {}),
    ("gazette insolvency", "https://www.thegazette.co.uk/insolvency/notice/data.json?text=carillion&results-page-size=2", {}),
    ("rdap", "https://rdap.org/domain/wirecard.com", {}),
    ("caselaw atom", "https://caselaw.nationalarchives.gov.uk/atom.xml?query=carillion", {}),
    ("gnews rss", "https://news.google.com/rss/search?q=%22Wirecard%22+fraud&hl=en-US&gl=US&ceid=US:en", {}),
    ("eu hub search", "https://data.europa.eu/api/hub/search/search?q=transparency%20register&filter=dataset&limit=3", {}),
    ("tr xml legacy", "https://ec.europa.eu/transparencyregister/public/consultation/statistics.do?action=getLobbyistsXml&fileType=NEW", {}),
    ("tr search", "https://transparency-register.europa.eu/searchregister-or-update/search-register_en", {}),
    ("cro ckan list", "https://opendata.cro.ie/api/3/action/package_list", {}),
    ("cro ckan show", "https://opendata.cro.ie/api/3/action/package_search?q=companies&rows=3", {}),
    ("datagovie cro", "https://data.gov.ie/api/3/action/package_search?q=companies%20registration%20office&rows=3", {}),
]
with httpx.Client(timeout=40, follow_redirects=True, headers=UA) as c:
    for name, url, h in PROBES:
        try:
            r = c.get(url, headers=h)
            body = r.text
            print(f"\n=== {name} {r.status_code} {r.headers.get('content-type')} len={len(body)} final={r.url}")
            print(body[:1800])
        except Exception as exc:  # noqa: BLE001
            print(f"\n=== {name} ERROR {exc!r}")
