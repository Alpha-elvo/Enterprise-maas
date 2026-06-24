"""
workflows/engine.py — Approval Workflow State Machine Engine
=============================================================
Orchestrates state transitions with:
  • Guard validation  (permission check before transition)
  • Atomic DB update  (state change + history entry in one transaction)
  • Audit logging     (every transition is permanently recorded)
  • Notification hook (pluggable — default is log-only)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from auth.models import AuthContext, Permission
from core.logger import get_logger, AuditLogger
from workflows.models import (
    ACTION_PERMISSIONS,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    InvalidTransitionError,
    WorkflowAction,
    WorkflowError,
    WorkflowHistoryEntry,
    WorkflowNotFoundError,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowTerminalError,
)

log = get_logger(__name__)


class WorkflowEngine:
    """
    Stateless workflow engine — all state lives in WorkflowDatabase.

    Dependency-injected for testability:
        db     = WorkflowDatabase()
        engine = WorkflowEngine(db=db)
        engine.transition(workflow_id, WorkflowAction.APPROVE, ctx, comment="LGTM")
    """

    def __init__(
        self,
        db: "WorkflowDatabase",
        notify_fn: Optional[Callable[[WorkflowRecord, WorkflowAction], None]] = None,
    ) -> None:
        self._db        = db
        self._notify_fn = notify_fn or self._default_notify

    # ── Core transition ───────────────────────────────────────────────────────

    def transition(
        self,
        workflow_id: str,
        action:      WorkflowAction,
        ctx:         AuthContext,
        comment:     str = "",
    ) -> WorkflowRecord:
        """
        Apply an action to a workflow, driving a state transition.

        Args:
            workflow_id: Target workflow UUID.
            action:      Requested WorkflowAction.
            ctx:         Authenticated caller context (for RBAC and audit).
            comment:     Optional free-text reason.

        Returns:
            The updated WorkflowRecord.

        Raises:
            WorkflowNotFoundError:  Unknown workflow_id.
            WorkflowTerminalError:  Already in a terminal state.
            InvalidTransitionError: Action not valid from current state.
            PermissionDeniedError:  Caller lacks required permission.
        """
        wf = self._db.get(workflow_id)
        if not wf:
            raise WorkflowNotFoundError(workflow_id)

        # Guard 1: terminal state
        if wf.is_terminal:
            raise WorkflowTerminalError(wf.status)

        # Guard 2: valid transition
        key = (wf.status_enum, action)
        if key not in VALID_TRANSITIONS:
            raise InvalidTransitionError(wf.status, action.value)

        # Guard 3: RBAC permission
        required_perm_str = ACTION_PERMISSIONS.get(action, "")
        if required_perm_str:
            from auth.models import Permission
            try:
                required_perm = Permission(required_perm_str)
                ctx.require(required_perm)
            except Exception as exc:
                raise

        # Compute next state
        next_status = VALID_TRANSITIONS[key]
        from_status = wf.status

        # Build history entry
        entry = WorkflowHistoryEntry(
            workflow_id = wf.workflow_id,
            action      = action.value,
            from_status = from_status,
            to_status   = next_status.value,
            actor_id    = ctx.user.user_id,
            actor_name  = ctx.user.username,
            comment     = comment[:1000],
        )

        # Apply transition
        wf.status     = next_status.value
        wf.updated_at = _now()
        if next_status in TERMINAL_STATES:
            wf.resolved_at = _now()
        wf.history.append(entry)

        # Persist atomically
        self._db.update(wf, entry)

        # Audit log
        AuditLogger.log(
            event_type = f"WORKFLOW_{action.value.upper()}",
            event_data = {
                "workflow_id": wf.workflow_id,
                "from_status": from_status,
                "to_status":   next_status.value,
                "actor":       ctx.user.username,
                "comment":     comment[:200],
            },
            severity  = "WARN" if next_status == WorkflowStatus.REJECTED else "INFO",
            record_id = wf.record_id,
            agent_name = "workflow_engine",
        )

        log.info(
            f"Workflow transition: {from_status} → {next_status.value}",
            extra={
                "workflow_id": wf.workflow_id,
                "action":      action.value,
                "actor":       ctx.user.username,
            },
        )

        # Notify (non-blocking — errors are logged but not propagated)
        try:
            self._notify_fn(wf, action)
        except Exception as exc:
            log.warning(f"Workflow notification failed: {exc}")

        return wf

    # ── Convenience methods ───────────────────────────────────────────────────

    def create(
        self,
        run_id:      str,
        record_id:   str,
        title:       str,
        ctx:         AuthContext,
        description: str = "",
        priority:    str = "MEDIUM",
    ) -> WorkflowRecord:
        """Create a new workflow in DRAFT state."""
        from auth.models import Permission
        ctx.require(Permission.WORKFLOWS_CREATE)

        wf = WorkflowRecord(
            run_id      = run_id,
            record_id   = record_id,
            tenant_id   = ctx.tenant_id,
            title       = title[:200],
            description = description[:2000],
            priority    = priority,
            status      = WorkflowStatus.DRAFT.value,
            created_by  = ctx.user.user_id,
        )
        self._db.create(wf)
        AuditLogger.log(
            event_type = "WORKFLOW_CREATED",
            event_data = {"workflow_id": wf.workflow_id, "title": title[:100]},
            severity   = "INFO",
            record_id  = record_id,
            agent_name = "workflow_engine",
        )
        return wf

    def submit(self, workflow_id: str, ctx: AuthContext, comment: str = "") -> WorkflowRecord:
        return self.transition(workflow_id, WorkflowAction.SUBMIT, ctx, comment)

    def approve(self, workflow_id: str, ctx: AuthContext, comment: str = "") -> WorkflowRecord:
        return self.transition(workflow_id, WorkflowAction.APPROVE, ctx, comment)

    def reject(self, workflow_id: str, ctx: AuthContext, comment: str = "") -> WorkflowRecord:
        return self.transition(workflow_id, WorkflowAction.REJECT, ctx, comment)

    def request_revision(self, workflow_id: str, ctx: AuthContext, comment: str = "") -> WorkflowRecord:
        return self.transition(workflow_id, WorkflowAction.REQUEST_REVISION, ctx, comment)

    def resubmit(self, workflow_id: str, ctx: AuthContext, comment: str = "") -> WorkflowRecord:
        return self.transition(workflow_id, WorkflowAction.RESUBMIT, ctx, comment)

    def get(self, workflow_id: str) -> WorkflowRecord:
        wf = self._db.get(workflow_id)
        if not wf:
            raise WorkflowNotFoundError(workflow_id)
        return wf

    def list_by_status(
        self,
        tenant_id: str,
        status:    Optional[WorkflowStatus] = None,
        limit:     int = 50,
    ) -> list[WorkflowRecord]:
        return self._db.list_by_tenant(tenant_id, status, limit)

    @staticmethod
    def _default_notify(wf: WorkflowRecord, action: WorkflowAction) -> None:
        log.info(
            f"[NOTIFY] Workflow '{wf.title[:40]}' → {wf.status} after '{action.value}'",
            extra={"workflow_id": wf.workflow_id},
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
