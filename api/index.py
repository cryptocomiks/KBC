"""Vercel serverless entry point: exposes the FastAPI app of ./backend.

Every request to /api/* is rewritten to this function (see vercel.json);
FastAPI then routes on the original path. If the application fails to
import (missing dependency, bad configuration...), a minimal fallback app
returns the error on every route instead of an opaque HTTP 500.
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

try:
    from app.main import app
except Exception as exc:  # noqa: BLE001 - surface any startup failure
    _error = f"{type(exc).__name__}: {exc}"
    _trace = traceback.format_exc()
    print(_trace, file=sys.stderr)

    async def app(scope, receive, send):  # type: ignore[no-redef]
        import json

        if scope["type"] != "http":
            return
        body = json.dumps({"detail": f"Backend failed to start — {_error}", "trace": _trace}).encode()
        await send({"type": "http.response.start", "status": 500,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})
