"""SQLite cache for raw API responses and computed investigations.

Personal data is only kept here (never in another store) and can be wiped
from the UI with the "Clear cache" button (DELETE /api/cache).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app.settings import get_settings

log = logging.getLogger(__name__)


class Cache:
    def __init__(self, path: str, ttl_hours: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_hours * 3600
        self._lock = threading.Lock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " key TEXT PRIMARY KEY, namespace TEXT NOT NULL,"
            " value TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, namespace: str, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value, created_at FROM cache WHERE key = ?", (f"{namespace}:{key}",)
            ).fetchone()
        if row is None:
            return None
        value, created_at = row
        if time.time() - created_at > self.ttl_seconds:
            return None
        return json.loads(value)

    def set(self, namespace: str, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, namespace, value, created_at)"
                " VALUES (?, ?, ?, ?)",
                (f"{namespace}:{key}", namespace, json.dumps(value, default=str), time.time()),
            )
            self._conn.commit()

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT namespace, COUNT(*) FROM cache GROUP BY namespace"
            ).fetchall()
        return {ns: n for ns, n in rows}

    def clear(self) -> int:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            self._conn.execute("DELETE FROM cache")
            self._conn.commit()
            self._conn.execute("VACUUM")
        return n


_cache: Cache | None = None


def get_cache() -> Cache:
    """Open the cache, falling back to /tmp then to memory on read-only hosts."""
    global _cache
    if _cache is None:
        s = get_settings()
        for path in (s.cache_path, "/tmp/kbc_cache.db", ":memory:"):
            try:
                _cache = Cache(path, s.cache_ttl_hours)
                break
            except (OSError, sqlite3.Error) as exc:
                log.warning("Cache unavailable at %s (%s), trying next location", path, exc)
    return _cache


def set_cache(cache: Cache) -> None:
    """Used by tests to inject an in-memory cache."""
    global _cache
    _cache = cache
