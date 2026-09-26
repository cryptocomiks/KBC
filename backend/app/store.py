"""Durable storage for cases, analyst decisions and monitoring history.

Postgres when DATABASE_URL / POSTGRES_URL is set (Vercel Postgres / Neon),
SQLite otherwise (local runs and Docker). Unlike the cache, this store holds
the analyst's work and is not wiped by "Clear cache".
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.settings import get_settings

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS cases (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        subject_name TEXT NOT NULL,
        subject_type TEXT NOT NULL,
        record_ids TEXT NOT NULL,
        depth INTEGER NOT NULL,
        max_nodes INTEGER NOT NULL,
        demo INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'open',
        monitor INTEGER NOT NULL DEFAULT 1,
        notes TEXT NOT NULL DEFAULT '',
        risk_score REAL,
        risk_level TEXT,
        countries TEXT NOT NULL DEFAULT '[]',
        snapshot TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_run_at TEXT,
        questionnaire TEXT NOT NULL DEFAULT '{}',
        import_state TEXT NOT NULL DEFAULT '',
        import_info TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS decisions (
        case_id TEXT NOT NULL,
        item_key TEXT NOT NULL,
        item_label TEXT NOT NULL DEFAULT '',
        decision TEXT NOT NULL,
        comment TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        decided_at TEXT NOT NULL,
        PRIMARY KEY (case_id, item_key)
    )""",
    """CREATE TABLE IF NOT EXISTS dismissals (
        item_key TEXT PRIMARY KEY,
        item_label TEXT NOT NULL DEFAULT '',
        comment TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        case_id TEXT NOT NULL DEFAULT '',
        decided_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS changes (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        run_at TEXT NOT NULL,
        kind TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT NOT NULL,
        seen INTEGER NOT NULL DEFAULT 0
    )""",
]
CASE_FIELDS = (
    "id", "title", "subject_name", "subject_type", "record_ids", "depth", "max_nodes", "demo",
    "status", "monitor", "notes", "risk_score", "risk_level", "countries", "snapshot",
    "created_at", "updated_at", "last_run_at", "questionnaire", "import_state", "import_info",
)  # fmt: skip
JSON_FIELDS = ("record_ids", "countries", "snapshot", "questionnaire", "import_info")
# Columns added after the first release: created on existing databases at start-up.
MIGRATIONS = {
    "questionnaire": "TEXT NOT NULL DEFAULT '{}'",
    "import_state": "TEXT NOT NULL DEFAULT ''",
    "import_info": "TEXT NOT NULL DEFAULT '{}'",
}
# import_state: '' = analysed case; pending (company to find) -> resolved (to investigate);
# ambiguous (several candidates: the analyst picks one) or not_found / error (to fix).
IMPORT_ACTIVE = ("pending", "resolved")


