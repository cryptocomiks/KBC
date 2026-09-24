"""Internet Archive — Wayback Machine.

Public service, no key. For every official website found for a company of
the network (Wikidata, registries), the first and last archived captures and
a link to the full capture history. Useful to see what a company claimed
about itself at a given date, when a website appeared, or that it vanished.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse

from app.connectors.base import BaseConnector
from app.models import Document, Entity, EntityType

CDX = "https://web.archive.org/cdx/search/cdx"
HISTORY = "https://web.archive.org/web/*/{domain}"
SNAPSHOT = "https://web.archive.org/web/{ts}/{url}"
SOCIAL = (
    "x.com",
    "twitter.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "wikidata.org",
)
MAX_SITES = 2


def websites(entity: Entity) -> list[str]:
    """Official website domains known for an entity (documents or attributes), social networks excluded."""
    urls = [
        d.url for d in entity.documents if d.url and d.title.lower().startswith("official website")
    ]
    urls += [
        v for k, v in entity.extra.items() if k in ("website", "domain") and isinstance(v, str)
    ]
    out: list[str] = []
    for u in urls:
        host = (
            (urlparse(u if "://" in u else f"https://{u}").hostname or "")
            .lower()
            .removeprefix("www.")
        )
        if host and "." in host and not host.endswith(SOCIAL) and host not in out:
            out.append(host)
    return out[:MAX_SITES]


def _ts_date(ts: str) -> date | None:
    try:
        return date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
    except (ValueError, IndexError):
        return None


class WaybackConnector(BaseConnector):
    name = "wayback"
    label = "Internet Archive — Wayback Machine (website history)"
    kind = "archive"
    homepage = "https://web.archive.org"
    timeout_seconds = 8.0
    max_retries = 0

    def _capture(self, domain: str, limit: int) -> list[str] | None:
        rows: Any = self.http_get_json(
            CDX,
            params={
                "url": domain,
                "output": "json",
                "limit": limit,
                "fl": "timestamp,original,statuscode",
            },
        )
        return rows[1] if isinstance(rows, list) and len(rows) > 1 else None

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY:
            return []
        docs = []
        for domain in websites(entity):
            first, last = self._capture(domain, 1), self._capture(domain, -1)
            if not first:
                docs.append(
                    Document(
                        title=f"Website archive: {domain} — never captured",
                        kind="archive",
                        url=HISTORY.format(domain=domain),
                        source=self.label,
                    )
                )
                continue
            first_d, last_d = _ts_date(first[0]), _ts_date(last[0]) if last else None
            docs.append(
                Document(
                    title=f"Website archive: {domain} — first captured {first_d}",
                    kind="archive",
                    date=first_d,
                    url=SNAPSHOT.format(ts=first[0], url=first[1]),
                    summary=f"Last capture {last_d}. Full history: {HISTORY.format(domain=domain)}",
                    source=self.label,
                )
            )
            if last and last_d and last_d != first_d:
                docs.append(
                    Document(
                        title=f"Website archive: {domain} — latest capture",
                        kind="archive",
                        date=last_d,
                        url=SNAPSHOT.format(ts=last[0], url=last[1]),
                        source=self.label,
                    )
                )
        return docs
