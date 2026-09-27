"""Temporary probe: UK individual record structure, Swiss SECO list."""

import re

import httpx

H = {"User-Agent": "KYC1CLICK-probe/1.0 (+https://kbc-lemon.vercel.app)"}
r = httpx.get("https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml", headers=H, timeout=90)
body = r.text
i = body.find("<IndividualEntityShip>Individual")
start = body.rfind("<Designation>", 0, i)
print(body[start : body.find("</Designation>", i) + 14][:6000])
print("TAGS:", sorted(set(re.findall(r"<([A-Za-z]+)>", body[:3_000_000]))))
print("designations:", body.count("<Designation>"), "individuals:", body.count("<IndividualEntityShip>Individual"))
print("ships:", body.count("<IndividualEntityShip>Ship"))
for url in (
    "https://www.sesam.search.admin.ch/sesam-search-web/pages/downloadXmlGesamtliste.xhtml?lang=en&action=downloadXmlGesamtlisteAction",
    "https://www.sesam.search.admin.ch/sesam-search-web/pages/downloadXmlGesamtliste.xhtml?lang=de&action=downloadXmlGesamtlisteAction",
):
    for attempt in range(2):
        try:
            buf = bytearray()
            with httpx.stream("GET", url, headers=H, timeout=120, follow_redirects=True) as s:
                print(url, s.status_code, s.headers.get("content-type"), s.headers.get("content-length"))
                for chunk in s.iter_bytes():
                    buf.extend(chunk)
            txt = buf.decode("utf-8", "replace")
            print("OK", len(buf))
            print(txt[:2000])
            j = txt.find("<individual")
            print(txt[j : j + 4000])
            break
        except Exception as exc:  # noqa: BLE001
            print("ERROR", attempt, type(exc).__name__, exc, "got", len(buf))
    else:
        continue
    break
