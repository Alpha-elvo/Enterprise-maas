"""
api/dependencies.py — FastAPI Dependency Injection
====================================================
Provides reusable FastAPI dependencies injected into route handlers.
All dependencies use FastAPI's Depends() system for testability.

Available:
  get_auth_service()   → AuthService singleton
  get_current_user()   → Authenticated AuthContext from Bearer token
  require_permission() → Auth + RBAC gate as a single dependency
  get_db()             → Main Database instance
  get_auth_db()        → AuthDatabase instance
  get_pagination()     → PaginationParams from query string
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

try:
    from fastapi import Depends, Header, HTTPException, Query, status
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from auth.auth_service import AuthService
from auth.jwt_handler import JWTHandler
from auth.models import (
    AuthContext, AuthError, Permission, PermissionDeniedError,
    TokenExpiredError, TokenInvalidError, TokenRevokedError,
)
from auth.rbac import RBACEnforcer
from config import config
from storage.auth_db import AuthDatabase
from storage.database import Database


# ── Singletons (created once per process) ────────────────────────────────────

@lru_cache(maxsize=1)
def _jwt_handler() -> JWTHandler:
    return JWTHandler(
        secret=config.SECRET_KEY,
        access_ttl=1_800,
        refresh_ttl=604_800,
    )


@lru_cache(maxsize=1)
def _auth_db() -> AuthDatabase:
    return AuthDatabase()


@lru_cache(maxsize=1)
def _main_db() -> Database:
    return Database()


@lru_cache(maxsize=1)
def _rbac() -> RBACEnforcer:
    return RBACEnforcer()


# ── FastAPI dependencies ──────────────────────────────────────────────────────

if _HAS_FASTAPI:
    _bearer = HTTPBearer(auto_error=False)

    def get_auth_service() -> AuthService:
        return AuthService(db=_auth_db(), jwt=_jwt_handler())

    def get_db() -> Database:
        return _main_db()

    def get_auth_db() -> AuthDatabase:
        return _auth_db()

    def get_pagination(
        page:     int = Query(default=1,  ge=1),
        per_page: int = Query(default=20, ge=1, le=100),
    ):
        from api.schemas import PaginationParams
        return PaginationParams(page=page, per_page=per_page)

    def get_current_user(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
        auth_svc:    AuthService = Depends(get_auth_service),
    ) -> AuthContext:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return auth_svc.get_auth_context(credentials.credentials)
        except TokenExpiredError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except (TokenInvalidError, TokenRevokedError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            )

    def require(permission: Permission):
        """
        Return a FastAPI dependency that enforces a single permission.

        Usage:
            @router.post("/runs")
            def create_run(
                ctx: AuthContext = Depends(require(Permission.RUNS_CREATE))
            ): ...
        """
        def _check(
            ctx: AuthContext = Depends(get_current_user),
        ) -> AuthContext:
            try:
                _rbac().require(ctx, permission)
            except PermissionDeniedError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(exc),
                )
            return ctx
        _check.__name__ = f"require_{permission.value.replace(':', '_')}"
        return _check

else:
    # Stubs so the module imports without FastAPI installed
    def get_auth_service():  # type: ignore
        return AuthService(db=_auth_db(), jwt=_jwt_handler())

    def get_db():  # type: ignore
        return _main_db()

    def get_current_user():  # type: ignore
        raise RuntimeError("FastAPI not installed")

    def require(permission):  # type: ignore
        raise RuntimeError("FastAPI not installed")

    def get_pagination():  # type: ignore
        pass
