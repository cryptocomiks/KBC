"""One-screen brief of an investigation: verdict, key figures, red flags with next steps.

Designed to be read in 30 seconds by a compliance officer: what the subject
is, how serious it is and why, and what to do next. Every statement comes
from the risk factors and screening hits already computed (no new inference),
and points to the entities behind it.
"""

from __future__ import annotations

import networkx as nx
from pydantic import BaseModel, Field

from app.graph.expander import Network
from app.graph.ownership import ownership_graph
from app.insights import _best_paths, _pct
from app.models import EntityType, ListType, RelationType
from app.risk.engine import RiskAssessment

STRONG = 85.0

# What an analyst does about each red flag (usual KYC / AML practice; adapt to your policy).
NEXT_STEPS = {
    "formation_agent": "Ask who instructed the service provider and obtain its KYC on the beneficial owners (certificate of incumbency, register of members).",
    "corporate_director": "Identify the natural persons behind the corporate director and the reason for this arrangement.",
    "multi_jurisdiction_officer": "Ask for the economic rationale of the cross-border positions; check each country's register.",
    "possible_same_person": "Compare dates of birth, nationalities and addresses in both registers before linking the two records.",
    "batch_incorporation": "Ask for the purpose of each company created together and who ordered their incorporation.",
    "pre_event_resignation": "Ask the officer about the circumstances of the departure; check the liquidator's report for liabilities.",
    "officer_turnover": "Obtain the history of officers and the reasons for the changes.",
    "sanctions_match": "Confirm identity with official documents (date of birth, nationality, registration number). "
    "If confirmed: do not onboard, freeze and report to the financial intelligence unit.",
    "sanctions_possible_match": "Rule the match out with date of birth or registration number and record the decision.",
    "sanctioned_counterparty": "Block the flows, trace their origin and file a suspicious activity report if confirmed.",
    "watchlist_match": "Read the listing (debarment, wanted notice) and confirm or dismiss the identity match.",
    "pep_match": "Enhanced due diligence: source of wealth and funds, senior management approval, ongoing monitoring.",
    "pep_possible_match": "Confirm whether the person is the PEP (date of birth, positions) before applying EDD.",
    "pep_relative": "Treat as PEP-related: enhanced due diligence on the relationship and the source of funds.",
    "leak_appearance": "Ask for the purpose of the offshore structure, its beneficial owners and supporting documents.",
    "fatf_blacklist": "Apply the counter-measures required for FATF call-for-action countries; senior approval.",
    "fatf_greylist": "Enhanced due diligence on the geographic risk (FATF increased monitoring).",
    "eu_tax_blacklist": "Check the tax rationale of the structure (EU non-cooperative jurisdiction).",
    "high_risk_country": "Enhanced due diligence on the geographic risk; document why the country is used.",
    "offshore_jurisdiction": "Obtain the register extract and the beneficial ownership declaration of the offshore entity.",
    "circular_ownership": "Ask for a signed group chart and an explanation of the circular holding.",
    "long_ownership_chain": "Identify the beneficial owner through every layer (registers, chart, trust deeds).",
    "ubo_discrepancy": "Reconcile declared and computed beneficial owners with the client; report discrepancies "
    "to the register where required (EU AMLD, art. 30).",
    "shared_domiciliation": "Check whether the address is a domiciliation provider hosting many companies.",
    "nominee_director": "Find out on whose behalf the professional director acts.",
    "shell_company_indicators": "Ask for the economic rationale and evidence of real activity (staff, premises, contracts).",
    "recent_incorporation": "Verify business substance: premises, staff, first contracts, bank references.",
    "missing_accounts": "Request the latest financial statements.",
    "dissolved_company": "Make sure the dissolved company no longer plays a role (contracts, accounts, flows).",
    "insolvency_proceedings": "Check the status of the proceedings and the counterparty's solvency.",
    "adverse_media": "Read the articles, keep the relevant ones in the file, dismiss namesakes.",
}


class Figure(BaseModel):
    key: str
    label: str
    value: str
    tone: str = "neutral"  # neutral | good | warning | critical
    hint: str | None = None
    tab: str | None = None  # table to open in the UI


class Flag(BaseModel):
    key: str
    title: str
    severity: str  # critical | warning | info
    points: float
    evidence: list[str]
    next_step: str | None = None
    entity_ids: list[str] = Field(default_factory=list)


class Owner(BaseModel):
    entity_id: str
    name: str
    kind: str
    pct: float
    path: list[str]  # names from the owner down to the subject
    flags: list[str] = Field(default_factory=list)


class Brief(BaseModel):
    subject_type: str
    level: str
    score: float
    headline: str
    figures: list[Figure]
    flags: list[Flag]
    owners: list[Owner]
    coverage: str


def _severity(points: float, key: str) -> str:
    if key.startswith(("sanctions_match", "sanctioned_", "fatf_blacklist")) or points >= 20:
        return "critical"
    return "warning" if points >= 5 else "info"


