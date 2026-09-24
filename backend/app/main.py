"""FastAPI application entry point.

Local:   uvicorn app.main:app --reload   (from ./backend)
Vercel:  api/index.py imports `app` from here.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router

logging.basicConfig(level=logging.INFO)

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
