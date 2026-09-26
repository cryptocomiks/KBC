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

from app import questionnaire as kyc
from app import workflow as wf
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
from app.store import IMPORT_ACTIVE, Store, get_store, now

DECISIONS = {"confirmed", "false_positive", "to_review"}
STRONG = 85.0
# Name search: the best candidate is picked automatically only when there is no real doubt —
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
        "factors": sorted({f.key for f in inv.risk.factors}),
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
        decisions = self.store.decisions(case_id)
        inv = apply_decisions(self.service.investigate(self._params(case)), decisions)
        checklist = wf.checklist_view(
            case, [r.model_dump() for r in inv.requests], kyc_view["assessment"]
        )
        workflow = self.workflow_view(case, checklist, kyc_view["assessment"])
        case.pop("snapshot", None)
        return {
            "case": case,
            "investigation": inv,
            "decisions": decisions,
            "changes": self.store.changes(case_id),
            "questionnaire": kyc_view,
            "checklist": checklist,
            "workflow": workflow,
        }

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
            "suggested": kyc.suggest(case),
            "assessment": kyc.assess({**answers, "_answered_at": saved.get("answered_at")}, case)
            if answers
            else None,
        }

    def save_questionnaire(
        self, case_id: str, answers: dict[str, Any], author: str
    ) -> dict[str, Any]:
        case = self.store.get_case(case_id)
        if case is None:
            raise LookupError("Case not found")
        answers = kyc.clean(answers)
        stamp = now()
        assessment = kyc.assess({**answers, "_answered_at": stamp}, case)
        case = self.store.update_case(
            case_id,
            questionnaire={
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
        return {
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
