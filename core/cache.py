"""
core/cache.py — In-Memory TTL Cache
=====================================
LRU cache with per-entry TTL expiry. Used to avoid redundant API calls
for identical payloads within the same session window.
Thread-safe for concurrent agent execution.
"""

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Optional
from core.logger import get_logger

log = get_logger(__name__)


class TTLCache:
    """
    Least-Recently-Used cache with Time-To-Live expiry.

    Entries are evicted when:
      1. Their TTL expires (checked on every access).
      2. The cache exceeds max_size (oldest entry removed, LRU policy).
    """

    def __init__(self, max_size: int = 100, ttl: int = 3600) -> None:
        """
        Args:
            max_size: Maximum number of entries before eviction.
            ttl:      Time-to-live in seconds for each entry.
        """
        self._store:    OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size  = max_size
        self._ttl       = ttl
        self._lock      = threading.RLock()
        self._hits      = 0
        self._misses    = 0

    # ── Public Interface ──────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        """Return cached value or None if absent/expired."""
        with self._lock:
            if key not in self._store:
                self._misses += 1
                return None

            value, expiry = self._store[key]
            if time.monotonic() > expiry:
                del self._store[key]
                self._misses += 1
                log.debug("Cache miss (expired)", extra={"key": key[:32]})
                return None

            # Move to end (most recently used)
            self._store.move_to_end(key)
            self._hits += 1
            log.debug("Cache hit", extra={"key": key[:32]})
            return value

    def set(self, key: str, value: Any) -> None:
        """Store a value with the configured TTL."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, time.monotonic() + self._ttl)

            # Evict oldest if over capacity
            while len(self._store) > self._max_size:
                evicted_key, _ = self._store.popitem(last=False)
                log.debug(
                    "Cache eviction (capacity)",
                    extra={"evicted_key": evicted_key[:32]},
                )

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if it existed."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self) -> int:
        """Clear all entries. Returns the count of entries removed."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            self._hits = 0
            self._misses = 0
            return count

    def stats(self) -> dict:
        """Return cache performance statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size":        len(self._store),
                "max_size":    self._max_size,
                "ttl_seconds": self._ttl,
                "hits":        self._hits,
                "misses":      self._misses,
                "hit_rate":    round(self._hits / total, 3) if total > 0 else 0.0,
            }

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def make_key(agent_name: str, system_prompt: str, user_message: str) -> str:
        """
        Deterministic cache key from agent identity + prompt content.
        Uses SHA-256 so long prompts don't bloat key storage.
        """
        raw = f"{agent_name}::{system_prompt[:200]}::{user_message[:500]}"
        return hashlib.sha256(raw.encode()).hexdigest()


# ── Module-Level Singleton ────────────────────────────────────────────────────

# Single cache instance shared across all agents in a run
_cache: Optional[TTLCache] = None


def get_cache(max_size: int = 100, ttl: int = 3600) -> TTLCache:
    """Return the module-level cache singleton, creating it if necessary."""
    global _cache
    if _cache is None:
        _cache = TTLCache(max_size=max_size, ttl=ttl)
        log.info(
            "Cache initialised",
            extra={"max_size": max_size, "ttl": ttl},
        )
    return _cache


def reset_cache() -> None:
    """Reset the cache (useful between test runs)."""
    global _cache
    if _cache:
        count = _cache.clear()
        log.info("Cache reset", extra={"entries_cleared": count})
    _cache = None
