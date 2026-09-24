"""Application services: search / disambiguation, investigation, tables."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.cache import get_cache
from app.connectors.base import ConnectorError
from app.connectors.registry import ConnectorRegistry
from app.graph.expander import Network, NetworkExpander
from app.graph.ownership import indirect_stakes, ownership_graph
from app.graph.resolver import EntityResolver
from app.matching.matcher import match_name
from app.models import Entity, EntityType, ListType, RelationType, SearchCandidate, utcnow
from app.risk.config import get_jurisdictions, get_risk_config
from app.risk.engine import RiskAssessment, RiskEngine
from app.schemas import Investigation, InvestigationRequest, SearchResponse
from app.settings import get_settings

SEARCH_LIMIT = 25


class KbcService:
    def __init__(self, registry: ConnectorRegistry | None = None) -> None:
        self.registry = registry or ConnectorRegistry()

    # ------------------------------------------------------------- search
    def search(self, query: str, etype: str = "any") -> SearchResponse:
        registries = self.registry.enabled("registry")
        warnings: list[str] = []
        resolver = EntityResolver()
        for conn in registries:
            try:
                if etype in ("any", "person"):
                    for e in conn.search_person(query):
                        resolver.add(e)
                if etype in ("any", "company"):
                    for e in conn.search_company(query):
                        resolver.add(e)
            except ConnectorError as exc:
                warnings.append(str(exc))

        candidates = []
        for ent in resolver.entities.values():
            m = match_name(query, ent)
            linked, roles = self._linked_summary(ent, warnings)
            candidates.append(
                SearchCandidate(
                    entity=ent,
                    score=m.score,
                    explanation=m.explanation,
                    linked_companies=linked,
                    roles_count=roles,
                )
            )
        candidates.sort(key=lambda c: (-c.score, -c.roles_count))
        return SearchResponse(
            query=query,
            type=etype,
            candidates=candidates[:SEARCH_LIMIT],
            sources=[c.label for c in registries],
            warnings=warnings,
        )

    def _linked_summary(self, ent: Entity, warnings: list[str]) -> tuple[list[str], int]:
        """Companies linked to a candidate — the key hint to tell homonyms apart."""
        names: dict[str, None] = {}
        for rid in ent.record_ids:
            conn = self.registry.for_record(rid)
            if conn is None:
                continue
            try:
                if ent.type == EntityType.PERSON:
                    links = conn.get_person_roles(rid)
                else:
                    links = conn.get_officers(rid) + conn.get_shareholders(rid)
            except ConnectorError as exc:
                warnings.append(str(exc))
                continue
            for link in links:
                names[link.entity.name] = None
        return list(names)[:8], len(names)

    # ------------------------------------------------------ investigation
    def investigate(self, req: InvestigationRequest) -> Investigation:
        settings = get_settings()
        key_src = json.dumps(
            [sorted(req.record_ids), req.depth, req.max_nodes, settings.demo_mode], sort_keys=True
        )
        key = hashlib.sha256(key_src.encode()).hexdigest()[:16]
        cache = get_cache()
        cached = cache.get("investigation", key)
        if cached is not None:
            return Investigation.model_validate(cached)

        seeds = self._load_seeds(req.record_ids)
        if not seeds:
            raise LookupError(
                "None of the requested records could be found in the enabled sources."
            )
        depth = min(req.depth, settings.max_depth)
        max_nodes = min(req.max_nodes, settings.max_nodes_limit)
        net = NetworkExpander(self.registry, max_depth=depth, max_nodes=max_nodes).expand(seeds)
        risk = RiskEngine().assess(net)
        inv = Investigation(
            id=key,
            subject_id=net.subject_id,
            params=req,
            generated_at=utcnow(),
            demo=any(e.demo for e in net.entities.values()),
            entities=list(net.entities.values()),
            depth=net.depth,
            relationships=list(net.relationships.values()),
            hits=net.hits,
            risk=risk,
            tables=build_tables(net, risk),
            queries=net.queries,
            merges=net.merges,
            warnings=net.warnings,
            truncated=net.truncated,
            stats={
                "persons": sum(e.type == EntityType.PERSON for e in net.entities.values()),
                "companies": sum(e.type == EntityType.COMPANY for e in net.entities.values()),
                "addresses": sum(e.type == EntityType.ADDRESS for e in net.entities.values()),
                "relationships": len(net.relationships),
                "screening_hits": len(net.hits),
                "queries": len(net.queries),
                "sources": len({q.source for q in net.queries}),
            },
        )
        cache.set("investigation", key, inv.model_dump(mode="json"))
        return inv

    def _load_seeds(self, record_ids: list[str]) -> list[Entity]:
        seeds = []
        for rid in record_ids:
            conn = self.registry.for_record(rid)
            if conn is None:
                continue
            ent = conn.get_company_details(rid) or conn.get_person_details(rid)
            if ent:
                seeds.append(ent)
        return seeds


# ---------------------------------------------------------------- tables
def _sources(provs) -> str:
    return ", ".join(dict.fromkeys(p.source_label for p in provs))


def _source_urls(provs) -> list[str]:
    return [p.url for p in provs if p.url]


def _hit_status(score: float) -> str:
    t = get_risk_config().thresholds
    if score >= t["strong_match_score"]:
        return "match"
    if score >= t["possible_match_score"]:
        return "possible match"
    return "weak — likely false positive"


def build_tables(net: Network, risk: RiskAssessment) -> dict[str, list[dict[str, Any]]]:
    ents = net.entities
    jur = get_jurisdictions()
    subject = ents[net.subject_id]
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731
    rels = list(net.relationships.values())

    # Mandates / positions of the subject (or officers when the subject is a company)
    mandates = []
    for r in rels:
        if r.type == RelationType.REGISTERED_AT:
            continue
        if subject.type == EntityType.PERSON and r.source_id == subject.id:
            counterpart = ents[r.target_id]
        elif (
            subject.type == EntityType.COMPANY
            and r.target_id == subject.id
            and r.type == RelationType.OFFICER
        ):
            counterpart = ents[r.source_id]
        else:
            continue
        mandates.append(
            {
                "entity_id": counterpart.id,
                "name": counterpart.name,
                "jurisdiction": counterpart.jurisdiction,
                "relation": r.type.value,
                "role": r.role or ("Shareholder" if r.type == RelationType.SHAREHOLDER else ""),
                "share_pct": r.share_pct,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "status": "active" if r.is_active else "ended",
                "company_status": counterpart.status.value if counterpart.status else None,
                "sources": _sources(r.sources),
                "urls": _source_urls(r.sources),
            }
        )

    companies = []
    for eid, e in ents.items():
        if e.type != EntityType.COMPANY:
            continue
        companies.append(
            {
                "entity_id": eid,
                "name": e.name,
                "jurisdiction": e.jurisdiction,
                "jurisdiction_name": jur.name(e.jurisdiction),
                "registration_number": e.registration_number,
                "legal_form": e.legal_form,
                "status": e.status.value if e.status else None,
                "incorporation_date": e.incorporation_date,
                "last_accounts_date": e.last_accounts_date,
                "address": e.address,
                "offshore": e.is_offshore,
                "depth": net.depth.get(eid),
                "risk_level": risk.entity_levels.get(eid, "none"),
                "flags": "; ".join(risk.entity_flags.get(eid, [])),
                "sources": _sources(e.sources),
                "urls": _source_urls(e.sources),
            }
        )
    companies.sort(key=lambda r: (r["depth"] or 0, r["name"]))

    shareholders = []
    for r in rels:
        if r.type not in (RelationType.SHAREHOLDER, RelationType.BENEFICIAL_OWNER):
            continue
        shareholders.append(
            {
                "owner_id": r.source_id,
                "owner": name(r.source_id),
                "owner_type": ents[r.source_id].type.value,
                "company_id": r.target_id,
                "company": name(r.target_id),
                "relation": "Declared beneficial owner"
                if r.type == RelationType.BENEFICIAL_OWNER
                else "Shareholder",
                "share_pct": r.share_pct,
                "details": r.role,
                "sources": _sources(r.sources),
                "urls": _source_urls(r.sources),
            }
        )
    shareholders.sort(key=lambda r: (r["company"], -(r["share_pct"] or 0)))

    # Computed (indirect) ownership
    og = ownership_graph(rels)
    ownership = []
    if subject.type == EntityType.PERSON:
        for cid, pct in sorted(indirect_stakes(og, subject.id).items(), key=lambda kv: -kv[1]):
            direct = og.edges[subject.id, cid]["pct"] if og.has_edge(subject.id, cid) else None
            ownership.append(
                {
                    "owner": subject.name,
                    "company_id": cid,
                    "company": name(cid),
                    "direct_pct": direct,
                    "effective_pct": pct,
                    "ubo_threshold_met": pct >= 25,
                }
            )
    else:
        for pid, p in ents.items():
            if p.type != EntityType.PERSON:
                continue
            pct = indirect_stakes(og, pid).get(subject.id)
            if pct:
                direct = og.edges[pid, subject.id]["pct"] if og.has_edge(pid, subject.id) else None
                ownership.append(
                    {
                        "owner": p.name,
                        "owner_id": pid,
                        "company_id": subject.id,
                        "company": subject.name,
                        "direct_pct": direct,
                        "effective_pct": pct,
                        "ubo_threshold_met": pct >= 25,
                    }
                )
        ownership.sort(key=lambda r: -r["effective_pct"])

    def hit_row(h):
        return {
            "entity_id": h.entity_id,
            "entity": name(h.entity_id),
            "matched_name": h.matched_name,
            "list_type": h.list_type.value,
            "dataset": h.dataset,
            "score": h.score,
            "status": _hit_status(h.score),
            "explanation": "; ".join(h.explanation),
            "details": "; ".join(
                f"{k.replace('_', ' ')}: {', '.join(map(str, v)) if isinstance(v, list) else v}"
                for k, v in h.details.items()
            ),
            "source": h.provenance.source_label,
            "url": h.provenance.url,
            "retrieved_at": h.provenance.retrieved_at,
        }

    screening = [hit_row(h) for h in net.hits if h.list_type in (ListType.SANCTION, ListType.PEP)]
    leaks = [hit_row(h) for h in net.hits if h.list_type in (ListType.LEAK, ListType.ADVERSE)]

    by_source: dict[str, dict[str, Any]] = {}
    for q in net.queries:
        row = by_source.setdefault(
            q.source,
            {
                "source": q.source_label,
                "connector": q.source,
                "queries": 0,
                "records": 0,
                "errors": 0,
                "first_retrieved": q.retrieved_at,
                "last_retrieved": q.retrieved_at,
            },
        )
        row["queries"] += 1
        row["records"] += q.results
        row["errors"] += 1 if q.error else 0
        row["first_retrieved"] = min(row["first_retrieved"], q.retrieved_at)
        row["last_retrieved"] = max(row["last_retrieved"], q.retrieved_at)
    sources = list(by_source.values())

    return {
        "mandates": mandates,
        "companies": companies,
        "shareholders": shareholders,
        "ownership": ownership,
        "screening": screening,
        "leaks": leaks,
        "sources": sources,
    }
