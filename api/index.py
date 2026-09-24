"""Vercel serverless entry point: exposes the FastAPI app of ./backend.

Every request to /api/* is rewritten to this function (see vercel.json);
FastAPI then routes on the original path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app  # noqa: E402,F401
