"""FastAPI application entry point.

Local:   uvicorn app.main:app --reload   (from ./backend)
Vercel:  api/index.py imports `app` from here.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.cases_routes import monitor_router
from app.api.cases_routes import router as cases_router
from app.api.routes import router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kbc")

app = FastAPI(
    title="KBC — Corporate Mapping API",
    version=__version__,
    description="Corporate mapping, ownership analysis and AML/KYC red flags from public sources.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(cases_router, prefix="/api")
app.include_router(monitor_router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Return a readable error (shown in the UI) instead of a bare HTTP 500."""
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})
