"""Cases, analyst decisions, dashboard and monitoring (mounted under /api).

Protected by APP_PASSWORD (header X-KBC-Password). On Vercel the password is
mandatory: without it the case endpoints stay disabled, so saved files never
become public by accident. The monitoring job authenticates with CRON_SECRET
(Authorization: Bearer ...) or the password.
"""

from __future__ import annotations

import hmac
import os
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import bulk_import
from app.cases import DECISIONS, CaseService
from app.schemas import InvestigationRequest
from app.service import KbcService
from app.settings import get_settings
from app.store import get_store
from app.workflow import WorkflowError

router = APIRouter(prefix="/cases", tags=["cases"])


def cases_status() -> dict:
    s = get_settings()
    on_vercel = bool(os.environ.get("VERCEL"))
    if on_vercel and not s.app_password:
        return {
            "enabled": False,
            "auth_required": True,
            "storage": None,
            "message": "Cases are disabled: set APP_PASSWORD in Vercel → Settings → Environment Variables.",
        }
    if on_vercel and not s.database_url:
        return {
            "enabled": True,
            "auth_required": True,
            "storage": "sqlite (temporary)",
            "message": "No database connected: cases are lost when the server restarts. "
            "Create a Postgres database in Vercel → Storage, then redeploy.",
        }
    return {
        "enabled": True,
        "auth_required": bool(s.app_password),
        "storage": "postgres" if s.database_url else "sqlite",
        "message": None,
    }


def _same(given: str | None, expected: str) -> bool:
    return bool(given) and bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def require_access(x_kbc_password: str | None = Header(default=None)) -> None:
    status = cases_status()
    if not status["enabled"]:
        raise HTTPException(status_code=503, detail=status["message"])
    expected = get_settings().app_password
    if expected and not _same(x_kbc_password, expected):
        raise HTTPException(status_code=401, detail="Password required")


def cases() -> CaseService:
    return CaseService(get_store(), KbcService())


class CaseCreate(InvestigationRequest):
    title: str | None = Field(default=None, max_length=160)
    monitor: bool = True


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=20000)
    status: Literal["open", "closed"] | None = None
    monitor: bool | None = None


class DecisionIn(BaseModel):
    item_key: str = Field(max_length=600)
    item_label: str = Field(default="", max_length=600)
    decision: Literal["confirmed", "false_positive", "to_review", "none"]
    comment: str = Field(default="", max_length=4000)
    author: str = Field(default="", max_length=120)


@router.get("/status")
def status() -> dict:
    return cases_status()


class QuestionnaireIn(BaseModel):
    answers: dict[str, Any]
    author: str = Field(default="", max_length=120)


class WorkflowIn(BaseModel):
    action: Literal["submit", "validate", "reject", "reopen"]
    by: str = Field(max_length=120)
    comment: str = Field(default="", max_length=2000)


class OverrideIn(BaseModel):
    level: Literal["simplified", "standard", "enhanced"] | None = None
    justification: str = Field(default="", max_length=2000)
    by: str = Field(default="", max_length=120)


class MemoIn(BaseModel):
    text: str = Field(max_length=60000)
    by: str = Field(default="", max_length=120)


class TickIn(BaseModel):
    done: bool
    by: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=1000)


class DiligenceIn(BaseModel):
    label: str = Field(min_length=3, max_length=500)


class ResolveIn(BaseModel):
    record_ids: list[str] = Field(min_length=1, max_length=20)


@router.get("", dependencies=[Depends(require_access)])
def dashboard() -> dict:
    return cases().dashboard()


# ------------------------------------------------------------------ bulk import
def require_access_or_cron(
    authorization: str | None = Header(default=None),
    x_kbc_password: str | None = Header(default=None),
) -> None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if _same(token, get_settings().cron_secret):
        if not cases_status()["enabled"]:
            raise HTTPException(status_code=503, detail=cases_status()["message"])
        return
    require_access(x_kbc_password)


@router.post("/import", dependencies=[Depends(require_access)])
async def import_file(
    file: UploadFile = File(...),
    depth: int = Form(default=2, ge=1, le=3),
    max_nodes: int = Form(default=60, ge=5, le=250),
    monitor: bool = Form(default=True),
) -> dict:
    """Client list (CSV / Excel) → one case per line, analysed step by step (see /import/next)."""
    data = await file.read(bulk_import.MAX_BYTES + 1)
    try:
        rows, warnings = bulk_import.parse(file.filename or "", data)
    except bulk_import.ImportError_ as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    batch = uuid.uuid4().hex[:8]
    created = cases().import_rows(rows, depth, max_nodes, monitor, batch)
    return {
        "batch": batch,
        "created": len(created),
        "warnings": warnings,
        **cases().import_status(),
    }


