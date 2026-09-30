"""KYC 1 CLICK as a tool for AI agents: a Model Context Protocol (MCP) server.

Streamable HTTP transport, stateless: every JSON-RPC message is a POST to /api/mcp and
is answered with plain JSON. Any MCP client (Claude, an agent framework, an internal
compliance copilot) can then search a name, run a full due diligence, screen a list of
counterparties or check an IBAN / e-mail / website / crypto address, and get the same
sourced, explained results as the web app. Cases and client documents are not exposed:
they stay behind the password of the web app.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app import __version__ as VERSION
from app.schemas import InvestigationRequest

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DISCLAIMER = (
    "Analytical aid only: automated matches may be false positives or false negatives and "
    "must be verified by a qualified analyst against primary sources before any decision."
)
INSTRUCTIONS = (
    "KYC 1 CLICK: due diligence on companies and persons from public registries, official "
    "sanctions lists (OFAC, UN, EU, UK, Switzerland, US export lists, France), PEP lists, "
    "leaks, press and court records. Typical flow: search_entities, then run_due_diligence "
    "on the right record_ids. Every result carries its sources. " + DISCLAIMER
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_entities",
        "title": "Search a company or a person",
        "description": (
            "Search registries and lists for a company, a person, an identifier (SIREN, LEI, "
            "Swiss UID, UK company number, SEC CIK) or a crypto address. Returns candidates "
            "with their record_ids, to pass to run_due_diligence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name, identifier or crypto address"},
                "type": {"type": "string", "enum": ["any", "company", "person"], "default": "any"},
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "run_due_diligence",
        "title": "Run a full due diligence",
        "description": (
            "Map the network around a company or person (owners, officers, subsidiaries, "
            "cross-border links), screen everyone against sanctions, PEP and watchlists, compute "
            "beneficial ownership (OFAC 50 % rule), and return a risk rating with the findings, "
            "their evidence, the recommended action and the legal basis. Give record_ids from "
            "search_entities, or a query to use the best candidate. Takes 1 to 3 minutes on live "
            "sources."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_ids": {"type": "array", "items": {"type": "string"}},
                "query": {"type": "string", "description": "Used when record_ids is not given"},
                "type": {"type": "string", "enum": ["any", "company", "person"], "default": "any"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 2, "default": 1},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "screen_names",
        "title": "Screen a list of names",
        "description": (
            "Screen up to 60 names (payment counterparties, directors, a customer list) against "
            "every sanctions, PEP and watchlist source at once. Returns the possible matches "
            "(score 70 and above) with the list, the listed name and the reasons."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"}, "maxItems": 60},
                "type": {
                    "type": "string",
                    "enum": ["person", "company", "auto"],
                    "default": "auto",
                },
            },
            "required": ["names"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "quick_checks",
        "title": "Check an IBAN, e-mail, website or crypto address",
        "description": (
            "IBAN validity, bank and country risk; e-mail domain (MX, SPF, DMARC, age, scam "
            "lists); website age and registration; crypto address on sanctions and scam lists."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "iban": {"type": "string"},
                "email": {"type": "string"},
                "website": {"type": "string"},
                "wallet": {"type": "string"},
            },
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
]


class ToolError(Exception):
    """A tool that ran but could not answer: returned to the agent as isError content."""


def _service():
    from app.service import KbcService

    return KbcService()


def _search(args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query is empty")
    res = _service().search(query, str(args.get("type") or "any"))
    return {
        "query": query,
        "candidates": [
            {
                "name": c.entity.name,
                "type": c.entity.type.value,
                "jurisdiction": c.entity.jurisdiction,
                "birth_date": c.entity.birth_date,
                "status": getattr(c.entity.status, "value", c.entity.status),
                "record_ids": c.entity.record_ids,
                "score": c.score,
                "why": c.explanation[:3],
            }
            for c in res.candidates[:10]
        ],
        "sources": res.sources,
        "warnings": res.warnings[:5],
    }


def _due_diligence(args: dict) -> dict:
    ids = [str(x) for x in args.get("record_ids") or [] if x]
    if not ids:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ToolError("give record_ids (from search_entities) or a query")
        found = _service().search(query, str(args.get("type") or "any")).candidates
        if not found:
            raise ToolError(f"nothing found for {query!r}")
        ids = found[0].entity.record_ids
    depth = max(1, min(2, int(args.get("depth") or 1)))
    try:
        inv = _service().investigate(
            InvestigationRequest(record_ids=ids, depth=depth, max_nodes=60)
        )
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
    names = {e.id: e.name for e in inv.entities}
    subject = next((e for e in inv.entities if e.id == inv.subject_id), None)
    hits = sorted(
        (h for h in inv.hits if h.triage not in ("namesake", "dismissed") and h.score >= 70),
        key=lambda h: -h.score,
    )
    brief = inv.brief
    own = inv.ownership
    return {
        "subject": {
            "name": subject.name if subject else None,
            "type": subject.type.value if subject else None,
            "jurisdiction": subject.jurisdiction if subject else None,
        },
        "risk": {"level": inv.risk.level, "score": inv.risk.score},
        "headline": brief.headline if brief else None,
        "recommended_action": brief.action if brief else None,
        "findings": [
            {
                "title": f.title,
                "severity": f.severity,
                "evidence": f.evidence[:3],
                "next_step": f.next_step,
            }
            for f in (brief.flags if brief else [])[:12]
        ],
        "screening_hits": [
            {
                "entity": names.get(h.entity_id, h.entity_id),
                "list": h.dataset,
                "type": h.list_type.value,
                "listed_as": h.matched_name,
                "score": h.score,
                "source": h.provenance.url,
            }
            for h in hits[:20]
        ],
        "beneficial_owners": [
            {
                "name": o.name,
                "effective_pct": o.effective_pct,
                "status": o.status,
                "pep": o.pep,
                "sanctioned": o.sanctioned,
                "countries": o.countries,
            }
            for o in (own.owners if own else [])[:10]
        ],
        "blocked_by_ownership": [
            {"entity": b.name, "sanctioned_ownership_pct": b.aggregate_pct, "blocked": b.blocked}
            for b in (own.sanctions if own else [])
        ],
        "questions_for_the_client": (own.questions if own else [])[:8],
        "legal_basis": [
            {
                "finding": item.get("label"),
                "provisions": [r.get("short") for r in item.get("refs") or []],
                "justification": item.get("en"),
            }
            for item in inv.legal[:10]
        ],
        "network": {"entities": len(inv.entities), "relationships": len(inv.relationships)},
        "warnings": inv.warnings[:8],
        "open_in_browser": "https://kbc-lemon.vercel.app/#/investigate?ids="
        + ",".join(ids)
        + f"&depth={depth}",
        "disclaimer": DISCLAIMER,
    }


def _screen(args: dict) -> dict:
    from app.screening_tools import screen_list

    raw = [str(n).strip() for n in args.get("names") or [] if str(n).strip()]
    if not raw:
        raise ToolError("names is empty")
    kind = args.get("type") if args.get("type") in ("person", "company") else "auto"
    res = screen_list([{"name": n, "type": kind} for n in raw], _service().screen_entities)
    return {**res, "disclaimer": DISCLAIMER}


def _checks(args: dict) -> dict:
    from app.checks import run_checks

    payload = {
        k: str(args[k]).strip() for k in ("iban", "email", "website", "wallet") if args.get(k)
    }
    if not payload:
        raise ToolError("give at least one of iban, email, website, wallet")
    return run_checks(payload)


HANDLERS = {
    "search_entities": _search,
    "run_due_diligence": _due_diligence,
    "screen_names": _screen,
    "quick_checks": _checks,
}


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(message: Any) -> dict | None:
    """One JSON-RPC message -> its response (None for a notification)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(
            message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request"
        )
    method, req_id, params = message["method"], message.get("id"), message.get("params") or {}
    if "id" not in message:
        return None  # notifications (initialized, cancelled…) need no answer
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(
            req_id,
            {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "kyc-1-click", "title": "KYC 1 CLICK", "version": VERSION},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(req_id, -32602, f"Unknown tool: {name}")
        try:
            data = handler(params.get("arguments") or {})
        except ToolError as exc:
            return _result(
                req_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            )
        except Exception as exc:  # noqa: BLE001 - reported to the agent, never a 500
            return _result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"{name} failed: {str(exc)[:200]}"}],
                    "isError": True,
                },
            )
        return _result(
            req_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}
                ],
                "structuredContent": data,
                "isError": False,
            },
        )
    return _error(req_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    if isinstance(body, list):  # a batch
        out = [r for r in (handle(m) for m in body) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    res = handle(body)
    return JSONResponse(res) if res is not None else Response(status_code=202)


@router.get("/mcp")
def mcp_get() -> Response:
    """No server-initiated stream: this server only answers requests (stateless)."""
    return JSONResponse(
        {
            "name": "KYC 1 CLICK MCP server",
            "transport": "streamable HTTP, POST JSON-RPC 2.0 to this URL",
            "tools": [t["name"] for t in TOOLS],
        },
        status_code=405,
        headers={"Allow": "POST"},
    )
