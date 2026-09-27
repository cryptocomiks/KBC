"""Beneficial ownership analysis: the questions an AML analyst asks of every structure.

* Who are the beneficial owners, really? Every natural person above the subject with the
  effective interest summed over all ownership routes, the routes themselves (layers,
  countries crossed), whether the person is declared as UBO, and screening flags.
* How much of the capital is traced to natural persons, and who holds the rest? Per company
  in the chain: shareholding identified vs unexplained, and the "dead ends" where the chain
  stops (a corporate owner whose own owners are unknown).
* No one above the threshold? EU AMLD art. 3(6)(a)(ii): the senior managing official is
  recorded as beneficial owner (fallback), with the reason documented.
* Sanctions by ownership (OFAC 50 % rule; EU "ownership and control"): an entity owned
  50 % or more, in aggregate, by blocked persons is itself blocked; blocked status
  propagates down the chain. A sanctioned person on the board is flagged as possible control.
* Questions to ask the client, generated from the gaps.

Threshold: 25 % (EU AMLD reference, config/risk.yaml), 10 % when the case is rated high or
critical (the enhanced threshold many banks apply, and the EU AMLR's lower threshold for
higher-risk sectors).
"""

from __future__ import annotations

import re
from typing import Any

import networkx as nx
from pydantic import BaseModel, Field

from app.graph.ownership import MAX_PATH_LENGTH, ownership_graph
from app.models import Entity, EntityType, ListType, RelationType
from app.risk.config import get_risk_config

ENHANCED_THRESHOLD = 10.0
MAX_PATHS = 40
BLOCKING_PCT = 50.0
# Roles of the senior managing officials (fallback UBO when no one reaches the threshold)
SMO_ROLES = re.compile(
    r"direct(or|eur|rice|ora)|dirigeant|president|présiden|chief|ceo|managing|manager|gérant|gerant|administrat|"
    r"geschäftsführer|geschaftsfuhrer|verwaltungsrat|board|chair|partner|associé gérant|"
    r"statutory body|jednatel|prokur|representative|représentant",
    re.I,
)


class Route(BaseModel):
    ids: list[str]
    names: list[str]
    pcts: list[float | None]
    effective: float | None
    countries: list[str]


class OwnerRow(BaseModel):
    id: str
    name: str
    type: str
    natural_person: bool
    effective_pct: float | None
    direct_pct: float | None
    partly_unknown: bool = False
    routes: list[Route] = Field(default_factory=list)
    layers: int = 0
    countries: list[str] = Field(default_factory=list)
    declared: bool = False
    declared_pct: float | None = None
    roles: list[str] = Field(default_factory=list)
    pep: bool = False
    sanctioned: bool = False
    status: str = "below_threshold"


class CoverageRow(BaseModel):
    id: str
    name: str
    jurisdiction: str | None
    offshore: bool
    identified_pct: float
    unexplained_pct: float
    holders: int
    holders_without_pct: int
    dead_end: bool
    reason: str | None = None
    #: at the edge of the explored network: owners may exist beyond the search depth
    depth_limited: bool = False


class BlockedRow(BaseModel):
    id: str
    name: str
    aggregate_pct: float
    blocked: bool
    owners: list[dict[str, Any]]
    control: list[str] = Field(default_factory=list)


class OwnershipAnalysis(BaseModel):
    subject_id: str
    subject_is_company: bool
    threshold: float
    enhanced_threshold: float = ENHANCED_THRESHOLD
    threshold_applied: float
    traced_pct: float | None = None
    unexplained_pct: float | None = None
    owners: list[OwnerRow] = Field(default_factory=list)
    coverage: list[CoverageRow] = Field(default_factory=list)
    smo: list[dict[str, str]] = Field(default_factory=list)
    smo_reason: str | None = None
    sanctions: list[BlockedRow] = Field(default_factory=list)
    holdings: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    #: internal steps (escalation, approvals), not to be sent to the client
    actions: list[str] = Field(default_factory=list)
    #: part of the chain lies beyond the search depth: a deeper investigation may explain more
    depth_limited: bool = False
    max_depth: int = 0


def _flagged(net: Any, list_type: ListType, min_score: float) -> set[str]:
    return {
        h.entity_id
        for h in net.hits
        if h.list_type == list_type
        and h.score >= min_score
        and h.triage not in ("namesake", "dismissed")
    }


def sanctioned_ids(net: Any) -> set[str]:
    t = get_risk_config().thresholds
    return _flagged(net, ListType.SANCTION, t["strong_match_score"])


