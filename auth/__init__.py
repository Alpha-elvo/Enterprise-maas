"""
auth/__init__.py — Authentication & RBAC Package
=================================================
Public surface:
    from auth import AuthService, RBACEnforcer, Role, Permission
    from auth import require_permission, require_role
    from auth.models import AuthContext, UserRecord
"""

from auth.models import (
    AuthContext,
    AuthError,
    AccountLockedError,
    InvalidCredentialsError,
    Permission,
    PermissionDeniedError,
    Role,
    ROLE_PERMISSIONS,
    SessionRecord,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserRecord,
    get_permissions,
    role_has_permission,
)
from auth.password import hash_password, verify_password, password_meets_policy
from auth.jwt_handler import JWTHandler, TokenPair
from auth.rbac import RBACEnforcer, enforcer, require_permission, require_role

__all__ = [
    # Models
    "AuthContext", "UserRecord", "SessionRecord",
    "Role", "Permission", "ROLE_PERMISSIONS",
    # Exceptions
    "AuthError", "AccountLockedError", "InvalidCredentialsError",
    "PermissionDeniedError", "TokenExpiredError", "TokenInvalidError",
    "TokenRevokedError", "UserAlreadyExistsError", "UserNotFoundError",
    # RBAC helpers
    "get_permissions", "role_has_permission",
    # Password
    "hash_password", "verify_password", "password_meets_policy",
    # JWT
    "JWTHandler", "TokenPair",
    # RBAC
    "RBACEnforcer", "enforcer", "require_permission", "require_role",
]
