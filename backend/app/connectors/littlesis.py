"""LittleSis — power networks (boards, donors, lobbying; mostly US).

Public API, no key (CC BY-SA). The profile of the entity when LittleSis has
an exact name match of the right type, plus its documented relationships
(positions, memberships, donations, business dealings). Privacy rule: only
companies and public figures (Wikidata item) are searched.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from rapidfuzz import fuzz
from unidecode import unidecode

from app.connectors.base import BaseConnector, ConnectorError
from app.connectors.public_figures import may_query
from app.models import Document, Entity, EntityType

SEARCH = "https://littlesis.org/api/entities/search"
RELATIONSHIPS = "https://littlesis.org/api/entities/{id}/relationships"
PROFILE = "https://littlesis.org/entities/{id}"
MAX_RELATIONSHIPS = 12
MIN_SCORE = 95
EXT = {EntityType.COMPANY: "Org", EntityType.PERSON: "Person"}
SOURCE = "LittleSis — power networks (CC BY-SA)"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", unidecode(name or "").lower()).strip()


def _day(value: Any) -> date | None:
    """LittleSis dates look like "2010-05-00" (unknown day/month = 00): keep what has a year."""
    m = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", str(value or ""))
    if not m or m.group(1) == "0000":
        return None
    try:
        return date(int(m.group(1)), int(m.group(2) or 0) or 1, int(m.group(3) or 0) or 1)
    except ValueError:
        return None


class LittleSisConnector(BaseConnector):
    name = "littlesis"
    label = "LittleSis — power networks (boards, donors, lobbying; mostly US)"
    kind = "documents"
    homepage = "https://littlesis.org"
    document_types = {"company", "person"}
    documents_max_depth = 1
    max_retries = 1
    timeout_seconds = 15.0

    def _match(self, entity: Entity) -> dict | None:
        data: Any = self.http_get_json(SEARCH, params={"q": entity.name})
        rows = (data or {}).get("data") or [] if isinstance(data, dict) else []
        wanted = [_norm(n) for n in (entity.name, *entity.aliases) if n]
        best, best_score = None, 0.0
        for row in rows:
            attrs = (row or {}).get("attributes") or {}
            if attrs.get("primary_ext") != EXT.get(entity.type):
                continue
            names = [attrs.get("name") or "", *(attrs.get("aliases") or [])]
            score = max(
                (fuzz.token_set_ratio(w, _norm(n)) for w in wanted for n in names if n),
                default=0.0,
            )
            if score >= MIN_SCORE and score > best_score:
                best, best_score = row, score
        return best

    def get_documents(self, entity: Entity) -> list[Document]:
        if not may_query(entity) or len(entity.name.strip()) < 3:
            return []
        row = self._match(entity)
        if row is None:
            return []
        attrs = row.get("attributes") or {}
        eid = row.get("id") or attrs.get("id")
        url = ((row.get("links") or {}).get("self")) or attrs.get("url") or PROFILE.format(id=eid)
        name = attrs.get("name") or entity.name
        docs = [
            Document(
                title=f"LittleSis profile: {name}",
                kind="profile",
                url=url,
                summary=attrs.get("blurb") or None,
                source=SOURCE,
                flags=[],
            )
        ]
        if eid is None:
            return docs
        try:
            rels: Any = self.http_get_json(RELATIONSHIPS.format(id=eid))
        except ConnectorError:
            return docs  # the profile alone is still useful
        items = (rels or {}).get("data") or [] if isinstance(rels, dict) else []
        for rel in items[:MAX_RELATIONSHIPS]:
            doc = self._relationship(rel)
            if doc:
                docs.append(doc)
        return docs

    def _relationship(self, rel: Any) -> Document | None:
        if not isinstance(rel, dict):
            return None
        a = rel.get("attributes") or {}
        description = re.sub(r"\s+", " ", a.get("description") or "").strip()
        if not description:
            return None
        parts = []
        if a.get("is_current") is True:
            parts.append("current")
        elif a.get("end_date") or a.get("is_current") is False:
            ended = _day(a.get("end_date"))
            parts.append(f"ended {ended.year}" if ended else "ended")
        if a.get("amount"):
            parts.append(f"amount {a['amount']} {a.get('currency') or ''}".strip())
        if a.get("goods"):
            parts.append(str(a["goods"]))
        rid = rel.get("id") or a.get("id")
        return Document(
            title=description,
            kind="relationship",
            date=_day(a.get("start_date")),
            url=rel.get("self") or (f"https://littlesis.org/relationships/{rid}" if rid else None),
            summary=" · ".join(parts) or None,
            source=SOURCE,
            flags=[],
        )
