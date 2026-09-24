"""Cases: saved investigations, analyst decisions and monitoring (what changed since last run).

A case stores the investigation parameters and a compact snapshot of what was
found (screening hits, links, documents, flows, score). A refresh re-runs the
investigation with fresh data and records every difference as a change.
Analyst decisions (confirmed / false positive / to review) are applied on top:
a hit marked as a false positive no longer counts in the score, and every
decision is kept for the audit trail and printed in the report.
"""

from __future__ import annotations

import os
import time
from typing import Any

from app.brief import build_brief
from app.cache import get_cache
from app.doc_requests import build_requests
from app.graph.expander import Network
from app.insights import build_summary, build_timeline
from app.models import EntityType, RelationType
from app.risk.config import get_jurisdictions
from app.risk.engine import RiskEngine
from app.schemas import Investigation, InvestigationRequest
from app.service import KbcService, build_tables
from app.settings import get_settings
from app.store import Store, get_store, now

DECISIONS = {"confirmed", "false_positive", "to_review"}
STRONG = 85.0


def hit_key(inv: Investigation, entity_id: str, dataset: str, matched_name: str) -> str:
    names = {e.id: e.name for e in inv.entities}
    return f"hit|{names.get(entity_id, entity_id)}|{dataset}|{matched_name}"


def snapshot(inv: Investigation) -> dict[str, Any]:
    names = {e.id: e.name for e in inv.entities}
    n = lambda eid: names.get(eid, eid)  # noqa: E731
    hits = {
        hit_key(
            inv, h.entity_id, h.dataset, h.matched_name
        ): f"{n(h.entity_id)} ≈ {h.matched_name} ({h.dataset})"
        for h in inv.hits
        if h.score >= STRONG
    }
    links = {}
    flows = {}
    for r in inv.relationships:
        if r.type == RelationType.TRANSFER:
            flows[f"flow|{n(r.source_id)}>{n(r.target_id)}|{r.currency}"] = (
                f"{n(r.source_id)} → {n(r.target_id)}: {r.amount or 0:,.2f} {r.currency or ''}"
            )
        elif r.type != RelationType.REGISTERED_AT and r.is_active:
            label = r.role or r.type.value
            pct = f" ({r.share_pct:g}%)" if r.share_pct is not None else ""
            links[f"link|{r.type.value}|{n(r.source_id)}>{n(r.target_id)}"] = (
                f"{n(r.source_id)} — {label}{pct} — {n(r.target_id)}"
            )
    documents = {
        f"doc|{e.name}|{d.title}|{d.date}": f"{e.name}: {d.title} ({d.date})"
        for e in inv.entities
        for d in e.documents
        if d.date
    }
    return {
        "score": inv.risk.score,
        "level": inv.risk.level,
        "hits": hits,
        "links": links,
        "documents": documents,
        "flows": flows,
    }


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, str]]:
    """Human-readable changes between two snapshots (empty on the first run)."""
    if not old:
        return []
    out: list[dict[str, str]] = []
    for key, label in new.get("hits", {}).items():
        if key not in old.get("hits", {}):
            out.append(
                {
                    "kind": "new_hit",
                    "severity": "critical",
                    "description": f"New screening hit: {label}",
                }
            )
    for key, label in old.get("hits", {}).items():
        if key not in new.get("hits", {}):
            out.append(
                {
                    "kind": "removed_hit",
                    "severity": "info",
                    "description": f"Hit no longer returned: {label}",
                }
            )
    for key, label in new.get("links", {}).items():
        if key not in old.get("links", {}):
            out.append(
                {"kind": "new_link", "severity": "warning", "description": f"New link: {label}"}
            )
    for key, label in old.get("links", {}).items():
        if key not in new.get("links", {}):
            out.append(
                {
                    "kind": "ended_link",
                    "severity": "info",
                    "description": f"Link ended or no longer found: {label}",
                }
            )
    for key, label in new.get("documents", {}).items():
        if key not in old.get("documents", {}):
            out.append(
                {"kind": "new_document", "severity": "info", "description": f"New record: {label}"}
            )
    for key, label in new.get("flows", {}).items():
        if old.get("flows", {}).get(key) != label:
            out.append(
                {
                    "kind": "flow",
                    "severity": "warning",
                    "description": f"Crypto flows changed: {label}",
                }
            )
    if (
        old.get("level") != new.get("level")
        or abs((old.get("score") or 0) - (new.get("score") or 0)) >= 5
    ):
        worse = (new.get("score") or 0) > (old.get("score") or 0)
        out.append(
            {
                "kind": "score",
                "severity": "warning" if worse else "info",
                "description": f"Risk score {old.get('score', 0):.0f} ({old.get('level')}) → "
                f"{new.get('score', 0):.0f} ({new.get('level')})",
            }
        )
    return out


