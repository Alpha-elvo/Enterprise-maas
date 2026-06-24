"""
auth/rbac.py — Role-Based Access Control Enforcer
===================================================
Three usage patterns for consuming code:

  1. Imperative (service layer):
       enforcer.require(ctx, Permission.RUNS_CREATE)

  2. Decorator (API handler functions):
       @require_permission(Permission.REPORTS_EXPORT)
       def export_report(ctx: AuthContext, run_id: str): ...

  3. Direct boolean check (conditional UI logic):
       if rbac.can(ctx, Permission.USERS_DELETE):
           show_delete_button()

All checks emit to the audit logger so every access decision is traceable.
"""

from __future__ import annotations

import functools
from typing import Callable, Optional

from auth.models import (
    AuthContext,
    Permission,
    PermissionDeniedError,
    Role,
    ROLE_PERMISSIONS,
    get_permissions,
    role_has_permission,
)
from core.logger import get_logger, AuditLogger

log = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# RBAC ENFORCER
# ══════════════════════════════════════════════════════════════════════════════

class RBACEnforcer:
    """
    Stateless permission enforcer.

    All methods are pure functions of (AuthContext, Permission).
    No state is stored — safe to use as a singleton or instantiate per-request.
    """

    # ── Core checks ───────────────────────────────────────────────────────────

    def require(
        self,
        ctx:        AuthContext,
        permission: Permission,
        resource:   str = "",
    ) -> None:
        """
        Assert the caller holds a permission. Raises PermissionDeniedError if not.

        Args:
            ctx:        Resolved auth context for the current request.
            permission: The specific permission required.
            resource:   Optional resource identifier for audit trail granularity.

        Raises:
            PermissionDeniedError: Immediately when permission is absent.
        """
        granted = permission in ctx.permissions
        self._audit(ctx, permission, resource, granted)

        if not granted:
            log.warning(
                "Permission denied",
                extra={
                    "user_id":    ctx.user.user_id,
                    "username":   ctx.user.username,
                    "role":       ctx.user.role,
                    "permission": permission.value,
                    "resource":   resource,
                    "tenant_id":  ctx.tenant_id,
                },
            )
            raise PermissionDeniedError(
                f"Role '{ctx.user.role}' does not grant '{permission.value}'."
            )

    def require_any(
        self,
        ctx:         AuthContext,
        *permissions: Permission,
        resource:    str = "",
    ) -> Permission:
        """
        Assert the caller holds AT LEAST ONE of the given permissions.

        Returns:
            The first matching permission (useful for conditional branching).

        Raises:
            PermissionDeniedError: If none of the permissions are held.
        """
        for perm in permissions:
            if perm in ctx.permissions:
                self._audit(ctx, perm, resource, True)
                return perm

        # None matched — log and raise
        self._audit(ctx, permissions[0] if permissions else None, resource, False)
        perm_list = ", ".join(p.value for p in permissions)
        raise PermissionDeniedError(
            f"Role '{ctx.user.role}' requires at least one of: {perm_list}."
        )

    def require_all(
        self,
        ctx:         AuthContext,
        *permissions: Permission,
        resource:    str = "",
    ) -> None:
        """
        Assert the caller holds ALL of the given permissions.

        Raises:
            PermissionDeniedError: On the first missing permission.
        """
        for perm in permissions:
            self.require(ctx, perm, resource)

    def can(self, ctx: AuthContext, permission: Permission) -> bool:
        """Non-raising boolean check. Use for conditional UI/logic branching."""
        return permission in ctx.permissions

    def can_any(self, ctx: AuthContext, *permissions: Permission) -> bool:
        return any(p in ctx.permissions for p in permissions)

    def can_all(self, ctx: AuthContext, *permissions: Permission) -> bool:
        return all(p in ctx.permissions for p in permissions)

    def permission_matrix(self, role: Role) -> dict[str, bool]:
        """
        Return a full permission → granted mapping for a given role.
        Useful for UI permission inspection panels.
        """
        perms = get_permissions(role)
        return {p.value: (p in perms) for p in Permission}

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _audit(
        ctx:        AuthContext,
        permission: Optional[Permission],
        resource:   str,
        granted:    bool,
    ) -> None:
        AuditLogger.log(
            event_type = "RBAC_CHECK",
            event_data = {
                "permission": permission.value if permission else "none",
                "resource":   resource,
                "granted":    granted,
                "role":       ctx.user.role,
            },
            severity   = "INFO" if granted else "WARN",
            record_id  = resource,
            agent_name = "rbac",
        )


# ══════════════════════════════════════════════════════════════════════════════
# DECORATOR
# ══════════════════════════════════════════════════════════════════════════════

# Module-level singleton — import and use directly
enforcer = RBACEnforcer()


def require_permission(permission: Permission, resource_arg: str = ""):
    """
    Decorator that enforces a permission on the AuthContext.

    The decorated function MUST accept `ctx: AuthContext` as its first
    positional argument (or as a keyword argument named 'ctx').

    Usage:
        @require_permission(Permission.RUNS_CREATE)
        def create_run(ctx: AuthContext, payload: dict) -> dict:
            ...

        @require_permission(Permission.REPORTS_EXPORT, resource_arg="report_id")
        def export_report(ctx: AuthContext, report_id: str) -> bytes:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Resolve AuthContext from positional or keyword args
            ctx: Optional[AuthContext] = None
            for arg in args:
                if isinstance(arg, AuthContext):
                    ctx = arg
                    break
            if ctx is None:
                ctx = kwargs.get("ctx")
            if ctx is None:
                raise TypeError(
                    f"@require_permission: function '{func.__name__}' must accept "
                    "an AuthContext as 'ctx' argument."
                )

            # Resolve optional resource identifier
            resource = kwargs.get(resource_arg, "") if resource_arg else ""

            enforcer.require(ctx, permission, str(resource))
            return func(*args, **kwargs)

        return wrapper
    return decorator


def require_role(minimum_role: Role):
    """
    Decorator that enforces a minimum role level.
    Roles are ordered: SUPER_ADMIN > TENANT_ADMIN > ANALYST > APPROVER > VIEWER.

    Usage:
        @require_role(Role.TENANT_ADMIN)
        def admin_only_action(ctx: AuthContext) -> None: ...
    """
    _ROLE_ORDER = {
        Role.SUPER_ADMIN:  5,
        Role.TENANT_ADMIN: 4,
        Role.ANALYST:      3,
        Role.APPROVER:     2,
        Role.VIEWER:       1,
    }
    min_level = _ROLE_ORDER.get(minimum_role, 0)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ctx: Optional[AuthContext] = None
            for arg in args:
                if isinstance(arg, AuthContext):
                    ctx = arg
                    break
            if ctx is None:
                ctx = kwargs.get("ctx")
            if ctx is None:
                raise TypeError(
                    f"@require_role: function '{func.__name__}' must accept "
                    "an AuthContext as 'ctx' argument."
                )
            user_level = _ROLE_ORDER.get(ctx.user.role_enum, 0)
            if user_level < min_level:
                raise PermissionDeniedError(
                    f"Minimum role '{minimum_role.value}' required. "
                    f"User has role '{ctx.user.role}'."
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator
