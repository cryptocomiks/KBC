"""One-off: read a design guideline page (text only)."""

import html
import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; KBC-corporate-mapping/0.1)"}
c = httpx.Client(timeout=30, follow_redirects=True, headers=UA)
for url in (
    "https://www.ui-skills.com/skills/emilkowalski/apple-design",
    "https://raw.githubusercontent.com/emilkowalski/skills/main/apple-design/SKILL.md",
    "https://raw.githubusercontent.com/emilkowalski/skill/main/skills/apple-design/SKILL.md",
):
    r = c.get(url)
    print(f"\n===== {url}: {r.status_code} len={len(r.text)}")
    if r.status_code != 200:
        continue
    t = r.text
    if "<html" in t[:500].lower():
        m = re.search(r"<main.*?</main>", t, re.S) or re.search(r"<body.*?</body>", t, re.S)
        t = m.group(0) if m else t
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
        t = re.sub(r"<(h[1-6]|p|li|pre|code|br|div)[^>]*>", "\n", t)
        t = html.unescape(re.sub(r"<[^>]+>", "", t))
        t = re.sub(r"\n\s*\n+", "\n", t)
    print(t[:20000])
    links = sorted(set(re.findall(r'https://github\.com/[^"\'\s<>]+', r.text)))[:20]
    print("github links:", links)