def now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Store:
    def __init__(self, url: str | None, sqlite_path: str) -> None:
        self._lock = threading.Lock()
        self.kind = "postgres" if url else "sqlite"
        if url:
            import psycopg  # only needed when a Postgres URL is configured

            self._pg_url = url
            self._conn: Any = psycopg.connect(url, autocommit=True)
        else:
            if sqlite_path != ":memory:":
                Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        for stmt in SCHEMA:
            self._exec(stmt)
        self._migrate()

    def _migrate(self) -> None:
        if self.kind == "postgres":
            for col, decl in MIGRATIONS.items():
                self._exec(f"ALTER TABLE cases ADD COLUMN IF NOT EXISTS {col} {decl}")
            return
        present = {r["name"] for r in self._exec("PRAGMA table_info(cases)")}
        for col, decl in MIGRATIONS.items():
            if col not in present:
                self._exec(f"ALTER TABLE cases ADD COLUMN {col} {decl}")

    # ------------------------------------------------------------ low level
    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.kind == "postgres" else sql

    def _exec(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            if self.kind == "postgres":
                try:
                    cur = self._conn.execute(self._sql(sql), params)
                except Exception:  # noqa: BLE001 - serverless connections get closed: reconnect once
                    import psycopg

                    self._conn = psycopg.connect(self._pg_url, autocommit=True)
                    cur = self._conn.execute(self._sql(sql), params)
                if cur.description is None:
                    return []
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return [dict(r) for r in cur.fetchall()] if cur.description else []

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        for f in JSON_FIELDS:
            if isinstance(row.get(f), str):
                row[f] = json.loads(row[f])
        for f in ("demo", "monitor"):
            if f in row:
                row[f] = bool(row[f])
        return row

    # ----------------------------------------------------------------- cases
    def create_case(self, **fields: Any) -> dict[str, Any]:
        stamp = now()
        row = {
            "id": uuid.uuid4().hex[:12],
            "status": "open",
            "monitor": 1,
            "notes": "",
            "countries": [],
            "snapshot": {},
            "created_at": stamp,
            "updated_at": stamp,
            "last_run_at": None,
            "risk_score": None,
            "risk_level": None,
            "questionnaire": {},
            "import_state": "",
            "import_info": {},
            **fields,
        }
        values = tuple(
            json.dumps(row[f])
            if f in JSON_FIELDS
            else (int(row[f]) if isinstance(row[f], bool) else row[f])
            for f in CASE_FIELDS
        )
        self._exec(
            f"INSERT INTO cases ({', '.join(CASE_FIELDS)}) VALUES ({', '.join('?' for _ in CASE_FIELDS)})",
            values,
        )
        return self.get_case(row["id"])  # type: ignore[return-value]

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM cases WHERE id = ?", (case_id,))
        return self._decode(rows[0]) if rows else None

    def list_cases(self) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM cases ORDER BY updated_at DESC")
        unseen = {
            r["case_id"]: r["n"]
            for r in self._exec(
                "SELECT case_id, COUNT(*) AS n FROM changes WHERE seen = 0 GROUP BY case_id"
            )
        }
        out = []
        for r in rows:
            r = self._decode(r)
            r.pop("snapshot", None)
            r["unseen_changes"] = int(unseen.get(r["id"], 0))
            out.append(r)
        return out

    def update_case(self, case_id: str, **fields: Any) -> dict[str, Any] | None:
        fields = {k: v for k, v in fields.items() if k in CASE_FIELDS and k != "id"}
        if fields:
            fields["updated_at"] = now()
            sets = ", ".join(f"{k} = ?" for k in fields)
            values = tuple(
                json.dumps(v) if k in JSON_FIELDS else (int(v) if isinstance(v, bool) else v)
                for k, v in fields.items()
            )
            self._exec(f"UPDATE cases SET {sets} WHERE id = ?", (*values, case_id))
        return self.get_case(case_id)

    def delete_case(self, case_id: str) -> None:
        for table, col in (("decisions", "case_id"), ("changes", "case_id"), ("cases", "id")):
            self._exec(f"DELETE FROM {table} WHERE {col} = ?", (case_id,))

    def stalest_monitored(self) -> dict[str, Any] | None:
        rows = self._exec(
            "SELECT id FROM cases WHERE monitor = 1 AND status = 'open' AND import_state = '' "
            "ORDER BY COALESCE(last_run_at, '') ASC LIMIT 1"
        )
        return self.get_case(rows[0]["id"]) if rows else None

    # ---------------------------------------------------------------- import
    def next_import(self) -> dict[str, Any] | None:
        """Oldest imported case still to process (to find, then to investigate)."""
        rows = self._exec(
            "SELECT id FROM cases WHERE import_state IN (?, ?) ORDER BY created_at ASC, id ASC LIMIT 1",
            IMPORT_ACTIVE,
        )
        return self.get_case(rows[0]["id"]) if rows else None

    def import_counts(self) -> dict[str, int]:
        return {
            (r["import_state"] or "done"): int(r["n"])
            for r in self._exec(
                "SELECT import_state, COUNT(*) AS n FROM cases GROUP BY import_state"
            )
        }

    # ------------------------------------------------------------- decisions
    def decisions(self, case_id: str) -> list[dict[str, Any]]:
        return self._exec(
            "SELECT * FROM decisions WHERE case_id = ? ORDER BY decided_at DESC", (case_id,)
        )

    def set_decision(
        self, case_id: str, item_key: str, item_label: str, decision: str, comment: str, author: str
    ) -> None:
        self._exec("DELETE FROM decisions WHERE case_id = ? AND item_key = ?", (case_id, item_key))
        if decision != "none":
            self._exec(
                "INSERT INTO decisions (case_id, item_key, item_label, decision, comment, author, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (case_id, item_key, item_label, decision, comment, author, now()),
            )
        # Memory of decisions: a hit ruled out once is ruled out everywhere (until changed).
        if decision == "false_positive":
            self.set_dismissal(item_key, item_label, comment, author, case_id)
        else:
            self.remove_dismissal(item_key)
        self.update_case(case_id)  # bump updated_at

    # ------------------------------------------------------------ dismissals
    def dismissals(self) -> dict[str, dict[str, Any]]:
        """Hits ruled out as namesakes, remembered across cases and investigations."""
        return {r["item_key"]: r for r in self._exec("SELECT * FROM dismissals")}

    def set_dismissal(
        self, item_key: str, item_label: str, comment: str, author: str, case_id: str
    ) -> None:
        self._exec("DELETE FROM dismissals WHERE item_key = ?", (item_key.lower(),))
        self._exec(
            "INSERT INTO dismissals (item_key, item_label, comment, author, case_id, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_key.lower(), item_label, comment, author, case_id, now()),
        )

    def remove_dismissal(self, item_key: str) -> None:
        self._exec("DELETE FROM dismissals WHERE item_key = ?", (item_key.lower(),))

    # --------------------------------------------------------------- changes
    def add_changes(self, case_id: str, run_at: str, changes: list[dict[str, str]]) -> None:
        for c in changes:
            self._exec(
                "INSERT INTO changes (id, case_id, run_at, kind, severity, description, seen) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    uuid.uuid4().hex[:16],
                    case_id,
                    run_at,
                    c["kind"],
                    c["severity"],
                    c["description"],
                ),
            )

    def changes(self, case_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if case_id:
            return self._exec(
                "SELECT * FROM changes WHERE case_id = ? ORDER BY run_at DESC LIMIT ?",
                (case_id, limit),
            )
        return self._exec(
            "SELECT c.*, k.title AS case_title FROM changes c JOIN cases k ON k.id = c.case_id "
            "ORDER BY c.run_at DESC LIMIT ?",
            (limit,),
        )

    def mark_seen(self, case_id: str) -> None:
        self._exec("UPDATE changes SET seen = 1 WHERE case_id = ?", (case_id,))


_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    global _store
    with _store_lock:
        if _store is None:
            s = get_settings()
            _store = Store(s.database_url or None, s.store_path)
        return _store


def reset_store() -> None:
    """Tests: forget the current store (a new one is opened on next use)."""
    global _store
    with _store_lock:
        _store = None
