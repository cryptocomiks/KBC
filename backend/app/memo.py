"""Decision memo: the written justification of a KYC decision, drafted from the case.

The memo gathers what a reviewer or a supervisor looks for: who the client is,
who owns it, what the screening found and how each hit was resolved, the risk
assessment and the vigilance level (with any analyst adjustment), the documents
received, the diligences performed: and proposes a conclusion. The analyst
edits it and signs it; placeholders in [brackets] mark what is still to write.

Plain text with light markup: "# " title, "## " section, "- " bullet.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import EntityType, ListType
from app.risk.config import get_jurisdictions
from app.schemas import Investigation

DECISION = {"confirmed": "Confirmed", "false_positive": "Ruled out", "to_review": "To review"}
LEVEL = {"simplified": "SIMPLIFIED", "standard": "STANDARD", "enhanced": "ENHANCED"}


def _day(value: Any) -> str:
    return str(value or "")[:10]


def build_memo(
    case: dict[str, Any],
    inv: Investigation,
    kyc: dict[str, Any],
    checklist: dict[str, Any],
    workflow: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> str:
    jur = get_jurisdictions()
    subject = next(e for e in inv.entities if e.id == inv.subject_id)
    answers = kyc.get("answers") or {}
    a = kyc.get("assessment")
    lines: list[str] = []
    add = lines.append

    add(f"# Decision memo: {case['title']}")
    add(
        f"Case {case['id']} · drafted {datetime.now(UTC):%Y-%m-%d} · prepared by "
        f"{kyc.get('author') or '[analyst]'}"
    )
    add("")

    # 1. Client
    add("## 1. Client and relationship")
    kind = "Company" if subject.type == EntityType.COMPANY else subject.type.value.capitalize()
    ident = [f"{kind}: {subject.name}"]
    if subject.jurisdiction:
        ident.append(f"registered in {jur.name(subject.jurisdiction)}")
    if subject.registration_number:
        ident.append(f"n° {subject.registration_number}")
    add("- " + ", ".join(ident) + ".")
    if subject.legal_form:
        add(f"- Legal form: {subject.legal_form}.")
    if subject.status and subject.status.value != "unknown":
        add(f"- Status: {subject.status.value}.")
    if subject.incorporation_date:
        add(f"- Incorporated on {subject.incorporation_date}.")
    if subject.address:
        add(f"- Registered address: {subject.address}.")
    if subject.birth_date:
        add(f"- Born {subject.birth_date}.")
    add(f"- Purpose of the relationship: {answers.get('purpose') or '[to complete]'}")
    add("")

    # 2. Ownership
    add("## 2. Ownership and control")
    owners = inv.brief.owners if inv.brief else []
    if owners:
        for o in owners:
            chain = " → ".join(o.path)
            add(
                f"- {o.name}: {o.pct:.1f} % effective ({chain})"
                + (f": {', '.join(o.flags)}" if o.flags else "")
            )
    else:
        add(
            "- No beneficial owner above 25 % could be computed from the registers: "
            "[explain: dispersed ownership, listed company, register gap; senior managing "
            "official retained as beneficial owner by default]"
        )
    s = inv.stats
    add(
        f"- Network reviewed: {s.get('companies', 0)} companies and {s.get('persons', 0)} persons "
        f"over {inv.params.depth} level(s), {s.get('sources', 0)} sources."
    )
    add("")

    # 3. Screening
    add("## 3. Screening results")
    hits = [h for h in inv.hits if h.list_type != ListType.LEAK]
    leaks = [h for h in inv.hits if h.list_type == ListType.LEAK]
    by_triage: dict[str, int] = {}
    for h in hits:
        by_triage[h.triage or "verify"] = by_triage.get(h.triage or "verify", 0) + 1
    if hits:
        add(
            f"- Sanctions / PEP / watchlist matches: {len(hits)}: "
            f"{by_triage.get('likely', 0)} likely, {by_triage.get('verify', 0)} to check, "
            f"{by_triage.get('namesake', 0)} probable namesakes, "
            f"{by_triage.get('dismissed', 0)} already ruled out."
        )
    else:
        add("- No sanctions, PEP or watchlist match on the client or its network.")
    if leaks:
        add(f"- Appearances in leaked or investigative data: {len(leaks)}.")
    if decisions:
        add("- Analyst decisions:")
        for d in decisions:
            comment = f": {d['comment']}" if d.get("comment") else ""
            who = (
                f" ({d['author']}, {_day(d.get('decided_at'))})"
                if d.get("author")
                else f" ({_day(d.get('decided_at'))})"
            )
            add(
                f"  - {DECISION.get(d['decision'], d['decision'])}: {d.get('item_label') or d['item_key']}{comment}{who}"
            )
    open_likely = [h for h in hits if h.triage == "likely"]
    decided = {d["item_key"].split("|")[1] for d in decisions if d["item_key"].count("|") >= 2}
    names = {e.id: e.name for e in inv.entities}
    pending = [h for h in open_likely if names.get(h.entity_id) not in decided]
    if pending:
        add(
            f"- [To resolve before the decision] {len(pending)} likely match(es) without a decision: "
            + "; ".join(
                f"{names.get(h.entity_id, h.entity_id)} ≈ {h.matched_name} ({h.dataset})"
                for h in pending[:5]
            )
        )
    add("")

    # 4. Risk assessment
    add("## 4. Risk assessment")
    add(f"- Automatic network assessment: {inv.risk.level.upper()} ({inv.risk.score:g}/100).")
    for f in inv.risk.factors[:6]:
        add(f"  - {f.label} (+{f.points:g}): {f.evidence[0] if f.evidence else ''}")
    if a:
        add(f"- Vigilance level: {LEVEL[a['level']]} ({a['points']} risk points).")
        if a.get("override"):
            o = a["override"]
            add(
                f"  - Adjusted by {o['by']} on {_day(o['at'])} from {LEVEL[a['computed_level']]}: "
                f"{o['justification']}"
            )
        if a["triggers"]:
            add(f"  - Enhanced measures required because: {', '.join(a['triggers'])}.")
        axes = a.get("axes") or {}
        if axes:
            add(
                "- Risk map: "
                + ", ".join(f"{v['label']} {v['score']}/100" for v in axes.values())
                + "."
            )
        if a["missing"]:
            add(f"- [Questionnaire incomplete: {', '.join(a['missing'])}]")
    else:
        add("- [KYC questionnaire not answered: vigilance level to assess]")
    add("")

    # 5. Documents and diligences
    add("## 5. Documents and diligences")
    received = [d for d in checklist.get("documents", []) if d["done"]]
    missing = [d for d in checklist.get("documents", []) if not d["done"] and d.get("required")]
    if received:
        add("- Documents received:")
        for d in received:
            add(f"  - {d['label']} ({d['by'] or 'received'}, {_day(d['at'])})")
    if missing:
        add("- Required documents still missing:")
        for d in missing:
            add(f"  - {d['label']}")
    done = [d for d in checklist.get("diligences", []) if d["done"]]
    todo = [d for d in checklist.get("diligences", []) if not d["done"]]
    if done:
        add("- Diligences performed:")
        for d in done:
            add(f"  - {d['label']} ({d['by'] or 'done'}, {_day(d['at'])})")
    if todo:
        add(f"- Diligences not performed: {len(todo)} (optional, see the case checklist).")
    add("")

    # 6. Conclusion
    add("## 6. Conclusion")
    factors = {f.key for f in inv.risk.factors}
    level = a["level"] if a else None
    if "sanctions_match" in factors and not any(
        d["decision"] == "false_positive" for d in decisions
    ):
        add(
            "- Proposal: DO NOT PROCEED until the sanctions match is cleared. If confirmed, "
            "freeze the funds and report to the competent authority (DG Trésor / SECO) and "
            "the financial intelligence unit."
        )
    elif level == "enhanced":
        add(
            "- Proposal: ACCEPT SUBJECT TO enhanced due diligence: the measures listed in "
            "section 4, senior management approval and yearly review."
        )
    elif level == "standard":
        add("- Proposal: ACCEPT with standard vigilance and a review every 2 years.")
    elif level == "simplified":
        add("- Proposal: ACCEPT with simplified vigilance and a review every 3 years.")
    else:
        add("- Proposal: [to decide once the questionnaire is answered]")
    if missing:
        add("- Acceptance conditional on receipt of the missing required documents (section 5).")
    if a:
        add(f"- Next review: {a['next_review']}.")
    add("- Analyst's comment: " + (answers.get("comment") or "[to complete]"))
    add("")

    # 7. Sign-off
    add("## 7. Sign-off")
    add(f"- Prepared by: {kyc.get('author') or '[name]'}: date: [date]: signature: [ ]")
    if workflow.get("validated_by"):
        add(
            f"- Validated by: {workflow['validated_by']} on {_day(workflow.get('validated_at'))} (four-eyes)"
        )
    else:
        add("- Validated by (four-eyes): [name]: date: [date]: signature: [ ]")
    if level == "enhanced":
        add("- Senior management approval: [name]: date: [date]: signature: [ ]")
    return "\n".join(lines)