def _walk_blocked(
    g: nx.DiGraph,
    owner: str,
    node: str,
    pct: float,
    seen: set[str],
    aggregate: dict[str, dict[str, float]],
    blocked: set[str],
) -> None:
    for owned in g.successors(node):
        edge = g.edges[node, owned].get("pct")
        if owned in seen or edge is None:
            continue
        share = pct * edge / 100
        aggregate.setdefault(owned, {})
        aggregate[owned][owner] = aggregate[owned].get(owner, 0.0) + share
        # Stop at another blocked entity: its own holding is counted from it, once.
        if owned not in blocked and len(seen) < MAX_PATH_LENGTH:
            _walk_blocked(g, owner, owned, share, seen | {owned}, aggregate, blocked)


def blocked_by_ownership(net: Any, g: nx.DiGraph | None = None) -> list[BlockedRow]:
    """OFAC 50 % rule / EU ownership: aggregate holdings of blocked persons, to a fixpoint
    (an entity owned 50 % or more by blocked persons is blocked, and so are its own 50 %
    subsidiaries). A walk stops at another blocked owner, whose holding is counted once."""
    g = g if g is not None else ownership_graph(net.relationships.values())
    ents: dict[str, Entity] = net.entities
    blocked = set(sanctioned_ids(net))
    listed = set(blocked)
    if not blocked:
        return []
    aggregate: dict[str, dict[str, float]] = {}
    for _ in range(6):
        aggregate = {}
        for owner in blocked:
            if owner not in g:
                continue

            _walk_blocked(g, owner, owner, 100.0, {owner}, aggregate, blocked)
        grown = {
            eid
            for eid, by in aggregate.items()
            if sum(by.values()) >= BLOCKING_PCT and eid not in blocked
        }
        if not grown:
            break
        blocked |= grown
    control: dict[str, list[str]] = {}
    for r in net.relationships.values():
        if r.type == RelationType.OFFICER and r.is_active and r.source_id in listed:
            control.setdefault(r.target_id, []).append(
                ents[r.source_id].name if r.source_id in ents else r.source_id
            )
    rows = []
    for eid in set(aggregate) | set(control):
        if eid in listed or eid not in ents or ents[eid].type != EntityType.COMPANY:
            continue
        by = aggregate.get(eid, {})
        total = round(min(100.0, sum(by.values())), 2)
        rows.append(
            BlockedRow(
                id=eid,
                name=ents[eid].name,
                aggregate_pct=total,
                blocked=total >= BLOCKING_PCT,
                owners=[
                    {
                        "id": o,
                        "name": ents[o].name if o in ents else o,
                        "pct": round(p, 2),
                        "listed": o in listed,
                    }
                    for o, p in sorted(by.items(), key=lambda x: -x[1])
                ],
                control=sorted(set(control.get(eid, []))),
            )
        )
    return sorted(rows, key=lambda r: (-r.blocked, -r.aggregate_pct, r.name))


def _routes(g: nx.DiGraph, owner: str, subject: str, ents: dict[str, Entity]) -> list[Route]:
    out: list[Route] = []
    for path in nx.all_simple_paths(g, owner, subject, cutoff=MAX_PATH_LENGTH):
        pcts = [g.edges[a, b].get("pct") for a, b in zip(path, path[1:], strict=False)]
        eff: float | None = 100.0
        for p in pcts:
            eff = None if eff is None or p is None else eff * p / 100
        countries = [
            ents[x].jurisdiction
            for x in path
            if x in ents and ents[x].type == EntityType.COMPANY and ents[x].jurisdiction
        ]
        out.append(
            Route(
                ids=path,
                names=[ents[x].name if x in ents else x for x in path],
                pcts=pcts,
                effective=None if eff is None else round(eff, 2),
                countries=list(dict.fromkeys(countries)),
            )
        )
        if len(out) >= MAX_PATHS:
            break
    return out


def _dead_end_reason(e: Entity) -> str:
    if e.is_offshore:
        return "offshore jurisdiction: the register does not publish shareholders"
    if (e.legal_form or "").lower().find("trust") >= 0 or "trust" in e.name.lower():
        return "trust: settlor, trustees and beneficiaries to be obtained from the client"
    if re.search(r"foundation|stiftung|fondation", f"{e.legal_form or ''} {e.name}", re.I):
        return "foundation: founder, council and beneficiaries to be obtained from the client"
    return "shareholders not found in the sources consulted"