def apply_decisions(inv: Investigation, decisions: list[dict[str, Any]]) -> Investigation:
    """Recompute score, tables, brief and findings without the hits marked as false positives."""
    rejected = {d["item_key"].lower() for d in decisions if d["decision"] == "false_positive"}
    if not rejected:
        return inv
    net = Network(
        subject_id=inv.subject_id,
        max_depth=inv.params.depth,
        max_nodes=inv.params.max_nodes,
        entities={e.id: e for e in inv.entities},
        relationships={r.id: r for r in inv.relationships},
        depth=inv.depth,
        hits=[
            h
            for h in inv.hits
            if hit_key(inv, h.entity_id, h.dataset, h.matched_name).lower() not in rejected
        ],
        queries=inv.queries,
        merges=inv.merges,
        warnings=inv.warnings,
        truncated=inv.truncated,
    )
    risk = RiskEngine().assess(net)
    jur = get_jurisdictions().name
    # Tables keep every hit (the analyst can see and undo a decision); score, brief and
    # findings ignore the rejected ones.
    full = net.model_copy(update={"hits": inv.hits})
    return inv.model_copy(
        update={
            "risk": risk,
            "tables": build_tables(full, risk),
            "summary": build_summary(net, risk, jur),
            "timeline": build_timeline(net),
            "brief": build_brief(net, risk, jur),
            "requests": build_requests(net, risk, jur),
        }
    )


def memory_enabled() -> bool:
    """Same rule as the case endpoints: on Vercel the store needs APP_PASSWORD."""
    s = get_settings()
    return not (os.environ.get("VERCEL") and not s.app_password)


def apply_dismissals(inv: Investigation) -> Investigation:
    """Hits already ruled out by an analyst are shown as dismissed and leave the score."""
    if not memory_enabled() or not inv.hits:
        return inv
    try:
        memory = get_store().dismissals()
    except Exception:  # noqa: BLE001 - the store is optional for plain investigations
        return inv
    if not memory:
        return inv
    decisions = []
    for h in inv.hits:
        key = hit_key(inv, h.entity_id, h.dataset, h.matched_name).lower()
        m = memory.get(key)
        if m:
            h.triage = "dismissed"
            h.triage_reasons = [
                f"ruled out on {str(m['decided_at'])[:10]}"
                + (f" by {m['author']}" if m.get("author") else ""),
                *([m["comment"]] if m.get("comment") else []),
            ]
            decisions.append({"item_key": key, "decision": "false_positive"})
    return apply_decisions(inv, decisions) if decisions else inv


class CaseService:
    def __init__(self, store: Store, service: KbcService) -> None:
        self.store = store
        self.service = service

    def _params(self, case: dict[str, Any]) -> InvestigationRequest:
        return InvestigationRequest(
            record_ids=case["record_ids"], depth=case["depth"], max_nodes=case["max_nodes"]
        )

    def _record(
        self, case_id: str, inv: Investigation, previous: dict[str, Any]
    ) -> list[dict[str, str]]:
        snap = snapshot(inv)
        changes = diff(previous, snap)
        run_at = now()
        countries = sorted(
            {
                e.jurisdiction
                for e in inv.entities
                if e.type == EntityType.COMPANY and e.jurisdiction
            }
        )
        self.store.update_case(
            case_id,
            snapshot=snap,
            risk_score=inv.risk.score,
            risk_level=inv.risk.level,
            countries=countries,
            last_run_at=run_at,
        )
        self.store.add_changes(case_id, run_at, changes)
        return changes

    def create(self, req: InvestigationRequest, title: str | None, monitor: bool) -> dict[str, Any]:
        inv = self.service.investigate(req)
        subject = next(e for e in inv.entities if e.id == inv.subject_id)
        case = self.store.create_case(
            title=title or subject.name,
            subject_name=subject.name,
            subject_type=subject.type.value,
            record_ids=req.record_ids,
            depth=req.depth,
            max_nodes=req.max_nodes,
            demo=inv.demo,
            monitor=monitor,
        )
        self._record(case["id"], inv, {})
        return self.store.get_case(case["id"])  # type: ignore[return-value]

    def refresh(self, case_id: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        cache = get_cache()
        cache.fresh_after = time.time()  # ignore cached API answers: we want today's data
        try:
            inv = self.service.investigate(self._params(case))
        finally:
            cache.fresh_after = 0.0
        changes = self._record(case_id, inv, case.get("snapshot") or {})
        return self.store.get_case(case_id), changes  # type: ignore[return-value]

    def view(self, case_id: str) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        decisions = self.store.decisions(case_id)
        inv = apply_decisions(self.service.investigate(self._params(case)), decisions)
        case.pop("snapshot", None)
        return {
            "case": case,
            "investigation": inv,
            "decisions": decisions,
            "changes": self.store.changes(case_id),
        }

    def dashboard(self) -> dict[str, Any]:
        cases = self.store.list_cases()
        by_level: dict[str, int] = {}
        by_country: dict[str, int] = {}
        for c in cases:
            by_level[c.get("risk_level") or "unknown"] = (
                by_level.get(c.get("risk_level") or "unknown", 0) + 1
            )
            for code in c.get("countries") or []:
                by_country[code] = by_country.get(code, 0) + 1
        jur = get_jurisdictions()
        return {
            "cases": cases,
            "by_level": by_level,
            "by_country": sorted(
                ({"code": k, "country": jur.name(k), "cases": v} for k, v in by_country.items()),
                key=lambda r: -r["cases"],
            ),
            "recent_changes": self.store.changes(limit=40),
            "to_review": sum(
                1
                for c in cases
                if c["unseen_changes"] or c.get("risk_level") in ("high", "critical")
            ),
        }