def build_brief(net: Network, risk: RiskAssessment, jur_name=lambda c: c or "?") -> Brief:
    ents = net.entities
    subject = ents[net.subject_id]
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731
    hits = [h for h in net.hits if h.score >= STRONG]
    sanctioned = {h.entity_id for h in hits if h.list_type == ListType.SANCTION}
    peps = {h.entity_id for h in hits if h.list_type == ListType.PEP}
    leaked = {h.entity_id for h in hits if h.list_type == ListType.LEAK}

    # --- Ultimate owners of a company subject (persons, or companies nobody is known to own)
    owners: list[Owner] = []
    g = ownership_graph(net.relationships.values())
    if subject.type == EntityType.COMPANY and subject.id in g:
        for node in nx.ancestors(g, subject.id):
            ent = ents.get(node)
            if g.in_degree(node) > 0 and ent is not None and ent.type == EntityType.COMPANY:
                continue
            total, path = _best_paths(g, node, subject.id)
            if total <= 0:
                continue
            tags = [
                t
                for t, members in (("sanctioned", sanctioned), ("PEP", peps), ("in leaks", leaked))
                if node in members
            ]
            owners.append(
                Owner(
                    entity_id=node,
                    name=name(node),
                    kind=ent.type.value if ent else "unknown",
                    pct=total,
                    path=[name(p) for p in path],
                    flags=tags,
                )
            )
        owners.sort(key=lambda o: -o.pct)
    elif subject.type == EntityType.PERSON and subject.id in g:
        # For a person: what they control, directly or through companies (effective %).
        for node in nx.descendants(g, subject.id):
            total, path = _best_paths(g, subject.id, node)
            ent = ents.get(node)
            if total <= 0 or ent is None:
                continue
            tags = [
                t
                for t, members in (("sanctioned", sanctioned), ("PEP", peps), ("in leaks", leaked))
                if node in members
            ]
            owners.append(
                Owner(
                    entity_id=node,
                    name=name(node),
                    kind=ent.type.value,
                    pct=total,
                    path=[name(p) for p in reversed(path)],
                    flags=tags,
                )
            )
        owners.sort(key=lambda o: -o.pct)

    # --- Headline: the single most important fact, in plain words
    def distance(eid: str) -> int:
        return net.depth.get(eid, 9)

    headline = ""
    sanctioned_owner = next((o for o in owners if "sanctioned" in o.flags), None)
    if subject.id in sanctioned:
        h = next(h for h in hits if h.entity_id == subject.id and h.list_type == ListType.SANCTION)
        headline = (
            f"{subject.name} matches the sanctions list “{h.dataset}” ({h.score:.0f}% confidence)."
        )
    elif sanctioned_owner:
        via = (
            f" via {' → '.join(sanctioned_owner.path[1:-1])}"
            if len(sanctioned_owner.path) > 2
            else ""
        )
        headline = f"{subject.name} is {_pct(sanctioned_owner.pct)} owned by a sanctioned {sanctioned_owner.kind}, {sanctioned_owner.name}{',' if via else ''}{via}."
    elif sanctioned:
        closest = min(sanctioned, key=distance)
        headline = f"{subject.name} is {distance(closest)} link(s) away from a sanctioned party: {name(closest)}."
    elif any(f.key == "sanctioned_counterparty" for f in risk.factors):
        headline = f"{subject.name} is exposed to crypto flows with a sanctioned wallet."
    elif peps:
        closest = min(peps, key=distance)
        role = "is" if closest == subject.id else f"is linked ({distance(closest)} link(s)) to"
        headline = f"{subject.name} {role} a politically exposed person{'' if closest == subject.id else ': ' + name(closest)}."
    elif leaked:
        datasets = sorted({h.dataset.split(" (")[0] for h in hits if h.list_type == ListType.LEAK})
        headline = (
            f"{subject.name}'s network appears in leaked offshore data ({', '.join(datasets[:3])})."
        )
    elif risk.factors:
        top = max(risk.factors, key=lambda f: f.points)
        headline = f"{subject.name}: main concern — {top.label.lower()}."
    else:
        headline = f"No red flag found for {subject.name} in the sources queried."

    if subject.type == EntityType.COMPANY:
        if owners:
            o = owners[0]
            if sanctioned_owner is None or o.entity_id != sanctioned_owner.entity_id:
                headline += f" Largest ultimate owner: {o.name} ({_pct(o.pct)})."
        else:
            headline += " Ultimate owners not identified in the sources."
    if subject.id in net.unscreened:
        headline = (
            f"Screening of {subject.name} against sanctions, PEP and leak lists could not finish "
            f"in time: the score ({risk.score:.0f}) leaves out those checks and must not be relied on. "
            "Rerun the investigation (answers are cached) or reduce the depth."
        )
    elif net.unscreened:
        headline += f" {len(net.unscreened)} linked parties could not be screened in time (rerun to complete)."
    headline = f"{risk.level.upper()} — {headline}"

    # --- Key figures
    countries = {
        e.jurisdiction for e in ents.values() if e.type == EntityType.COMPANY and e.jurisdiction
    }
    risky = {
        eid
        for f in risk.factors
        if f.key
        in (
            "high_risk_country",
            "fatf_blacklist",
            "fatf_greylist",
            "offshore_jurisdiction",
            "eu_tax_blacklist",
        )
        for eid in f.entities
    }
    risky_countries = {ents[e].jurisdiction for e in risky if e in ents and ents[e].jurisdiction}
    flows = [
        r
        for r in net.relationships.values()
        if r.type == RelationType.TRANSFER
        and (r.source_id in sanctioned or r.target_id in sanctioned)
    ]
    media = sum(d.kind == "adverse_media" for e in ents.values() for d in e.documents)
    persons = sum(e.type == EntityType.PERSON for e in ents.values())
    companies = sum(e.type == EntityType.COMPANY for e in ents.values())

    def tone(n: int, bad: str) -> str:
        return bad if n else "good"

    figures = [
        Figure(
            key="network",
            label="Network",
            value=f"{companies} companies · {persons} persons",
            tab="companies",
        ),
        Figure(
            key="owners",
            label="Ultimate owners",
            value=f"{len(owners)} identified" if owners else "unknown",
            tone="neutral" if owners else "warning",
            hint=f"largest: {owners[0].name} {_pct(owners[0].pct)}"
            if owners
            else "no shareholder data found",
            tab="ownership",
        )
        if subject.type == EntityType.COMPANY
        else Figure(
            key="mandates",
            label="Mandates",
            value=str(
                sum(
                    r.source_id == subject.id and r.type == RelationType.OFFICER
                    for r in net.relationships.values()
                )
            ),
            tab="mandates",
        ),
        Figure(
            key="sanctions",
            label="Sanctions hits",
            value=str(len(sanctioned)),
            tone=tone(len(sanctioned), "critical"),
            tab="screening",
        ),
        Figure(
            key="pep",
            label="PEP",
            value=str(len(peps)),
            tone=tone(len(peps), "warning"),
            tab="screening",
        ),
        Figure(
            key="leaks",
            label="In leaks",
            value=str(len(leaked)),
            tone=tone(len(leaked), "warning"),
            tab="leaks",
        ),
        Figure(
            key="countries",
            label="Countries",
            value=f"{len(countries)}"
            + (f" · {len(risky_countries)} high-risk" if risky_countries else ""),
            tone="warning" if risky_countries else "neutral",
            hint=", ".join(jur_name(c) for c in sorted(risky_countries)[:3]) or None,
            tab="jurisdictions",
        ),
        Figure(
            key="media",
            label="Adverse media",
            value=str(media),
            tone=tone(media, "warning"),
            tab="documents",
        ),
    ]
    if flows:
        total = {}
        for r in flows:
            total[r.currency or "?"] = total.get(r.currency or "?", 0) + (r.amount or 0)
        figures.append(
            Figure(
                key="crypto",
                label="Flows with sanctioned wallets",
                value=", ".join(f"{v:,.0f} {k}" for k, v in total.items()),
                tone="critical",
                tab="crypto",
            )
        )

    triaged = [
        h
        for h in net.hits
        if h.list_type in (ListType.SANCTION, ListType.PEP, ListType.ADVERSE, ListType.LEAK)
    ]
    counts = {
        k: sum(1 for h in triaged if (h.triage or "verify") == k)
        for k in ("likely", "verify", "namesake", "dismissed")
    }
    if triaged:
        figures.insert(
            1,
            Figure(
                key="triage",
                label="Alerts to review",
                value=f"{counts['likely']} likely · {counts['verify']} to check",
                tone="critical" if counts["likely"] else "warning" if counts["verify"] else "good",
                hint=f"{counts['namesake']} probable namesakes"
                + (f", {counts['dismissed']} already ruled out" if counts["dismissed"] else ""),
                tab="screening",
            ),
        )

    flags = [
        Flag(
            key=f.key,
            title=f.label,
            severity=_severity(f.points, f.key),
            points=f.points,
            evidence=f.evidence[:3],
            next_step=NEXT_STEPS.get(f.key),
            entity_ids=f.entities[:5],
        )
        for f in sorted(risk.factors, key=lambda f: -f.points)
    ]
    sources = len({q.source for q in net.queries})
    coverage = f"{sources} sources queried, {len(net.queries)} queries."
    if net.truncated or net.warnings:
        coverage += " Partial coverage: " + "; ".join(net.warnings[:2])
    return Brief(
        subject_type=subject.type.value,
        level=risk.level,
        score=risk.score,
        headline=headline,
        figures=figures,
        flags=flags,
        owners=owners[:8],
        coverage=coverage,
    )
