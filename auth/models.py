"""
auth/models.py — Authentication & RBAC Domain Models
======================================================
Three model layers:
  1. Enums          — Role, Permission (canonical string values)
  2. RBAC matrix    — explicit allow-list per role, deny-by-default
  3. Dataclasses    — internal domain objects (UserRecord, SessionRecord)
  4. Pydantic v2    — API request/response schemas with validation

SOLID: Single-Responsibility per class, Open for extension via Role/Permission enums.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Set

# ── Optional Pydantic (graceful degradation if not installed) ─────────────────
try:
    from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
    _PYDANTIC = True
except ImportError:                         # pragma: no cover
    _PYDANTIC = False                        # tests skip Pydantic sections


# ══════════════════════════════════════════════════════════════════════════════
# 1. ENUMERATIONS
# ══════════════════════════════════════════════════════════════════════════════

class Role(str, Enum):
    """Platform roles ordered from most to least privileged."""
    SUPER_ADMIN  = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    ANALYST      = "analyst"
    APPROVER     = "approver"
    VIEWER       = "viewer"


class Permission(str, Enum):
    """Granular permission tokens. Format: resource:action."""
    # ── Analysis runs ─────────────────────────────────────────────────────────
    RUNS_CREATE   = "runs:create"
    RUNS_READ     = "runs:read"
    RUNS_DELETE   = "runs:delete"
    # ── Reports ───────────────────────────────────────────────────────────────
    REPORTS_READ   = "reports:read"
    REPORTS_EXPORT = "reports:export"
    # ── Users ─────────────────────────────────────────────────────────────────
    USERS_CREATE  = "users:create"
    USERS_READ    = "users:read"
    USERS_UPDATE  = "users:update"
    USERS_DELETE  = "users:delete"
    # ── Approval workflows ────────────────────────────────────────────────────
    WORKFLOWS_CREATE  = "workflows:create"
    WORKFLOWS_READ    = "workflows:read"
    WORKFLOWS_APPROVE = "workflows:approve"
    WORKFLOWS_REJECT  = "workflows:reject"
    # ── Platform settings ─────────────────────────────────────────────────────
    SETTINGS_READ   = "settings:read"
    SETTINGS_UPDATE = "settings:update"
    # ── Audit trail ───────────────────────────────────────────────────────────
    AUDIT_READ = "audit:read"
    # ── Tenant management (super-admin only) ──────────────────────────────────
    TENANTS_CREATE = "tenants:create"
    TENANTS_READ   = "tenants:read"
    TENANTS_UPDATE = "tenants:update"
    TENANTS_DELETE = "tenants:delete"


# ══════════════════════════════════════════════════════════════════════════════
# 2. RBAC PERMISSION MATRIX
# Deny-by-default: roles receive ONLY what is explicitly listed here.
# Extension: add new Permission values and assign to roles without touching
# any consumer code (Open/Closed Principle).
# ══════════════════════════════════════════════════════════════════════════════

ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {

    Role.SUPER_ADMIN: set(Permission),   # all permissions

    Role.TENANT_ADMIN: {
        Permission.RUNS_CREATE, Permission.RUNS_READ, Permission.RUNS_DELETE,
        Permission.REPORTS_READ, Permission.REPORTS_EXPORT,
        Permission.USERS_CREATE, Permission.USERS_READ,
        Permission.USERS_UPDATE, Permission.USERS_DELETE,
        Permission.WORKFLOWS_CREATE, Permission.WORKFLOWS_READ,
        Permission.WORKFLOWS_APPROVE, Permission.WORKFLOWS_REJECT,
        Permission.SETTINGS_READ, Permission.SETTINGS_UPDATE,
        Permission.AUDIT_READ,
        Permission.TENANTS_READ,
    },

    Role.ANALYST: {
        Permission.RUNS_CREATE, Permission.RUNS_READ,
        Permission.REPORTS_READ, Permission.REPORTS_EXPORT,
        Permission.WORKFLOWS_CREATE, Permission.WORKFLOWS_READ,
        Permission.SETTINGS_READ,
        Permission.AUDIT_READ,
        Permission.USERS_READ,
    },

    Role.APPROVER: {
        Permission.RUNS_READ,
        Permission.REPORTS_READ, Permission.REPORTS_EXPORT,
        Permission.WORKFLOWS_READ,
        Permission.WORKFLOWS_APPROVE, Permission.WORKFLOWS_REJECT,
        Permission.AUDIT_READ,
        Permission.SETTINGS_READ,
        Permission.USERS_READ,
    },

    Role.VIEWER: {
        Permission.RUNS_READ,
        Permission.REPORTS_READ,
        Permission.AUDIT_READ,
        Permission.SETTINGS_READ,
    },
}


def get_permissions(role: Role) -> Set[Permission]:
    """Return the permission set for a given role. Safe for unknown roles."""
    return ROLE_PERMISSIONS.get(role, set())


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Single-call permission gate used throughout the platform."""
    return permission in get_permissions(role)


