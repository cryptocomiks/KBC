"""One-off probe of financial regulators' registers, round 2: find the APIs behind the web apps."""

import re

import httpx

UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept": "application/json, text/html, */*"}
c = httpx.Client(headers=UA, timeout=40, follow_redirects=True)


def show(label, method, url, n=1500, **kw):
    print(f"\n===== {label}\n{method} {url} {kw.get('params') or ''} {kw.get('json') or ''}")
    try:
        r = c.request(method, url, **kw)
        print(f"status {r.status_code} · {r.headers.get('content-type')} · {len(r.content)} bytes")
        print(re.sub(r"\s+", " ", r.text)[:n])
        return r
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))


def api_strings(label, page_url, base):
    print(f"\n===== API strings in {label}")
    try:
        html = c.get(page_url).text
        scripts = re.findall(r'src="([^"]+\.js)"', html)
        found = set()
        for s in scripts[:6]:
            url = s if s.startswith("http") else base + ("" if s.startswith("/") else "/") + s
            js = c.get(url).text
            found |= set(re.findall(r'["\'`](/?(?:api|rest|services|solr|search)[A-Za-z0-9_/\-.?=&{}$]*)["\'`]', js))
            found |= set(re.findall(r'["\'`](https?://[a-z0-9.\-]+/[A-Za-z0-9_/\-.]*(?:api|solr|rest)[A-Za-z0-9_/\-.]*)["\'`]', js))
        for f in sorted(found)[:60]:
            print("  ", f)
    except Exception as e:  # noqa: BLE001
        print("ERROR", repr(e))


api_strings("CSSF search-entities", "https://edesk.apps.cssf.lu/search-entities/search?lng=en", "https://edesk.apps.cssf.lu")
api_strings("EBA EUCLID", "https://euclid.eba.europa.eu/register/pir/search", "https://euclid.eba.europa.eu/register")
api_strings("ESMA registers", "https://registers.esma.europa.eu/publication/", "https://registers.esma.europa.eu")
show("FINMA search POST", "POST", "https://www.finma.ch/en/api/search/getresult", data={"query": "UBS", "Order": "4", "pageSize": "3"})
show("REGAFI opendatasoft catalog", "GET", "https://www.regafi.fr/api/explore/v2.1/catalog/datasets", params={"limit": 20, "select": "dataset_id"}, n=2500)
show("ESMA solr upreg", "GET", "https://registers.esma.europa.eu/solr/esma_registers_upreg/select", params={"q": "*:*", "rows": 1, "wt": "json"})
show("ESMA publication search", "GET", "https://registers.esma.europa.eu/publication/searchRegister", params={"core": "esma_registers_mica_casp"}, n=800)
