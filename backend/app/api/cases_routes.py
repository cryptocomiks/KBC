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
    get_store().set_decision(case_id, d.item_key, d.item_label, d.decision, d.comment, d.author)
    return {"decisions": get_store().decisions(case_id)}


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
