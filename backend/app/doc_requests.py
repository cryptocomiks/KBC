"""Documents to request from the client, derived from the findings.

Each red flag translates into the evidence an analyst usually asks for to
clear it (FATF / EU AMLD customer due diligence practice). The list is a
starting point to adapt to the institution's procedures, not legal advice.
"""

from __future__ import annotations

import networkx as nx
from pydantic import BaseModel, Field

from app.graph.expander import Network
from app.graph.ownership import ownership_graph
from app.insights import _best_paths
from app.models import EntityType, ListType
from app.risk.engine import RiskAssessment


class DocRequest(BaseModel):
    document: str
    reason: str
    priority: str = "standard"  # required | standard
    entity_ids: list[str] = Field(default_factory=list)


def build_requests(
    net: Network, risk: RiskAssessment, jur_name=lambda c: c or "?"
) -> list[DocRequest]:
    ents = net.entities
    subject = ents[net.subject_id]
    name = lambda eid: ents[eid].name if eid in ents else eid  # noqa: E731
    out: list[DocRequest] = []

    def add(
        document: str, reason: str, priority: str = "standard", ids: list[str] | None = None
    ) -> None:
        if not any(r.document == document for r in out):
            out.append(
                DocRequest(
                    document=document, reason=reason, priority=priority, entity_ids=ids or []
                )
            )

    # --- Baseline customer due diligence
    if subject.type == EntityType.COMPANY:
        add(
            "Certified register extract (less than 3 months old)",
            "Identification of the legal entity",
            "required",
            [subject.id],
        )
        add(
            "Articles of association (up-to-date version)",
            "Powers, share capital and governance",
            "required",
            [subject.id],
        )
        add(
            "Beneficial ownership declaration / UBO register extract",
            "Identification of the beneficial owners (≥ 25 %)",
            "required",
            [subject.id],
        )
        add(
            "Identity documents of the legal representatives",
            "Verification of the persons acting for the company",
            "required",
        )
        g = ownership_graph(net.relationships.values())
        if subject.id in g:
            for node in nx.ancestors(g, subject.id):
                e = ents.get(node)
                if e is None or e.type != EntityType.PERSON:
                    continue
                total, path = _best_paths(g, node, subject.id)
                if total >= 25:
                    add(
                        f"Identity document and proof of address of {e.name}",
                        f"Beneficial owner: {total:.0f} % through {' → '.join(name(p) for p in path[1:-1]) or 'direct holding'}",
                        "required",
                        [node],
                    )
    elif subject.type == EntityType.PERSON:
        add(
            "Identity document (passport or national ID)",
            "Identification of the person",
            "required",
            [subject.id],
        )
        add(
            "Proof of address (less than 3 months old)",
            "Verification of residence",
            "required",
            [subject.id],
        )

    # --- Red flags -> evidence that clears (or confirms) them
    for f in sorted(risk.factors, key=lambda f: -f.points):
        ids = f.entities[:5]
        names = ", ".join(name(i) for i in ids[:3])
        k = f.key
        if k in ("sanctions_match", "sanctions_possible_match", "watchlist_match"):
            for eid in ids[:3]:
                add(
                    f"Passport copy of {name(eid)} (full date of birth and nationality)",
                    f"Confirm or rule out the {f.label.lower()} — {f.evidence[0][:120]}",
                    "required",
                    [eid],
                )
        elif k in ("pep_match", "pep_possible_match", "pep_relative"):
            add(
                "Source of wealth: evidence of how the wealth was built (tax returns, sale deeds, inheritance, payslips)",
                f"PEP exposure: {names}",
                "required",
                ids,
            )
            add(
                "Source of funds for the relationship (bank statements, contracts)",
                f"PEP exposure: {names}",
                "required",
                ids,
            )
            add(
                "Senior management approval of the business relationship",
                "Required for PEP relationships (EU AMLD art. 20)",
                "required",
                ids,
            )
        elif k == "sanctioned_counterparty":
            add(
                "Explanation and transaction history for the flows with the sanctioned wallet(s)",
                f.evidence[0][:160],
                "required",
                ids,
            )
        elif k in ("offshore_jurisdiction", "eu_tax_blacklist"):
            for eid in ids[:3]:
                e = ents.get(eid)
                where = jur_name(e.jurisdiction) if e and e.jurisdiction else "offshore"
                add(
                    f"Register extract and register of directors / members of {name(eid)} ({where})",
                    "Offshore entity in the chain: identify who stands behind it",
                    "required",
                    [eid],
                )
            add(
                "Certificate of incumbency from the registered agent",
                f"Offshore entities: {names}",
                "standard",
                ids,
            )
        elif k in ("circular_ownership", "long_ownership_chain", "ubo_discrepancy"):
            add(
                "Group structure chart down to the natural persons, dated and signed by the client",
                f"{f.label}: {f.evidence[0][:140]}",
                "required",
                ids,
            )
            if k == "ubo_discrepancy":
                add(
                    "Explanation of the difference between declared and computed beneficial owners, and updated UBO declaration",
                    f.evidence[0][:160],
                    "required",
                    ids,
                )
        elif k == "leak_appearance":
            add(
                "Purpose and economic rationale of the offshore structure(s) found in leaks, with their financial statements",
                f"Appears in: {f.evidence[0][:140]}",
                "standard",
                ids,
            )
        elif k in ("missing_accounts", "shell_company_indicators"):
            add("Latest audited financial statements", f"{f.label}: {names}", "required", ids)
            add(
                "Evidence of real activity (contracts, invoices, lease, payroll)",
                f"{f.label}: {names}",
                "standard",
                ids,
            )
        elif k == "recent_incorporation":
            add(
                "Business plan and expected account activity (volumes, counterparties, countries)",
                f"Recently incorporated: {names}",
                "standard",
                ids,
            )
        elif k == "shared_domiciliation":
            add(
                "Domiciliation contract and proof of physical premises",
                f"Shared address: {names}",
                "standard",
                ids,
            )
        elif k == "nominee_director":
            add(
                "Nominee agreement or declaration of the person on whose behalf the director acts",
                f"Possible nominee: {names}",
                "required",
                ids,
            )
        elif k in ("fatf_blacklist", "fatf_greylist", "high_risk_country"):
            add(
                "Explanation of the business links with the high-risk countries, and origin of the funds involved",
                f"{f.label}: {names}",
                "required" if k == "fatf_blacklist" else "standard",
                ids,
            )
        elif k == "insolvency_proceedings":
            add(
                "Status of the insolvency proceedings (court decision, administrator's report)",
                f.evidence[0][:160],
                "standard",
                ids,
            )
        elif k == "adverse_media":
            add(
                "Client's written explanation on the press articles found",
                f"Adverse media on {names}",
                "standard",
                ids,
            )
        elif k == "dissolved_company":
            add(
                "Confirmation that the dissolved companies no longer play any role (contracts, accounts)",
                f"Dissolved: {names}",
                "standard",
                ids,
            )

    # Hits still to verify: identity evidence of the persons concerned
    for h in net.hits:
        e = ents.get(h.entity_id)
        if (
            h.triage == "verify"
            and e is not None
            and e.type == EntityType.PERSON
            and h.list_type != ListType.LEAK
        ):
            add(
                f"Passport copy of {e.name} (full date of birth and nationality)",
                f"Rule out the possible match with “{h.matched_name}” ({h.dataset})",
                "required",
                [e.id],
            )
    out.sort(key=lambda r: r.priority != "required")
    return out
