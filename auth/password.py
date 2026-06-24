"""
auth/password.py — Cryptographic Password Hashing
===================================================
Uses PBKDF2-HMAC-SHA256 from Python stdlib (hashlib).
No third-party dependency — bcrypt can be dropped in as an alternative
by swapping the two public functions without changing call sites.

Security properties:
  • 600,000 iterations  (NIST SP 800-132 recommendation for PBKDF2-SHA256)
  • 32-byte random salt  per password
  • 32-byte derived key
  • Constant-time comparison  (hmac.compare_digest)
  • Stored format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

Never logs, stores, or returns plaintext passwords.
"""

import hashlib
import hmac
import os
import re
from dataclasses import dataclass

# ── Configuration ─────────────────────────────────────────────────────────────
_ALGORITHM  = "sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 32
_HASH_BYTES = 32
_SEPARATOR  = "$"
_PREFIX     = "pbkdf2_sha256"

# Minimum password strength pattern (also enforced in Pydantic schema)
_STRENGTH_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]).{10,}$"
)


@dataclass(frozen=True)
class _ParsedHash:
    algorithm:  str
    iterations: int
    salt_hex:   str
    hash_hex:   str


def hash_password(plaintext: str) -> str:
    """
    Hash a plaintext password and return a storable string.

    Args:
        plaintext: The raw password string (UTF-8).

    Returns:
        Encoded string: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

    Raises:
        ValueError: If plaintext is empty.
    """
    if not plaintext:
        raise ValueError("Password must not be empty.")

    salt       = os.urandom(_SALT_BYTES)
    dk         = hashlib.pbkdf2_hmac(
        _ALGORITHM,
        plaintext.encode("utf-8"),
        salt,
        _ITERATIONS,
        _HASH_BYTES,
    )
    return _SEPARATOR.join([
        _PREFIX,
        str(_ITERATIONS),
        salt.hex(),
        dk.hex(),
    ])


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """
    Verify plaintext against a stored hash in constant time.

    Returns True on match, False on mismatch. Never raises on bad input —
    always returns False to prevent oracle attacks.

    Args:
        plaintext:   The candidate password (UTF-8).
        stored_hash: The value returned by hash_password().
    """
    if not plaintext or not stored_hash:
        return False

    try:
        parsed = _parse_hash(stored_hash)
    except (ValueError, IndexError):
        return False

    try:
        candidate = hashlib.pbkdf2_hmac(
            parsed.algorithm.split("_")[-1],   # "sha256"
            plaintext.encode("utf-8"),
            bytes.fromhex(parsed.salt_hex),
            parsed.iterations,
            _HASH_BYTES,
        )
    except Exception:
        return False

    return hmac.compare_digest(candidate.hex(), parsed.hash_hex)


def needs_rehash(stored_hash: str, target_iterations: int = _ITERATIONS) -> bool:
    """
    Return True if the stored hash was created with fewer iterations
    than the current target (indicates rehash is needed on next login).
    """
    try:
        parsed = _parse_hash(stored_hash)
        return parsed.iterations < target_iterations
    except (ValueError, IndexError):
        return True


def password_meets_policy(plaintext: str) -> tuple[bool, list[str]]:
    """
    Validate a candidate password against the platform policy.

    Returns:
        (True, [])           if the password meets policy
        (False, [reason1, …]) if it does not
    """
    reasons: list[str] = []
    if len(plaintext) < 10:
        reasons.append("Minimum 10 characters required.")
    if not any(c.isupper() for c in plaintext):
        reasons.append("At least one uppercase letter required.")
    if not any(c.islower() for c in plaintext):
        reasons.append("At least one lowercase letter required.")
    if not any(c.isdigit() for c in plaintext):
        reasons.append("At least one digit required.")
    if not any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in plaintext):
        reasons.append("At least one special character required.")
    return (len(reasons) == 0, reasons)


# ── Private ───────────────────────────────────────────────────────────────────

def _parse_hash(stored: str) -> _ParsedHash:
    parts = stored.split(_SEPARATOR)
    if len(parts) != 4:
        raise ValueError(f"Expected 4 parts, got {len(parts)}")
    prefix, iters, salt_hex, hash_hex = parts
    if prefix != _PREFIX:
        raise ValueError(f"Unknown algorithm prefix: {prefix}")
    return _ParsedHash(
        algorithm  = prefix,
        iterations = int(iters),
        salt_hex   = salt_hex,
        hash_hex   = hash_hex,
    )
