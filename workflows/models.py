"""
workflows/models.py — Approval Workflow Domain Models
======================================================
Implements a formal state machine for escalated analysis records.

State diagram:
  DRAFT ──► PENDING_REVIEW ──► APPROVED
                            ├──► REJECTED
                            └──► REVISION_REQUESTED ──► PENDING_REVIEW

Transitions are guarded: each requires a specific Permission and
produces an immutable HistoryEntry for the audit trail.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── State enumeration ─────────────────────────────────────────────────────────

class WorkflowStatus(str, Enum):
    DRAFT                = "DRAFT"
    PENDING_REVIEW       = "PENDING_REVIEW"
    REVISION_REQUESTED   = "REVISION_REQUESTED"
    APPROVED             = "APPROVED"
    REJECTED             = "REJECTED"


class WorkflowPriority(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"


class WorkflowAction(str, Enum):
    """Actions that drive state transitions."""
    SUBMIT           = "submit"            # DRAFT → PENDING_REVIEW
    APPROVE          = "approve"           # PENDING_REVIEW → APPROVED
    REJECT           = "reject"            # PENDING_REVIEW → REJECTED
    REQUEST_REVISION = "request_revision"  # PENDING_REVIEW → REVISION_REQUESTED
    RESUBMIT         = "resubmit"          # REVISION_REQUESTED → PENDING_REVIEW
    WITHDRAW         = "withdraw"          # Any non-terminal → DRAFT


# Valid transition table: (current_status, action) → next_status
VALID_TRANSITIONS: dict[tuple[WorkflowStatus, WorkflowAction], WorkflowStatus] = {
    (WorkflowStatus.DRAFT,              WorkflowAction.SUBMIT):           WorkflowStatus.PENDING_REVIEW,
    (WorkflowStatus.PENDING_REVIEW,     WorkflowAction.APPROVE):          WorkflowStatus.APPROVED,
    (WorkflowStatus.PENDING_REVIEW,     WorkflowAction.REJECT):           WorkflowStatus.REJECTED,
    (WorkflowStatus.PENDING_REVIEW,     WorkflowAction.REQUEST_REVISION): WorkflowStatus.REVISION_REQUESTED,
    (WorkflowStatus.REVISION_REQUESTED, WorkflowAction.RESUBMIT):        WorkflowStatus.PENDING_REVIEW,
    (WorkflowStatus.DRAFT,              WorkflowAction.WITHDRAW):         WorkflowStatus.DRAFT,
    (WorkflowStatus.PENDING_REVIEW,     WorkflowAction.WITHDRAW):         WorkflowStatus.DRAFT,
    (WorkflowStatus.REVISION_REQUESTED, WorkflowAction.WITHDRAW):        WorkflowStatus.DRAFT,
}

# Terminal states — no further transitions allowed
TERMINAL_STATES = {WorkflowStatus.APPROVED, WorkflowStatus.REJECTED}

# Required permission per action (maps to auth.models.Permission values)
ACTION_PERMISSIONS: dict[WorkflowAction, str] = {
    WorkflowAction.SUBMIT:           "workflows:create",
    WorkflowAction.APPROVE:          "workflows:approve",
    WorkflowAction.REJECT:           "workflows:approve",   # same gate
    WorkflowAction.REQUEST_REVISION: "workflows:approve",
    WorkflowAction.RESUBMIT:         "workflows:create",
    WorkflowAction.WITHDRAW:         "workflows:create",
}


# ── Domain dataclasses ────────────────────────────────────────────────────────

@dataclass
class WorkflowHistoryEntry:
    """Immutable audit record for a single state transition."""
    entry_id:     str  = field(default_factory=lambda: str(uuid.uuid4())[:8])
    workflow_id:  str  = ""
    action:       str  = ""
    from_status:  str  = ""
    to_status:    str  = ""
    actor_id:     str  = ""
    actor_name:   str  = ""
    comment:      str  = ""
    timestamp:    str  = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "entry_id":    self.entry_id,
            "workflow_id": self.workflow_id,
            "action":      self.action,
            "from_status": self.from_status,
            "to_status":   self.to_status,
            "actor_id":    self.actor_id,
            "actor_name":  self.actor_name,
            "comment":     self.comment,
            "timestamp":   self.timestamp,
        }


@dataclass
class WorkflowRecord:
    """A single approval workflow instance."""
    workflow_id:  str  = field(default_factory=lambda: str(uuid.uuid4()))
    run_id:       str  = ""
    record_id:    str  = ""
    tenant_id:    str  = "default"
    title:        str  = ""
    description:  str  = ""
    priority:     str  = WorkflowPriority.MEDIUM.value
    status:       str  = WorkflowStatus.DRAFT.value
    created_by:   str  = ""
    assigned_to:  str  = ""
    created_at:   str  = field(default_factory=_now)
    updated_at:   str  = field(default_factory=_now)
    resolved_at:  Optional[str] = None
    history:      list[WorkflowHistoryEntry] = field(default_factory=list)

    @property
    def status_enum(self) -> WorkflowStatus:
        return WorkflowStatus(self.status)

    @property
    def is_terminal(self) -> bool:
        return self.status_enum in TERMINAL_STATES

    @property
    def is_approved(self) -> bool:
        return self.status_enum == WorkflowStatus.APPROVED

    @property
    def is_rejected(self) -> bool:
        return self.status_enum == WorkflowStatus.REJECTED

    def available_actions(self) -> list[WorkflowAction]:
        """Return all valid actions from the current state."""
        return [
            action for (state, action) in VALID_TRANSITIONS
            if state == self.status_enum
        ]

    def to_dict(self) -> dict:
        return {
            "workflow_id":  self.workflow_id,
            "run_id":       self.run_id,
            "record_id":    self.record_id,
            "tenant_id":    self.tenant_id,
            "title":        self.title,
            "description":  self.description,
            "priority":     self.priority,
            "status":       self.status,
            "created_by":   self.created_by,
            "assigned_to":  self.assigned_to,
            "created_at":   self.created_at,
            "updated_at":   self.updated_at,
            "resolved_at":  self.resolved_at,
            "history":      [h.to_dict() for h in self.history],
        }


# ── Exceptions ────────────────────────────────────────────────────────────────

class WorkflowError(Exception):
    """Base workflow exception."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code

class InvalidTransitionError(WorkflowError):
    def __init__(self, current: str, action: str):
        super().__init__(
            f"Action '{action}' is not valid from state '{current}'.", 409
        )

class WorkflowTerminalError(WorkflowError):
    def __init__(self, status: str):
        super().__init__(
            f"Workflow is in terminal state '{status}' and cannot be modified.", 409
        )

class WorkflowNotFoundError(WorkflowError):
    def __init__(self, workflow_id: str):
        super().__init__(f"Workflow '{workflow_id}' not found.", 404)
