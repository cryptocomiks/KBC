"""Entity-level matching: combines name similarity with secondary attributes.

The resulting confidence score is always returned with a human-readable
explanation. Weights are intentionally simple so they can be defended in
front of a compliance officer or an auditor.
"""

from __future__ import annotations

from app.matching.names import name_similarity
from app.models import Entity, EntityType, MatchResult

DOB_EXACT_BONUS = 8
DOB_YEAR_BONUS = 4
DOB_CONFLICT_PENALTY = 30
# A conflicting date of birth is strong evidence of a different person: whatever the
# name similarity, the candidate can at most be displayed for review, never counted.
DOB_CONFLICT_CAP = 65
DOB_NEAR_PENALTY = 10
NATIONALITY_BONUS = 4
NATIONALITY_CONFLICT_PENALTY = 8
JURISDICTION_CONFLICT_PENALTY = 15


def best_name_score(query: str, candidate: Entity, kind: str) -> tuple[float, list[str], str]:
    """Compare against the primary name and all aliases; keep the best."""
    best = (0.0, [], candidate.name)
    for name in [candidate.name, *candidate.aliases]:
        score, notes = name_similarity(query, name, kind)
        if score > best[0]:
            best = (score, notes, name)
    return best


def _dob_compare(a: str | None, b: str | None) -> tuple[int, str | None, str | None]:
    """Returns (score delta, explanation, signal)."""
    if not a or not b:
        return 0, None, None
    common = min(len(a), len(b))
    if a[:common] == b[:common]:
        if common >= 10:
            return DOB_EXACT_BONUS, f"same date of birth ({a[:common]})", "match"
        return DOB_YEAR_BONUS, f"compatible date of birth ({a[:common]}, partial)", "partial"
    try:
        gap = abs(int(a[:4]) - int(b[:4]))
    except ValueError:
        return 0, None, None
    if gap <= 1:
        return -DOB_NEAR_PENALTY, f"date of birth differs slightly ({a} vs {b})", "near"
    return -DOB_CONFLICT_PENALTY, f"date of birth conflict ({a} vs {b})", "conflict"


def match_entities(query: Entity, candidate: Entity) -> MatchResult:
    """Confidence that `candidate` refers to the same real-world entity as `query`."""
    if query.type != candidate.type and EntityType.ADDRESS in (query.type, candidate.type):
        return MatchResult(score=0, explanation=["different entity types"])
    kind = "company" if query.type == EntityType.COMPANY else "person"

    # Strong identifier: registration number in the same jurisdiction.
    if (
        kind == "company"
        and query.registration_number
        and candidate.registration_number
        and _clean_id(query.registration_number) == _clean_id(candidate.registration_number)
        and (query.jurisdiction or "") == (candidate.jurisdiction or "")
    ):
        return MatchResult(
            score=100,
            explanation=[f"same registration number {query.registration_number}"],
            signals={"identifier": "match"},
        )

    score, notes, _ = max(
        (best_name_score(n, candidate, kind) for n in [query.name, *query.aliases]),
        key=lambda r: r[0],
    )
    explanation = [f"name {score:.0f}%" + (f" ({'; '.join(notes)})" if notes else "")]
    signals: dict[str, object] = {"name": score}

    if kind == "person":
        delta, note, signals["dob"] = _dob_compare(query.birth_date, candidate.birth_date)
        score += delta
        if note:
            explanation.append(f"{note} [{delta:+d}]")
        qn, cn = set(query.nationalities), set(candidate.nationalities)
        if qn and cn:
            if qn & cn:
                score += NATIONALITY_BONUS
                explanation.append(
                    f"shared nationality {', '.join(sorted(qn & cn))} [+{NATIONALITY_BONUS}]"
                )
            else:
                score -= NATIONALITY_CONFLICT_PENALTY
                explanation.append(
                    f"different nationalities ({', '.join(sorted(qn))} vs {', '.join(sorted(cn))})"
                    f" [-{NATIONALITY_CONFLICT_PENALTY}]"
                )
    else:
        if (
            query.jurisdiction
            and candidate.jurisdiction
            and query.jurisdiction != candidate.jurisdiction
        ):
            score -= JURISDICTION_CONFLICT_PENALTY
            explanation.append(
                f"different jurisdictions ({query.jurisdiction} vs {candidate.jurisdiction})"
                f" [-{JURISDICTION_CONFLICT_PENALTY}]"
            )

    if signals.get("dob") == "conflict" and score > DOB_CONFLICT_CAP:
        score = DOB_CONFLICT_CAP
        explanation.append(f"capped at {DOB_CONFLICT_CAP}: conflicting dates of birth")
    return MatchResult(
        score=round(max(0.0, min(100.0, score)), 1), explanation=explanation, signals=signals
    )


def match_name(query: str, candidate: Entity) -> MatchResult:
    """Match a free-text query (search box) against a candidate entity."""
    kind = "company" if candidate.type == EntityType.COMPANY else "person"
    score, notes, matched = best_name_score(query, candidate, kind)
    expl = [f"name {score:.0f}%" + (f" via alias '{matched}'" if matched != candidate.name else "")]
    expl.extend(notes)
    return MatchResult(score=score, explanation=expl)


def _clean_id(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())
