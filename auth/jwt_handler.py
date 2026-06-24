"""
auth/jwt_handler.py — JWT Token Handler
=========================================
Pure stdlib implementation of HS256-signed JWTs.
No PyJWT required — uses hmac + hashlib + base64 from Python stdlib.
PyJWT can be dropped in later as an optional backend without changing call sites.

Token structure:
  Header  : {"alg": "HS256", "typ": "JWT"}
  Payload : {sub, username, jti, role, tenant_id, type, iat, exp}
  Signature: HMAC-SHA256 over "<header_b64>.<payload_b64>"

Security properties:
  • Constant-time signature comparison (hmac.compare_digest)
  • JTI (JWT ID) per token — enables selective revocation
  • Access tokens:  30 minutes
  • Refresh tokens: 7 days
  • Token type field prevents access-token/refresh-token substitution attacks
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from auth.models import (
    TokenExpiredError,
    TokenInvalidError,
    UserRecord,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Decode a base64url string, adding back stripped padding."""
    pad = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


# ── Token result carrier ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenPair:
    """Returned by create_pair(). Both tokens are opaque JWT strings."""
    access_token:   str
    refresh_token:  str
    access_jti:     str
    refresh_jti:    str
    access_expires_in: int      # seconds until access token expires


# ── JWTHandler ────────────────────────────────────────────────────────────────

class JWTHandler:
    """
    Stateless JWT factory and verifier.

    Single instance shared per application (no state after __init__).
    Thread-safe — all methods are pure functions over the secret key.

    Args:
        secret:      HMAC secret key.  Minimum 32 characters recommended.
        access_ttl:  Access token lifetime  in seconds (default: 1800 = 30 min).
        refresh_ttl: Refresh token lifetime in seconds (default: 604800 = 7 days).
    """

    ALGORITHM   = "HS256"
    _HEADER_B64 = _b64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )

    def __init__(
        self,
        secret:      str,
        access_ttl:  int = 1_800,
        refresh_ttl: int = 604_800,
    ) -> None:
        if not secret or len(secret) < 16:
            raise ValueError("JWT secret must be at least 16 characters.")
        self._secret      = secret.encode("utf-8")
        self._access_ttl  = access_ttl
        self._refresh_ttl = refresh_ttl

    # ── Public API ────────────────────────────────────────────────────────────

    def create_access_token(
        self,
        user_id:   str,
        username:  str,
        role:      str,
        tenant_id: str,
        jti:       Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Create a signed access token.

        Returns:
            (encoded_token, jti) — caller stores jti for revocation tracking.
        """
        jti = jti or str(uuid.uuid4())
        now = int(time.time())
        payload = {
            "sub":       user_id,
            "username":  username,
            "jti":       jti,
            "role":      role,
            "tenant_id": tenant_id,
            "type":      "access",
            "iat":       now,
            "exp":       now + self._access_ttl,
        }
        return self._encode(payload), jti

    def create_refresh_token(
        self,
        user_id: str,
        jti:     Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Create a signed refresh token (carries only user_id + jti, no role/tenant).

        Returns:
            (encoded_token, jti)
        """
        jti = jti or str(uuid.uuid4())
        now = int(time.time())
        payload = {
            "sub":  user_id,
            "jti":  jti,
            "type": "refresh",
            "iat":  now,
            "exp":  now + self._refresh_ttl,
        }
        return self._encode(payload), jti

    def create_pair(self, user: UserRecord) -> TokenPair:
        """
        Issue a fresh access + refresh pair for the given user.

        Both tokens get independent JTIs so either can be revoked individually.
        """
        access_token, access_jti = self.create_access_token(
            user_id   = user.user_id,
            username  = user.username,
            role      = user.role,
            tenant_id = user.tenant_id,
        )
        refresh_token, refresh_jti = self.create_refresh_token(
            user_id = user.user_id,
        )
        return TokenPair(
            access_token      = access_token,
            refresh_token     = refresh_token,
            access_jti        = access_jti,
            refresh_jti       = refresh_jti,
            access_expires_in = self._access_ttl,
        )

    def decode(self, token: str, expected_type: Optional[str] = None) -> dict:
        """
        Verify and decode a JWT.

        Args:
            token:         The JWT string.
            expected_type: If provided ("access" | "refresh"), reject tokens of
                           the wrong type to prevent substitution attacks.

        Returns:
            Verified payload dict.

        Raises:
            TokenInvalidError:  Bad structure, wrong key, or wrong type.
            TokenExpiredError:  Expiry claim has passed.
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise TokenInvalidError("Malformed token: expected 3 dot-separated parts.")

        header_b64, payload_b64, sig_b64 = parts

        # Verify signature in constant time
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig  = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        try:
            actual_sig = _b64url_decode(sig_b64)
        except Exception:
            raise TokenInvalidError("Cannot base64-decode signature.")

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise TokenInvalidError("Signature verification failed.")

        # Decode payload
        try:
            payload = json.loads(_b64url_decode(payload_b64))
        except Exception:
            raise TokenInvalidError("Cannot decode token payload.")

        # Expiry check
        exp = payload.get("exp", 0)
        if int(time.time()) > exp:
            raise TokenExpiredError()

        # Type check (substitution attack prevention)
        if expected_type and payload.get("type") != expected_type:
            raise TokenInvalidError(
                f"Token type mismatch: expected '{expected_type}', "
                f"got '{payload.get('type')}'."
            )

        return payload

    def get_jti(self, token: str) -> Optional[str]:
        """
        Extract JTI from a token without full verification.
        Used for revocation lookup when the token may already be expired.
        Never raises — returns None on any error.
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload = json.loads(_b64url_decode(parts[1]))
            return payload.get("jti")
        except Exception:
            return None

    def time_until_expiry(self, token: str) -> int:
        """
        Return seconds until expiry (negative if already expired).
        Does not verify signature — call decode() for verified expiry.
        """
        try:
            parts   = token.split(".")
            payload = json.loads(_b64url_decode(parts[1]))
            return int(payload.get("exp", 0)) - int(time.time())
        except Exception:
            return -1

    # ── Private ───────────────────────────────────────────────────────────────

    def _encode(self, payload: dict) -> str:
        payload_b64   = _b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        signing_input = f"{self._HEADER_B64}.{payload_b64}".encode("ascii")
        sig           = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        return f"{self._HEADER_B64}.{payload_b64}.{_b64url_encode(sig)}"
