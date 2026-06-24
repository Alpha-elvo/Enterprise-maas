"""
storage/workflow_db.py — Workflow Persistence Layer
====================================================
Additive SQLite tables (workflow_records, workflow_history).
Shares the same database file as the main and auth layers.
Schema is idempotent — safe to run multiple times.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import config
from core.logger import get_logger
from workflows.models import (
    WorkflowHistoryEntry,
    WorkflowRecord,
    WorkflowStatus,
)

log = get_logger(__name__)

DB_PATH = config.STORAGE_DIR / "enterprise_maas.db"


class WorkflowDatabase:

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS workflow_records (
                    workflow_id  TEXT PRIMARY KEY,
                    run_id       TEXT NOT NULL DEFAULT '',
                    record_id    TEXT NOT NULL DEFAULT '',
                    tenant_id    TEXT NOT NULL DEFAULT 'default',
                    title        TEXT NOT NULL DEFAULT '',
                    description  TEXT DEFAULT '',
                    priority     TEXT DEFAULT 'MEDIUM',
                    status       TEXT NOT NULL DEFAULT 'DRAFT',
                    created_by   TEXT DEFAULT '',
                    assigned_to  TEXT DEFAULT '',
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL,
                    resolved_at  TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_wf_tenant_status
                    ON workflow_records(tenant_id, status);
                CREATE INDEX IF NOT EXISTS idx_wf_record
                    ON workflow_records(record_id);

                CREATE TABLE IF NOT EXISTS workflow_history (
                    entry_id     TEXT PRIMARY KEY,
                    workflow_id  TEXT NOT NULL,
                    action       TEXT NOT NULL,
                    from_status  TEXT NOT NULL,
                    to_status    TEXT NOT NULL,
                    actor_id     TEXT DEFAULT '',
                    actor_name   TEXT DEFAULT '',
                    comment      TEXT DEFAULT '',
                    timestamp    TEXT NOT NULL,
                    FOREIGN KEY (workflow_id)
                        REFERENCES workflow_records(workflow_id)
                );
                CREATE INDEX IF NOT EXISTS idx_wf_history_wf_id
                    ON workflow_history(workflow_id);
            """)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create(self, wf: WorkflowRecord) -> WorkflowRecord:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO workflow_records
                    (workflow_id, run_id, record_id, tenant_id, title,
                     description, priority, status, created_by, assigned_to,
                     created_at, updated_at, resolved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    wf.workflow_id, wf.run_id, wf.record_id, wf.tenant_id,
                    wf.title, wf.description, wf.priority, wf.status,
                    wf.created_by, wf.assigned_to,
                    wf.created_at, wf.updated_at, wf.resolved_at,
                ),
            )
        return wf

    def get(self, workflow_id: str) -> Optional[WorkflowRecord]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM workflow_records WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()
            if not row:
                return None
            wf = self._row_to_wf(row)
            wf.history = self._load_history(conn, workflow_id)
        return wf

    def update(self, wf: WorkflowRecord, new_entry: WorkflowHistoryEntry) -> None:
        """Update status and append a history entry atomically."""
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE workflow_records
                SET status=?, updated_at=?, resolved_at=?, assigned_to=?
                WHERE workflow_id=?
                """,
                (wf.status, wf.updated_at, wf.resolved_at,
                 wf.assigned_to, wf.workflow_id),
            )
            conn.execute(
                """
                INSERT INTO workflow_history
                    (entry_id, workflow_id, action, from_status, to_status,
                     actor_id, actor_name, comment, timestamp)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_entry.entry_id, new_entry.workflow_id,
                    new_entry.action, new_entry.from_status, new_entry.to_status,
                    new_entry.actor_id, new_entry.actor_name,
                    new_entry.comment, new_entry.timestamp,
                ),
            )

    def delete(self, workflow_id: str) -> bool:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM workflow_history WHERE workflow_id=?", (workflow_id,)
            )
            cur = conn.execute(
                "DELETE FROM workflow_records WHERE workflow_id=?", (workflow_id,)
            )
        return cur.rowcount > 0

    def list_by_tenant(
        self,
        tenant_id: str,
        status:    Optional[WorkflowStatus] = None,
        limit:     int = 50,
    ) -> list[WorkflowRecord]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM workflow_records "
                    "WHERE tenant_id=? AND status=? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (tenant_id, status.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM workflow_records "
                    "WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ?",
                    (tenant_id, limit),
                ).fetchall()
            result = []
            for row in rows:
                wf = self._row_to_wf(row)
                wf.history = self._load_history(conn, wf.workflow_id)
                result.append(wf)
        return result

    def count_by_status(self, tenant_id: str) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM workflow_records "
                "WHERE tenant_id=? GROUP BY status",
                (tenant_id,),
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_wf(row: sqlite3.Row) -> WorkflowRecord:
        return WorkflowRecord(
            workflow_id = row["workflow_id"],
            run_id      = row["run_id"],
            record_id   = row["record_id"],
            tenant_id   = row["tenant_id"],
            title       = row["title"],
            description = row["description"] or "",
            priority    = row["priority"],
            status      = row["status"],
            created_by  = row["created_by"] or "",
            assigned_to = row["assigned_to"] or "",
            created_at  = row["created_at"],
            updated_at  = row["updated_at"],
            resolved_at = row["resolved_at"],
            history     = [],
        )

    @staticmethod
    def _load_history(
        conn: sqlite3.Connection, workflow_id: str
    ) -> list[WorkflowHistoryEntry]:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM workflow_history WHERE workflow_id=? ORDER BY timestamp",
            (workflow_id,),
        ).fetchall()
        return [
            WorkflowHistoryEntry(
                entry_id    = r["entry_id"],
                workflow_id = r["workflow_id"],
                action      = r["action"],
                from_status = r["from_status"],
                to_status   = r["to_status"],
                actor_id    = r["actor_id"] or "",
                actor_name  = r["actor_name"] or "",
                comment     = r["comment"] or "",
                timestamp   = r["timestamp"],
            )
            for r in rows
        ]

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
