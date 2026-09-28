"""Relevance of a document to the entity it was found for.

Full-text sources (press, court opinions, gazettes) return anything that mentions the
name somewhere. A document is kept as evidence only when the entity is *named where it
matters*: in the headline of an article, among the parties of a case. Otherwise it is
set aside: still listed, folded, with the reason, but never counted in the score.
"""

from __future__ import annotations

from app.matching.names import (
    GENERIC_COMPANY_WORDS,
    canonical,
    normalize_company,
    normalize_person,
    tokenize,
)
from app.models import Document, Entity, EntityType

SET_ASIDE = "set_aside"


def named_in(entity: Entity, text: str) -> bool:
    """True when the entity's name (its distinctive part for a company, every name token for a
    person, transliteration variants allowed) appears in the text."""
    words = {canonical(t) for t in tokenize(text or "")}
    if not words:
        return False
    if entity.type == EntityType.COMPANY:
        tokens = normalize_company(entity.name)
        distinctive = [t for t in tokens if t not in GENERIC_COMPANY_WORDS] or tokens
        return bool(distinctive) and all(canonical(t) in words for t in distinctive)
    tokens = normalize_person(entity.name)
    return bool(tokens) and all(canonical(t) in words for t in tokens)


def set_aside(doc: Document, reason: str) -> Document:
    """Mark a document as not relevant enough to count, keeping it for the audit trail."""
    if SET_ASIDE not in doc.flags:
        doc.flags = [*doc.flags, SET_ASIDE]
        doc.summary = f"Set aside automatically: {reason}" + (
            f": {doc.summary}" if doc.summary else ""
        )
    return doc


def is_set_aside(doc: Document) -> bool:
    return SET_ASIDE in doc.flags
