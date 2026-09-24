"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.brief import Brief
from app.graph.expander import QueryLog
from app.insights import Finding, TimelineEvent
from app.models import Entity, Relationship, ScreeningHit, SearchCandidate
from app.risk.engine import RiskAssessment

DISCLAIMER = (
    "Analytical aid only. Automated matches (name similarity, entity resolution, screening) "
    "may be false positives or false negatives and MUST be verified by a qualified analyst "
    "against primary sources before any decision is taken. Only public or lawfully accessible "
    "sources are queried."
)


class InvestigationRequest(BaseModel):
    record_ids: list[str] = Field(min_length=1, max_length=20)
    depth: int = Field(default=2, ge=1, le=3)
    max_nodes: int = Field(default=60, ge=5, le=250)


class ReportRequest(InvestigationRequest):
    graph_png: str | None = None  # base64 PNG exported by Cytoscape in the browser
    analyst: str | None = Field(default=None, max_length=120)
    reference: str | None = Field(default=None, max_length=120)


class SearchResponse(BaseModel):
    query: str
    type: str
    candidates: list[SearchCandidate]
    sources: list[str]
    warnings: list[str] = Field(default_factory=list)


class Investigation(BaseModel):
    id: str
    subject_id: str
    params: InvestigationRequest
    generated_at: datetime
    demo: bool
    disclaimer: str = DISCLAIMER
    entities: list[Entity]
    depth: dict[str, int]
    relationships: list[Relationship]
    hits: list[ScreeningHit]
    risk: RiskAssessment
    tables: dict[str, list[dict[str, Any]]]
    queries: list[QueryLog]
    merges: list[dict[str, Any]]
    warnings: list[str]
    truncated: bool
    stats: dict[str, int]
    summary: list[Finding] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    brief: Brief | None = None
