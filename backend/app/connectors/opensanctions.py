"""OpenSanctions — consolidated sanctions lists, PEPs and other risk data.

API: https://api.opensanctions.org (key required: OPENSANCTIONS_API_KEY; free
for non-commercial use on request). The /match endpoint scores candidates
with names, birth dates and nationalities; KBC re-scores every candidate with
its own transparent matcher so that the explanation is consistent across
sources, and keeps the OpenSanctions score in the details.
Data licence: CC BY-NC 4.0 (commercial use requires a licence).
"""

from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector, ConnectorError
from app.matching.matcher import match_entities
from app.models import Entity, EntityType, ListType, ScreeningHit

API = "https://api.opensanctions.org/match/default"
ENTITY_URL = "https://www.opensanctions.org/entities/{id}/"
MIN_SCORE = 45
BATCH_SIZE = 20

SANCTION_TOPICS = {"sanction", "sanction.linked", "sanction.counter", "debarment"}
PEP_TOPICS = {"role.pep", "role.rca", "role.judge", "role.diplo", "gov.head", "gov.national"}


def _first(props: dict[str, list[Any]], key: str) -> Any:
    values = props.get(key) or []
    return values[0] if values else None


# Readable names for the most frequent sources (others: "gb_hmt_sanctions" -> "GB HMT sanctions")
LABELS = {
    "us_ofac_sdn": "OFAC SDN list (US Treasury)",
    "us_ofac_cons": "OFAC consolidated non-SDN lists",
    "un_sc_sanctions": "UN Security Council sanctions",
    "gb_hmt_sanctions": "UK financial sanctions (HM Treasury)",
    "wd_peps": "Wikidata politically exposed persons",
    "everypolitician": "EveryPolitician (legislators)",
    "ru_rupep": "RuPEP — Russian PEPs",
    "icij_offshoreleaks": "ICIJ Offshore Leaks",
    "interpol_red_notices": "Interpol red notices",
}


def _datasets_label(ids: list[str]) -> str:
    from app.connectors.open_datasets import DATASETS

    def label(ds: str) -> str:
        if ds in LABELS:
            return LABELS[ds]
        if ds in DATASETS:
            return DATASETS[ds][0]
        words = ds.split("_")
        country = words[0].upper() if len(words[0]) == 2 else words[0].capitalize()
        return " ".join([country, *words[1:]])

    names = [label(d) for d in ids[:4]]
    more = f" (+{len(ids) - 4} more)" if len(ids) > 4 else ""
    return (", ".join(names) + more) or "OpenSanctions"


class OpenSanctionsConnector(BaseConnector):
    name = "opensanctions"
    label = "OpenSanctions (sanctions, PEPs, watchlists)"
    kind = "screening"
    key_setting = "opensanctions_api_key"
    homepage = "https://www.opensanctions.org"

    def screen(self, entity: Entity) -> list[ScreeningHit]:
        return self.screen_many([entity])

    def screen_many(self, entities: list[Entity]) -> list[ScreeningHit]:
        targets = [e for e in entities if e.type in (EntityType.PERSON, EntityType.COMPANY)]
        hits: list[ScreeningHit] = []
        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start : start + BATCH_SIZE]
            queries = {f"q{i}": self._query(e) for i, e in enumerate(batch)}
            try:
                data = self.http_post_json(
                    API,
                    json_body={"queries": queries},
                    params={"algorithm": "logic-v1", "limit": 5},
                    headers={"Authorization": f"ApiKey {self.api_key}"},
                )
            except ConnectorError as exc:
                if "HTTP 429" in str(exc):
                    raise ConnectorError(
                        f"{self.label}: request quota exceeded (HTTP 429) — check the plan of the API key "
                        "on opensanctions.org; the bulk lists keep screening meanwhile"
                    ) from exc
                raise
            responses = (data or {}).get("responses", {})
            for i, entity in enumerate(batch):
                for result in (responses.get(f"q{i}") or {}).get("results", []):
                    hit = self._hit(entity, result)
                    if hit:
                        hits.append(hit)
        return hits

    @staticmethod
    def _query(e: Entity) -> dict[str, Any]:
        if e.type == EntityType.PERSON:
            props: dict[str, list[str]] = {"name": [e.name, *e.aliases]}
            if e.birth_date:
                props["birthDate"] = [e.birth_date]
            if e.nationalities:
                props["nationality"] = [n.lower() for n in e.nationalities]
            return {"schema": "Person", "properties": props}
        props = {"name": [e.name, *e.aliases]}
        if e.jurisdiction:
            props["jurisdiction"] = [e.jurisdiction.lower()]
        if e.registration_number:
            props["registrationNumber"] = [e.registration_number]
        return {"schema": "Company", "properties": props}

    def _hit(self, entity: Entity, r: dict[str, Any]) -> ScreeningHit | None:
        props = r.get("properties") or {}
        topics = set(props.get("topics") or [])
        if topics & SANCTION_TOPICS:
            list_type = ListType.SANCTION
        elif topics & PEP_TOPICS or any(t.startswith("role.") for t in topics):
            list_type = ListType.PEP
        elif topics:
            list_type = ListType.ADVERSE
        else:
            return None
        listed = Entity(
            id=r.get("id", ""),
            type=EntityType.PERSON if r.get("schema") == "Person" else EntityType.COMPANY,
            name=r.get("caption") or _first(props, "name") or "",
            aliases=[
                n for n in props.get("name", []) + props.get("alias", []) if n != r.get("caption")
            ][:20],
            birth_date=_first(props, "birthDate"),
            nationalities=sorted(
                {
                    c.upper()
                    for c in props.get("nationality", []) + props.get("citizenship", [])
                    if len(c) == 2
                }
            ),
            jurisdiction=(_first(props, "jurisdiction") or "").upper() or None,
            registration_number=_first(props, "registrationNumber"),
        )
        if listed.type != entity.type:
            return None
        result = match_entities(entity, listed)
        if result.score < MIN_SCORE:
            return None
        rid = self.record_id(r.get("id", ""))
        return ScreeningHit(
            entity_id=entity.id,
            list_type=list_type,
            dataset=_datasets_label(r.get("datasets") or []),
            matched_name=listed.name,
            score=result.score,
            explanation=result.explanation,
            details={
                "topics": sorted(topics),
                "position": "; ".join((props.get("position") or [])[:3]) or None,
                "program": "; ".join((props.get("program") or [])[:2]) or None,
                "birth_date": listed.birth_date,
                "nationalities": listed.nationalities or None,
                "opensanctions_score": r.get("score"),
            },
            provenance=self.provenance(rid, ENTITY_URL.format(id=r.get("id", ""))),
        )
