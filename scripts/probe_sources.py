"""One-off probe of candidate open sources (formats + reachability from a cloud runner)."""

import re

import httpx

SEC_UA = {"User-Agent": "KBC Corporate Mapping research-contact@kbc-mapping.org", "Accept-Encoding": "gzip, deflate"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping/0.1)"}
c = httpx.Client(timeout=30, follow_redirects=True)


def show(label, method, url, n=1500, headers=UA, **kw):
    print(f"\n===== {label}\n{method} {url}")
    try:
        r = c.request(method, url, headers=headers, **kw)
        print("status", r.status_code, r.headers.get("content-type"), "len", len(r.content))
        print(r.text[:n].replace("\n", " "))
        return r
    except Exception as e:  # noqa: BLE001
        print("ERROR", type(e).__name__, e)


# Open Ownership datasette
DS = "https://bods-data-datasette.openownership.org"
show("ds uk tables", "GET", f"{DS}/uk_version_0_4.json", 3000)
show("ds gleif tables", "GET", f"{DS}/gleif_version_0_4.json", 1500)
for t in ("entity_statement", "person_statement", "ownership_or_control_statement"):
    show(f"ds uk {t} sample", "GET", f"{DS}/uk_version_0_4/{t}.json?_size=1&_shape=objects", 2500)
show("ds uk search entity", "GET", f"{DS}/uk_version_0_4/entity_statement.json?_search=TESCO&_size=3&_shape=objects", 1500)
show("ds uk sql", "GET", f"{DS}/uk_version_0_4.json", 800,
     params={"sql": "select * from entity_statement where name like 'TESCO PLC' limit 2", "_shape": "objects"})
for t in ("ownership_or_control_statement_interests", "person_statement_names", "person_statement_nationalities", "entity_statement_identifiers"):
    show(f"ds uk {t} sample", "GET", f"{DS}/uk_version_0_4/{t}.json?_size=2&_shape=objects", 1500)

# SEC: efts by cik, entity suggestions, 13G XML
show("efts keysTyped", "GET", "https://efts.sec.gov/LATEST/search-index?keysTyped=tesla", 1500, headers=SEC_UA)
show("efts ciks filter", "GET", "https://efts.sec.gov/LATEST/search-index?q=&forms=SCHEDULE%2013G,SCHEDULE%2013D,SC%2013G,SC%2013D&ciks=0000320193", 1500, headers=SEC_UA)
show("13G xml", "GET", "https://www.sec.gov/Archives/edgar/data/1318605/000110465926075203/primary_doc.xml", 4000, headers=SEC_UA)
show("filing index json", "GET", "https://www.sec.gov/Archives/edgar/data/1318605/000110465926075203/index.json", 1500, headers=SEC_UA)

# Basel table rows
r = show("basel", "GET", "https://index.baselgovernance.org/ranking", 10)
if r is not None:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S)
    print("rows:", len(rows))
    for row in rows[:3] + rows[-2:]:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        print(cells)
    print(re.findall(r"<th[^>]*>(.*?)</th>", r.text, re.S)[:8])
    m = re.search(r"(20\d\d) Basel AML Index|Basel AML Index (20\d\d)", r.text)
    print("edition:", m.group(0) if m else None)