# ══════════════════════════════════════════════════════════════════════════════
# 3. INTERNAL DATACLASSES (persistence & business logic layer)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class UserRecord:
    """Stored user. Never expose password_hash over API."""
    user_id:       str   = field(default_factory=lambda: str(uuid.uuid4()))
    username:      str   = ""
    email:         str   = ""
    password_hash: str   = ""
    role:          str   = Role.VIEWER.value
    tenant_id:     str   = "default"
    is_active:     bool  = True
    is_verified:   bool  = False
    failed_logins: int   = 0
    locked_until:  Optional[str] = None
    created_at:    str   = field(default_factory=lambda: _now())
    updated_at:    str   = field(default_factory=lambda: _now())
    last_login:    Optional[str] = None

    def to_public_dict(self) -> dict:
        """Safe dict without password_hash for API responses."""
        return {
            "user_id":     self.user_id,
            "username":    self.username,
            "email":       self.email,
            "role":        self.role,
            "tenant_id":   self.tenant_id,
            "is_active":   self.is_active,
            "is_verified": self.is_verified,
            "created_at":  self.created_at,
            "last_login":  self.last_login,
        }

    @property
    def role_enum(self) -> Role:
        return Role(self.role)

    def has_permission(self, permission: Permission) -> bool:
        return role_has_permission(self.role_enum, permission)


@dataclass
class SessionRecord:
    """Active JWT session for token revocation tracking."""
    jti:        str  = field(default_factory=lambda: str(uuid.uuid4()))
    user_id:    str  = ""
    tenant_id:  str  = "default"
    token_type: str  = "access"     # "access" | "refresh"
    issued_at:  str  = field(default_factory=lambda: _now())
    expires_at: str  = ""
    revoked:    bool = False
    ip_address: str  = ""
    user_agent: str  = ""

    def to_dict(self) -> dict:
        return {
            "jti":        self.jti,
            "user_id":    self.user_id,
            "tenant_id":  self.tenant_id,
            "token_type": self.token_type,
            "issued_at":  self.issued_at,
            "expires_at": self.expires_at,
            "revoked":    self.revoked,
        }


@dataclass
class AuthContext:
    """
    Injected into every authenticated request.
    Carries the resolved user and their permission set.
    """
    user:        UserRecord
    permissions: Set[Permission]
    jti:         str = ""
    tenant_id:   str = "default"

    def require(self, permission: Permission) -> None:
        """Raise PermissionDeniedError if permission absent."""
        if permission not in self.permissions:
            raise PermissionDeniedError(
                f"Permission '{permission.value}' required. "
                f"Role '{self.user.role}' does not grant it."
            )

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


# ══════════════════════════════════════════════════════════════════════════════
# 4. PYDANTIC SCHEMAS (API layer only — never stored directly)
# ══════════════════════════════════════════════════════════════════════════════

if _PYDANTIC:

    class UserCreateRequest(BaseModel):
        username:  str  = Field(..., min_length=3, max_length=64,
                                 pattern=r"^[a-zA-Z0-9_.-]+$")
        email:     str  = Field(..., min_length=5, max_length=254)
        password:  str  = Field(..., min_length=10, max_length=128)
        role:      Role = Role.VIEWER
        tenant_id: str  = Field(default="default", min_length=1, max_length=64)

        @field_validator("password")
        @classmethod
        def password_complexity(cls, v: str) -> str:
            errors = []
            if not any(c.isupper() for c in v):
                errors.append("one uppercase letter")
            if not any(c.islower() for c in v):
                errors.append("one lowercase letter")
            if not any(c.isdigit() for c in v):
                errors.append("one digit")
            if not any(c in "!@#$%^&*()-_=+[]{}|;:,.<>?" for c in v):
                errors.append("one special character")
            if errors:
                raise ValueError(f"Password must contain: {', '.join(errors)}")
            return v

        model_config = {"str_strip_whitespace": True}

    class LoginRequest(BaseModel):
        username:  str = Field(..., min_length=1)
        password:  str = Field(..., min_length=1)
        tenant_id: str = Field(default="default")

        model_config = {"str_strip_whitespace": True}

    class TokenResponse(BaseModel):
        access_token:  str
        refresh_token: str
        token_type:    str = "bearer"
        expires_in:    int           # seconds until access token expires
        user:          dict

    class RefreshRequest(BaseModel):
        refresh_token: str

    class PasswordChangeRequest(BaseModel):
        current_password: str = Field(..., min_length=1)
        new_password:     str = Field(..., min_length=10, max_length=128)

    class UserUpdateRequest(BaseModel):
        email: Optional[str]  = None
        role:  Optional[Role] = None
        is_active: Optional[bool] = None

    class UserPublicResponse(BaseModel):
        user_id:    str
        username:   str
        email:      str
        role:       str
        tenant_id:  str
        is_active:  bool
        created_at: str
        last_login: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# 5. EXCEPTIONS
# ══════════════════════════════════════════════════════════════════════════════

class AuthError(Exception):
    """Base for all authentication/authorisation errors."""
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code

class InvalidCredentialsError(AuthError):
    def __init__(self):
        super().__init__("Invalid username or password.", 401)

class AccountLockedError(AuthError):
    def __init__(self, until: str = ""):
        super().__init__(f"Account locked until {until}." if until else "Account locked.", 403)

class TokenExpiredError(AuthError):
    def __init__(self):
        super().__init__("Token has expired.", 401)

class TokenInvalidError(AuthError):
    def __init__(self, detail: str = ""):
        super().__init__(f"Invalid token. {detail}".strip(), 401)

class TokenRevokedError(AuthError):
    def __init__(self):
        super().__init__("Token has been revoked.", 401)

class PermissionDeniedError(AuthError):
    def __init__(self, detail: str = ""):
        super().__init__(f"Permission denied. {detail}".strip(), 403)

class UserNotFoundError(AuthError):
    def __init__(self, identifier: str = ""):
        super().__init__(f"User not found: {identifier}", 404)

class UserAlreadyExistsError(AuthError):
    def __init__(self, username: str):
        super().__init__(f"Username '{username}' already exists.", 409)


# ── Utility ───────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
