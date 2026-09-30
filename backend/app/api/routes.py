"""REST API routes (mounted under /api)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from unidecode import unidecode

from app import __version__
from app.api.cases_routes import cases_status, require_access
from app.cache import get_cache
from app.risk.config import get_jurisdictions, get_risk_config
from app.schemas import (
    DISCLAIMER,
    Investigation,
    InvestigationRequest,
    ReportRequest,
    SearchResponse,
)
from app.service import KbcService
from app.settings import get_settings

router = APIRouter()


def service() -> KbcService:
    return KbcService()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/meta")
def meta() -> dict:
    s = get_settings()
    return {
        "version": __version__,
        "demo_mode": s.demo_mode,
        "commercial_mode": s.commercial_mode,
        "disclaimer": DISCLAIMER,
        "max_depth": s.max_depth,
        "max_nodes_limit": s.max_nodes_limit,
        "cases": cases_status(),
    }


@router.get("/connectors")
def connectors() -> list[dict]:
    return service().registry.statuses()


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(min_length=2, max_length=200),
    type: Literal["any", "person", "company"] = "any",
) -> SearchResponse:
    return service().search(q.strip(), type)


@router.post("/investigations", response_model=Investigation)
def investigate(req: InvestigationRequest) -> Investigation:
    try:
        return service().investigate(req)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/validation")
def matching_validation() -> dict:
    """Detection and false-positive rates of the match engine on the labelled test set."""
    from app.validation import cached_validation

    return cached_validation()


class ChecksRequest(BaseModel):
    iban: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=253)
    wallet: str | None = Field(default=None, max_length=128)
    company: str | None = Field(default=None, max_length=200)
    client_country: str | None = Field(default=None, max_length=2)


@router.post("/checks")
def quick_checks(req: ChecksRequest) -> dict:
    """IBAN, e-mail, website and crypto-address checks. Nothing is stored."""
    from app.checks import run_checks

    if not any((req.iban, req.email, req.website, req.wallet)):
        raise HTTPException(status_code=422, detail="Nothing to check")
    return run_checks(req.model_dump())


class ScreenRow(BaseModel):
    name: str = Field(max_length=300)
    type: str | None = Field(default=None, pattern="^(person|company|auto)$")
    country: str | None = Field(default=None, max_length=2)
    reference: str | None = Field(default=None, max_length=100)


class ScreenRequest(BaseModel):
    rows: list[ScreenRow] = Field(max_length=60)


@router.post("/screen")
def screen_names(req: ScreenRequest) -> dict:
    """Screen up to 60 names (a customer list, payment counterparties) against every sanctions,
    PEP and watchlist source at once. Nothing is stored."""
    from app.screening_tools import screen_list

    if not req.rows:
        raise HTTPException(status_code=422, detail="Nothing to screen")
    return screen_list([r.model_dump() for r in req.rows], service().screen_entities)


@router.get("/designations")
def designations(days: int = 90, limit: int = 300) -> dict:
    """New entries on the official sanctions lists (UN, EU, UK, US export lists) in the last
    `days` days, newest first."""
    from app.screening_tools import recent_designations

    return recent_designations(service().registry, max(1, min(days, 730)), max(1, min(limit, 2000)))


@router.post("/transactions/analyze")
async def analyze_transactions(
    file: UploadFile = File(...),
    profile: str = Form(default="{}"),
    screen: bool = Form(default=True),
) -> dict:
    """Bank statement analysis (CSV / Excel). The file is read in memory and never stored."""
    import json

    from app.transactions import MAX_BYTES, analyse

    data = await file.read(MAX_BYTES + 1)
    try:
        prof = json.loads(profile or "{}")
    except ValueError:
        prof = {}
    try:
        return analyse(
            data,
            file.filename or "statement.csv",
            prof if isinstance(prof, dict) else {},
            service().screen_entities if screen else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        del data


@router.post("/reports/pdf")
def report_pdf(req: ReportRequest, x_kbc_password: str | None = Header(default=None)) -> Response:
    from app.cases import apply_decisions
    from app.report.pdf import build_pdf
    from app.store import get_store

    try:
        inv = service().investigate(
            InvestigationRequest(**req.model_dump(include={"record_ids", "depth", "max_nodes"}))
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    decisions: list[dict] = []
    changes: list[dict] = []
    questionnaire: dict | None = None
    case_file: dict | None = None
    if req.case_id:
        from app.cases import CaseService

        require_access(x_kbc_password)
        from app.cases import active, mark_stale

        raw = inv
        decisions = mark_stale(inv, get_store().decisions(req.case_id))
        changes = get_store().changes(req.case_id)
        inv = apply_decisions(inv, active(decisions))
        case = get_store().get_case(req.case_id)
        if case:
            from app.workflow import checklist_view

            questionnaire = CaseService.questionnaire(case)
            checklist = checklist_view(
                case, [r.model_dump() for r in inv.requests], questionnaire["assessment"]
            )
            from app import cdb as cdb_forms
            from app import sow as sow_mod

            workflow = CaseService.workflow_view(case, checklist, questionnaire["assessment"])
            case_file = {
                "checklist": checklist,
                "workflow": workflow,
                "overview": CaseService.overview(
                    case, raw, inv, decisions, questionnaire, checklist, workflow
                ),
                "cdb": cdb_forms.build(inv, case.get("cdb") or {}),
                "sow": sow_mod.assess(inv, case["sow"])
                if (case.get("sow") or {}).get("sources")
                else None,
            }
    pdf = build_pdf(
        inv,
        graph_png_b64=req.graph_png,
        analyst=req.analyst,
        reference=req.reference,
        decisions=decisions,
        template=req.template,
        changes=changes,
        questionnaire=questionnaire,
        case_file=case_file,
    )
    subject = next(e for e in inv.entities if e.id == inv.subject_id)
    # HTTP headers are Latin-1: keep the file name ASCII ("S.à r.l." -> "S_a_r_l_")
    safe = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in unidecode(subject.name))[
        :60
    ]
    prefix = {"kyc": "kyc", "edd": "edd", "review": "periodic_review"}.get(
        req.template, "due_diligence"
    )
    filename = f"{prefix}_{safe}_{inv.generated_at:%Y%m%d}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class SarRequest(InvestigationRequest):
    fiu: Literal["tracfin", "mros", "lu_crf"] = "tracfin"
    lang: Literal["fr", "en"] | None = None
    reference: str | None = Field(default=None, max_length=120)
    case_id: str | None = Field(default=None, max_length=40)


@router.post("/reports/sar")
def sar_draft(req: SarRequest, x_kbc_password: str | None = Header(default=None)) -> Response:
    """Draft suspicious activity report (TRACFIN / MROS / CRF Luxembourg), never filed automatically."""
    from app.cases import apply_decisions
    from app.report.sar import build_sar
    from app.store import get_store

    try:
        inv = service().investigate(
            InvestigationRequest(**req.model_dump(include={"record_ids", "depth", "max_nodes"}))
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    decisions: list[dict] = []
    if req.case_id:
        require_access(x_kbc_password)
        decisions = get_store().decisions(req.case_id)
        inv = apply_decisions(inv, decisions)
    pdf = build_sar(inv, req.fiu, req.lang, req.reference, decisions)
    subject = next(e for e in inv.entities if e.id == inv.subject_id)
    safe = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in unidecode(subject.name))[
        :60
    ]
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="DRAFT_SAR_{req.fiu}_{safe}.pdf"'},
    )


@router.get("/config/risk")
def risk_config() -> dict:
    jur = get_jurisdictions()
    return {
        "risk": get_risk_config().model_dump(),
        "jurisdictions": {
            "as_of": jur.as_of,
            "fatf_blacklist": sorted(jur.fatf_blacklist),
            "fatf_greylist": sorted(jur.fatf_greylist),
            "eu_tax_blacklist": sorted(jur.eu_tax_blacklist),
            "offshore_centres": sorted(jur.offshore_centres),
        },
    }


@router.get("/cache")
def cache_stats() -> dict:
    return {"entries": get_cache().stats()}


@router.delete("/cache")
def clear_cache() -> dict:
    return {"deleted": get_cache().clear()}
