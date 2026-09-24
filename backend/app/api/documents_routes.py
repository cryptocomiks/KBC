"""Client documents: extract officers / owners from a register extract or UBO declaration,
then compare them with the registries. Files are read in memory and never stored."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import Field

from app.doc_reader import (
    DeclaredCompany,
    DeclaredPerson,
    Extraction,
    compare,
    extract,
    read_text,
    serialize,
)
from app.graph.expander import Network
from app.schemas import InvestigationRequest
from app.service import KbcService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/extract", response_model=Extraction)
async def extract_document(file: UploadFile = File(...)) -> Extraction:
    data = await file.read()
    try:
        text, pages = read_text(data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - unreadable / encrypted PDF
        raise HTTPException(
            status_code=422, detail=f"Unreadable document ({type(exc).__name__})"
        ) from exc
    finally:
        del data  # nothing is kept
    return extract(text, pages)


class CompareRequest(InvestigationRequest):
    company: DeclaredCompany = Field(default_factory=DeclaredCompany)
    officers: list[DeclaredPerson] = Field(default_factory=list, max_length=200)
    owners: list[DeclaredPerson] = Field(default_factory=list, max_length=200)


@router.post("/compare")
def compare_document(req: CompareRequest) -> dict:
    try:
        inv = KbcService().investigate(
            InvestigationRequest(
                record_ids=req.record_ids, depth=req.depth, max_nodes=req.max_nodes
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    net = Network(
        subject_id=inv.subject_id,
        max_depth=inv.params.depth,
        max_nodes=inv.params.max_nodes,
        entities={e.id: e for e in inv.entities},
        relationships={r.id: r for r in inv.relationships},
        depth=inv.depth,
    )
    rows = compare(net, req.company, req.officers, req.owners)
    return {
        "rows": serialize(rows),
        "summary": {
            s: sum(1 for r in rows if r.status == s)
            for s in ("match", "mismatch", "missing_in_registry", "missing_in_document")
        },
    }
