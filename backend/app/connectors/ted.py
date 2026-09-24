"""EU public procurement — TED (Tenders Electronic Daily), contracts awarded.

Public API, no key. Contract award notices in which the company is named as
winner (tenderer awarded the contract): who buys from the company, where, for
how much. Companies only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.connectors.base import BaseConnector
from app.models import Document, Entity, EntityType

API = "https://api.ted.europa.eu/v3/notices/search"
NOTICE = "https://ted.europa.eu/en/notice/-/detail/{number}"
FIELDS = [
    "notice-title",
    "winner-name",
    "buyer-name",
    "buyer-country",
    "publication-date",
    "total-value",
    "total-value-cur",
    "notice-type",
    "contract-conclusion-date",
]
MAX_NOTICES = 10
LANGS = ("eng", "ENG", "en", "fra", "FRA", "deu", "DEU")


def _day(value: Any) -> date | None:
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _first(value: Any) -> Any:
    """TED fields are scalars, lists, or {lang: scalar | list}: return one value (English first)."""
    if isinstance(value, dict):
        for lang in (*LANGS, *value.keys()):
            if lang in value:
                found = _first(value[lang])
                if found not in (None, ""):
                    return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _first(item)
            if found not in (None, ""):
                return found
        return None
    return value


def _text(value: Any) -> str | None:
    found = _first(value)
    return str(found).strip() or None if found is not None else None


def _amount(value: Any) -> str | None:
    found = _first(value)
    if found is None:
        return None
    try:
        return f"{float(found):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(found)


def _link(notice: dict) -> str | None:
    html = ((notice.get("links") or {}).get("html") or {}) if isinstance(notice, dict) else {}
    if isinstance(html, dict) and html:
        return html.get("ENG") or next((v for v in html.values() if isinstance(v, str)), None)
    number = notice.get("publication-number")
    return NOTICE.format(number=number) if number else None


class TedConnector(BaseConnector):
    name = "ted"
    label = "EU public procurement — TED (contracts awarded)"
    kind = "documents"
    homepage = "https://ted.europa.eu"
    document_types = {"company"}
    documents_max_depth = 2
    max_retries = 1
    timeout_seconds = 15.0

    def get_documents(self, entity: Entity) -> list[Document]:
        if entity.type != EntityType.COMPANY or len(entity.name.strip()) < 3:
            return []
        name = entity.name.replace('"', " ").strip()
        data: Any = self.http_post_json(
            API,
            json_body={
                "query": f'winner-name = "{name}"',
                "fields": FIELDS,
                "limit": MAX_NOTICES,
                "scope": "ALL",
            },
        )
        notices = (data or {}).get("notices") or [] if isinstance(data, dict) else []
        docs = [self._doc(n) for n in notices if isinstance(n, dict)]
        return sorted(docs, key=lambda d: (d.date is None, -(d.date.toordinal() if d.date else 0)))[
            :MAX_NOTICES
        ]

    def _doc(self, n: dict) -> Document:
        buyer = _text(n.get("buyer-name"))
        country = _text(n.get("buyer-country"))
        notice_title = _text(n.get("notice-title"))
        number = n.get("publication-number")
        if buyer:
            title = f"Contract awarded by {buyer}" + (f" ({country})" if country else "")
        else:
            title = notice_title or f"TED notice {number or ''}".strip()
        parts = []
        if notice_title and notice_title != title:
            parts.append(notice_title)
        value = _amount(n.get("total-value"))
        if value:
            parts.append(f"Value: {value} {_text(n.get('total-value-cur')) or ''}".strip())
        concluded = _day(n.get("contract-conclusion-date"))
        if concluded:
            parts.append(f"Contract concluded {concluded.isoformat()}")
        if _text(n.get("notice-type")):
            parts.append(f"Notice type: {_text(n.get('notice-type'))}")
        if number:
            parts.append(f"TED {number}")
        return Document(
            title=title,
            kind="public_contract",
            date=_day(n.get("publication-date")),
            url=_link(n),
            summary=" · ".join(parts) or None,
            source="TED — EU public procurement (winner name match, verify the company)",
            flags=["public_contract"],
        )
