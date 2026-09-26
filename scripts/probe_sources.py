"""One-off: check candidate sources (removed afterwards)."""

import httpx

c = httpx.Client(headers={"User-Agent": "KYC1Click research (+https://github.com/cryptocomiks/KBC)"}, timeout=60, follow_redirects=True)


def show(label, url, n=900, **kw):
    try:
        r = c.get(url, **kw)
        print(f"\n== {label}: {r.status_code} {r.headers.get('content-type')} {len(r.content)}B\n{r.text[:n]}")
    except Exception as e:  # noqa: BLE001
        print(f"\n== {label}: ERROR {e!r}")


idx = c.get("https://data.opensanctions.org/datasets/latest/index.json").json()
print("== PEP datasets")
for d in sorted(idx["datasets"], key=lambda d: d["name"]):
    tags = d.get("tags") or []
    if d.get("type") != "collection" and any(t.startswith("list.pep") for t in tags):
        print(d["name"], "|", d.get("title"), "|", (d.get("things") or {}).get("total") or d.get("entity_count"), "|", d.get("publisher", {}).get("country"))
show("il_mod_crypto csv", "https://data.opensanctions.org/datasets/latest/il_mod_crypto/targets.simple.csv", n=1200)
show("crypto collection?", "https://data.opensanctions.org/datasets/latest/crypto/targets.simple.csv", n=300)
show("permid", "https://data.opensanctions.org/datasets/latest/permid/targets.simple.csv", n=600)
show("GLEIF isins", "https://api.gleif.org/api/v1/lei-records/2138002658CPO9NBH955/isins", n=800)
show("Latvia UR search", "https://data.gov.lv/dati/api/3/action/datastore_search", params={"resource_id": "25e80bf3-f107-4ab4-89ef-251b5b9374e9", "q": "Baltic", "limit": 2}, n=1500)
show("Latvia UR officers dataset", "https://data.gov.lv/dati/api/3/action/package_show", params={"id": "uzznemumu-registrs"}, n=3000)
show("Poland KRS by number", "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000019193", params={"rejestr": "P", "format": "json"}, n=10)
show("Ireland CRO", "https://services.cro.ie/cws/companies", params={"company_name": "ryanair", "format": "json"}, n=300)
show("Lithuania JAR", "https://www.registrucentras.lt/aduomenys/?byla=JAR_IREGISTRUOTI.csv", n=500)
show("Croatia sudreg", "https://sudreg-data.gov.hr/api/javni/subjekti", n=300)
show("Moldova", "https://dataset.gov.md/api/3/action/package_search", params={"q": "companii"}, n=300)
