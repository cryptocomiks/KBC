"""Build a compact index of the EU Transparency Register (lobbying) for the app.

The Commission publishes the full register as one XML file (~120 MB, ~18,000
organisations), too large to download at each request on a serverless host. This
script, run monthly by a GitHub workflow, streams it and keeps what a KYC check needs:
register id, names, legal form, category, head-office country and city, website,
registration date, persons accredited to the European Parliament and staff (FTE).

Output: config/eu_transparency_register.json.gz
"""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

URL = "https://transparency-register.europa.eu/odplastorganisationxml_en"
OUT = Path(__file__).resolve().parent.parent / "config" / "eu_transparency_register.json.gz"
NS = "{http://intragate.ec.europa.eu/transparencyregister/odp}"


def _tag(el: ET.Element) -> str:
    return el.tag.replace(NS, "")


def _text(el: ET.Element | None, path: str) -> str:
    if el is None:
        return ""
    found = el.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def main() -> int:
    with tempfile.NamedTemporaryFile(suffix=".xml") as tmp:
        with httpx.stream("GET", URL, follow_redirects=True, timeout=300) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 20):
                tmp.write(chunk)
        tmp.flush()
        rows = []
        export_date = ""
        for _, el in ET.iterparse(tmp.name, events=("end",)):
            tag = _tag(el)
            if tag == "exportDate":
                export_date = (el.text or "")[:10]
            if tag != "interestRepresentative":
                continue
            office = el.find("headOffice")
            members = el.find("members")
            row = {
                "id": _text(el, "identificationCode"),
                "name": _text(el, "name/originalName"),
                "acronym": _text(el, "acronym"),
                "form": _text(el, "entityForm"),
                "category": _text(el, "registrationCategory"),
                "country": _text(office, "country").title(),
                "city": _text(office, "city"),
                "web": _text(el, "webSiteURL"),
                "since": _text(el, "registrationDate")[:10],
                "updated": _text(el, "lastUpdateDate")[:10],
                "ep": int(float(_text(el, "EPAccreditedNumber") or 0)),
                "fte": float(_text(members, "membersFTE") or 0) if members is not None else 0.0,
            }
            if row["id"] and row["name"]:
                rows.append({k: v for k, v in row.items() if v not in ("", 0, 0.0)})
            el.clear()
    if len(rows) < 5000:
        print(f"Only {len(rows)} organisations parsed: keeping the previous file", file=sys.stderr)
        return 1
    rows.sort(key=lambda r: r["id"])
    payload = {"source": URL, "export_date": export_date, "count": len(rows), "organisations": rows}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0: identical content gives an identical file (no commit when nothing changed)
    with gzip.GzipFile(OUT, "wb", mtime=0) as f:
        f.write(data)
    print(f"{len(rows)} organisations, export {export_date}, {OUT.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
