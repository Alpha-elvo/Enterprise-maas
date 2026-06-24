"""
agents/base_agent.py — Abstract Base Agent
===========================================
All 8 agents extend this class. Provides:
  - Standardised execute() interface
  - Automatic timing and token tracking
  - Audit trail integration
  - Error isolation (agent failures never crash the orchestrator)
"""

import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from core.logger import get_logger, AuditLogger
from core.models import AgentStatus, AgentTrace
from services.groq_client import get_client, GroqClient

log = get_logger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for all multi-agent pipeline agents.

    Subclasses must define:
      NAME           — Human-readable agent name
      VERSION        — Semantic version string
      SYSTEM_PROMPT  — The LLM instruction persona (str)
      execute()      — Core logic, returns a typed dataclass result
    """

    NAME:           str = "Base Agent"
    VERSION:        str = "1.0.0"
    SYSTEM_PROMPT:  str = ""

    def __init__(
        self,
        client: Optional[GroqClient] = None,
        run_id: str = "",
    ) -> None:
        self._client  = client or get_client()
        self._run_id  = run_id
        self._log     = get_logger(f"agents.{self.NAME.replace(' ', '_').lower()}")

    # ── Public Interface (called by orchestrator) ─────────────────────────────

    def run(self, record_id: str, domain: str, user_message: str, **kwargs: Any) -> Any:
        """
        Wraps execute() with timing, audit logging, and error isolation.
        Always returns a result — never propagates exceptions upstream.
        """
        t_start = time.monotonic()
        trace   = AgentTrace(
            run_id      = self._run_id,
            record_id   = record_id,
            agent_name  = self.NAME,
            agent_version = self.VERSION,
        )

        self._log.info(
            f"Starting",
            extra={"record_id": record_id, "domain": domain},
        )

        try:
            result = self.execute(
                record_id    = record_id,
                domain       = domain,
                user_message = user_message,
                **kwargs,
            )
            trace.status     = AgentStatus.SUCCESS
            trace.execution_ms = int((time.monotonic() - t_start) * 1000)

            AuditLogger.log(
                event_type = f"AGENT_SUCCESS:{self.NAME}",
                event_data = {
                    "execution_ms": trace.execution_ms,
                    "version":      self.VERSION,
                },
                severity   = "INFO",
                run_id     = self._run_id,
                record_id  = record_id,
                agent_name = self.NAME,
            )
            return result

        except Exception as exc:
            trace.status      = AgentStatus.FAILED
            trace.error_detail = str(exc)
            trace.execution_ms = int((time.monotonic() - t_start) * 1000)

            self._log.error(
                f"Agent failed: {exc}",
                exc_info=True,
                extra={"record_id": record_id},
            )
            AuditLogger.log(
                event_type = f"AGENT_FAILURE:{self.NAME}",
                event_data = {"error": str(exc)},
                severity   = "ERROR",
                run_id     = self._run_id,
                record_id  = record_id,
                agent_name = self.NAME,
            )
            return self._error_result(record_id, domain, str(exc))

    # ── Abstract Methods ──────────────────────────────────────────────────────

    @abstractmethod
    def execute(
        self,
        record_id:    str,
        domain:       str,
        user_message: str,
        **kwargs:     Any,
    ) -> Any:
        """Core agent logic. Must return a typed dataclass from core.models."""
        ...

    @abstractmethod
    def _error_result(self, record_id: str, domain: str, error: str) -> Any:
        """Return a failed-state dataclass when execute() raises."""
        ...

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _call_api(
        self,
        user_message: str,
        record_id:    str = "",
        use_cache:    bool = True,
    ) -> tuple[bool, dict]:
        """Convenience wrapper for chat_and_parse with agent identity."""
        return self._client.chat_and_parse(
            system_prompt = self.SYSTEM_PROMPT,
            user_message  = user_message,
            agent_name    = self.NAME,
            run_id        = self._run_id,
            record_id     = record_id,
            use_cache     = use_cache,
        )

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id
