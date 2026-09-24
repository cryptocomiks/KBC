"""Adverse media — press mentions of the subject with financial-crime keywords (no key).

1. GDELT DOC 2.0 API (open news index). It allows one request every 5 s per
   IP address and answers HTTP 429 to shared cloud IPs, so it is not retried;
2. fallback: Google News RSS search.

Results are *leads*: a name-only match in an article is weak evidence
(homonyms), so each article is shown with title, outlet and date for review.
Only the investigated subject is searched.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.connectors.base import USER_AGENT, BaseConnector, ConnectorError
from app.models import Document, Entity, EntityType

API = "https://api.gdeltproject.org/api/v2/doc/doc"
RSS = "https://news.google.com/rss/search"
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
    label = "Adverse media — GDELT news index (Google News fallback)"
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
            return [
                self._doc(
                    a.get("title"),
                    a.get("url"),
                    _gdelt_day(a.get("seendate")),
                    " · ".join(p for p in (a.get("domain"), a.get("sourcecountry")) if p),
                    "GDELT",
                )
                for a in articles
            ]
        except ConnectorError:
            return self._google_news(query)

    def _google_news(self, query: str) -> list[Document]:
        root = None
        for _ in range(2):  # one retry: the feed occasionally answers 5xx / empty to cloud IPs
            try:
                resp = httpx.get(
                    RSS,
                    params={"q": query, "hl": "en", "gl": "US", "ceid": "US:en"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=self.settings.http_timeout_seconds,
                    follow_redirects=True,
                )
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                break
            except (httpx.HTTPError, ET.ParseError):
                continue
        if root is None:
            return []
        docs = []
        for it in root.iter("item"):
            try:
                day = parsedate_to_datetime(it.findtext("pubDate") or "").date()
            except (TypeError, ValueError):
                day = None
            docs.append(
                self._doc(
                    it.findtext("title"),
                    it.findtext("link"),
                    day,
                    it.findtext("source") or "",
                    "Google News",
                )
            )
            if len(docs) >= MAX_ARTICLES:
                break
        return docs

    def _doc(
        self, title: str | None, url: str | None, day: date | None, outlet: str, via: str
    ) -> Document:
        return Document(
            title=title or url or "Article",
            kind="adverse_media",
            date=day,
            url=url,
            summary=outlet or None,
            source=f"Adverse media via {via} — keyword match, verify relevance (homonyms)",
            flags=["adverse_media"],
        )
