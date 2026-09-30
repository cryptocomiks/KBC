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
import uuid
from datetime import date, timedelta
from typing import Any

from app import alerts
from app import cdb as cdb_forms
from app import questionnaire as kyc
from app import review as review_pack
from app import sow as sow_mod
from app import workflow as wf
from app.brief import build_brief
from app.cache import get_cache
from app.doc_requests import build_requests
from app.graph.expander import Network
from app.insights import build_summary, build_timeline
from app.memo import build_memo
from app.models import EntityType, RelationType
from app.risk.config import get_jurisdictions
from app.risk.engine import RiskEngine
from app.schemas import Investigation, InvestigationRequest
from app.service import KbcService, build_tables
from app.settings import get_settings
from app.store import IMPORT_ACTIVE, Store, get_store, now

DECISIONS = {"confirmed", "false_positive", "to_review"}
STRONG = 85.0
# Name search: the best candidate is picked automatically only when there is no real doubt:
# a near-exact name ahead of the rest, or a good match with no other plausible company.
# Anything else is left to the analyst (a wrong company in a KYC file is worse than a click).
IMPORT_EXACT_SCORE = 97.0
IMPORT_EXACT_MARGIN = 4.0
IMPORT_MIN_SCORE = 90.0
IMPORT_RIVAL_SCORE = 80.0


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
                f"{n(r.source_id)}, {label}{pct}, {n(r.target_id)}"
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
        "factors": sorted({f.key for f in inv.risk.factors}),
        "hits": hits,
        "links": links,
        "documents": documents,
        "flows": flows,
        # documents to ask the client for (back office: requests and receptions)
        "requests": [
            {"document": r.document, "reason": r.reason, "priority": r.priority}
            for r in inv.requests
        ],
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
    ents = {e.id: e for e in inv.entities}
    decisions = []
    for h in inv.hits:
        key = hit_key(inv, h.entity_id, h.dataset, h.matched_name).lower()
        m = memory.get(key)
        if not m:
            continue
        who = f"ruled out on {str(m['decided_at'])[:10]}" + (
            f" by {m['author']}" if m.get("author") else ""
        )
        if m.get("fingerprint"):
            now_ev = alerts.evidence(h, ents.get(h.entity_id))
            if now_ev["fingerprint"] != m["fingerprint"]:
                # The evidence the decision rested on changed: the alert comes back.
                diffs = alerts.changed(m.get("evidence") or {}, now_ev) or ["the record changed"]
                h.triage = "verify"
                h.triage_reasons = [f"re-alert: {who}, but " + "; ".join(diffs)]
                h.details = {**(h.details or {}), "realert": diffs}
                continue
        h.triage = "dismissed"
        h.triage_reasons = [who, *([m["comment"]] if m.get("comment") else [])]
        decisions.append({"item_key": key, "decision": "false_positive"})
    return apply_decisions(inv, decisions) if decisions else inv


