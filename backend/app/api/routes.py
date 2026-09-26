"""REST API routes (mounted under /api)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field
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
    if req.case_id:
        from app.cases import CaseService

        require_access(x_kbc_password)
        decisions = get_store().decisions(req.case_id)
        changes = get_store().changes(req.case_id)
        inv = apply_decisions(inv, decisions)
        case = get_store().get_case(req.case_id)
        if case:
            questionnaire = CaseService.questionnaire(case)
    pdf = build_pdf(
        inv,
        graph_png_b64=req.graph_png,
        analyst=req.analyst,
        reference=req.reference,
        decisions=decisions,
        template=req.template,
        changes=changes,
        questionnaire=questionnaire,
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
