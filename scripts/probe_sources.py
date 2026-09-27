"""Temporary probe: official EU, UK and Swiss sanctions list downloads."""

import re

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 (+https://kbc-lemon.vercel.app)"}
URLS = [
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
    "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
    "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml",
    "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv",
    "https://www.gov.uk/government/publications/the-uk-sanctions-list",
    "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.xml",
    "https://www.sesam.search.admin.ch/sesam-search-web/pages/downloadXmlGesamtliste.xhtml?lang=en&action=downloadXmlGesamtlisteAction",
]
for url in URLS:
    print("=" * 100)
    print(url)
    try:
        r = httpx.get(url, headers=H, timeout=90, follow_redirects=True)
        body = r.text
        print(r.status_code, r.headers.get("content-type"), len(r.content), "bytes", "final:", r.url)
        if "gov.uk/government" in url:
            for m in sorted(set(re.findall(r'href="([^"]+\.(?:xml|csv|ods|xlsx|json))"', body)))[:30]:
                print("  link:", m)
            continue
        print(body[:2500])
        for tag in ("sanctionEntity", "Designation", "FinancialSanctionsTarget", "individual", "entity", "target"):
            i = body.find("<" + tag)
            if i >= 0:
                print(f"--- first <{tag}> ---")
                print(body[i : i + 3500])
                break
    except Exception as exc:  # noqa: BLE001
        print("ERROR", type(exc).__name__, exc)