def mark_stale(inv: Investigation, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A "false positive" whose evidence changed since (re-alert) no longer holds: flag it."""
    realert = {
        hit_key(inv, h.entity_id, h.dataset, h.matched_name).lower()
        for h in inv.hits
        if (h.details or {}).get("realert")
    }
    return [
        {**d, "stale": True}
        if d["decision"] == "false_positive" and d["item_key"].lower() in realert
        else d
        for d in decisions
    ]


def active(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [d for d in decisions if not d.get("stale")]


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
        run_at = now()
        if inv.unscreened and previous:
            # Partial screening: comparing it would report hits as "removed". Keep the last
            # complete snapshot; the next run (daily monitoring) completes the comparison.
            self.store.update_case(case_id, last_run_at=run_at)
            return []
        snap = snapshot(inv)
        changes = diff(previous, snap)
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
        case = self.store.get_case(case_id)
        reopened = wf.auto_reopen(case or {}, changes, run_at)
        if reopened:
            self.store.update_case(case_id, workflow=reopened)
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
        if case.get("import_state"):
            raise ValueError("This imported case has not been analysed yet.")
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
        kyc_view = self.questionnaire(case)
        if case.get("import_state"):
            case.pop("snapshot", None)
            return {
                "case": case,
                "investigation": None,
                "decisions": [],
                "changes": [],
                "questionnaire": kyc_view,
            }
        raw = self.service.investigate(self._params(case))
        decisions = mark_stale(raw, self.store.decisions(case_id))
        inv = apply_decisions(raw, active(decisions))
        checklist = wf.checklist_view(
            case, [r.model_dump() for r in inv.requests], kyc_view["assessment"]
        )
        workflow = self.workflow_view(case, checklist, kyc_view["assessment"])
        overview = self.overview(case, raw, inv, decisions, kyc_view, checklist, workflow)
        case.pop("snapshot", None)
        return {
            "case": case,
            "investigation": inv,
            "decisions": decisions,
            "changes": self.store.changes(case_id),
            "questionnaire": kyc_view,
            "checklist": checklist,
            "workflow": workflow,
            "overview": overview,
        }

    @staticmethod
    def overview(
        case: dict[str, Any],
        raw: Investigation,
        inv: Investigation,
        decisions: list[dict[str, Any]],
        kyc_view: dict[str, Any],
        checklist: dict[str, Any],
        workflow: dict[str, Any],
    ) -> dict[str, Any]:
        """The file at a glance: alerts, documents, UBO forms, source of wealth, review and
        what is still missing before validation (header badges and the KYC overview)."""
        decided = {d["item_key"].lower() for d in active(decisions)}
        triage: dict[str, int] = {}
        by_list: dict[str, dict[str, int]] = {}
        open_alerts = 0
        for h in raw.hits:
            t = h.triage or "verify"
            triage[t] = triage.get(t, 0) + 1
            row = by_list.setdefault(h.list_type.value, {"total": 0, "open": 0})
            row["total"] += 1
            key = hit_key(raw, h.entity_id, h.dataset, h.matched_name).lower()
            if t in ("likely", "verify") and key not in decided:
                open_alerts += 1
                row["open"] += 1
        docs = checklist.get("documents") or []
        a = kyc_view.get("assessment")
        forms = cdb_forms.build(inv, case.get("cdb") or {})
        sow_saved = case.get("sow") or {}
        sow_a = sow_mod.assess(inv, sow_saved) if sow_saved.get("sources") else None
        due = (case.get("questionnaire") or {}).get("next_review") or (a or {}).get("next_review")
        days_left = None
        if due:
            try:
                days_left = (date.fromisoformat(str(due)[:10]) - date.today()).days
            except ValueError:
                days_left = None
        review_status = (
            "not_set"
            if days_left is None
            else "overdue"
            if days_left < 0
            else "due"
            if days_left <= 30
            else "not_due"
        )
        level = (a or {}).get("level")
        readiness = [
            {
                "key": "questionnaire",
                "label": "Questionnaire answered",
                "done": bool(a) and not (a or {}).get("missing"),
                "detail": "done"
                if a and not a.get("missing")
                else f"{len((a or {}).get('missing') or [])} question(s) open"
                if a
                else "not started",
                "tab": "kyc",
            },
            {
                "key": "alerts",
                "label": "Alerts resolved",
                "done": open_alerts == 0,
                "detail": f"{open_alerts} open" if open_alerts else "none open",
                "tab": "alerts",
            },
            {
                "key": "documents",
                "label": "Required documents",
                "done": not checklist.get("missing_required"),
                "detail": f"{sum(1 for d in docs if d['done'])}/{len(docs)} received",
                "tab": "kyc",
            },
            {
                "key": "cdb",
                "label": "UBO form complete",
                "done": forms["missing_total"] == 0,
                "detail": f"{forms['missing_total']} field(s) to complete"
                if forms["missing_total"]
                else "ready to sign",
                "tab": "cdb",
            },
        ]
        if level == "enhanced" or sow_a:
            readiness.append(
                {
                    "key": "sow",
                    "label": "Source of wealth",
                    "done": bool(sow_a and sow_a["verdict"] == "plausible"),
                    "detail": f"{round((sow_a['coverage'] or 0) * 100)} % explained"
                    if sow_a and sow_a.get("coverage") is not None
                    else "to document",
                    "tab": "sow",
                }
            )
        return {
            "risk": {"score": inv.risk.score, "level": inv.risk.level},
            "alerts": {
                "total": len(raw.hits),
                "open": open_alerts,
                "triage": triage,
                "by_list": by_list,
            },
            "documents": {
                "received": sum(1 for d in docs if d["done"]),
                "total": len(docs),
                "required_missing": len(checklist.get("missing_required") or []),
            },
            "cdb": {
                "forms": [f["code"] for f in forms["forms"]],
                "missing": forms["missing_total"],
                "persons": sum(len(f["persons"]) for f in forms["forms"]),
            },
            "sow": {
                "verdict": sow_a["verdict"],
                "coverage": sow_a["coverage"],
                "sources": len(sow_a["sources"]),
            }
            if sow_a
            else None,
            "review": {"status": review_status, "days_left": days_left, "next_review": due},
            "vigilance": level,
            "workflow": workflow.get("state"),
            "readiness": readiness,
            "ready": sum(1 for r in readiness if r["done"]),
        }

    # ------------------------------------------------------ alerts & memory
    def _hit_index(self, inv: Investigation) -> dict[str, tuple[Any, Any]]:
        ents = {e.id: e for e in inv.entities}
        return {
            hit_key(inv, h.entity_id, h.dataset, h.matched_name).lower(): (h, ents.get(h.entity_id))
            for h in inv.hits
        }

    def decide(
        self, case_id: str, item_key: str, item_label: str, decision: str, comment: str, author: str
    ) -> list[dict[str, Any]]:
        """Record a decision; a false positive keeps the evidence it rests on (for re-alerts)."""
        case = self._get(case_id)
        ev = None
        if decision == "false_positive":
            raw = self.service.investigate(self._params(case), memory=False)
            found = self._hit_index(raw).get(item_key.lower())
            if found:
                ev = alerts.evidence(*found)
        self.store.set_decision(case_id, item_key, item_label, decision, comment, author, ev)
        return self.store.decisions(case_id)

    def alerts_view(self, case_id: str) -> dict[str, Any]:
        case = self._get(case_id)
        inv = self.service.investigate(self._params(case))
        raw = self._hit_index(self.service.investigate(self._params(case), memory=False))
        decisions = {
            d["item_key"].lower(): d for d in mark_stale(inv, self.store.decisions(case_id))
        }
        memory = self.store.dismissals() if memory_enabled() else {}
        ents = {e.id: e for e in inv.entities}
        rows = []
        counts: dict[str, int] = {}
        for h in inv.hits:
            key = hit_key(inv, h.entity_id, h.dataset, h.matched_name)
            e = ents.get(h.entity_id)
            m = memory.get(key.lower())
            triage = h.triage or "verify"
            counts[triage] = counts.get(triage, 0) + 1
            raw_hit = raw.get(key.lower(), (h, e))[0]
            rows.append(
                {
                    "key": key,
                    "label": f"{e.name if e else h.entity_id} ≈ {h.matched_name} ({h.dataset})",
                    "entity": e.name if e else h.entity_id,
                    "entity_type": e.type.value if e else None,
                    "dataset": h.dataset,
                    "list_type": h.list_type.value,
                    "matched_name": h.matched_name,
                    "score": round(h.score, 1),
                    "triage": triage,
                    "reasons": h.triage_reasons,
                    "realert": (h.details or {}).get("realert"),
                    "decision": decisions.get(key.lower()),
                    "memory": {k: m.get(k) for k in ("decided_at", "author", "comment", "case_id")}
                    if m
                    else None,
                    "proposed": alerts.justification(raw_hit, e)
                    if triage in ("namesake", "verify")
                    else None,
                    "url": h.provenance.url,
                }
            )
        cleared = counts.get("dismissed", 0)
        return {
            "alerts": rows,
            "counts": counts,
            "cleared_by_memory": cleared,
            "batch_candidates": sum(
                1 for r in rows if r["triage"] == "namesake" and not r["decision"]
            ),
            "minutes_per_alert": alerts.MINUTES_PER_ALERT,
            "minutes_saved": cleared * alerts.MINUTES_PER_ALERT,
            "memory_enabled": memory_enabled(),
        }

    def batch_dismiss(self, case_id: str, by: str, keys: list[str] | None) -> dict[str, Any]:
        """Rule out, in one go, the hits the triage labels as namesakes (or the ones given),
        each with a justification written from the evidence."""
        if not by.strip():
            raise wf.WorkflowError("Give your name: each ruling is signed.")
        case = self._get(case_id)
        view = self.alerts_view(case_id)
        wanted = {k.lower() for k in keys} if keys else None
        raw = self._hit_index(self.service.investigate(self._params(case), memory=False))
        done = 0
        for row in view["alerts"]:
            k = row["key"].lower()
            if row["decision"] and not row["decision"].get("stale"):
                continue
            if wanted is not None:
                if k not in wanted:
                    continue
            elif row["triage"] != "namesake":
                continue
            hit, ent = raw.get(k, (None, None))
            if hit is None:
                continue
            self.store.set_decision(
                case_id,
                row["key"],
                row["label"],
                "false_positive",
                alerts.justification(hit, ent) + f" [batch triage by {by.strip()}]",
                by.strip(),
                alerts.evidence(hit, ent),
            )
            done += 1
        return {"dismissed": done, **self.alerts_view(case_id)}

    def memory(self) -> list[dict[str, Any]]:
        titles = {c["id"]: c["title"] for c in self.store.list_cases()}
        rows = sorted(
            self.store.dismissals().values(), key=lambda r: str(r["decided_at"]), reverse=True
        )
        return [
            {
                "item_key": r["item_key"],
                "item_label": r["item_label"],
                "comment": r["comment"],
                "author": r["author"],
                "decided_at": r["decided_at"],
                "case_id": r["case_id"],
                "case_title": titles.get(r["case_id"]),
                "tracked": bool(r.get("fingerprint")),
                "evidence": r.get("evidence") or {},
            }
            for r in rows
        ]

    # ----------------------------------------------------- CDB 20 forms
    def cdb(self, case_id: str) -> dict[str, Any]:
        case = self._get(case_id)
        inv = self.service.investigate(self._params(case))
        return {"title": case["title"], **cdb_forms.build(inv, case.get("cdb") or {})}

    def edit_cdb(self, case_id: str, edit: dict[str, Any], by: str) -> dict[str, Any]:
        case = self._get(case_id)
        if not by.strip():
            raise wf.WorkflowError("Give your name: edits are signed.")
        saved = (
            {}
            if edit.get("reset")
            else cdb_forms.merge_edit(case.get("cdb") or {}, edit, by.strip(), now())
        )
        self.store.update_case(case_id, cdb=saved)
        return self.cdb(case_id)

    # --------------------------------------------------- source of wealth
    def sow(self, case_id: str) -> dict[str, Any]:
        case = self._get(case_id)
        inv = self.service.investigate(self._params(case))
        return sow_mod.assess(inv, case.get("sow") or {})

    def save_sow(self, case_id: str, data: dict[str, Any], by: str) -> dict[str, Any]:
        self._get(case_id)
        if not by.strip():
            raise wf.WorkflowError("Give your name: the assessment is signed.")
        self.store.update_case(case_id, sow={**sow_mod.clean(data), "by": by.strip(), "at": now()})
        return self.sow(case_id)

    # --------------------------------------------------- periodic review
    def review(self, case_id: str) -> dict[str, Any]:
        case = self._get(case_id)
        raw = self.service.investigate(self._params(case))
        decisions = mark_stale(raw, self.store.decisions(case_id))
        inv = apply_decisions(raw, active(decisions))
        kyc_view = self.questionnaire(case)
        checklist = wf.checklist_view(
            case, [r.model_dump() for r in inv.requests], kyc_view["assessment"]
        )
        workflow = self.workflow_view(case, checklist, kyc_view["assessment"])
        decided = {d["item_key"].lower() for d in active(decisions)}
        names = {e.id: e.name for e in raw.entities}
        open_alerts = [
            {
                "label": f"{names.get(h.entity_id, h.entity_id)} ≈ {h.matched_name} ({h.dataset})",
                "triage": h.triage,
                "score": round(h.score, 1),
            }
            for h in raw.hits
            if h.triage in ("likely", "verify")
            and hit_key(raw, h.entity_id, h.dataset, h.matched_name).lower() not in decided
        ]
        sow_a = sow_mod.assess(inv, case["sow"]) if (case.get("sow") or {}).get("sources") else None
        pack = review_pack.build_pack(
            case, self.store.changes(case_id), checklist, kyc_view, workflow, open_alerts, sow_a
        )
        return {"title": case["title"], **pack}

    def start_review(self, case_id: str, by: str) -> dict[str, Any]:
        """Start a periodic review: re-check with today's data, record it, reopen the case."""
        if not by.strip():
            raise wf.WorkflowError("Give your name: the review is signed.")
        case = self._get(case_id)
        warning = None
        try:
            self.refresh(case_id)
        except Exception as exc:  # noqa: BLE001 - the pack is still useful on the last data
            warning = f"Re-check failed, pack built on the last data: {str(exc)[:200]}"
        case = self.store.get_case(case_id) or case
        pack = self.review(case_id)
        saved_wf = case.get("workflow") or {}
        entry = {
            "started_at": now(),
            "by": by.strip(),
            "previous_validation": saved_wf.get("validated_at"),
            "due": pack["next_review"],
            "changes": sum(pack["changes_count"].values()),
            "actions": len(pack["actions"]),
        }
        fields: dict[str, Any] = {"reviews": [*(case.get("reviews") or []), entry][-50:]}
        if wf.state_of(case) == "validated":
            fields["workflow"] = wf.transition(
                case,
                "reopen",
                by,
                f"Periodic review started (due {pack['next_review'] or 'not set'}).",
                now(),
                [],
            )
        self.store.update_case(case_id, **fields)
        return {**self.review(case_id), "warning": warning}

    # ------------------------------------------------- workflow & checklist
    @staticmethod
    def workflow_view(
        case: dict[str, Any], checklist: dict[str, Any], assessment: dict | None
    ) -> dict[str, Any]:
        saved = case.get("workflow") or {}
        state = wf.state_of(case)
        return {
            "state": state,
            "label": wf.STATE_LABELS[state],
            "history": list(reversed(saved.get("history") or [])),
            "submitted_by": saved.get("submitted_by"),
            "validated_by": saved.get("validated_by"),
            "validated_at": saved.get("validated_at"),
            "blockers": wf.blockers(case, checklist, assessment),
        }

    def _case_file(self, case: dict[str, Any]) -> tuple[dict, dict, dict | None]:
        """Checklist, workflow and assessment of a case (runs the cached investigation)."""
        assessment = self.questionnaire(case)["assessment"]
        inv = self.service.investigate(self._params(case))
        checklist = wf.checklist_view(case, [r.model_dump() for r in inv.requests], assessment)
        return checklist, self.workflow_view(case, checklist, assessment), assessment

    def _get(self, case_id: str) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        if case.get("import_state"):
            raise wf.WorkflowError("This imported case has not been analysed yet.")
        return case

    def act(self, case_id: str, action: str, who: str, comment: str) -> dict[str, Any]:
        case = self._get(case_id)
        checklist, _, assessment = self._case_file(case)
        blocking = wf.blockers(case, checklist, assessment) if action == "submit" else []
        state = wf.transition(case, action, who, comment, now(), blocking)
        case = self.store.update_case(case_id, workflow=state)
        return self.workflow_view(case, checklist, assessment)  # type: ignore[arg-type]

    def tick(self, case_id: str, item_key: str, done: bool, by: str, note: str) -> dict[str, Any]:
        case = self._get(case_id)
        saved = dict(case.get("checklist") or {})
        ticks = dict(saved.get("ticks") or {})
        ticks[item_key] = {"done": done, "by": by, "at": now(), "note": note[:1000]}
        saved["ticks"] = ticks
        self.store.update_case(case_id, checklist=saved)
        return self._case_file(self.store.get_case(case_id))[0]  # type: ignore[arg-type]

    def add_diligence(self, case_id: str, label: str) -> dict[str, Any]:
        case = self._get(case_id)
        saved = dict(case.get("checklist") or {})
        custom = list(saved.get("custom") or [])
        custom.append({"key": "c" + uuid.uuid4().hex[:11], "label": label.strip()[:500]})
        saved["custom"] = custom[-100:]
        self.store.update_case(case_id, checklist=saved)
        return self._case_file(self.store.get_case(case_id))[0]  # type: ignore[arg-type]

    def remove_diligence(self, case_id: str, item_key: str) -> dict[str, Any]:
        case = self._get(case_id)
        saved = dict(case.get("checklist") or {})
        custom = [c for c in saved.get("custom") or [] if c["key"] != item_key]
        if len(custom) == len(saved.get("custom") or []):
            saved["removed"] = sorted({*(saved.get("removed") or []), item_key})
        saved["custom"] = custom
        self.store.update_case(case_id, checklist=saved)
        return self._case_file(self.store.get_case(case_id))[0]  # type: ignore[arg-type]

    # --------------------------------------------------------- questionnaire
    @staticmethod
    def questionnaire(case: dict[str, Any]) -> dict[str, Any]:
        saved = case.get("questionnaire") or {}
        answers = saved.get("answers") or {}
        return {
            "form": kyc.QUESTIONS,
            "answers": answers,
            "author": saved.get("author", ""),
            "answered_at": saved.get("answered_at"),
            "override_history": list(reversed(saved.get("override_history") or [])),
            "suggested": kyc.suggest(case),
            "assessment": kyc.assess({**answers, "_answered_at": saved.get("answered_at")}, case)
            if answers
            else None,
        }

    def memo(self, case_id: str, regenerate: bool = False) -> dict[str, Any]:
        """The saved memo, or a draft written from the current state of the case."""
        case = self._get(case_id)
        saved = case.get("memo") or {}
        raw = self.service.investigate(self._params(case))
        decisions = mark_stale(raw, self.store.decisions(case_id))
        inv = apply_decisions(raw, active(decisions))
        kyc_view = self.questionnaire(case)
        checklist = wf.checklist_view(
            case, [r.model_dump() for r in inv.requests], kyc_view["assessment"]
        )
        workflow = self.workflow_view(case, checklist, kyc_view["assessment"])
        kpis = self.overview(case, raw, inv, decisions, kyc_view, checklist, workflow)
        if saved.get("text") and not regenerate:
            return {"title": case["title"], "draft": False, **saved, "kpis": kpis}
        text = build_memo(case, inv, kyc_view, checklist, workflow, decisions)
        if (case.get("sow") or {}).get("sources"):
            text += "\n\n## Source of wealth\n" + sow_mod.assess(inv, case["sow"])["narrative"]
        return {
            "title": case["title"],
            "draft": True,
            "text": text,
            "generated_at": now(),
            "updated_by": saved.get("updated_by"),
            "updated_at": saved.get("updated_at"),
            "kpis": kpis,
        }

    def save_memo(self, case_id: str, text: str, by: str) -> dict[str, Any]:
        case = self._get(case_id)
        memo = {"text": text, "updated_by": by.strip(), "updated_at": now()}
        self.store.update_case(case_id, memo=memo)
        return {"title": case["title"], "draft": False, **memo}

    def override_vigilance(
        self, case_id: str, level: str | None, justification: str, by: str
    ) -> dict[str, Any]:
        """The analyst sets the final vigilance level (or goes back to the computed one)."""
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        saved = dict(case.get("questionnaire") or {})
        if not saved.get("answers"):
            raise wf.WorkflowError("Answer the questionnaire before adjusting the level.")
        if level is not None and level not in kyc.LEVELS:
            raise wf.WorkflowError("Unknown vigilance level.")
        if not by.strip():
            raise wf.WorkflowError("Give your name: the adjustment is signed.")
        if len(justification.strip()) < 15:
            raise wf.WorkflowError("A justification of at least 15 characters is required.")
        stamp = now()
        history = list(saved.get("override_history") or [])
        history.append(
            {
                "level": level,
                "justification": justification.strip()[:2000],
                "by": by.strip(),
                "at": stamp,
            }
        )
        saved["override_history"] = history[-50:]
        saved["override"] = (
            {
                "level": level,
                "justification": justification.strip()[:2000],
                "by": by.strip(),
                "at": stamp,
            }
            if level
            else None
        )
        case = self.store.update_case(case_id, questionnaire=saved)
        view = self.questionnaire(case)  # type: ignore[arg-type]
        a = view["assessment"]
        saved.update(vigilance=a["level"], next_review=a["next_review"])
        self.store.update_case(case_id, questionnaire=saved)
        return view

    def save_questionnaire(
        self, case_id: str, answers: dict[str, Any], author: str
    ) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        answers = kyc.clean(answers)
        stamp = now()
        assessment = kyc.assess({**answers, "_answered_at": stamp}, case)
        previous = case.get("questionnaire") or {}
        case = self.store.update_case(
            case_id,
            questionnaire={
                **{k: previous[k] for k in ("override", "override_history") if k in previous},
                "answers": answers,
                "author": author,
                "answered_at": stamp,
                "vigilance": assessment["level"],
                "next_review": assessment["next_review"],
            },
        )
        return self.questionnaire(case)  # type: ignore[arg-type]

    # ---------------------------------------------------------------- import
    def import_rows(
        self, rows: list[dict[str, Any]], depth: int, max_nodes: int, monitor: bool, batch: str
    ) -> list[dict[str, Any]]:
        created = []
        for row in rows:
            label = row["name"] or row["identifier"]
            title = f"{row['reference']} · {label}" if row["reference"] else label
            created.append(
                self.store.create_case(
                    title=title[:160],
                    subject_name=label[:200],
                    subject_type="company",
                    record_ids=[],
                    depth=depth,
                    max_nodes=max_nodes,
                    demo=False,
                    monitor=monitor,
                    import_state="pending",
                    import_info={**row, "batch": batch},
                )
            )
        return created

    def _pick(self, info: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Find the company of an imported row: (new state, info update)."""
        resp = self.service.search(info["query"], "company")
        cands = [c for c in resp.candidates if c.entity.type == EntityType.COMPANY]
        country = info.get("country")
        if country:
            local = [c for c in cands if (c.entity.jurisdiction or "").upper() == country]
            cands = local or cands
        # An identifier gives the exact company; the name search needs a clear winner.
        exact = [c for c in cands if c.score >= 100 and "identifier" in " ".join(c.explanation)]
        choices = [
            {
                "record_ids": c.entity.record_ids,
                "name": c.entity.name,
                "jurisdiction": c.entity.jurisdiction,
                "registration_number": c.entity.registration_number,
                "status": c.entity.status.value if c.entity.status else None,
                "score": round(c.score, 1),
            }
            for c in cands[:6]
        ]
        best = exact[0] if len(exact) == 1 else None
        if best is None and cands and not exact:
            top = cands[0]
            second = cands[1].score if len(cands) > 1 else 0.0
            if (top.score >= IMPORT_EXACT_SCORE and top.score - second >= IMPORT_EXACT_MARGIN) or (
                top.score >= IMPORT_MIN_SCORE and second < IMPORT_RIVAL_SCORE
            ):
                best = top
        if best is None:
            if not cands:
                return "not_found", {
                    "note": "No company found in the registers for this line.",
                    "choices": [],
                }
            return "ambiguous", {
                "note": "Several companies match: pick the right one.",
                "choices": choices,
            }
        return "resolved", {
            "record_ids": best.entity.record_ids,
            "matched": best.entity.name,
            "note": "; ".join(best.explanation[:2]),
            "choices": [],
        }

    def import_step(self, case_id: str | None = None) -> dict[str, Any] | None:
        """One step for the oldest imported case (or the one given): find the company, or
        investigate it."""
        case = self.store.get_case(case_id) if case_id else self.store.next_import()
        if case is None or case.get("import_state") not in IMPORT_ACTIVE:
            return None
        info = dict(case.get("import_info") or {})
        try:
            if case["import_state"] == "pending":
                state, update = self._pick(info)
                info.update(update)
                fields: dict[str, Any] = {"import_state": state, "import_info": info}
                if state == "resolved":
                    fields["record_ids"] = update["record_ids"]
                    fields["subject_name"] = update["matched"]
                self.store.update_case(case["id"], **fields)
                return {"case_id": case["id"], "title": case["title"], "state": state}
            inv = self.service.investigate(self._params(case))
            subject = next(e for e in inv.entities if e.id == inv.subject_id)
            self.store.update_case(
                case["id"],
                import_state="",
                subject_name=subject.name,
                subject_type=subject.type.value,
                demo=inv.demo,
                import_info={**info, "note": "", "choices": []},
            )
            self._record(case["id"], inv, {})
            return {"case_id": case["id"], "title": case["title"], "state": "done"}
        except Exception as exc:  # noqa: BLE001 - one bad line never blocks the queue
            info["note"] = f"Analysis failed: {str(exc)[:300]}"
            self.store.update_case(case["id"], import_state="error", import_info=info)
            return {"case_id": case["id"], "title": case["title"], "state": "error"}

    def resolve(self, case_id: str, record_ids: list[str]) -> dict[str, Any]:
        """The analyst picked the company of an imported line (or retries a failed one)."""
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        info = {**(case.get("import_info") or {}), "note": "", "choices": []}
        return self.store.update_case(  # type: ignore[return-value]
            case_id,
            record_ids=record_ids,
            import_state="resolved",
            import_info=info,
        )

    def import_status(self) -> dict[str, Any]:
        counts = self.store.import_counts()
        return {
            "counts": counts,
            "remaining": sum(counts.get(s, 0) for s in ("pending", "resolved")),
            "to_fix": sum(counts.get(s, 0) for s in ("ambiguous", "not_found", "error")),
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
        horizon = (date.today() + timedelta(days=30)).isoformat()
        queues = {
            q: 0 for q in ("sensitive", "to_validate", "to_complete", "review_due", "validated")
        }
        for c in cases:
            c["queue"] = wf.queue_of(c, horizon)
            c["workflow_state"] = wf.state_of(c)
            c.pop("workflow", None)
            c.pop("checklist", None)
            if c["queue"]:
                queues[c["queue"]] += 1
        jur = get_jurisdictions()
        # Changes per day over the last 30 days, by severity (monitoring activity).
        start = date.today() - timedelta(days=29)
        days = {
            (start + timedelta(days=i)).isoformat(): {"critical": 0, "warning": 0, "info": 0}
            for i in range(30)
        }
        for ch in self.store.changes(limit=5000):
            day = str(ch.get("run_at") or "")[:10]
            if day in days and ch.get("severity") in days[day]:
                days[day][ch["severity"]] += 1
        vigilance: dict[str, int] = {}
        states: dict[str, int] = {}
        upcoming = []
        for c in cases:
            if c.get("import_state"):
                continue
            v = (c.get("questionnaire") or {}).get("vigilance") or "to_assess"
            vigilance[v] = vigilance.get(v, 0) + 1
            states[c["workflow_state"]] = states.get(c["workflow_state"], 0) + 1
            nxt = (c.get("questionnaire") or {}).get("next_review")
            if nxt:
                upcoming.append({"id": c["id"], "title": c["title"], "date": str(nxt)[:10]})
        upcoming.sort(key=lambda r: r["date"])
        return {
            "changes_by_day": [{"day": k, **v} for k, v in days.items()],
            "vigilance": vigilance,
            "workflow": states,
            "upcoming_reviews": upcoming[:12],
            "memory": len(self.store.dismissals()) if memory_enabled() else 0,
            "cases": cases,
            "queues": queues,
            "by_level": by_level,
            "by_country": sorted(
                ({"code": k, "country": jur.name(k), "cases": v} for k, v in by_country.items()),
                key=lambda r: -r["cases"],
            ),
            "recent_changes": self.store.changes(limit=40),
            "imports": self.import_status(),
            "to_review": sum(
                1
                for c in cases
                if c["unseen_changes"] or c.get("risk_level") in ("high", "critical")
            ),
        }
