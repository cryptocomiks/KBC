"""Explainable risk scoring.

Each rule inspects the resolved network and returns a factor with:
the configured weight, the proximity multiplier (distance of the closest
affected entity to the subject), the resulting points, the affected
entities and human-readable evidence. Nothing is hidden: the global score
is literally the sum of the points displayed in the UI and in the report.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.graph.expander import Network
from app.graph.ownership import (
    corporate_layers_above,
    find_cycles,
    indirect_stakes,
    ownership_graph,
)
from app.models import CompanyStatus, EntityType, ListType, RelationType
from app.risk.config import (
    JurisdictionLists,
    RiskConfig,
    get_country_risk,
    get_jurisdictions,
    get_risk_config,
)

FACTOR_LABELS = {
    "sanctions_match": "Sanctions list match",
    "sanctions_possible_match": "Possible sanctions match (to be ruled out)",
    "pep_match": "Politically exposed person (PEP)",
    "pep_possible_match": "Possible PEP match (to be ruled out)",
    "leak_appearance": "Appears in leaked data (offshore leaks / Aleph)",
    "fatf_blacklist": "FATF black list jurisdiction",
    "fatf_greylist": "FATF grey list jurisdiction",
    "eu_tax_blacklist": "EU non-cooperative tax jurisdiction",
    "offshore_jurisdiction": "Offshore financial centre",
    "circular_ownership": "Circular ownership",
    "long_ownership_chain": "Long ownership chain",
    "shared_domiciliation": "Shared domiciliation address",
    "recent_incorporation": "Recently incorporated company",
    "dissolved_company": "Dissolved / struck-off company",
    "missing_accounts": "No recent accounts filed",
    "nominee_director": "Possible nominee / professional director",
    "ubo_discrepancy": "Undeclared beneficial owner (computed vs declared)",
    "insolvency_proceedings": "Insolvency proceedings (legal notice)",
    "sanctioned_counterparty": "Crypto flows with a sanctioned wallet",
    "pep_relative": "Relative or close associate of a PEP",
    "watchlist_match": "Watchlist match (debarment, wanted notice, criminal / court records)",
    "adverse_media": "Adverse media (press mentions with risk keywords)",
    "high_risk_country": "High-risk country (Basel AML Index / corruption perception)",
    "shell_company_indicators": "Shell-company indicator (large balance sheet, no revenue)",
}


class RiskFactor(BaseModel):
    key: str
    label: str
    weight: float
    distance: int
    multiplier: float
    points: float
    entities: list[str]
    evidence: list[str]


class RiskAssessment(BaseModel):
    score: float
    level: str
    factors: list[RiskFactor]
    entity_flags: dict[str, list[str]] = Field(default_factory=dict)
    entity_points: dict[str, float] = Field(default_factory=dict)
    entity_levels: dict[str, str] = Field(default_factory=dict)
    cycles: list[list[str]] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)


def _amount(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


class RiskEngine:
    def __init__(
        self,
        config: RiskConfig | None = None,
        jurisdictions: JurisdictionLists | None = None,
        today: date | None = None,
    ) -> None:
        self.cfg = config or get_risk_config()
        self.jur = jurisdictions or get_jurisdictions()
        self.countries = get_country_risk()
        self.today = today or date.today()

    def _shell_indicator(self, financials: list[dict]) -> str | None:
        """Large balance sheet with (almost) no revenue in the latest published accounts."""
        if not financials:
            return None
        latest = financials[0]
        assets, revenue = _amount(latest.get("total_assets")), _amount(latest.get("revenue"))
        t = self.cfg.thresholds
        if assets is None or revenue is None or assets < t.get("shell_min_assets", 1_000_000):
            return None
        if revenue > assets * t.get("shell_max_revenue_ratio", 0.01):
            return None
        cur = latest.get("currency", "")
        return (
            f"total assets {latest['total_assets']} {cur} but revenue {latest['revenue']} {cur} "
            f"({latest.get('year')}) — a holding or an empty shell: check the economic rationale"
        )

    def assess(self, net: Network) -> RiskAssessment:
        hits: dict[str, list[tuple[str, str]]] = {}  # factor -> [(entity_id, evidence)]

        def flag(factor: str, entity_id: str, evidence: str) -> None:
            hits.setdefault(factor, []).append((entity_id, evidence))

        t = self.cfg.thresholds
        ents = net.entities
        name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731

        # 1. Screening hits (sanctions / PEP / leaks)
        for h in net.hits:
            if h.score < t["possible_match_score"]:
                continue  # weak hit: displayed for review but not scored
            strong = h.score >= t["strong_match_score"]
            ev = f"{name(h.entity_id)} ≈ '{h.matched_name}' — {h.dataset} (confidence {h.score:.0f}%)"
            if h.list_type == ListType.SANCTION:
                flag("sanctions_match" if strong else "sanctions_possible_match", h.entity_id, ev)
            elif h.list_type == ListType.PEP:
                flag("pep_match" if strong else "pep_possible_match", h.entity_id, ev)
            elif h.list_type == ListType.LEAK:
                flag("leak_appearance", h.entity_id, ev)
            elif h.list_type == ListType.ADVERSE and strong:
                flag("watchlist_match", h.entity_id, ev)

        # 2. Jurisdictions and company lifecycle
        for eid, e in ents.items():
            if e.type != EntityType.COMPANY:
                continue
            code = (e.jurisdiction or "").upper()
            label = f"{e.name} ({self.jur.name(code)})"
            if code in self.jur.fatf_blacklist:
                flag("fatf_blacklist", eid, label)
            if code in self.jur.fatf_greylist:
                flag("fatf_greylist", eid, label)
            if code in self.jur.eu_tax_blacklist:
                flag("eu_tax_blacklist", eid, label)
            if code in self.jur.offshore_centres:
                flag("offshore_jurisdiction", eid, label)
            indicators = self.countries.get(code)
            basel = indicators.get("basel_aml_score")
            cpi = indicators.get("cpi_score")
            if (basel is not None and basel >= t.get("basel_high_score", 6.0)) or (
                cpi is not None and cpi < t.get("cpi_low_score", 30)
            ):
                flag("high_risk_country", eid, f"{label}: {self.countries.describe(code)}")

            for doc in e.documents:
                if "insolvency" in doc.flags:
                    when = f" on {doc.date}" if doc.date else ""
                    flag(
                        "insolvency_proceedings",
                        eid,
                        f"{e.name}: {doc.title}{when}"
                        + (f" — {doc.summary}" if doc.summary else ""),
                    )
            shell = self._shell_indicator(e.extra.get("financials") or [])
            if shell:
                flag("shell_company_indicators", eid, f"{e.name}: {shell}")
            if e.status == CompanyStatus.DISSOLVED:
                when = f" on {e.dissolution_date}" if e.dissolution_date else ""
                flag("dissolved_company", eid, f"{e.name} dissolved{when}")
                continue
            if e.incorporation_date:
                age = _months_between(e.incorporation_date, self.today)
                if age < t["recent_incorporation_months"]:
                    flag(
                        "recent_incorporation",
                        eid,
                        f"{e.name} incorporated {e.incorporation_date} ({age} months ago)",
                    )
            if e.extra.get("accounts_overdue"):
                flag(
                    "missing_accounts", eid, f"{e.name}: accounts overdue according to the registry"
                )
            elif e.last_accounts_date is None:
                if not e.extra.get("accounts_unknown"):
                    flag("missing_accounts", eid, f"{e.name}: no accounts on file")
            else:
                overdue = _months_between(e.last_accounts_date, self.today)
                if overdue > t["accounts_overdue_months"]:
                    flag(
                        "missing_accounts",
                        eid,
                        f"{e.name}: last accounts dated {e.last_accounts_date} ({overdue} months ago)",
                    )

        # 3. Ownership structure
        og = ownership_graph(net.relationships.values())
        cycles = [c for c in find_cycles(og) if len(c) > 1]
        for cycle in cycles:
            path = " → ".join(name(x) for x in [*cycle, cycle[0]])
            for eid in cycle:
                flag("circular_ownership", eid, f"Circular shareholding: {path}")
        for eid, e in ents.items():
            if e.type != EntityType.COMPANY:
                continue
            layers = corporate_layers_above(og, eid, ents)
            if len(layers) >= t["long_chain_min_layers"]:
                chain = " → ".join(name(x) for x in [*reversed(layers), eid])
                flag("long_ownership_chain", eid, f"{len(layers)} corporate layers: {chain}")

        # UBO discrepancy: a person whose computed effective interest reaches the
        # UBO threshold but who is absent from the declared beneficial owners.
        declared: dict[str, set[str]] = {}
        for r in net.relationships.values():
            if r.type == RelationType.BENEFICIAL_OWNER and r.is_active:
                declared.setdefault(r.target_id, set()).add(r.source_id)
        ubo_min = t.get("ubo_threshold_pct", 25)
        for pid, p in ents.items():
            if p.type != EntityType.PERSON:
                continue
            for cid, pct in indirect_stakes(og, pid).items():
                if cid in declared and pid not in declared[cid] and pct >= ubo_min:
                    listed = ", ".join(sorted(name(x) for x in declared[cid]))
                    flag(
                        "ubo_discrepancy",
                        cid,
                        f"{p.name} holds an effective {pct:g}% of {name(cid)} but is not among "
                        f"its declared beneficial owners ({listed})",
                    )
                    flag(
                        "ubo_discrepancy",
                        pid,
                        f"{p.name}: undeclared UBO of {name(cid)} ({pct:g}%)",
                    )

        # Crypto: direct on-chain flows with a sanctioned wallet (exposure)
        sanctioned = {
            h.entity_id
            for h in net.hits
            if h.list_type == ListType.SANCTION and h.score >= t["strong_match_score"]
        }
        for r in net.relationships.values():
            if r.type != RelationType.TRANSFER:
                continue
            for mine, other, verb in (
                (r.target_id, r.source_id, "received from"),
                (r.source_id, r.target_id, "sent to"),
            ):
                if other in sanctioned and mine not in sanctioned and mine in ents:
                    amount = f"{r.amount:,.2f} {r.currency}" if r.amount is not None else "funds"
                    flag(
                        "sanctioned_counterparty",
                        mine,
                        f"{ents[mine].name} {verb} sanctioned wallet {name(other)}: {amount} in {r.tx_count or '?'} tx",
                    )

        # PEP relatives and close associates (RCA)
        peps = {
            h.entity_id: h
            for h in net.hits
            if h.list_type == ListType.PEP and h.score >= t["strong_match_score"]
        }
        for r in net.relationships.values():
            if r.type != RelationType.RELATIVE:
                continue
            for mine, other in ((r.source_id, r.target_id), (r.target_id, r.source_id)):
                if other in peps and mine not in peps and mine in ents:
                    flag(
                        "pep_relative",
                        mine,
                        f"{ents[mine].name} — {r.role or 'relative'} of {name(other)} (PEP: {peps[other].matched_name})",
                    )

        # Adverse media: keyword-filtered press mentions (leads to review)
        for eid, e in ents.items():
            articles = [d for d in e.documents if "adverse_media" in d.flags]
            if articles:
                titles = "; ".join(f"“{d.title[:80]}” ({d.date})" for d in articles[:3])
                flag(
                    "adverse_media",
                    eid,
                    f"{e.name}: {len(articles)} article(s) with risk keywords — {titles}",
                )

        # 4. Addresses and nominee directors
        for eid, e in ents.items():
            if e.type == EntityType.ADDRESS:
                in_graph = sum(
                    1
                    for r in net.relationships.values()
                    if r.type == RelationType.REGISTERED_AT and r.target_id == eid
                )
                registered = max(in_graph, int(e.extra.get("companies_registered", 0)))
                if registered >= t["shared_address_min_companies"]:
                    flag(
                        "shared_domiciliation",
                        eid,
                        f"{registered} companies registered at {e.name}",
                    )
            elif e.type == EntityType.PERSON:
                n = int(e.extra.get("active_mandates", 0))
                if n >= t["nominee_min_mandates"]:
                    flag("nominee_director", eid, f"{e.name} holds {n} active board mandates")

        # Assemble factors (each counted once, weighted by proximity).
        factors = []
        entity_flags: dict[str, list[str]] = {}
        entity_points: dict[str, float] = {}
        for key, items in hits.items():
            weight = float(self.cfg.weights.get(key, 0))
            affected = list(dict.fromkeys(eid for eid, _ in items))
            distance = min(net.depth.get(eid, 99) for eid in affected)
            multiplier = self.cfg.multiplier(distance)
            factors.append(
                RiskFactor(
                    key=key,
                    label=FACTOR_LABELS.get(key, key),
                    weight=weight,
                    distance=distance,
                    multiplier=multiplier,
                    points=round(weight * multiplier, 1),
                    entities=affected,
                    evidence=list(dict.fromkeys(ev for _, ev in items)),
                )
            )
            for eid in affected:
                entity_flags.setdefault(eid, []).append(FACTOR_LABELS.get(key, key))
                entity_points[eid] = entity_points.get(eid, 0) + weight

        factors.sort(key=lambda f: -f.points)
        score = round(min(100.0, sum(f.points for f in factors)), 1)
        return RiskAssessment(
            score=score,
            level=self.cfg.level(score),
            factors=factors,
            entity_flags=entity_flags,
            entity_points=entity_points,
            entity_levels={eid: self.cfg.level(p) for eid, p in entity_points.items()},
            cycles=cycles,
            methodology=[
                "Score = Σ (factor weight × proximity multiplier), capped at 100.",
                "Each factor counts once, whatever the number of affected entities.",
                "Proximity multiplier by distance to the subject: "
                + ", ".join(f"{k} hop(s) ×{v}" for k, v in self.cfg.proximity_multiplier.items()),
                f"Screening hits ≥ {t['strong_match_score']:.0f}% count as matches, "
                f"{t['possible_match_score']:.0f}–{t['strong_match_score']:.0f}% as possible matches, "
                "below are shown for review only.",
                "Weights and thresholds: config/risk.yaml — jurisdiction lists: config/jurisdictions.yaml"
                " — country indicators (Basel AML Index, CPI, World Bank WGI): config/country_risk.json"
                + (f", retrieved {self.countries.retrieved}." if self.countries.retrieved else "."),
            ],
        )
