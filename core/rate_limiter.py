"""
core/rate_limiter.py — Reliability Infrastructure
===================================================
Implements three complementary reliability patterns:

  1. Token Bucket Rate Limiter  — caps requests per second
  2. Exponential Backoff        — retries with increasing delays
  3. Circuit Breaker            — stops hammering a failing service

All three are composable: the Groq client uses them in sequence.
"""

import time
import threading
from enum import Enum
from typing import Callable, Any, Optional
from core.logger import get_logger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 1. TOKEN BUCKET RATE LIMITER
# ══════════════════════════════════════════════════════════════════════════════

class TokenBucketRateLimiter:
    """
    Classic token bucket implementation.
    Tokens replenish at a fixed rate; each request consumes one token.
    Thread-safe via threading.Lock.
    """

    def __init__(self, rate: float = 1.0, capacity: float = 5.0) -> None:
        """
        Args:
            rate:     Tokens added per second.
            capacity: Maximum tokens the bucket can hold.
        """
        self._rate     = rate
        self._capacity = capacity
        self._tokens   = capacity
        self._last_ts  = time.monotonic()
        self._lock     = threading.Lock()

    def acquire(self, timeout: float = 60.0) -> bool:
        """
        Block until a token is available or timeout expires.
        Returns True if acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            time.sleep(0.05)
        return False

    def _refill(self) -> None:
        now    = time.monotonic()
        delta  = now - self._last_ts
        self._tokens = min(self._capacity, self._tokens + delta * self._rate)
        self._last_ts = now


# ══════════════════════════════════════════════════════════════════════════════
# 2. EXPONENTIAL BACKOFF
# ══════════════════════════════════════════════════════════════════════════════

class RetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""
    pass


def with_exponential_backoff(
    func: Callable,
    max_retries: int       = 3,
    base_delay: float      = 2.0,
    max_delay: float       = 30.0,
    backoff_factor: float  = 2.0,
    retryable_codes: set   = frozenset({429, 500, 502, 503, 504}),
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Execute `func` with exponential backoff on retryable HTTP errors.

    Delay sequence (base=2, factor=2): 2s → 4s → 8s → 16s … capped at max_delay.

    Args:
        func:            Callable to execute. Must raise HTTPError or return (bool, str).
        max_retries:     Maximum number of attempts (first attempt + retries).
        base_delay:      Initial wait in seconds.
        max_delay:       Maximum wait cap in seconds.
        backoff_factor:  Multiplier applied after each failure.
        retryable_codes: HTTP status codes that trigger a retry.

    Returns:
        The return value of func() on success.

    Raises:
        RetryExhausted: When all retries are spent.
    """
    delay   = base_delay
    attempt = 0

    while attempt <= max_retries:
        try:
            result = func(*args, **kwargs)
            # If the function returns a (success, content) tuple:
            if isinstance(result, tuple) and len(result) == 2:
                success, content = result
                if success:
                    return result
                # Check if the error content contains a retryable HTTP code
                if not any(str(code) in str(content) for code in retryable_codes):
                    return result  # Non-retryable failure — return immediately
            else:
                return result

        except Exception as exc:
            log.warning(
                "Attempt failed",
                extra={
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "error": str(exc),
                    "next_delay_s": delay,
                },
            )

        attempt += 1
        if attempt > max_retries:
            raise RetryExhausted(
                f"All {max_retries + 1} attempts exhausted. Last delay was {delay:.1f}s."
            )

        log.info(
            f"Retry {attempt}/{max_retries} — waiting {delay:.1f}s",
            extra={"attempt": attempt, "delay": delay},
        )
        time.sleep(delay)
        delay = min(delay * backoff_factor, max_delay)

    raise RetryExhausted("Retry loop exited unexpectedly.")


# ══════════════════════════════════════════════════════════════════════════════
# 3. CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════════

class CircuitState(str, Enum):
    CLOSED    = "CLOSED"     # Normal — requests pass through
    OPEN      = "OPEN"       # Tripped — requests are blocked
    HALF_OPEN = "HALF_OPEN"  # Probing — one request allowed to test recovery


class CircuitBreaker:
    """
    Circuit breaker pattern for the Groq API client.

    State transitions:
      CLOSED  → OPEN      : After failure_threshold consecutive failures
      OPEN    → HALF_OPEN : After recovery_timeout seconds
      HALF_OPEN → CLOSED  : On successful probe request
      HALF_OPEN → OPEN    : On failed probe request
    """

    def __init__(
        self,
        name:               str   = "groq_api",
        failure_threshold:  int   = 5,
        recovery_timeout:   float = 60.0,
    ) -> None:
        self.name               = name
        self.failure_threshold  = failure_threshold
        self.recovery_timeout   = recovery_timeout

        self._state             = CircuitState.CLOSED
        self._failure_count     = 0
        self._last_failure_time: Optional[float] = None
        self._lock              = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if (
                    self._last_failure_time is not None
                    and (time.monotonic() - self._last_failure_time) >= self.recovery_timeout
                ):
                    self._state = CircuitState.HALF_OPEN
                    log.info(
                        f"Circuit '{self.name}': OPEN → HALF_OPEN (probe allowed)"
                    )
            return self._state

    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    def record_success(self) -> None:
        with self._lock:
            if self._state in (CircuitState.HALF_OPEN, CircuitState.CLOSED):
                if self._failure_count > 0:
                    log.info(
                        f"Circuit '{self.name}': recovery confirmed → CLOSED",
                        extra={"failures_cleared": self._failure_count},
                    )
                self._failure_count = 0
                self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                log.error(
                    f"Circuit '{self.name}': TRIPPED → OPEN after "
                    f"{self._failure_count} consecutive failures. "
                    f"Will retry in {self.recovery_timeout}s."
                )

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "name":            self.name,
                "state":           self._state.value,
                "failure_count":   self._failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
            }

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute func through the circuit breaker.
        Raises RuntimeError if the circuit is OPEN.
        """
        current_state = self.state
        if current_state == CircuitState.OPEN:
            raise RuntimeError(
                f"Circuit '{self.name}' is OPEN. "
                f"Service unavailable. Retry after {self.recovery_timeout}s."
            )

        try:
            result = func(*args, **kwargs)
            # Determine success for (bool, str) tuples returned by groq_client
            if isinstance(result, tuple) and len(result) == 2:
                success, _ = result
                if success:
                    self.record_success()
                else:
                    self.record_failure()
            else:
                self.record_success()
            return result
        except Exception as exc:
            self.record_failure()
            raise exc


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singletons shared across the application
# ══════════════════════════════════════════════════════════════════════════════

# One request per second sustained, burst up to 5
groq_rate_limiter = TokenBucketRateLimiter(rate=1.0, capacity=5.0)

# Circuit breaker for the Groq API endpoint
groq_circuit_breaker = CircuitBreaker(
    name="groq_api",
    failure_threshold=5,
    recovery_timeout=60.0,
)
