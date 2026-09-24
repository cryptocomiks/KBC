"""Privacy guard shared by the court / procurement / power-network document sources.

These sources may only be queried for companies and for public figures, never
for private individuals. In this app a person is a public figure when it has
a Wikidata item (Wikidata only holds notable people).
"""

from __future__ import annotations

from app.models import Entity, EntityType


def is_public_figure(entity: Entity) -> bool:
    """True for a person with a Wikidata item (public figure), False otherwise."""
    return entity.type == EntityType.PERSON and bool(entity.identifiers.get("Wikidata"))


def may_query(entity: Entity) -> bool:
    """Companies always; persons only when they are public figures."""
    return entity.type == EntityType.COMPANY or is_public_figure(entity)
