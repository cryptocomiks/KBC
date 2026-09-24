"""Adverse media — GDELT DOC 2.0 API (no key).

Searches worldwide online news for the subject's name together with
financial-crime keywords. Results are *leads*: a name-only match in a news
article is weak evidence (homonyms), so each article is shown with its title,
outlet and date for the analyst to review. Only the investigated subject is
searched (the free API is rate-limited).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError
from app.models import Document, Entity, EntityType

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
    "tax evasion",
]
MAX_ARTICLES = 15


def _day(value: str | None) -> date | None:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])) if value else None
    except (TypeError, ValueError):
        return None


class GdeltConnector(BaseConnector):
    name = "gdelt_media"
    label = "Adverse media — GDELT worldwide news index"
    kind = "media"
    homepage = "https://www.gdeltproject.org"
    document_types = {"person", "company"}
    documents_max_depth = 0

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
        except ConnectorError:
            return []  # rate limit or non-JSON answer: media screening is best effort
        docs = []
        for a in (data or {}).get("articles", []):
            docs.append(
                Document(
                    title=a.get("title") or a.get("url", "Article"),
                    kind="adverse_media",
                    date=_day(a.get("seendate")),
                    url=a.get("url"),
                    summary=" · ".join(
                        p for p in (a.get("domain"), a.get("sourcecountry"), a.get("language")) if p
                    ),
                    source=f"{self.label} — keyword match, verify relevance (homonyms)",
                    flags=["adverse_media"],
                )
            )
        return docs
