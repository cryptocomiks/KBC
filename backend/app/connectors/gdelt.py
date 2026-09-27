"""Adverse media — press mentions of the subject with financial-crime keywords (no key).

GDELT DOC 2.0 API (open news index). It allows one request every 5 s per IP address and
answers HTTP 429 to shared cloud IPs, so it is not retried. (Google News feeds are
licensed for personal reading only: the analyst gets a Google News search link instead.)

Results are *leads*. An article counts as adverse media only when its headline names the
subject; an article that only mentions the name somewhere in its text is set aside (still
listed, not scored). Only the investigated subject is searched.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError
from app.models import Document, Entity, EntityType
from app.relevance import named_in, set_aside

API = "https://api.gdeltproject.org/api/v2/doc/doc"
KEYWORDS = [
    "fraud",
    "corruption",
    "bribery",
    '"money laundering"',
    "sanctions",
    "embezzlement",
    "indicted",
    "convicted",
    "scandal",
    "investigation",
    "arrested",
    '"tax evasion"',
]
MAX_ARTICLES = 15


def _gdelt_day(value: str | None) -> date | None:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])) if value else None
    except (TypeError, ValueError):
        return None


class GdeltConnector(BaseConnector):
    name = "gdelt_media"
    label = "Adverse media — GDELT news index"
    kind = "media"
    homepage = "https://www.gdeltproject.org"
    document_types = {"person", "company"}
    documents_max_depth = 0
    max_retries = 0
    timeout_seconds = (
        4.0  # GDELT is often slow to refuse cloud clients: fail fast, use the fallback
    )

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type not in (EntityType.PERSON, EntityType.COMPANY) or len(entity.name) < 4:
            return []
        query = f'"{entity.name}" ({" OR ".join(KEYWORDS)})'
        try:
            data: Any = self.http_get_json(
                API,
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": MAX_ARTICLES,
                    "sort": "DateDesc",
                    "timespan": "12m",
                },
            )
            articles = (data or {}).get("articles", [])
            docs = [
                self._doc(
                    a.get("title"),
                    a.get("url"),
                    _gdelt_day(a.get("seendate")),
                    " · ".join(p for p in (a.get("domain"), a.get("sourcecountry")) if p),
                    "GDELT",
                )
                for a in articles
            ]
            for d in docs:
                if not named_in(entity, d.title):
                    set_aside(
                        d, "the headline does not name the subject (mentioned in the text only)"
                    )
            return docs
        except ConnectorError:
            return []

    def _doc(
        self, title: str | None, url: str | None, day: date | None, outlet: str, via: str
    ) -> Document:
        return Document(
            title=title or url or "Article",
            kind="adverse_media",
            date=day,
            url=url,
            summary=outlet or None,
            source=f"Adverse media via {via} — subject named in the headline, verify (homonyms)",
            flags=["adverse_media"],
        )
