"""One-off: read a public product page as text (removed afterwards)."""

import html
import re

import httpx

c = httpx.Client(headers={"User-Agent": "Mozilla/5.0 (Macintosh) KBC research"}, timeout=40, follow_redirects=True)
for url in (
    "https://www.legal2digital.fr/conformite/",
    "https://www.legal2digital.fr/",
    "https://www.legal2digital.fr/tarifs/",
):
    try:
        r = c.get(url)
        t = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
        t = re.sub(r"<(h[1-4]|li|p|br|div|section|a|button)[^>]*>", "\n", t, flags=re.I)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        lines = [re.sub(r"\s+", " ", x).strip() for x in t.split("\n")]
        lines = [x for i, x in enumerate(lines) if x and len(x) > 2 and x not in lines[:i]]
        print(f"\n===== {url} status {r.status_code} ({len(lines)} lines)")
        print("\n".join(lines)[:14000])
    except Exception as e:  # noqa: BLE001
        print("ERROR", url, repr(e))
