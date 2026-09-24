"""One-off look at casinosecrets.lol search results (format only)."""

import json

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping/0.1; +https://github.com/cryptocomiks/KBC)"}
c = httpx.Client(timeout=30, follow_redirects=True, headers=UA)

for q in ("softswiss", "Dama N.V.", "stake.com"):
    r = c.get("https://casinosecrets.lol/api/search.json", params={"q": q})
    print(f"\n===== q={q}: {r.status_code} {r.headers.get('content-type')} len={len(r.content)}")
    try:
        data = r.json()
        print("keys:", list(data) if isinstance(data, dict) else type(data))
        results = data.get("results", []) if isinstance(data, dict) else data
        print("count:", len(results))
        for item in results[:4]:
            print(json.dumps(item, ensure_ascii=False)[:700])
    except ValueError:
        print(r.text[:800])
r = c.get("https://casinosecrets.lol/api/search.json", params={"q": "softswiss"})
first = (r.json().get("results") or [{}])[0] if r.headers.get("content-type", "").startswith("application/json") else {}
url = first.get("url") or first.get("href") or first.get("path")
if url:
    page = c.get(url if url.startswith("http") else "https://casinosecrets.lol" + url)
    print(f"\n===== detail page {url}: {page.status_code} len={len(page.content)}")
    import re
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page.text, flags=re.S)
    print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:1500])
