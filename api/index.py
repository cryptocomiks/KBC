"""Vercel serverless entry point: exposes the FastAPI app of ./backend.

Every request to /api/* is rewritten to this function (see vercel.json);
FastAPI then routes on the original path. If the application fails to
import (missing dependency, bad configuration...), a minimal fallback app
returns the error on every route instead of an opaque HTTP 500.

Note: Vercel detects the entrypoint statically, so `app` must be assigned
at module level (not only inside a try/except block).
"""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def _startup_error_app(error: str, trace: str):
    body = json.dumps(
        {"detail": f"Backend failed to start — {error}", "trace": trace}
    ).encode()

    async def fallback(scope, receive, send):
        if scope["type"] != "http":
            return
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return fallback


try:
    from app.main import app as _app
except Exception as exc:  # noqa: BLE001 - surface any startup failure
    print(traceback.format_exc(), file=sys.stderr)
    _app = _startup_error_app(f"{type(exc).__name__}: {exc}", traceback.format_exc())

app = _app
