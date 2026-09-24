"""Alert triage: sort screening hits into likely matches, hits to verify and likely namesakes.

In screening, most alerts are false positives. The analyst's time goes to the
few that can be true, so every hit gets a triage label with the reasons behind
it, derived from the evidence the matcher already produced (date of birth,
nationality, jurisdiction, identifiers) — never from the name alone.

Labels:
* ``likely``    — strong, corroborated match: same identifier, same date of birth, or an
                  exact name backed by a matching country / website.
* ``verify``    — plausible but not corroborated (typically: no date of birth to compare).
* ``namesake``  — contradicted by the evidence (different date of birth, nationality or
                  jurisdiction), or a weak name match: very probably another person/company.
* ``dismissed`` — the same hit was already ruled out by an analyst (memory of decisions).
"""

from __future__ import annotations

from app.models import Entity, EntityType, ListType, ScreeningHit

CONTRADICTIONS = (
    ("date of birth conflict", "different date of birth"),
    ("different nationalities", "different nationality"),
    ("different jurisdictions", "different country of registration"),
    ("capped at", "conflicting identifiers"),
)
CORROBORATIONS = (
    ("same date of birth", "same date of birth"),
    ("same registration number", "same registration number"),
    ("shared nationality", "same nationality"),
    ("official website", "same website domain"),
    ("address listed verbatim", "wallet address listed verbatim"),
)
ORDER = {"likely": 0, "verify": 1, "namesake": 2, "dismissed": 3}


def triage(hit: ScreeningHit, entity: Entity | None) -> tuple[str, list[str]]:
    text = " | ".join(hit.explanation).lower()
    contra = [label for needle, label in CONTRADICTIONS if needle in text]
    corro = [label for needle, label in CORROBORATIONS if needle in text]

    if contra:
        return "namesake", [*contra, f"confidence {hit.score:.0f}%"]
    if hit.score < 75:
        return "namesake", [f"weak name similarity ({hit.score:.0f}%)"]
    if corro and hit.score >= 85:
        return "likely", [*corro, f"confidence {hit.score:.0f}%"]

    reasons = []
    if entity is not None and entity.type == EntityType.PERSON and not entity.birth_date:
        reasons.append("no date of birth on our side to compare")
    elif entity is not None and entity.type == EntityType.PERSON:
        reasons.append("the list gives no date of birth to compare")
    if entity is not None and entity.type == EntityType.COMPANY and not entity.jurisdiction:
        reasons.append("country of registration unknown")
    if hit.list_type == ListType.LEAK:
        reasons.append("leak records carry no identifier: name-only match")
    if (
        hit.score >= 97
        and entity is not None
        and entity.type == EntityType.COMPANY
        and entity.jurisdiction
    ):
        return "likely", ["exact company name", f"confidence {hit.score:.0f}%"]
    return "verify", reasons or [f"name match {hit.score:.0f}%, not corroborated"]


def apply_triage(hits: list[ScreeningHit], entities: dict[str, Entity]) -> list[ScreeningHit]:
    for h in hits:
        if h.triage == "dismissed":
            continue
        h.triage, h.triage_reasons = triage(h, entities.get(h.entity_id))
    return sorted(hits, key=lambda h: (ORDER.get(h.triage or "verify", 1), -h.score))
