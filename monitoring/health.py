"""
monitoring/health.py — Platform Health Check Aggregator
=========================================================
Provides a single health() call that probes every component and
returns a structured report with:
  • Overall status   : healthy | degraded | unhealthy
  • Per-component    : ok | degraded | error + latency
  • Recommended action when degraded

Used by:
  FastAPI /health/ready endpoint
  Docker HEALTHCHECK
  Kubernetes readinessProbe / livenessProbe
  Prometheus alert rules
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class ComponentHealth:
    name:       str
    status:     str          # "ok" | "degraded" | "error"
    latency_ms: int = 0
    detail:     str = ""
    metadata:   Dict[str, Any] = field(default_factory=dict)

    def is_ok(self) -> bool:
        return self.status == "ok"


@dataclass
class PlatformHealth:
    status:     str                        # "healthy" | "degraded" | "unhealthy"
    version:    str
    timestamp:  str
    components: List[ComponentHealth]      = field(default_factory=list)
    uptime_s:   int                        = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status":     self.status,
            "version":    self.version,
            "timestamp":  self.timestamp,
            "uptime_s":   self.uptime_s,
            "components": [
                {
                    "name":       c.name,
                    "status":     c.status,
                    "latency_ms": c.latency_ms,
                    "detail":     c.detail,
                    "metadata":   c.metadata,
                }
                for c in self.components
            ],
        }

    @property
    def is_ready(self) -> bool:
        """True if all CRITICAL components are ok."""
        return self.status in ("healthy", "degraded")


# ── Individual component probes ───────────────────────────────────────────────

def _probe(name: str, fn: Callable) -> ComponentHealth:
    """Execute a probe function and capture latency + exceptions."""
    t0 = time.monotonic()
    try:
        detail, meta = fn()
        ms     = int((time.monotonic() - t0) * 1000)
        status = "ok"
    except Exception as exc:
        ms     = int((time.monotonic() - t0) * 1000)
        detail = str(exc)[:200]
        meta   = {}
        status = "error"
    return ComponentHealth(
        name=name, status=status,
        latency_ms=ms, detail=detail, metadata=meta,
    )


def _check_database() -> tuple[str, dict]:
    from storage.database import Database
    db  = Database()
    runs = db.get_runs("default", limit=1)
    return "ok", {"run_count_sample": len(runs)}


def _check_auth_database() -> tuple[str, dict]:
    from storage.auth_db import AuthDatabase
    db    = AuthDatabase()
    stats = db.get_auth_stats("default")
    return "ok", stats


def _check_circuit_breaker() -> tuple[str, dict]:
    from core.rate_limiter import groq_circuit_breaker
    stats = groq_circuit_breaker.get_stats()
    state = stats["state"]
    if state == "OPEN":
        raise RuntimeError(f"Circuit breaker OPEN ({stats['failure_count']} failures)")
    detail = f"state={state}"
    return detail, stats


def _check_cache() -> tuple[str, dict]:
    from core.cache import get_cache
    stats = get_cache().stats()
    return f"hit_rate={stats.get('hit_rate', 0):.1%}", stats


def _check_groq_api() -> tuple[str, dict]:
    """Light connectivity check — does NOT call the LLM, just verifies config."""
    from config import config
    if not config.GROQ_API_KEY or config.GROQ_API_KEY == "your_groq_api_key_here":
        raise RuntimeError("GROQ_API_KEY not configured")
    return "api_key=configured", {"endpoint": config.GROQ_ENDPOINT}


def _check_storage_filesystem() -> tuple[str, dict]:
    from config import config
    issues = []
    for path in [config.STORAGE_DIR, config.LOGS_DIR, config.REPORTS_DIR]:
        if not path.exists():
            issues.append(f"{path} missing")
    if issues:
        raise RuntimeError("; ".join(issues))
    return "all_dirs_present", {
        "storage_dir": str(config.STORAGE_DIR),
        "logs_dir":    str(config.LOGS_DIR),
    }


def _check_workflow_database() -> tuple[str, dict]:
    from storage.workflow_db import WorkflowDatabase
    db     = WorkflowDatabase()
    counts = db.count_by_status("default")
    return "ok", {"workflow_counts": counts}


# ── Aggregator ────────────────────────────────────────────────────────────────

_BOOT_TIME = time.monotonic()

# (name, probe_fn, is_critical)
_PROBES: list[tuple[str, Callable, bool]] = [
    ("database",           _check_database,           True),
    ("auth_database",      _check_auth_database,      True),
    ("circuit_breaker",    _check_circuit_breaker,    False),
    ("cache",              _check_cache,              False),
    ("groq_api",           _check_groq_api,           True),
    ("filesystem",         _check_storage_filesystem, True),
    ("workflow_database",  _check_workflow_database,  False),
]


def health_check(include_non_critical: bool = True) -> PlatformHealth:
    """
    Run all component probes and return a PlatformHealth report.

    Args:
        include_non_critical: If False, skip non-critical probes for
                              faster liveness checks.
    """
    from config import config

    components: list[ComponentHealth] = []
    for name, fn, is_critical in _PROBES:
        if not is_critical and not include_non_critical:
            continue
        result = _probe(name, fn)
        components.append(result)

    # Determine overall status
    errors    = [c for c in components if c.status == "error"]
    degraded  = [c for c in components if c.status == "degraded"]
    critical_errors = [
        c for c in errors
        if any(c.name == n for n, _, crit in _PROBES if crit)
    ]

    if critical_errors:
        overall = "unhealthy"
    elif errors or degraded:
        overall = "degraded"
    else:
        overall = "healthy"

    return PlatformHealth(
        status     = overall,
        version    = config.APP_VERSION,
        timestamp  = datetime.now(timezone.utc).isoformat(),
        components = components,
        uptime_s   = int(time.monotonic() - _BOOT_TIME),
    )


def liveness_check() -> bool:
    """
    Fast liveness probe — only checks process is alive.
    Does NOT probe external dependencies.
    Returns True always (if we get here, the process is alive).
    """
    return True


def readiness_check() -> tuple[bool, dict]:
    """
    Readiness probe for Kubernetes/Docker.
    Returns (is_ready, health_dict).
    """
    report = health_check(include_non_critical=False)
    return report.is_ready, report.to_dict()
