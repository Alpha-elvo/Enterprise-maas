"""
services/groq_client.py — Production Groq API Client
======================================================
Enterprise-grade HTTP client for the Groq inference API.

Reliability stack (applied in order):
  1. Cache check          — avoid redundant API calls
  2. Rate limiter         — token bucket, prevents 429s
  3. Circuit breaker      — stops hammering failed endpoints
  4. Exponential backoff  — intelligent retry with jitter
  5. Timeout handling     — hard 30s deadline per request
  6. Structured errors    — typed exceptions, never bare strings
"""

import json
import re
import time
from typing import Optional

import requests

from config import config
from core.cache import get_cache, TTLCache
from core.logger import get_logger, AuditLogger
from core.rate_limiter import (
    groq_circuit_breaker,
    groq_rate_limiter,
    with_exponential_backoff,
    RetryExhausted,
)

log = get_logger(__name__)


# ── Typed Exceptions ──────────────────────────────────────────────────────────

class GroqAPIError(Exception):
    """Base exception for all Groq API failures."""
    def __init__(self, message: str, status_code: int = 0, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body        = body


class GroqAuthError(GroqAPIError):
    """HTTP 401 — Invalid or missing API key."""
    pass


class GroqRateLimitError(GroqAPIError):
    """HTTP 429 — Rate limit exceeded."""
    pass


class GroqServerError(GroqAPIError):
    """HTTP 5xx — Groq infrastructure failure."""
    pass


class GroqTimeoutError(GroqAPIError):
    """Request timed out."""
    pass


class GroqConnectionError(GroqAPIError):
    """Network-level connection failure."""
    pass


class CircuitOpenError(GroqAPIError):
    """Circuit breaker is OPEN — service requests suspended."""
    pass


# ── JSON Recovery ─────────────────────────────────────────────────────────────

def safe_json_parse(raw_text: str) -> dict:
    """
    Multi-strategy JSON parser. Never raises — always returns a dict.

    Strategy order:
      1. Direct json.loads()
      2. Strip markdown fences (```json ... ```)
      3. String-slice: extract first { ... last }
      4. Graceful error dict with raw preview
    """
    # 1. Direct parse
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Strip markdown fences
    stripped = re.sub(r"```(?:json)?", "", raw_text, flags=re.IGNORECASE).strip()
    stripped = stripped.replace("```", "").strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # 3. Brace-slice extraction
    brace_open  = raw_text.find("{")
    brace_close = raw_text.rfind("}")
    if brace_open != -1 and brace_close > brace_open:
        candidate = raw_text[brace_open : brace_close + 1]
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            pass

    # 4. Failure record
    return {
        "parse_error":  True,
        "raw_preview":  raw_text[:400],
        "message":      "All JSON recovery strategies exhausted.",
    }


# ── Core Client ───────────────────────────────────────────────────────────────

class GroqClient:
    """
    Stateless Groq API client. Instantiate once (or use module singleton).
    All methods are thread-safe.
    """

    def __init__(
        self,
        api_key:  Optional[str] = None,
        model_id: Optional[str] = None,
        cache:    Optional[TTLCache] = None,
    ) -> None:
        self._api_key  = api_key  or config.GROQ_API_KEY
        self._model_id = model_id or config.MODEL_ID
        self._cache    = cache    or get_cache(
            max_size=config.CACHE_MAX_SIZE,
            ttl=config.CACHE_TTL,
        )
        self._session  = requests.Session()
        self._session.headers.update(self._build_headers())

    # ── Public API ────────────────────────────────────────────────────────────

    def chat(
        self,
        system_prompt: str,
        user_message:  str,
        agent_name:    str   = "unknown",
        run_id:        str   = "",
        record_id:     str   = "",
        use_cache:     bool  = True,
        temperature:   Optional[float] = None,
        max_tokens:    Optional[int]   = None,
    ) -> tuple[bool, str]:
        """
        Execute a single-turn chat completion.

        Returns:
            (True,  "<LLM response string>") on success
            (False, "<error description>")   on failure
        """
        t_start = time.monotonic()
        cache_key = TTLCache.make_key(agent_name, system_prompt, user_message)

        # ── Cache check ───────────────────────────────────────────────────────
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                log.info(
                    "Cache hit — skipping API call",
                    extra={"agent": agent_name, "record_id": record_id},
                )
                return (True, cached)

        # ── Circuit breaker gate ───────────────────────────────────────────────
        if groq_circuit_breaker.is_open():
            msg = (
                "Circuit breaker OPEN — Groq API requests suspended. "
                f"Retry after {config.CB_RECOVERY_TIMEOUT}s."
            )
            log.error(msg, extra={"agent": agent_name})
            AuditLogger.log(
                event_type="CIRCUIT_OPEN",
                event_data={"agent": agent_name},
                severity="ERROR",
                run_id=run_id,
                record_id=record_id,
                agent_name=agent_name,
            )
            return (False, msg)

        # ── Rate limiter gate ─────────────────────────────────────────────────
        log.debug(
            f"Rate limiter: waiting up to {config.RATE_LIMIT_SLEEP}s",
            extra={"agent": agent_name},
        )
        time.sleep(config.RATE_LIMIT_SLEEP)
        acquired = groq_rate_limiter.acquire(timeout=30.0)
        if not acquired:
            return (False, "Rate limiter timeout — could not acquire token in 30s.")

        # ── Execute with exponential backoff ──────────────────────────────────
        payload = {
            "model":       self._model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "temperature": temperature or config.TEMPERATURE,
            "max_tokens":  max_tokens  or config.MAX_TOKENS,
        }

        try:
            result = with_exponential_backoff(
                self._raw_post,
                max_retries    = config.MAX_RETRIES,
                base_delay     = 2.0,
                max_delay      = 30.0,
                backoff_factor = 2.0,
                payload        = payload,
                agent_name     = agent_name,
            )
        except RetryExhausted as exc:
            groq_circuit_breaker.record_failure()
            msg = f"All retries exhausted for agent '{agent_name}': {exc}"
            log.error(msg, extra={"agent": agent_name, "record_id": record_id})
            return (False, msg)
        except RuntimeError as exc:
            return (False, str(exc))

        success, content = result
        elapsed_ms = int((time.monotonic() - t_start) * 1000)

        if success:
            # Warm the cache
            if use_cache:
                self._cache.set(cache_key, content)

            groq_circuit_breaker.record_success()
            log.info(
                "API call succeeded",
                extra={
                    "agent":        agent_name,
                    "record_id":    record_id,
                    "elapsed_ms":   elapsed_ms,
                    "response_len": len(content),
                },
            )
            AuditLogger.log(
                event_type="API_CALL_SUCCESS",
                event_data={"elapsed_ms": elapsed_ms, "response_len": len(content)},
                severity="INFO",
                run_id=run_id,
                record_id=record_id,
                agent_name=agent_name,
            )
        else:
            groq_circuit_breaker.record_failure()
            AuditLogger.log(
                event_type="API_CALL_FAILURE",
                event_data={"error": content[:200]},
                severity="ERROR",
                run_id=run_id,
                record_id=record_id,
                agent_name=agent_name,
            )

        return success, content

    def chat_and_parse(
        self,
        system_prompt: str,
        user_message:  str,
        agent_name:    str  = "unknown",
        run_id:        str  = "",
        record_id:     str  = "",
        use_cache:     bool = True,
    ) -> tuple[bool, dict]:
        """
        chat() → safe_json_parse().
        Returns (True, dict) on success, (False, error_dict) on failure.
        """
        success, content = self.chat(
            system_prompt=system_prompt,
            user_message=user_message,
            agent_name=agent_name,
            run_id=run_id,
            record_id=record_id,
            use_cache=use_cache,
        )

        if not success:
            return (False, {"error_type": "API_CALL_FAILED", "error_detail": content})

        parsed = safe_json_parse(content)

        if "parse_error" in parsed:
            log.warning(
                "JSON parse failed after successful API call",
                extra={
                    "agent":       agent_name,
                    "record_id":   record_id,
                    "raw_preview": content[:200],
                },
            )
            parsed["error_type"] = "JSON_PARSE_FAILED"
            return (False, parsed)

        return (True, parsed)

    # ── Private ───────────────────────────────────────────────────────────────

    def _raw_post(self, payload: dict, agent_name: str) -> tuple[bool, str]:
        """
        Single HTTP POST attempt. Returns (success, content).
        Raises no exceptions — translates all HTTP/network errors to (False, str).
        """
        try:
            response = self._session.post(
                config.GROQ_ENDPOINT,
                json=payload,
                timeout=config.REQUEST_TIMEOUT,
            )
        except requests.exceptions.ConnectionError as exc:
            return (
                False,
                f"CONNECTION_ERROR — Cannot reach Groq API. "
                f"Check network in Termux. Detail: {exc}",
            )
        except requests.exceptions.Timeout:
            return (
                False,
                f"TIMEOUT_ERROR — Request exceeded {config.REQUEST_TIMEOUT}s.",
            )

        if not response.ok:
            try:
                body = response.json()
            except Exception:
                body = response.text[:400]

            error_msg = (
                f"HTTP {response.status_code} from Groq API. "
                f"Agent: '{agent_name}'. Body: {body}"
            )
            log.error(error_msg, extra={"status_code": response.status_code})
            return (False, error_msg)

        try:
            data    = response.json()
            content = data["choices"][0]["message"]["content"]
            return (True, content)
        except (KeyError, IndexError) as exc:
            return (
                False,
                f"RESPONSE_STRUCTURE_ERROR — Unexpected shape: {exc}",
            )

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }

    def health_check(self) -> dict:
        """Ping the API with a minimal request. Returns status dict."""
        success, content = self.chat(
            system_prompt="Respond with exactly: OK",
            user_message="Health check",
            agent_name="health_check",
            use_cache=False,
        )
        return {
            "status":   "healthy" if success else "unhealthy",
            "response": content[:50] if success else content[:200],
            "circuit":  groq_circuit_breaker.get_stats(),
            "cache":    self._cache.stats(),
        }


# ── Module Singleton ──────────────────────────────────────────────────────────

_client: Optional[GroqClient] = None


def get_client() -> GroqClient:
    """Return the module-level GroqClient singleton."""
    global _client
    if _client is None:
        _client = GroqClient()
    return _client
