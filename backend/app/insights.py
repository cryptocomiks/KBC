"""Readable layer on top of the network: key findings (summary) and a timeline.

Everything here is derived from data already in the investigation, with the
entity ids and source URLs behind each sentence, so the analyst can check
every statement. Nothing is inferred beyond what the sources say.
"""

from __future__ import annotations

from datetime import date

import networkx as nx
from pydantic import BaseModel, Field

from app.graph.expander import Network
from app.graph.ownership import MAX_PATH_LENGTH, ownership_graph
from app.models import CompanyStatus, Entity, EntityType, ListType, RelationType
from app.risk.engine import RiskAssessment

MIN_CONTROL_PCT = 10.0
MAX_TIMELINE = 300


class Finding(BaseModel):
    text: str
    severity: str = "info"  # info | warning | critical
    entity_ids: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    date: str  # "YYYY-MM-DD", or "YYYY" when the source only gives the year
    kind: str  # company | role | ownership | filing | legal_notice | sanction | media | transfer
    title: str
    entity_id: str | None = None
    detail: str | None = None
    url: str | None = None
    source: str | None = None


def _pct(v: float) -> str:
    return f"{v:.0f}%" if v >= 1 else f"{v:.2f}%"


def _url(e: Entity) -> list[str]:
    return [p.url for p in e.sources if p.url][:1]


def _best_paths(g: nx.DiGraph, owner: str, target: str) -> tuple[float, list[str]]:
    """Total economic interest of `owner` in `target` and the heaviest path behind it."""
    total, best, best_share = 0.0, [owner, target], -1.0

    def walk(node: str, share: float, path: list[str]) -> None:
        nonlocal total, best, best_share
        for nxt in g.successors(node):
            pct = g.edges[node, nxt].get("pct")
            if nxt in path or pct is None:
                continue
            s = share * pct / 100
            if nxt == target:
                total += s
                if s > best_share:
                    best, best_share = [*path, nxt], s
            elif len(path) < MAX_PATH_LENGTH:
                walk(nxt, s, [*path, nxt])

    walk(owner, 100.0, [owner])
    return round(total, 2), best


def _identity(e: Entity, jur_name) -> str:
    if e.type == EntityType.PERSON:
        bits = [f"born {e.birth_date}" if e.birth_date else None]
        if e.nationalities:
            bits.append("nationality " + ", ".join(jur_name(n) for n in e.nationalities))
        desc = e.extra.get("description")
        details = ", ".join(b for b in bits if b)
        return f"{e.name} is a person{f' ({details})' if details else ''}" + (
            f", described as “{desc}”." if desc else "."
        )
    if e.type == EntityType.WALLET:
        return f"{e.address or e.name} is a {e.chain or 'crypto'} wallet."
    since = (
        f" since {e.incorporation_date.year}"
        if e.incorporation_date
        else (f" since {e.extra['founded'][:4]}" if e.extra.get("founded") else "")
    )
    where = f" registered in {jur_name(e.jurisdiction)}" if e.jurisdiction else ""
    form = e.legal_form or "company"
    status = ""
    if e.status == CompanyStatus.DISSOLVED:
        status = f" It was dissolved{f' on {e.dissolution_date}' if e.dissolution_date else ''}."
    activity = f" Activity: {e.activity}." if e.activity else ""
    return f"{e.name} is a {form}{where}{since}.{status}{activity}"


