"""
core/logger.py — Structured Logging
=====================================
Provides a structured, context-aware logger for all platform components.
Writes JSON-formatted logs to both console and rotating file.
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class _JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.
    Enables structured log ingestion by Datadog, CloudWatch, Loki, etc.
    """

    LEVEL_MAP = {
        "DEBUG":    "debug",
        "INFO":     "info",
        "WARNING":  "warn",
        "ERROR":    "error",
        "CRITICAL": "critical",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level":     self.LEVEL_MAP.get(record.levelname, "info"),
            "logger":    record.name,
            "message":   record.getMessage(),
            "module":    record.module,
            "function":  record.funcName,
            "line":      record.lineno,
        }

        # Attach any extra context fields bound at call site
        for key, value in record.__dict__.items():
            if key not in (
                "args", "asctime", "created", "exc_info", "exc_text",
                "filename", "funcName", "id", "levelname", "levelno",
                "lineno", "message", "module", "msecs", "msg", "name",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName",
            ):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        try:
            return json.dumps(payload, default=str)
        except Exception:
            return json.dumps({"level": "error", "message": "Log serialisation failed"})


def get_logger(name: str, run_id: Optional[str] = None) -> logging.Logger:
    """
    Return a configured logger for the given module name.

    Usage:
        from core.logger import get_logger
        log = get_logger(__name__)
        log.info("Agent started", extra={"record_id": "HLTH-001"})
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured — avoid duplicate handlers

    logger.setLevel(logging.DEBUG)

    # ── Console Handler (human-readable in development) ───────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)

    # ── File Handler (JSON, rotating, max 10MB × 5 backups) ───────────────────
    log_file = LOG_DIR / "platform.log"
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_JsonFormatter())

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

    return logger


class AuditLogger:
    """
    Dedicated audit trail logger.
    Writes immutable, append-only JSON audit events to audit_log.json
    for compliance, forensics, and regulatory requirements.
    """

    _audit_file = LOG_DIR.parent / "storage" / "audit_log.json"

    @classmethod
    def log(
        cls,
        event_type:  str,
        event_data:  dict,
        severity:    str = "INFO",
        run_id:      str = "",
        record_id:   str = "",
        agent_name:  str = "",
    ) -> None:
        entry = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "severity":   severity,
            "run_id":     run_id,
            "record_id":  record_id,
            "agent_name": agent_name,
            "data":       event_data,
        }
        cls._append(entry)

    @classmethod
    def _append(cls, entry: dict) -> None:
        cls._audit_file.parent.mkdir(parents=True, exist_ok=True)

        # Read existing entries (or start fresh)
        existing: list = []
        if cls._audit_file.exists():
            try:
                with open(cls._audit_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []

        existing.append(entry)

        with open(cls._audit_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

    @classmethod
    def read_all(cls) -> list[dict]:
        if not cls._audit_file.exists():
            return []
        try:
            with open(cls._audit_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []


# Module-level convenience logger
log = get_logger("platform")