def analyse(net: Any, risk_level: str | None = None) -> OwnershipAnalysis:
    t = get_risk_config().thresholds
    threshold = float(t.get("ubo_threshold_pct", 25))
    applied = ENHANCED_THRESHOLD if risk_level in ("high", "critical") else threshold
    ents: dict[str, Entity] = net.entities
    sid = net.subject_id
    subject = ents[sid]
    g = ownership_graph(net.relationships.values())
    pep = _flagged(net, ListType.PEP, t["possible_match_score"])
    sanctioned = sanctioned_ids(net)
    out = OwnershipAnalysis(
        subject_id=sid,
        subject_is_company=subject.type == EntityType.COMPANY,
        threshold=threshold,
        threshold_applied=applied,
        sanctions=blocked_by_ownership(net, g),
    )
    name = lambda x: ents[x].name if x in ents else x  # noqa: E731

    if subject.type != EntityType.COMPANY:
        # A person: what they own, directly or through other companies.
        if sid in g:
            for cid in nx.descendants(g, sid):
                routes = _routes(g, sid, cid, ents)
                known = [r.effective for r in routes if r.effective is not None]
                out.holdings.append(
                    {
                        "id": cid,
                        "name": name(cid),
                        "jurisdiction": ents[cid].jurisdiction if cid in ents else None,
                        "effective_pct": round(min(100.0, sum(known)), 2) if known else None,
                        "direct": g.has_edge(sid, cid),
                        "layers": min(len(r.ids) - 2 for r in routes) if routes else 0,
                    }
                )
        out.holdings.sort(key=lambda h: -(h["effective_pct"] or 0))
        out.actions = _actions(out)
        return out

    ancestors = nx.ancestors(g, sid) if sid in g else set()
    declared: dict[str, float | None] = {}
    for r in net.relationships.values():
        if r.type == RelationType.BENEFICIAL_OWNER and r.is_active and r.target_id == sid:
            declared[r.source_id] = r.share_pct
    roles: dict[str, list[str]] = {}
    for r in net.relationships.values():
        if r.type == RelationType.OFFICER and r.is_active and r.target_id == sid:
            roles.setdefault(r.source_id, []).append(r.role or "officer")

    # Owners: natural persons anywhere above the subject, and the corporate tops of the chain.
    candidates = {
        x
        for x in ancestors
        if x in ents and (ents[x].type == EntityType.PERSON or g.in_degree(x) == 0)
    }
    candidates |= {p for p in declared if p in ents}
    for oid in candidates:
        e = ents[oid]
        routes = _routes(g, oid, sid, ents) if oid in g else []
        known = [r.effective for r in routes if r.effective is not None]
        eff = round(min(100.0, sum(known)), 2) if known else None
        natural = e.type == EntityType.PERSON
        row = OwnerRow(
            id=oid,
            name=e.name,
            type=e.type.value,
            natural_person=natural,
            effective_pct=eff,
            direct_pct=g.edges[oid, sid].get("pct") if g.has_edge(oid, sid) else None,
            partly_unknown=any(r.effective is None for r in routes),
            routes=routes,
            layers=min((len(r.ids) - 2 for r in routes), default=0),
            countries=list(dict.fromkeys(c for r in routes for c in r.countries)),
            declared=oid in declared,
            declared_pct=declared.get(oid),
            roles=sorted(set(roles.get(oid, []))),
            pep=oid in pep,
            sanctioned=oid in sanctioned,
        )
        above = eff is not None and eff >= applied
        if natural:
            row.status = (
                "ubo_both"
                if above and row.declared
                else "ubo_ownership"
                if above
                else "ubo_declared"
                if row.declared
                else "below_threshold"
            )
        else:
            row.status = "dead_end"
        out.owners.append(row)
    out.owners.sort(key=lambda o: (not o.natural_person, -(o.effective_pct or -1), o.name))

    traced = sum(o.effective_pct or 0 for o in out.owners if o.natural_person and o.routes)
    out.traced_pct = round(min(100.0, traced), 2)
    out.unexplained_pct = round(max(0.0, 100.0 - out.traced_pct), 2)

    # Coverage: shareholding identified at each level of the chain.
    for cid in [sid, *sorted(ancestors, key=lambda x: name(x))]:
        e = ents.get(cid)
        if e is None or e.type != EntityType.COMPANY:
            continue
        holders = list(g.predecessors(cid)) if cid in g else []
        pcts = [g.edges[h, cid].get("pct") for h in holders]
        identified = round(min(100.0, sum(p for p in pcts if p is not None)), 2)
        dead = not holders
        edge = net.depth.get(cid, 0) >= net.max_depth and (dead or identified < 100)
        out.coverage.append(
            CoverageRow(
                id=cid,
                name=e.name,
                jurisdiction=e.jurisdiction,
                offshore=e.is_offshore,
                identified_pct=identified,
                unexplained_pct=round(max(0.0, 100.0 - identified), 2),
                holders=len(holders),
                holders_without_pct=sum(p is None for p in pcts),
                dead_end=dead,
                reason=(
                    f"at the edge of the search (depth {net.max_depth}): owners may be found with a deeper investigation"
                    if edge
                    else _dead_end_reason(e)
                    if dead
                    else None
                ),
                depth_limited=edge,
            )
        )
    out.max_depth = net.max_depth
    out.depth_limited = any(c.depth_limited for c in out.coverage)

    # Fallback: senior managing officials when no natural person qualifies.
    if not any(o.status.startswith("ubo") for o in out.owners):
        out.smo_reason = (
            f"No natural person reaches {applied:g} % of {subject.name}, directly or indirectly, and none is "
            "declared: the senior managing official(s) must be recorded as beneficial owner(s) "
            "(EU AMLD art. 3(6)(a)(ii)), with the steps taken to identify an owner."
        )
        for oid, rs in roles.items():
            if (
                oid in ents
                and ents[oid].type == EntityType.PERSON
                and any(SMO_ROLES.search(r) for r in rs)
            ):
                out.smo.append(
                    {"id": oid, "name": ents[oid].name, "role": ", ".join(sorted(set(rs)))}
                )

    out.questions = _questions(out, subject, ents)
    out.actions = _actions(out)
    return out


