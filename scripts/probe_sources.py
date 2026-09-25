"""One-off probe of financial regulators' registers, round 3: field names."""

import re

import httpx

UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept": "application/json, */*"}
c = httpx.Client(headers=UA, timeout=40, follow_redirects=True)


def show(label, url, n=2200, **params):
    print(f"\n===== {label}\nGET {url} {params}")
    try:
        r = c.get(url, params=params)
        print(f"status {r.status_code} · {r.headers.get('content-type')} · {len(r.content)} bytes")
        print(re.sub(r"\s+", " ", r.text)[:n])
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))


CSSF = "https://edesk.apps.cssf.lu/search-entities-api/api/v1/entite"
for p in ({"page": 0, "size": 2, "nom": "Amazon"}, {"page": 0, "size": 2, "name": "Amazon"}, {"page": 0, "size": 2, "search": "Amazon"}, {"page": 0, "size": 2, "q": "Amazon"}, {"page": 0, "size": 2, "denomination": "Amazon"}):
    show(f"CSSF {list(p)[-1]}", CSSF, n=1200, **p)

page = c.get("https://registers.esma.europa.eu/publication/searchRegister", params={"core": "esma_registers_upreg"}).text
print("\n===== ESMA cores on the page:", sorted(set(re.findall(r"esma_registers_[a-z0-9_]+", page)))[:40])
show("ESMA upreg parent doc", "https://registers.esma.europa.eu/solr/esma_registers_upreg/select", n=3000, q="type_s:parent", rows=1, wt="json")
show("ESMA upreg Revolut", "https://registers.esma.europa.eu/solr/esma_registers_upreg/select", n=2500, q="ae_entityName:*Revolut*", rows=2, wt="json")
for core in ("esma_registers_casp", "esma_registers_mica_casp", "esma_registers_micacasp", "esma_registers_crypto"):
    show(f"ESMA {core}", f"https://registers.esma.europa.eu/solr/{core}/select", n=1500, q="*:*", rows=1, wt="json")

R = "https://www.regafi.fr/api/explore/v2.1/catalog/datasets/{ds}/records"
show("REGAFI banque entites", R.format(ds="prd-banque-entites"), n=2500, where='search("Revolut")', limit=2)
show("REGAFI banque autorisations", R.format(ds="prd-banque-autorisations"), n=2000, limit=1)
show("REGAFI assurance entites", R.format(ds="prd-assurance-entites"), n=1500, where='search("AXA")', limit=1)
