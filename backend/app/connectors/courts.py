"""Court decisions — Swiss (entscheidsuche.ch) and US (CourtListener) case law.

Both searches are an exact-phrase match on the name, so results are *leads*:
the parties must be verified (homonyms; Swiss decisions anonymise private
parties). Privacy rule: only companies and public figures are searched.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.public_figures import is_public_figure, may_query
from app.models import Document, Entity

__all__ = ["CourtListenerConnector", "SwissCourtsConnector", "is_public_figure"]

ENTSCHEIDSUCHE = "https://entscheidsuche.ch/_search.php"
COURTLISTENER = "https://www.courtlistener.com/api/rest/v4/search/"
COURTLISTENER_SITE = "https://www.courtlistener.com"
MAX_DECISIONS = 8
MIN_NAME_LENGTH = 4


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _localized(value: Any, order: tuple[str, ...] = ("fr", "de", "it")) -> str | None:
    """entscheidsuche gives {"de": ..., "fr": ..., "it": ...}: prefer French, then German, Italian."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for lang in (*order, *value.keys()):
            text = value.get(lang)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def _searchable(entity: Entity) -> bool:
    return may_query(entity) and len(entity.name.strip()) >= MIN_NAME_LENGTH


class SwissCourtsConnector(BaseConnector):
    name = "entscheidsuche"
    label = "Swiss court decisions — entscheidsuche.ch (federal and cantonal courts)"
    kind = "documents"
    homepage = "https://entscheidsuche.ch"
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 1
    timeout_seconds = 15.0

    def get_documents(self, entity: Entity) -> list[Document]:
        if not _searchable(entity):
            return []
        name = entity.name.replace('"', " ").strip()
        # The endpoint answers application/x-javascript with a JSON body.
        data: Any = self.http_post_json(
            ENTSCHEIDSUCHE,
            json_body={
                "query": {"simple_query_string": {"query": f'"{name}"', "default_operator": "and"}},
                "size": MAX_DECISIONS,
                "_source": [
                    "date",
                    "title",
                    "abstract",
                    "reference",
                    "attachment.content_url",
                    "hierarchy",
                ],
                "sort": [{"date": "desc"}],
            },
        )
        hits = ((data or {}).get("hits") or {}).get("hits") or [] if isinstance(data, dict) else []
        docs = []
        for hit in hits[:MAX_DECISIONS]:
            src = (hit or {}).get("_source") or {}
            refs = [r for r in src.get("reference") or [] if isinstance(r, str)]
            attachment = src.get("attachment") or {}
            title = _localized(src.get("title")) or (refs[0] if refs else None)
            if not title:
                continue
            docs.append(
                Document(
                    title=title,
                    kind="court_decision",
                    date=_day(src.get("date")),
                    url=attachment.get("content_url") if isinstance(attachment, dict) else None,
                    summary=_localized(src.get("abstract")) or (", ".join(refs) or None),
                    source="Swiss court decisions (entscheidsuche.ch) — name match, verify the parties",
                    flags=["court"],
                )
            )
        return docs


class CourtListenerConnector(BaseConnector):
    name = "courtlistener"
    label = "US court opinions — CourtListener (federal and state courts)"
    kind = "documents"
    homepage = "https://www.courtlistener.com"
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 0
    timeout_seconds = 15.0

    def get_documents(self, entity: Entity) -> list[Document]:
        if not _searchable(entity):
            return []
        name = entity.name.replace('"', " ").strip()
        data: Any = self.http_get_json(
            COURTLISTENER,
            params={"q": f'"{name}"', "type": "o", "order_by": "dateFiled desc"},
        )
        results = (data or {}).get("results") or [] if isinstance(data, dict) else []
        docs = []
        for r in results[:MAX_DECISIONS]:
            if not isinstance(r, dict):
                continue
            case = (r.get("caseName") or r.get("caseNameFull") or "").strip()
            if not case:
                continue
            path = r.get("absolute_url") or ""
            url = (
                path
                if path.startswith("http")
                else (f"{COURTLISTENER_SITE}{path}" if path else None)
            )
            summary = " · ".join(
                str(p) for p in (r.get("court"), r.get("docketNumber")) if p and str(p).strip()
            )
            docs.append(
                Document(
                    title=case,
                    kind="court_decision",
                    date=_day(r.get("dateFiled")),
                    url=url,
                    summary=summary or None,
                    source="US court opinions (CourtListener) — name match, verify the parties",
                    flags=["court"],
                )
            )
        return docs