def _questions(a: OwnershipAnalysis, subject: Entity, ents: dict[str, Entity]) -> list[str]:
    q: list[str] = []
    for c in a.coverage:
        if c.depth_limited:
            continue  # a deeper investigation first, not a question to the client
        if c.dead_end and c.id != subject.id:
            q.append(
                f"Who owns {c.name} ({c.jurisdiction or '?'})? Provide its register of shareholders and UBO declaration — {c.reason}."
            )
        elif c.dead_end:
            q.append(
                f"Provide the register of shareholders of {c.name}: no shareholder was found in the sources consulted."
            )
        elif c.unexplained_pct >= 5:
            q.append(
                f"{c.unexplained_pct:g} % of {c.name} is not accounted for by the shareholders identified: who holds it?"
            )
        if c.holders_without_pct:
            q.append(
                f"Give the percentage held by each shareholder of {c.name} ({c.holders_without_pct} without a published percentage)."
            )
    for o in a.owners:
        if not o.natural_person or o.sanctioned:
            continue  # sanctioned owners: internal escalation first, never a client question
        if o.status == "ubo_ownership":
            q.append(
                f"{o.name} holds an effective {o.effective_pct:g} % but is not declared as beneficial owner: confirm and add to the UBO declaration."
            )
        if (
            o.declared
            and o.declared_pct is not None
            and o.effective_pct is not None
            and abs(o.declared_pct - o.effective_pct) >= 5
        ):
            q.append(
                f"Declared interest of {o.name} ({o.declared_pct:g} %) differs from the computed one ({o.effective_pct:g} %): explain the difference (options, voting rights, nominee?)."
            )
        if o.layers >= 2 and o.effective_pct and o.effective_pct >= a.threshold_applied:
            q.append(
                f"Explain the rationale for holding {subject.name} through {o.layers} intermediate companies ({', '.join(o.countries) or '?'})."
            )
        if o.pep:
            q.append(
                f"{o.name} matches a PEP list: confirm the function held and document the source of wealth."
            )
    if a.smo:
        q.append(
            "No beneficial owner identified by ownership: confirm in writing that no natural person holds 25 % or controls the company by other means."
        )
    return list(dict.fromkeys(q))


def _actions(a: OwnershipAnalysis) -> list[str]:
    """Internal steps: never sent to the client (tipping-off)."""
    out: list[str] = []
    for s in a.sanctions:
        if s.blocked:
            out.append(
                f"Freeze / do not make funds available to {s.name} (owned {s.aggregate_pct:g} % by sanctioned persons): "
                "escalate to sanctions compliance and report to the competent authority."
            )
        elif s.control:
            out.append(
                f"Assess whether {', '.join(s.control)} controls {s.name} (EU control criteria) and record the conclusion."
            )
        elif s.aggregate_pct:
            out.append(
                f"Document the {s.aggregate_pct:g} % sanctioned minority holding in {s.name} and monitor changes in ownership."
            )
    for o in a.owners:
        if o.pep and o.status.startswith("ubo"):
            out.append(
                f"Senior management approval required: {o.name} is a PEP and a beneficial owner."
            )
        if o.sanctioned:
            out.append(
                f"{o.name} is on a sanctions list: confirm the match before any contact with the client about ownership."
            )
    return list(dict.fromkeys(out))
