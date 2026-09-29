"""Alert memory: rule out a namesake once, with the evidence, and only see it again if that
evidence changes.

When an analyst rules out a screening hit, we keep *what the decision was based on*: the
listed record (dates of birth, nationalities, programme, reference, topics...) and our own
entity (date of birth, nationality, country, registration number). The next time the same
hit comes back, it stays silent while that evidence is unchanged; if the list entry or our
data changed (new date of birth published, new programme, a nationality added), the alert
comes back with the list of what changed, so the analyst re-checks only what is new.

Batch triage: hits the triage already labels as namesakes (contradicted by a date of birth,
a nationality, a country of registration, or a weak name match) can be ruled out in one go,
each with a written justification drawn from the evidence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models import Entity, ScreeningHit

# Keys of the listed record that carry no evidence (scores, links, fetch metadata).
VOLATILE = ("score", "url", "retrieved", "fetched", "listed_owner", "rank")
OURS = (
    ("birth_date", "our date of birth"),
    ("nationalities", "our nationality"),
    ("jurisdiction", "our country of registration"),
    ("registration_number", "our registration number"),
)
MINUTES_PER_ALERT = 6  # order of magnitude used for the "time saved" estimate (stated in the UI)


def _norm(value: Any) -> Any:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, list | tuple | set):
        items = sorted({str(v).strip().upper() for v in value if v not in (None, "")})
        return items or None
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items()) if _norm(v) is not None} or None
    return str(value).strip()


def evidence(hit: ScreeningHit, entity: Entity | None) -> dict[str, Any]:
    """What a decision on this hit rests on, and its fingerprint."""
    listed = {
        k: _norm(v)
        for k, v in sorted((hit.details or {}).items())
        if not any(tok in k.lower() for tok in VOLATILE) and _norm(v) is not None
    }
    listed["matched_name"] = _norm(hit.matched_name)
    ours: dict[str, Any] = {}
    if entity is not None:
        for field, _ in OURS:
            v = _norm(getattr(entity, field, None))
            if v is not None:
                ours[field] = v
    blob = json.dumps({"list": listed, "ours": ours}, sort_keys=True, default=str)
    return {
        "fingerprint": hashlib.sha256(blob.encode()).hexdigest()[:20],
        "list": listed,
        "ours": ours,
    }


def _label(key: str) -> str:
    return key.replace("_", " ")


def changed(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Human-readable differences between the evidence of a past decision and today's."""
    out = []
    for side, prefix in (("list", "list entry"), ("ours", "our data")):
        a, b = old.get(side) or {}, new.get(side) or {}
        for k in sorted(set(a) | set(b)):
            if a.get(k) == b.get(k):
                continue
            name = (
                dict(OURS).get(k, f"{prefix}: {_label(k)}")
                if side == "ours"
                else f"{prefix}: {_label(k)}"
            )
            before = _fmt(a.get(k))
            after = _fmt(b.get(k))
            out.append(f"{name} {before} → {after}")
    return out


def _fmt(v: Any) -> str:
    if v is None:
        return "(none)"
    if isinstance(v, list):
        return ", ".join(v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)[:80]
    return str(v)[:80]


def justification(hit: ScreeningHit, entity: Entity | None) -> str:
    """Audit-trail text for ruling a hit out, written from the evidence (never from the name
    alone): what differs between the listed person/company and ours."""
    parts = []
    d = hit.details or {}
    listed_dob = d.get("birth_date") or d.get("dob")
    if (
        entity is not None
        and entity.birth_date
        and listed_dob
        and str(listed_dob)[:4] != entity.birth_date[:4]
    ):
        parts.append(f"date of birth differs (ours {entity.birth_date}, list {listed_dob})")
    nats = d.get("nationalities") or d.get("countries")
    if entity is not None and entity.nationalities and nats:
        listed = {str(n).upper() for n in (nats if isinstance(nats, list) else [nats])}
        if not listed & {n.upper() for n in entity.nationalities}:
            parts.append(
                f"nationality differs (ours {', '.join(entity.nationalities)}, "
                f"list {', '.join(sorted(listed))})"
            )
    reasons = [r for r in hit.triage_reasons if not r.startswith("confidence")]
    for r in reasons:
        if not any(r.split(" (")[0] in p for p in parts):
            parts.append(r)
    if not parts:
        parts.append(f"name similarity only ({hit.score:.0f}%), no corroborating identifier")
    who = entity.name if entity is not None else hit.entity_id
    return (
        f"Namesake: {who} is not the listed “{hit.matched_name}” ({hit.dataset}), "
        + "; ".join(parts)
        + f". Match confidence {hit.score:.0f}%."
    )
