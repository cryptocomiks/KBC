"""End-to-end smoke test of a deployed KBC instance (stdlib only).

    python scripts/smoke_test.py https://kbc-lemon.vercel.app [--live]

Checks the API health, the connectors, a demo search with homonyms, a full
investigation and the PDF report. Exits non-zero on the first failure, with
the server's error message (the API returns readable JSON errors).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def call(base: str, path: str, body: dict | None = None) -> tuple[int, bytes, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "kbc-smoke-test"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    if not ok:
        sys.exit(1)


def main(base: str) -> None:
    for attempt in range(6):  # the deployment may need a few seconds to warm up
        status, body, _ = call(base, "/api/health")
        if status == 200:
            break
        time.sleep(10)
    check("GET /api/health", status == 200, body[:300].decode(errors="replace"))

    status, body, _ = call(base, "/api/connectors")
    rows = json.loads(body) if status == 200 else []
    enabled = [r["name"] for r in rows if r["enabled"]]
    check("GET /api/connectors", status == 200 and len(enabled) >= 1, f"enabled: {enabled}")

    status, body, _ = call(base, "/api/search?" + urllib.parse.urlencode({"q": "Mohamed Qadrany", "type": "person"}))
    check("GET /api/search", status == 200, body[:300].decode(errors="replace"))
    candidates = json.loads(body)["candidates"]
    names = [c["entity"]["name"] for c in candidates]
    check("search returns candidates", len(candidates) >= 1, f"{names}")

    params = {"record_ids": candidates[0]["entity"]["record_ids"], "depth": 3, "max_nodes": 60}
    status, body, _ = call(base, "/api/investigations", params)
    check("POST /api/investigations", status == 200, body[:300].decode(errors="replace") if status != 200 else "")
    inv = json.loads(body)
    check("investigation content", len(inv["entities"]) > 3,
          f"{len(inv['entities'])} entities, risk {inv['risk']['score']} ({inv['risk']['level']})")

    status, body, ctype = call(base, "/api/reports/pdf", params)
    check("POST /api/reports/pdf", status == 200 and body.startswith(b"%PDF"), f"{len(body)} bytes, {ctype}")

    if "--live" in sys.argv:
        check_live(base)

    if "localhost" not in base:  # a local API run has no frontend
        status, body, ctype = call(base, "/")
        check("GET / (frontend)", status == 200 and b'<div id="root">' in body, ctype)
    print("All smoke tests passed.")


def check_live(base: str) -> None:
    """Real public sources: company search on data.gouv.fr + ICIJ leaks screening."""
    status, body, _ = call(base, "/api/connectors")
    live = [r["name"] for r in json.loads(body) if r["enabled"] and not r["demo"]]
    check("live connectors enabled", bool(live), f"{live}")

    status, body, _ = call(base, "/api/search?" + urllib.parse.urlencode({"q": "TotalEnergies", "type": "company"}))
    data = json.loads(body) if status == 200 else {}
    real = [c for c in data.get("candidates", []) if not c["entity"]["demo"]]
    check("live search (TotalEnergies)", status == 200 and bool(real),
          f"{len(real)} real candidates; warnings: {data.get('warnings')}")

    params = {"record_ids": real[0]["entity"]["record_ids"], "depth": 1, "max_nodes": 20}
    status, body, _ = call(base, "/api/investigations", params)
    check("live investigation", status == 200, body[:300].decode(errors="replace") if status != 200 else "")
    inv = json.loads(body)
    errors = [f"{q['source']}.{q['operation']}: {q['error']}" for q in inv["queries"] if q["error"]]
    sources = sorted({q["source"] for q in inv["queries"]})
    print(f"      sources queried: {sources}; entities: {len(inv['entities'])}; hits: {len(inv['hits'])}")
    for h in inv["hits"][:5]:
        print(f"      hit: {h['list_type']} {h['matched_name']} ({h['dataset']}, {h['score']})")
    check("live sources answered without error", not errors, "; ".join(errors[:5]))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "http://localhost:8000")
