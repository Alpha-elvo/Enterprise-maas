"""
storage/database.py — Persistence Layer
=========================================
SQLite-backed repository (swap DATABASE_URL to postgresql:// for production).
Schema mirrors what PostgreSQL would use — SQLAlchemy handles dialect differences.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import config
from core.logger import get_logger

log = get_logger(__name__)

# For Termux compatibility we use raw sqlite3 (no SQLAlchemy dependency).
# To use PostgreSQL: replace sqlite3 with psycopg2 and update connection string.
DB_PATH = config.STORAGE_DIR / "enterprise_maas.db"


class Database:
    """
    Lightweight repository wrapping SQLite.
    All public methods are idempotent — safe to call multiple times.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create tables if they don't exist (idempotent)."""
        with self._connect() as conn:
            conn.executescript("""
                -- ── Users (multi-tenancy) ────────────────────────────────────
                CREATE TABLE IF NOT EXISTS users (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    username    TEXT    UNIQUE NOT NULL,
                    email       TEXT,
                    password_hash TEXT,
                    role        TEXT    DEFAULT 'analyst',
                    tenant_id   TEXT    DEFAULT 'default',
                    is_active   INTEGER DEFAULT 1,
                    created_at  TEXT    DEFAULT (datetime('now'))
                );

                -- ── Orchestrator Runs ─────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS orchestrator_runs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id          TEXT    UNIQUE NOT NULL,
                    tenant_id       TEXT    DEFAULT 'default',
                    status          TEXT    DEFAULT 'running',
                    total_records   INTEGER DEFAULT 0,
                    escalated       INTEGER DEFAULT 0,
                    errors          INTEGER DEFAULT 0,
                    total_tokens    INTEGER DEFAULT 0,
                    elapsed_ms      INTEGER DEFAULT 0,
                    summary_json    TEXT,
                    started_at      TEXT    DEFAULT (datetime('now')),
                    completed_at    TEXT
                );

                -- ── Domain Records ────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS records (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id          TEXT    NOT NULL,
                    record_id       TEXT    NOT NULL,
                    domain          TEXT,
                    routing_decision TEXT,
                    impact_score    INTEGER DEFAULT 0,
                    urgency         TEXT,
                    overall_risk    TEXT,
                    validation_status TEXT,
                    confidence      REAL    DEFAULT 0,
                    result_json     TEXT,
                    created_at      TEXT    DEFAULT (datetime('now')),
                    FOREIGN KEY (run_id) REFERENCES orchestrator_runs(run_id)
                );

                -- ── Agent Executions ──────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS agent_executions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id          TEXT,
                    record_id       TEXT,
                    agent_name      TEXT,
                    agent_version   TEXT    DEFAULT '1.0.0',
                    status          TEXT,
                    execution_ms    INTEGER DEFAULT 0,
                    error_detail    TEXT,
                    output_json     TEXT,
                    created_at      TEXT    DEFAULT (datetime('now'))
                );

                -- ── Audit Logs ────────────────────────────────────────────────
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT,
                    record_id   TEXT,
                    agent_name  TEXT,
                    event_type  TEXT,
                    severity    TEXT    DEFAULT 'INFO',
                    event_json  TEXT,
                    timestamp   TEXT    DEFAULT (datetime('now'))
                );

                -- ── Indexes ───────────────────────────────────────────────────
                CREATE INDEX IF NOT EXISTS idx_records_run_id ON records(run_id);
                CREATE INDEX IF NOT EXISTS idx_runs_tenant ON orchestrator_runs(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_logs(run_id);
            """)
        log.info("Database schema initialised", extra={"db": str(self._path)})

    # ── Run Operations ────────────────────────────────────────────────────────

    def create_run(self, run_id: str, tenant_id: str, total_records: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO orchestrator_runs
                    (run_id, tenant_id, total_records, status, started_at)
                VALUES (?, ?, ?, 'running', ?)
                """,
                (run_id, tenant_id, total_records, _now()),
            )

    def complete_run(self, run_id: str, summary: dict) -> None:
        escalated = summary.get("escalated_records", 0)
        errors    = summary.get("errors_encountered", 0)
        tokens    = summary.get("total_tokens_used", 0)
        elapsed   = summary.get("total_execution_ms", 0)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orchestrator_runs
                SET status='completed', escalated=?, errors=?,
                    total_tokens=?, elapsed_ms=?,
                    summary_json=?, completed_at=?
                WHERE run_id=?
                """,
                (
                    escalated, errors, tokens, elapsed,
                    json.dumps(summary), _now(), run_id,
                ),
            )

    def get_runs(self, tenant_id: str = "default", limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM orchestrator_runs
                WHERE tenant_id=?
                ORDER BY started_at DESC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orchestrator_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    # ── Record Operations ─────────────────────────────────────────────────────

    def save_record_result(self, run_id: str, result: Any) -> None:
        triage = result.triage
        risk   = result.risk
        evidence = result.evidence

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO records
                    (run_id, record_id, domain, routing_decision,
                     impact_score, urgency, overall_risk, validation_status,
                     confidence, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    result.record_id,
                    result.domain,
                    result.routing_decision,
                    triage.impact_score   if triage   else 0,
                    triage.urgency        if triage   else "",
                    risk.overall_risk_level if risk   else "",
                    evidence.validation_status if evidence else "",
                    (triage.explainability.confidence_score
                     if triage and triage.explainability else 0.0),
                    json.dumps(result.to_dict(), default=str),
                    _now(),
                ),
            )

    def get_records_for_run(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM records WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("result_json"):
                try:
                    d["result"] = json.loads(d["result_json"])
                except Exception:
                    d["result"] = {}
            results.append(d)
        return results

    # ── Analytics Queries ─────────────────────────────────────────────────────

    def get_domain_score_history(self, tenant_id: str = "default") -> list[dict]:
        """Return impact scores over time for charting."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT r.domain, r.impact_score, r.urgency, r.created_at,
                       o.run_id
                FROM records r
                JOIN orchestrator_runs o ON r.run_id = o.run_id
                WHERE o.tenant_id=?
                ORDER BY r.created_at DESC
                LIMIT 200
                """,
                (tenant_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run_statistics(self, tenant_id: str = "default") -> dict:
        """Aggregate statistics for the dashboard KPI row."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as total_runs,
                    SUM(total_records) as total_records,
                    SUM(escalated) as total_escalated,
                    SUM(errors) as total_errors,
                    SUM(total_tokens) as total_tokens,
                    AVG(elapsed_ms) as avg_elapsed_ms
                FROM orchestrator_runs
                WHERE tenant_id=? AND status='completed'
                """,
                (tenant_id,),
            ).fetchone()
        if row:
            return {
                "total_runs":       row[0] or 0,
                "total_records":    row[1] or 0,
                "total_escalated":  row[2] or 0,
                "total_errors":     row[3] or 0,
                "total_tokens":     row[4] or 0,
                "avg_elapsed_ms":   round(row[5] or 0, 1),
            }
        return {}

    def get_audit_trail(self, run_id: str = "", limit: int = 200) -> list[dict]:
        from core.logger import AuditLogger
        entries = AuditLogger.read_all()
        if run_id:
            entries = [e for e in entries if e.get("run_id") == run_id]
        return entries[-limit:]

    # ── Helpers ───────────────────────────────────────────────────────────────


    def get_records_for_run_range(
        self, tenant_id: str = "default", limit: int = 200
    ) -> list[dict]:
        """Return the most recent record rows across all runs for a tenant."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT r.* FROM records r
                JOIN orchestrator_runs o ON r.run_id = o.run_id
                WHERE o.tenant_id = ?
                ORDER BY r.created_at DESC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("result_json"):
                try:
                    import json as _json
                    d["result"] = _json.loads(d["result_json"])
                except Exception:
                    d["result"] = {}
            result.append(d)
        return result

    def _connect(self):
        conn = sqlite3.connect(str(self._path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