@router.get("/import/status", dependencies=[Depends(require_access)])
def import_status() -> dict:
    return cases().import_status()


@router.post("/import/next", dependencies=[Depends(require_access_or_cron)])
def import_next(case_id: str | None = None) -> dict:
    """Process one step of the import queue (find a company, or investigate it).
    With case_id: that imported case, e.g. right after the analyst picked its company."""
    svc = cases()
    step = svc.import_step(case_id)
    return {"step": step, **svc.import_status()}


@router.post("", dependencies=[Depends(require_access)])
def create(req: CaseCreate) -> dict:
    try:
        return cases().create(
            InvestigationRequest(
                record_ids=req.record_ids, depth=req.depth, max_nodes=req.max_nodes
            ),
            req.title,
            req.monitor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class BatchIn(BaseModel):
    by: str = Field(max_length=120)
    keys: list[str] | None = Field(default=None, max_length=500)


class CdbEditIn(BaseModel):
    by: str = Field(max_length=120)
    form: str = Field(default="", max_length=400)
    person: str | None = Field(default=None, max_length=400)
    fields: dict[str, str] | None = None
    header: dict[str, str] | None = None
    structure: dict[str, str] | None = None
    add: bool = False
    role: str | None = Field(default=None, max_length=40)
    remove: str | None = Field(default=None, max_length=400)
    reset: bool = False


class SowIn(BaseModel):
    by: str = Field(max_length=120)
    data: dict[str, Any]


class ReviewIn(BaseModel):
    by: str = Field(max_length=120)


@router.get("/memory", dependencies=[Depends(require_access)])
def memory() -> dict:
    """Alerts ruled out as namesakes, remembered across cases (with the evidence kept)."""
    return {"items": cases().memory()}


@router.delete("/memory", dependencies=[Depends(require_access)])
def forget(key: str) -> dict:
    """Revoke a remembered ruling: the alert comes back everywhere at the next check."""
    get_store().remove_dismissal(key[:600])
    return {"items": cases().memory()}


@router.get("/{case_id}", dependencies=[Depends(require_access)])
def view(case_id: str) -> dict:
    try:
        return cases().view(case_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{case_id}", dependencies=[Depends(require_access)])
def update(case_id: str, req: CaseUpdate) -> dict:
    case = get_store().update_case(case_id, **req.model_dump(exclude_none=True))
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    case.pop("snapshot", None)
    return case


@router.delete("/{case_id}", dependencies=[Depends(require_access)])
def delete(case_id: str) -> dict:
    get_store().delete_case(case_id)
    return {"deleted": case_id}


@router.post("/{case_id}/refresh", dependencies=[Depends(require_access)])
def refresh(case_id: str) -> dict:
    try:
        case, changes = cases().refresh(case_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    case.pop("snapshot", None)
    return {"case": case, "changes": changes}


@router.put("/{case_id}/questionnaire", dependencies=[Depends(require_access)])
def save_questionnaire(case_id: str, q: QuestionnaireIn) -> dict:
    try:
        return cases().save_questionnaire(case_id, q.answers, q.author)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _run(fn, *args):
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{case_id}/workflow", dependencies=[Depends(require_access)])
def workflow_action(case_id: str, w: WorkflowIn) -> dict:
    """Send for validation, validate (four eyes), send back or reopen a case."""
    return _run(cases().act, case_id, w.action, w.by, w.comment)


@router.put("/{case_id}/vigilance", dependencies=[Depends(require_access)])
def override_vigilance(case_id: str, o: OverrideIn) -> dict:
    """Analyst's final vigilance level (null = back to the computed one), with a justification."""
    return _run(cases().override_vigilance, case_id, o.level, o.justification, o.by)


@router.get("/{case_id}/memo", dependencies=[Depends(require_access)])
def get_memo(case_id: str, regenerate: bool = False) -> dict:
    """Decision memo: the saved version, or a fresh draft written from the case."""
    return _run(cases().memo, case_id, regenerate)


@router.put("/{case_id}/memo", dependencies=[Depends(require_access)])
def save_memo(case_id: str, m: MemoIn) -> dict:
    return _run(cases().save_memo, case_id, m.text, m.by)


@router.get("/{case_id}/memo.pdf", dependencies=[Depends(require_access)])
def memo_pdf(case_id: str):
    from fastapi.responses import Response

    from app.report.memo_pdf import build_memo_pdf

    memo = _run(cases().memo, case_id, False)
    pdf = build_memo_pdf(memo)
    safe = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in memo["title"])[:60]
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="decision_memo_{safe}.pdf"'},
    )


@router.put("/{case_id}/checklist/{item_key}", dependencies=[Depends(require_access)])
def tick(case_id: str, item_key: str, t: TickIn) -> dict:
    return _run(cases().tick, case_id, item_key[:40], t.done, t.by, t.note)


@router.post("/{case_id}/diligences", dependencies=[Depends(require_access)])
def add_diligence(case_id: str, d: DiligenceIn) -> dict:
    return _run(cases().add_diligence, case_id, d.label)


@router.delete("/{case_id}/diligences/{item_key}", dependencies=[Depends(require_access)])
def remove_diligence(case_id: str, item_key: str) -> dict:
    return _run(cases().remove_diligence, case_id, item_key[:40])


@router.post("/{case_id}/resolve", dependencies=[Depends(require_access)])
def resolve(case_id: str, r: ResolveIn) -> dict:
    try:
        case = cases().resolve(case_id, r.record_ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    case.pop("snapshot", None)
    return case


@router.post("/{case_id}/seen", dependencies=[Depends(require_access)])
def mark_seen(case_id: str) -> dict:
    get_store().mark_seen(case_id)
    return {"ok": True}


@router.put("/{case_id}/decisions", dependencies=[Depends(require_access)])
def decide(case_id: str, d: DecisionIn) -> dict:
    if get_store().get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if d.decision != "none" and d.decision not in DECISIONS:
        raise HTTPException(status_code=422, detail="Unknown decision")
    return {
        "decisions": _run(
            cases().decide, case_id, d.item_key, d.item_label, d.decision, d.comment, d.author
        )
    }


@router.get("/{case_id}/alerts", dependencies=[Depends(require_access)])
def case_alerts(case_id: str) -> dict:
    """Screening alerts of the case with triage, memory, re-alerts and proposed justifications."""
    return _run(cases().alerts_view, case_id)


@router.post("/{case_id}/alerts/batch", dependencies=[Depends(require_access)])
def batch_dismiss(case_id: str, b: BatchIn) -> dict:
    """Rule out the probable namesakes (or the alerts given) in one go, each justified."""
    return _run(cases().batch_dismiss, case_id, b.by, b.keys)


@router.get("/{case_id}/cdb", dependencies=[Depends(require_access)])
def cdb_forms(case_id: str) -> dict:
    """CDB 20 beneficial-ownership forms (A / K / S / T) pre-filled from the registers."""
    return _run(cases().cdb, case_id)


@router.put("/{case_id}/cdb", dependencies=[Depends(require_access)])
def edit_cdb(case_id: str, e: CdbEditIn) -> dict:
    return _run(cases().edit_cdb, case_id, e.model_dump(exclude={"by"}), e.by)


@router.get("/{case_id}/cdb.pdf", dependencies=[Depends(require_access)])
def cdb_pdf(case_id: str):
    from fastapi.responses import Response

    from app.report.cdb_pdf import build_cdb_pdf

    data = _run(cases().cdb, case_id)
    pdf = build_cdb_pdf(data, data["title"])
    safe = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in data["title"])[:60]
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="cdb20_forms_{safe}.pdf"'},
    )


