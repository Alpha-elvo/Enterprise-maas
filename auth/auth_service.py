"""
auth/auth_service.py — Authentication Service
===============================================
Orchestrates all authentication flows:
  • Registration (with duplicate detection and password policy)
  • Login (with brute-force protection and lockout)
  • Token refresh (with rotation — old refresh token is immediately revoked)
  • Logout (single session) and logout-all (all sessions)
  • Password change (revokes all existing sessions)
  • Token introspection → AuthContext for downstream use

Dependency injection: AuthService receives AuthDatabase and JWTHandler,
making it fully testable without a real database or real JWT secrets.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from auth.jwt_handler import JWTHandler, TokenPair
from auth.models import (
    AccountLockedError,
    AuthContext,
    AuthError,
    InvalidCredentialsError,
    Permission,
    PermissionDeniedError,
    Role,
    SessionRecord,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserRecord,
    get_permissions,
)
from auth.password import (
    hash_password,
    needs_rehash,
    password_meets_policy,
    verify_password,
)
from core.logger import get_logger, AuditLogger
from storage.auth_db import AuthDatabase, _LOCKOUT_DURATION_MIN, _MAX_FAILED_ATTEMPTS

log = get_logger(__name__)


class AuthService:
    """
    Single entry point for all authentication operations.

    Usage:
        db      = AuthDatabase()
        handler = JWTHandler(secret=config.SECRET_KEY)
        auth    = AuthService(db=db, jwt=handler)

        # Register
        user = auth.register("alice", "alice@corp.com", "Str0ng!Pass", Role.ANALYST)

        # Login
        ctx, tokens = auth.login("alice", "Str0ng!Pass", tenant_id="corp")

        # Verify request token
        ctx = auth.get_auth_context(bearer_token)
        ctx.require(Permission.RUNS_CREATE)
    """

    def __init__(self, db: AuthDatabase, jwt: JWTHandler) -> None:
        self._db  = db
        self._jwt = jwt

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        username:  str,
        email:     str,
        password:  str,
        role:      Role      = Role.VIEWER,
        tenant_id: str       = "default",
        verified:  bool      = False,
    ) -> UserRecord:
        """
        Create a new user account.

        Raises:
            UserAlreadyExistsError: If username+tenant already taken.
            ValueError:             If password does not meet policy.
        """
        # Password policy
        ok, reasons = password_meets_policy(password)
        if not ok:
            raise ValueError("Password policy violations: " + "; ".join(reasons))

        # Duplicate check
        existing = self._db.get_user_by_username(username, tenant_id)
        if existing:
            raise UserAlreadyExistsError(username)

        user = UserRecord(
            user_id       = str(uuid.uuid4()),
            username      = username.strip().lower(),
            email         = email.strip().lower(),
            password_hash = hash_password(password),
            role          = role.value,
            tenant_id     = tenant_id,
            is_active     = True,
            is_verified   = verified,
        )
        self._db.create_user(user)

        AuditLogger.log(
            event_type = "USER_REGISTERED",
            event_data = {"username": user.username, "role": user.role},
            severity   = "INFO",
            agent_name = "auth_service",
        )
        log.info(
            "User registered",
            extra={"user_id": user.user_id, "username": user.username,
                   "role": role.value, "tenant_id": tenant_id},
        )
        return user

    # ── Login ─────────────────────────────────────────────────────────────────

    def login(
        self,
        username:   str,
        password:   str,
        tenant_id:  str = "default",
        ip_address: str = "",
        user_agent: str = "",
    ) -> tuple[AuthContext, TokenPair]:
        """
        Authenticate credentials and issue a token pair.

        Returns:
            (AuthContext, TokenPair) on success.

        Raises:
            InvalidCredentialsError: Wrong username/password.
            AccountLockedError:      Account locked due to too many failures.
        """
        user = self._db.get_user_by_username(username.strip().lower(), tenant_id)
        if not user:
            # Timing-safe: still verify a dummy hash to prevent enumeration
            verify_password(password, _DUMMY_HASH)
            self._db.record_failed_login(username, tenant_id, ip_address)
            raise InvalidCredentialsError()

        # Lockout check (before password verify to save CPU)
        if self._db.is_user_locked(user):
            raise AccountLockedError(user.locked_until or "")

        if not user.is_active:
            raise InvalidCredentialsError()

        # Password verification
        if not verify_password(password, user.password_hash):
            count = self._db.record_failed_login(username, tenant_id, ip_address)
            if count >= _MAX_FAILED_ATTEMPTS:
                locked_until = self._db.lock_user(user.user_id, _LOCKOUT_DURATION_MIN)
                AuditLogger.log(
                    event_type = "ACCOUNT_LOCKED",
                    event_data = {"username": username, "failed_attempts": count},
                    severity   = "WARN",
                    agent_name = "auth_service",
                )
                raise AccountLockedError(locked_until)
            raise InvalidCredentialsError()

        # Successful login
        self._db.reset_failed_logins(username, tenant_id)
        user.last_login = _now()
        self._db.update_user(user)

        # Optional: rehash if iteration count has been upgraded
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            self._db.update_user(user)
            log.info("Password rehashed", extra={"user_id": user.user_id})

        tokens = self._jwt.create_pair(user)
        self._store_sessions(user, tokens, ip_address, user_agent)

        AuditLogger.log(
            event_type = "USER_LOGIN",
            event_data = {"username": user.username, "ip": ip_address},
            severity   = "INFO",
            agent_name = "auth_service",
        )
        ctx = self._build_context(user, tokens.access_jti)
        return ctx, tokens

    # ── Token refresh ─────────────────────────────────────────────────────────

    def refresh(
        self,
        refresh_token: str,
        ip_address:    str = "",
        user_agent:    str = "",
    ) -> tuple[AuthContext, TokenPair]:
        """
        Rotate a refresh token: old token is revoked, new pair issued.

        Raises:
            TokenInvalidError, TokenExpiredError, TokenRevokedError,
            UserNotFoundError.
        """
        payload = self._jwt.decode(refresh_token, expected_type="refresh")
        jti     = payload.get("jti", "")
        user_id = payload.get("sub", "")

        if self._db.is_session_revoked(jti):
            raise TokenRevokedError()

        user = self._db.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id)

        if not user.is_active:
            raise InvalidCredentialsError()

        # Revoke old refresh session immediately (token rotation)
        self._db.revoke_session(jti)

        tokens = self._jwt.create_pair(user)
        self._store_sessions(user, tokens, ip_address, user_agent)

        AuditLogger.log(
            event_type = "TOKEN_REFRESHED",
            event_data = {"user_id": user_id, "old_jti": jti[:8]},
            severity   = "INFO",
            agent_name = "auth_service",
        )
        ctx = self._build_context(user, tokens.access_jti)
        return ctx, tokens

    # ── Logout ────────────────────────────────────────────────────────────────

    def logout(self, access_token: str) -> None:
        """Revoke the specific access token JTI."""
        jti = self._jwt.get_jti(access_token)
        if jti:
            self._db.revoke_session(jti)
            AuditLogger.log(
                event_type = "USER_LOGOUT",
                event_data = {"jti": jti[:8]},
                severity   = "INFO",
                agent_name = "auth_service",
            )

    def logout_all(self, user_id: str) -> int:
        """Revoke ALL sessions for a user (use on password change or compromise)."""
        count = self._db.revoke_all_user_sessions(user_id)
        AuditLogger.log(
            event_type = "USER_LOGOUT_ALL",
            event_data = {"user_id": user_id, "sessions_revoked": count},
            severity   = "WARN",
            agent_name = "auth_service",
        )
        return count

    # ── Token introspection → AuthContext ─────────────────────────────────────

    def get_auth_context(self, access_token: str) -> AuthContext:
        """
        Verify an access token and return a populated AuthContext.

        This is the primary entry point for request authentication.
        Call this at the top of every protected endpoint/handler.

        Raises:
            TokenInvalidError, TokenExpiredError, TokenRevokedError.
        """
        payload = self._jwt.decode(access_token, expected_type="access")
        jti     = payload.get("jti", "")

        if self._db.is_session_revoked(jti):
            raise TokenRevokedError()

        user_id = payload.get("sub", "")
        user    = self._db.get_user_by_id(user_id)
        if not user or not user.is_active:
            raise TokenInvalidError("User not found or deactivated.")

        return self._build_context(user, jti)

    # ── Password management ───────────────────────────────────────────────────

    def change_password(
        self,
        user_id:          str,
        current_password: str,
        new_password:     str,
    ) -> None:
        """
        Change password. Revokes ALL existing sessions for security.

        Raises:
            UserNotFoundError, InvalidCredentialsError, ValueError.
        """
        user = self._db.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id)

        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError()

        ok, reasons = password_meets_policy(new_password)
        if not ok:
            raise ValueError("Password policy violations: " + "; ".join(reasons))

        user.password_hash = hash_password(new_password)
        self._db.update_user(user)
        self.logout_all(user_id)   # force re-login everywhere

        AuditLogger.log(
            event_type = "PASSWORD_CHANGED",
            event_data = {"user_id": user_id},
            severity   = "WARN",
            agent_name = "auth_service",
        )

    def reset_password_admin(
        self,
        admin_ctx:    AuthContext,
        target_user_id: str,
        new_password: str,
    ) -> None:
        """Admin-only: reset another user's password without knowing the current one."""
        admin_ctx.require(Permission.USERS_UPDATE)

        ok, reasons = password_meets_policy(new_password)
        if not ok:
            raise ValueError("Password policy violations: " + "; ".join(reasons))

        user = self._db.get_user_by_id(target_user_id)
        if not user:
            raise UserNotFoundError(target_user_id)

        user.password_hash = hash_password(new_password)
        self._db.update_user(user)
        self.logout_all(target_user_id)

        AuditLogger.log(
            event_type = "PASSWORD_ADMIN_RESET",
            event_data = {
                "admin_id":      admin_ctx.user.user_id,
                "target_user_id": target_user_id,
            },
            severity   = "WARN",
            agent_name = "auth_service",
        )

    # ── User management ───────────────────────────────────────────────────────

    def get_user(self, user_id: str) -> UserRecord:
        user = self._db.get_user_by_id(user_id)
        if not user:
            raise UserNotFoundError(user_id)
        return user

    def update_role(
        self,
        admin_ctx: AuthContext,
        user_id:   str,
        new_role:  Role,
    ) -> UserRecord:
        """Change a user's role. Requires USERS_UPDATE permission."""
        admin_ctx.require(Permission.USERS_UPDATE)
        user = self.get_user(user_id)
        user.role = new_role.value
        self._db.update_user(user)
        self.logout_all(user_id)   # re-login to get new role in token
        return user

    def deactivate_user(self, admin_ctx: AuthContext, user_id: str) -> None:
        admin_ctx.require(Permission.USERS_DELETE)
        user = self.get_user(user_id)
        user.is_active = False
        self._db.update_user(user)
        self.logout_all(user_id)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _store_sessions(
        self,
        user:       UserRecord,
        tokens:     TokenPair,
        ip_address: str,
        user_agent: str,
    ) -> None:
        """Persist both JTIs so they can be revoked later."""
        import time
        now = _now()
        access_exp  = _iso_from_now(self._jwt._access_ttl)
        refresh_exp = _iso_from_now(self._jwt._refresh_ttl)

        self._db.create_session(SessionRecord(
            jti        = tokens.access_jti,
            user_id    = user.user_id,
            tenant_id  = user.tenant_id,
            token_type = "access",
            issued_at  = now,
            expires_at = access_exp,
            ip_address = ip_address,
            user_agent = user_agent,
        ))
        self._db.create_session(SessionRecord(
            jti        = tokens.refresh_jti,
            user_id    = user.user_id,
            tenant_id  = user.tenant_id,
            token_type = "refresh",
            issued_at  = now,
            expires_at = refresh_exp,
            ip_address = ip_address,
            user_agent = user_agent,
        ))

    @staticmethod
    def _build_context(user: UserRecord, jti: str) -> AuthContext:
        return AuthContext(
            user        = user,
            permissions = get_permissions(user.role_enum),
            jti         = jti,
            tenant_id   = user.tenant_id,
        )


# ── Module-level utilities ────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_from_now(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# Dummy hash for constant-time failure path (prevents user enumeration)
_DUMMY_HASH = (
    "pbkdf2_sha256$600000$"
    "00000000000000000000000000000000000000000000000000000000000000000$"
    "00000000000000000000000000000000000000000000000000000000000000000"
)
