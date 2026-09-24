"""One-off look at candidate sources: content, structure, terms."""

import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping/0.1; +https://github.com/cryptocomiks/KBC)"}
c = httpx.Client(timeout=30, follow_redirects=True, headers=UA)
BASE = "https://casinosecrets.lol"


def show(label, url, n=1500, **kw):
    print(f"\n===== {label}: {url}")
    try:
        r = c.get(url, **kw)
        print("status", r.status_code, r.headers.get("content-type"), "len", len(r.content))
        print(r.text[:n])
        return r
    except Exception as e:  # noqa: BLE001
        print("ERROR", e)


r = show("robots (full)", f"{BASE}/robots.txt", 6000)
home = c.get(BASE + "/").text
for js in re.findall(r'src="(/_astro/[^"]+\.js)"', home):
    code = c.get(BASE + js).text
    print(f"\n===== bundle {js} len={len(code)}")
    print("fetch urls:", sorted(set(re.findall(r'["`\'](/[a-z0-9_\-/]*(?:search|api|query|index|data)[a-z0-9_\-/.?=]*)["`\']', code, re.I)))[:30])
    print("abs urls:", sorted(set(re.findall(r'https?://[a-zA-Z0-9.\-]+(?:/[^\s"\'`)]*)?', code)))[:30])
    for m in re.finditer(r"fetch\(", code):
        print("fetch ctx:", code[max(0, m.start() - 150): m.start() + 250].replace("\n", " "))
        break
for path in ("/search?q=softswiss", "/search.json?q=softswiss", "/api/search?q=softswiss", "/pagefind/pagefind-entry.json", "/companies", "/domains"):
    show(path, BASE + path, 600)

# Wayback Machine, certificate transparency, RDAP, gambling registers
show("wayback available", "https://archive.org/wayback/available?url=totalenergies.com", 600)
show("wayback cdx first/last", "https://web.archive.org/cdx/search/cdx?url=totalenergies.com&output=json&limit=1&fl=timestamp,original,statuscode", 600)
show("wayback cdx last", "https://web.archive.org/cdx/search/cdx?url=totalenergies.com&output=json&limit=-1&fl=timestamp,original,statuscode", 600)
show("crt.sh", "https://crt.sh/?q=%25.stake.com&output=json", 800)
show("rdap", "https://rdap.org/domain/stake.com", 1500)
show("ukgc register", "https://www.gamblingcommission.gov.uk/public-register/businesses/download", 800)
show("mga register", "https://www.mga.org.mt/licensee-hub/licensee-register/", 800)