@router.get("/{case_id}/sow", dependencies=[Depends(require_access)])
def source_of_wealth(case_id: str) -> dict:
    return _run(cases().sow, case_id)


@router.put("/{case_id}/sow", dependencies=[Depends(require_access)])
def save_sow(case_id: str, s: SowIn) -> dict:
    return _run(cases().save_sow, case_id, s.data, s.by)


@router.get("/{case_id}/review", dependencies=[Depends(require_access)])
def review(case_id: str) -> dict:
    """Periodic review pack: changes since the last validation, documents to renew, actions."""
    return _run(cases().review, case_id)


@router.post("/{case_id}/review/start", dependencies=[Depends(require_access)])
def start_review(case_id: str, r: ReviewIn) -> dict:
    return _run(cases().start_review, case_id, r.by)


monitor_router = APIRouter(tags=["cases"])


@monitor_router.get(
    "/monitor/run"
)  # Vercel Cron sends GET with "Authorization: Bearer $CRON_SECRET"
@monitor_router.post("/monitor/run")
def monitor_run(
    authorization: str | None = Header(default=None),
    x_kbc_password: str | None = Header(default=None),
) -> dict:
    """Refresh the monitored case that was checked the longest ago (one per call: each run of the
    job calls this endpoint as many times as needed, which keeps every call within the host's limit)."""
    s = get_settings()
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not (_same(token, s.cron_secret) or _same(x_kbc_password, s.app_password)):
        raise HTTPException(status_code=401, detail="CRON_SECRET or password required")
    if not cases_status()["enabled"]:
        raise HTTPException(status_code=503, detail=cases_status()["message"])
    case = get_store().stalest_monitored()
    if case is None:
        return {"refreshed": None, "changes": []}
    case, changes = cases().refresh(case["id"])
    return {"refreshed": case["id"], "title": case["title"], "changes": changes}
