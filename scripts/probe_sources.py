"""One-off probe of candidate public sources (removed once the connectors are written). Round 3."""

import re

import httpx

UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept": "application/json, */*"}
c = httpx.Client(headers=UA, timeout=40, follow_redirects=True)


def main_html(label, url, start_marker, n=6000, **kw):
    print(f"\n===== {label}\nGET {url} {kw.get('params') or ''}")
    try:
        r = c.get(url, headers={"Accept": "text/html"}, **kw)
        t = r.text
        i = t.find(start_marker)
        print(f"status {r.status_code} · {len(t)} chars · marker at {i}")
        body = t[i if i >= 0 else 0:]
        body = re.sub(r"\s+", " ", body)
        print(body[:n])
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))


CH = "https://find-and-update.company-information.service.gov.uk"
main_html("CH overview OE", f"{CH}/company/OE000001", '<main', n=4000)
main_html("CH officers OE", f"{CH}/company/OE000001/officers", 'appointments-list', n=5000)
main_html("CH PSC OE (registrable beneficial owners)", f"{CH}/company/OE000001/persons-with-significant-control", '<main', n=7000)
main_html("CH officers Tesco", f"{CH}/company/00445790/officers", 'officer-name-1', n=3000)
main_html("CH PSC Tesco", f"{CH}/company/00445790/persons-with-significant-control", 'psc-name-1', n=3000)
r = c.get(f"{CH}/search/officers", params={"q": "Alisher Usmanov"})
print("\n===== CH officer search JSON", r.status_code, r.text[:1500])
link = None
try:
    link = next((i["links"]["self"] for i in r.json().get("items", [])), None)
except Exception:  # noqa: BLE001
    pass
if link:
    main_html("CH officer appointments", CH + link, 'appointment-1', n=3000)

RP = "https://rpvs.gov.sk/opendatav2"
for path, params in (
    ("/PartneriVerejnehoSektora(137929)", {"$expand": "Partner"}),
    ("/Partneri(137929)", {"$expand": "KonecniUzivateliaVyhod"}),
    ("/PartneriVerejnehoSektora", {"$filter": "Ico eq '31335853'", "$expand": "Partner($expand=KonecniUzivateliaVyhod,OpravneneOsoby)"}),
):
    try:
        r = c.get(RP + path, params=params)
        print(f"\n===== RPVS {path} {params}\nstatus {r.status_code}\n{r.text[:2500]}")
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))
