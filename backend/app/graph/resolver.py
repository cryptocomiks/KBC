"""Cross-source entity resolution (deduplication).

Records coming from different sources are merged into one canonical entity
when there is enough evidence they describe the same real-world entity:

* companies: identical registration number in the same jurisdiction, or a
  near-identical name (>= 95) in the same jurisdiction;
* persons: very close name (>= 90) AND a compatible date of birth. Two
  persons are never merged on the name alone — homonyms are the norm;
* addresses: token-set similarity >= 92 on the normalised address.

Every merge is logged with its score and explanation (audit trail).
"""

from __future__ import annotations

import hashlib

from rapidfuzz import fuzz

from app.matching.matcher import match_entities
from app.matching.names import tokenize
from app.models import Entity, EntityType

COMPANY_MERGE_SCORE = 95
PERSON_MERGE_SCORE = 90
ADDRESS_MERGE_SCORE = 92

_ADDRESS_NOISE = {
    "france",
    "luxembourg",
    "united",
    "kingdom",
    "cyprus",
    "british",
    "virgin",
    "islands",
}


def address_key(address: str) -> str:
    return " ".join(t for t in tokenize(address) if t not in _ADDRESS_NOISE)


def address_entity(address: str, *, demo: bool = False) -> Entity:
    digest = hashlib.sha1(address_key(address).encode()).hexdigest()[:12]
    return Entity(id=f"addr:{digest}", type=EntityType.ADDRESS, name=address, demo=demo)


_RICHNESS_FIELDS = (
    "legal_form",
    "status",
    "incorporation_date",
    "last_accounts_date",
    "activity",
    "address",
)


def _richness(e: Entity) -> int:
    """How complete a record is (used to pick the primary name when merging)."""
    return len(e.birth_date or "") + sum(getattr(e, f) not in (None, "") for f in _RICHNESS_FIELDS)


class EntityResolver:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self._record_index: dict[str, str] = {}
        self.merges: list[dict] = []

    # --------------------------------------------------------------- lookups
    def canonical_of(self, record_id: str) -> str | None:
        return self._record_index.get(record_id)

    def find(self, entity: Entity) -> tuple[str | None, float, list[str]]:
        for rid in [entity.id, *entity.record_ids]:
            if rid in self._record_index:
                return self._record_index[rid], 100.0, ["same source record"]
        best: tuple[str | None, float, list[str]] = (None, 0.0, [])
        for cid, existing in self.entities.items():
            if existing.type != entity.type:
                continue
            ok, score, expl = self.same_entity(existing, entity)
            if ok and score > best[1]:
                best = (cid, score, expl)
        return best

    @staticmethod
    def same_entity(a: Entity, b: Entity) -> tuple[bool, float, list[str]]:
        if a.type != b.type or a.demo != b.demo:  # never mix fictitious and real data
            return False, 0.0, []
        if a.type == EntityType.WALLET:
            from app.connectors.crypto_util import normalize_address

            same = a.chain == b.chain and normalize_address(a.name, a.chain) == normalize_address(
                b.name, b.chain
            )
            return same, 100.0 if same else 0.0, ["same blockchain address"] if same else []
        if a.type == EntityType.ADDRESS:
            score = fuzz.token_set_ratio(address_key(a.name), address_key(b.name))
            return score >= ADDRESS_MERGE_SCORE, score, [f"address similarity {score:.0f}%"]
        result = match_entities(a, b)
        if a.type == EntityType.COMPANY:
            same_jur = not a.jurisdiction or not b.jurisdiction or a.jurisdiction == b.jurisdiction
            return (
                result.score >= COMPANY_MERGE_SCORE and same_jur,
                result.score,
                result.explanation,
            )
        dob_ok = result.signals.get("dob") in ("match", "partial")
        return result.score >= PERSON_MERGE_SCORE and dob_ok, result.score, result.explanation

    # ------------------------------------------------------------- mutations
    def add(self, entity: Entity) -> tuple[str, bool]:
        """Insert or merge. Returns (canonical id, created)."""
        cid, score, expl = self.find(entity)
        if cid is not None:
            self._merge(cid, entity, score, expl)
            return cid, False
        ent = entity.model_copy(deep=True)
        if not ent.record_ids:
            ent.record_ids = [ent.id]
        self.entities[ent.id] = ent
        for rid in ent.record_ids:
            self._record_index[rid] = ent.id
        return ent.id, True

    def _merge(self, cid: str, other: Entity, score: float, expl: list[str]) -> None:
        target = self.entities[cid]
        new_records = [r for r in other.record_ids or [other.id] if r not in target.record_ids]
        for rid in new_records:
            self._record_index[rid] = cid
        if not new_records:
            # Same record fetched again (e.g. full profile after a partial one): enrich only.
            self._fill_missing(target, other)
            return
        self.merges.append(
            {
                "canonical_id": cid,
                "canonical_name": target.name,
                "merged_record": new_records[0],
                "merged_name": other.name,
                "merged_source": other.sources[0].source_label if other.sources else None,
                "score": score,
                "explanation": expl,
            }
        )
        target.record_ids.extend(new_records)
        target.sources.extend(other.sources)
        # Keep as primary name the properly cased spelling of the richest record
        # (registries often store names in capitals, or truncate data).
        if not other.name.isupper() and (
            target.name.isupper() or _richness(other) > _richness(target)
        ):
            target.aliases.append(target.name)
            target.name, other = other.name, other.model_copy(update={"name": target.name})
        names = {target.name.casefold(), *(a.casefold() for a in target.aliases)}
        for n in [other.name, *other.aliases]:
            if n.casefold() not in names:
                target.aliases.append(n)
                names.add(n.casefold())
        self._fill_missing(target, other)

    @staticmethod
    def _fill_missing(target: Entity, other: Entity) -> None:
        """Keep the most precise value for each attribute; never silently drop data."""
        if other.birth_date and len(other.birth_date) > len(target.birth_date or ""):
            target.birth_date = other.birth_date
        target.nationalities = sorted(set(target.nationalities) | set(other.nationalities))
        for field in (
            "jurisdiction",
            "registration_number",
            "legal_form",
            "status",
            "incorporation_date",
            "dissolution_date",
            "last_accounts_date",
            "activity",
            "address",
        ):
            if getattr(target, field) in (None, "") and getattr(other, field) not in (None, ""):
                setattr(target, field, getattr(other, field))
        target.identifiers = {**other.identifiers, **target.identifiers}
        extra = {**other.extra, **target.extra}
        if "accounts_unknown" not in other.extra:  # a full profile settles the question
            extra.pop("accounts_unknown", None)
        target.extra = extra
        target.demo = target.demo or other.demo
