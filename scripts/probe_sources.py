"""One-off look at a candidate source: what it publishes, how, and on what terms."""

import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping/0.1; +https://github.com/cryptocomiks/KBC)"}
c = httpx.Client(timeout=30, follow_redirects=True, headers=UA)
BASE = "https://casinosecrets.lol"

for path in ("/robots.txt", "/sitemap.xml", "/", "/api", "/terms", "/about"):
    try:
        r = c.get(BASE + path)
    except Exception as e:  # noqa: BLE001
        print(f"\n===== {path}: ERROR {e}")
        continue
    print(f"\n===== {path}: {r.status_code} {r.headers.get('content-type')} len={len(r.content)} final={r.url}")
    text = r.text
    if "html" in (r.headers.get("content-type") or ""):
        title = re.search(r"<title>(.*?)</title>", text, re.S)
        print("title:", title.group(1).strip() if title else None)
        meta = re.findall(r'<meta[^>]+(?:name|property)="(?:description|og:description)"[^>]+content="([^"]*)"', text)
        print("description:", meta[:2])
        body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
        body = re.sub(r"<[^>]+>", " ", body)
        print("text:", re.sub(r"\s+", " ", body)[:2500])
        links = sorted(set(re.findall(r'href="([^"#]+)"', text)))
        print("links:", links[:80])
        print("scripts:", re.findall(r'src="([^"]+\.js[^"]*)"', text)[:10])
        print("api hints:", sorted(set(re.findall(r'["\'](/api/[^"\']+|https?://[^"\']*api[^"\']*)["\']', text)))[:20])
    else:
        print(text[:2500])