def build_summary(net: Network, risk: RiskAssessment, jur_name=lambda c: c or "?") -> list[Finding]:
    ents = net.entities
    subject = ents.get(net.subject_id)
    if subject is None:
        return []
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731
    out: list[Finding] = [
        Finding(text=_identity(subject, jur_name), entity_ids=[subject.id], urls=_url(subject))
    ]

    # --- Control / holdings
    g = ownership_graph(net.relationships.values())
    if subject.type == EntityType.COMPANY:
        owners = []
        for node in nx.ancestors(g, subject.id) if subject.id in g else []:
            ent = ents.get(node)
            if g.in_degree(node) > 0 and ent is not None and ent.type == EntityType.COMPANY:
                continue  # only ultimate owners: persons, or companies nobody is known to own
            total, path = _best_paths(g, node, subject.id)
            if total >= MIN_CONTROL_PCT:
                owners.append((total, node, path))
        owners.sort(reverse=True)
        for total, node, path in owners[:3]:
            via = (
                f" via {' → '.join(name(p) for p in path[1:-1])}" if len(path) > 2 else " directly"
            )
            kind = "person" if ents.get(node) and ents[node].type == EntityType.PERSON else "entity"
            out.append(
                Finding(
                    text=f"Ultimately held at {_pct(total)} by {name(node)} ({kind}){via}.",
                    entity_ids=path,
                )
            )
        has_shareholders = subject.id in g and any(True for _ in g.predecessors(subject.id))
        if not has_shareholders:
            out.append(
                Finding(
                    text="No shareholder data was found in the sources queried: "
                    "the beneficial ownership remains to be established (UBO register, KYC documents).",
                    severity="warning",
                    entity_ids=[subject.id],
                )
            )
    elif subject.type == EntityType.PERSON:
        stakes = []
        if subject.id in g:
            for node in nx.descendants(g, subject.id):
                total, path = _best_paths(g, subject.id, node)
                if total > 0:
                    stakes.append((total, node, path))
        stakes.sort(reverse=True)
        mandates = [
            r
            for r in net.relationships.values()
            if r.source_id == subject.id and r.type == RelationType.OFFICER and r.is_active
        ]
        if stakes:
            top = "; ".join(
                f"{_pct(t)} of {name(n)}"
                + (f" (via {' → '.join(name(p) for p in path[1:-1])})" if len(path) > 2 else "")
                for t, n, path in stakes[:3]
            )
            out.append(
                Finding(
                    text=f"Holds interests in {len(stakes)} compan{'y' if len(stakes) == 1 else 'ies'}: {top}.",
                    entity_ids=[subject.id, *[n for _, n, _ in stakes[:3]]],
                )
            )
        if mandates:
            out.append(
                Finding(
                    text=f"Holds {len(mandates)} active mandate(s): "
                    + "; ".join(
                        f"{r.role or 'officer'} of {name(r.target_id)}" for r in mandates[:4]
                    )
                    + ("…" if len(mandates) > 4 else "."),
                    entity_ids=[subject.id, *[r.target_id for r in mandates[:4]]],
                )
            )

    # --- Risk drivers
    top = sorted(risk.factors, key=lambda f: f.points, reverse=True)[:3]
    if top:
        out.append(
            Finding(
                text=f"Overall risk {risk.level.upper()} ({risk.score:.0f}/100). Main drivers: "
                + "; ".join(f"{f.label} (+{f.points:.0f})" for f in top)
                + ".",
                severity="critical"
                if risk.level in ("high", "critical")
                else "warning"
                if risk.level == "medium"
                else "info",
            )
        )
    else:
        out.append(
            Finding(
                text=f"Overall risk {risk.level.upper()} ({risk.score:.0f}/100): no red flag raised."
            )
        )

    # --- Screening
    strong = 85.0
    for list_type, label, severity in (
        (ListType.SANCTION, "Sanctions", "critical"),
        (ListType.PEP, "PEP", "warning"),
        (ListType.ADVERSE, "Watchlists", "warning"),
    ):
        hits = sorted(
            (h for h in net.hits if h.list_type == list_type and h.score >= strong),
            key=lambda h: -h.score,
        )
        if hits:
            shown = "; ".join(
                f"{name(h.entity_id)} ≈ “{h.matched_name}” on {h.dataset} ({h.score:.0f}%)"
                for h in hits[:3]
            )
            more = f" and {len(hits) - 3} more" if len(hits) > 3 else ""
            out.append(
                Finding(
                    text=f"{label}: {shown}{more}. To be confirmed on identifiers (date of birth, registration number).",
                    severity=severity,
                    entity_ids=list(dict.fromkeys(h.entity_id for h in hits[:3])),
                    urls=[u for h in hits[:3] if (u := h.provenance.url)],
                )
            )
    leaks = [h for h in net.hits if h.list_type == ListType.LEAK and h.score >= strong]
    if leaks:
        datasets = sorted({h.dataset for h in leaks})
        out.append(
            Finding(
                text=f"{len({h.entity_id for h in leaks})} entit(ies) of the network appear in leaked data "
                f"({', '.join(datasets[:4])}). Appearing in a leak is not wrongdoing, but calls for an explanation.",
                severity="warning",
                entity_ids=list(dict.fromkeys(h.entity_id for h in leaks))[:5],
                urls=[u for h in leaks[:3] if (u := h.provenance.url)],
            )
        )
    media = [(e, d) for e in ents.values() for d in e.documents if d.kind == "adverse_media"]
    if media:
        out.append(
            Finding(
                text=f"{len(media)} press article(s) with risk keywords (fraud, corruption, sanctions…) "
                f"mention {len({e.id for e, _ in media})} entit(ies) of the network — see the timeline.",
                severity="warning",
                entity_ids=list(dict.fromkeys(e.id for e, _ in media))[:5],
                urls=[d.url for _, d in media[:3] if d.url],
            )
        )

    # --- Jurisdictions and network shape
    countries = sorted(
        {e.jurisdiction for e in ents.values() if e.type == EntityType.COMPANY and e.jurisdiction}
    )
    offshore = [
        e
        for e in ents.values()
        if e.is_offshore
        or e.id in {i for f in risk.factors if f.key == "offshore_jurisdiction" for i in f.entities}
    ]
    persons = sum(e.type == EntityType.PERSON for e in ents.values())
    companies = sum(e.type == EntityType.COMPANY for e in ents.values())
    shape = f"The mapped network has {companies} companies and {persons} persons across {len(countries)} jurisdiction(s)"
    shape += (
        f" ({', '.join(jur_name(c) for c in countries[:6])}{'…' if len(countries) > 6 else ''})."
        if countries
        else "."
    )
    if offshore:
        shape += f" {len(offshore)} entit(ies) sit in offshore centres: {', '.join(e.name for e in offshore[:3])}."
    out.append(
        Finding(
            text=shape,
            severity="warning" if offshore else "info",
            entity_ids=[e.id for e in offshore[:3]],
        )
    )

    if net.truncated or net.warnings:
        out.append(
            Finding(
                text="Coverage is partial ("
                + "; ".join(net.warnings[:2])
                + "). Absence of a flag is not evidence of absence.",
                severity="warning",
            )
        )
    return out


