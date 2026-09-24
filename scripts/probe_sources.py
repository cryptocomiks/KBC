"""One-off probe of candidate public sources (removed once the connectors are written). Round 4."""

import re

import httpx

UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept": "application/json, */*"}
c = httpx.Client(headers=UA, timeout=40, follow_redirects=True)
RP = "https://rpvs.gov.sk/opendatav2"
for path, params in (
    ("/Partneri(33216)", {"$expand": "KonecniUzivateliaVyhod,OpravneneOsoby,PartneriVerejnehoSektora"}),
    ("/Partneri(33216)/KonecniUzivateliaVyhod", {}),
    ("/KonecniUzivateliaVyhod", {"$filter": "contains(Priezvisko,'Kmotrík')"}),
):
    try:
        r = c.get(RP + path, params=params)
        print(f"\n===== RPVS {path} {params}\nstatus {r.status_code}\n{r.text[:3000]}")
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))

CH = "https://find-and-update.company-information.service.gov.uk"
for number in ("OE000001", "OE000123", "09446231", "SC005336"):
    r = c.get(f"{CH}/company/{number}/persons-with-significant-control", headers={"Accept": "text/html"})
    t = re.sub(r"<svg.*?</svg>", "", re.sub(r"\s+", " ", r.text))
    i = t.find('id="company-number"')
    j = t.find("psc-name-1") if "psc-name-1" in t else t.find('class="appointment-1"')
    print(f"\n===== CH PSC {number} status {r.status_code} len {len(t)} first-psc-at {j}")
    print(t[max(j - 400, i): max(j - 400, i) + 5000])