# ------------------------------------------------------------------ timeline
def _d(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)[:10] or None


def build_timeline(net: Network) -> list[TimelineEvent]:
    ents = net.entities
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731
    events: list[TimelineEvent] = []

    def src(e: Entity) -> tuple[str | None, str | None]:
        p = e.sources[0] if e.sources else None
        return (p.url, p.source_label) if p else (None, None)

    for e in ents.values():
        url, label = src(e)
        if e.type == EntityType.COMPANY:
            founded = _d(e.incorporation_date) or (
                str(e.extra["founded"])[:4] if e.extra.get("founded") else None
            )
            if founded:
                events.append(
                    TimelineEvent(
                        date=founded,
                        kind="company",
                        title=f"{e.name} incorporated",
                        entity_id=e.id,
                        url=url,
                        source=label,
                        detail=", ".join(x for x in (e.legal_form, e.jurisdiction) if x) or None,
                    )
                )
            if e.dissolution_date:
                events.append(
                    TimelineEvent(
                        date=_d(e.dissolution_date),
                        kind="company",
                        title=f"{e.name} dissolved",
                        entity_id=e.id,
                        url=url,
                        source=label,
                    )
                )
        for doc in e.documents:
            if not doc.date:
                continue
            kind = (
                "media"
                if doc.kind == "adverse_media"
                else "legal_notice"
                if doc.kind == "legal_notice"
                else "filing"
            )
            events.append(
                TimelineEvent(
                    date=_d(doc.date),
                    kind=kind,
                    title=f"{e.name}: {doc.title}",
                    entity_id=e.id,
                    detail=doc.summary,
                    url=doc.url,
                    source=doc.source,
                )
            )

    for r in net.relationships.values():
        prov = r.sources[0] if r.sources else None
        url, label = (prov.url, prov.source_label) if prov else (None, None)
        src_name, tgt_name = name(r.source_id), name(r.target_id)
        if r.type == RelationType.OFFICER:
            start, end = (
                f"{src_name} appointed {r.role or 'officer'} of {tgt_name}",
                f"{src_name} left {r.role or 'office'} at {tgt_name}",
            )
            kind = "role"
        elif r.type in (RelationType.SHAREHOLDER, RelationType.BENEFICIAL_OWNER):
            pct = f" ({_pct(r.share_pct)})" if r.share_pct is not None else ""
            start, end = (
                f"{src_name} becomes {'beneficial owner' if r.type == RelationType.BENEFICIAL_OWNER else 'shareholder'} of {tgt_name}{pct}",
                f"{src_name} no longer holds {tgt_name}",
            )
            kind = "ownership"
        elif r.type == RelationType.TRANSFER:
            amount = (
                f"{r.amount:,.2f} {r.currency or ''}".strip() if r.amount is not None else "funds"
            )
            start, end = (
                f"First transfer {src_name} → {tgt_name}",
                f"Last transfer {src_name} → {tgt_name}",
            )
            kind = "transfer"
            if r.start_date:
                events.append(
                    TimelineEvent(
                        date=_d(r.start_date),
                        kind=kind,
                        title=start,
                        entity_id=r.source_id,
                        detail=f"{amount} in {r.tx_count or '?'} transaction(s) in total",
                        url=url,
                        source=label,
                    )
                )
            if r.end_date and r.end_date != r.start_date:
                events.append(
                    TimelineEvent(
                        date=_d(r.end_date),
                        kind=kind,
                        title=end,
                        entity_id=r.source_id,
                        url=url,
                        source=label,
                    )
                )
            continue
        else:
            continue
        if r.start_date:
            events.append(
                TimelineEvent(
                    date=_d(r.start_date),
                    kind=kind,
                    title=start,
                    entity_id=r.target_id,
                    url=url,
                    source=label,
                )
            )
        if r.end_date:
            events.append(
                TimelineEvent(
                    date=_d(r.end_date),
                    kind=kind,
                    title=end,
                    entity_id=r.target_id,
                    url=url,
                    source=label,
                )
            )

    for h in net.hits:
        listed = (
            h.details.get("listed_on") or h.details.get("first_seen") or h.details.get("listed")
        )
        if not listed or h.list_type not in (ListType.SANCTION, ListType.ADVERSE):
            continue
        events.append(
            TimelineEvent(
                date=str(listed)[:10],
                kind="sanction",
                title=f"{h.matched_name} listed on {h.dataset}",
                entity_id=h.entity_id,
                detail=f"match confidence {h.score:.0f}%",
                url=h.provenance.url,
                source=h.provenance.source_label,
            )
        )

    seen: set[tuple[str, str]] = set()
    unique = []
    for ev in sorted(events, key=lambda e: e.date, reverse=True):
        if (ev.date, ev.title) in seen:
            continue
        seen.add((ev.date, ev.title))
        unique.append(ev)
    return unique[:MAX_TIMELINE]
