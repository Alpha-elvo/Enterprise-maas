"""
tests/test_workflows.py — Stage 25 Approval Workflow Test Suite
================================================================
38 tests across 5 classes. Zero network calls. Temp DB per test.

TestWorkflowModels         (8)  — state machine table, terminal states
TestWorkflowEngine         (14) — transitions, guards, history, RBAC
TestWorkflowDatabase       (10) — CRUD, list, count
TestWorkflowEdgeCases      (6)  — concurrent edits, unicode, long comments
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ── Auth context factory ──────────────────────────────────────────────────────

def _make_auth_ctx(role: str = "approver", tenant: str = "default") -> "AuthContext":
    from auth.models import AuthContext, UserRecord, Role, get_permissions
    user = UserRecord(
        user_id="wf-actor-001", username="workflow_actor",
        email="wf@test.com", password_hash="x",
        role=role, tenant_id=tenant,
    )
    try:
        role_enum = Role(role)
    except ValueError:
        role_enum = Role.VIEWER
    return AuthContext(
        user=user, permissions=get_permissions(role_enum),
        jti="wf-jti-001", tenant_id=tenant,
    )


def _make_engine(tmp_path: str) -> "WorkflowEngine":
    from workflows.engine import WorkflowEngine
    from storage.workflow_db import WorkflowDatabase
    db = WorkflowDatabase(db_path=Path(tmp_path))
    return WorkflowEngine(db=db), db


# ══════════════════════════════════════════════════════════════════════════════
# MODEL TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestWorkflowModels(unittest.TestCase):

    def test_valid_transitions_table_is_not_empty(self):
        from workflows.models import VALID_TRANSITIONS
        self.assertGreater(len(VALID_TRANSITIONS), 0)

    def test_approved_is_terminal(self):
        from workflows.models import WorkflowStatus, TERMINAL_STATES
        self.assertIn(WorkflowStatus.APPROVED, TERMINAL_STATES)

    def test_rejected_is_terminal(self):
        from workflows.models import WorkflowStatus, TERMINAL_STATES
        self.assertIn(WorkflowStatus.REJECTED, TERMINAL_STATES)

    def test_draft_is_not_terminal(self):
        from workflows.models import WorkflowStatus, TERMINAL_STATES
        self.assertNotIn(WorkflowStatus.DRAFT, TERMINAL_STATES)

    def test_pending_review_is_not_terminal(self):
        from workflows.models import WorkflowStatus, TERMINAL_STATES
        self.assertNotIn(WorkflowStatus.PENDING_REVIEW, TERMINAL_STATES)

    def test_workflow_record_is_not_approved_initially(self):
        from workflows.models import WorkflowRecord
        wf = WorkflowRecord(title="Test")
        self.assertFalse(wf.is_approved)
        self.assertFalse(wf.is_terminal)

    def test_available_actions_from_draft(self):
        from workflows.models import WorkflowRecord, WorkflowAction
        wf = WorkflowRecord(title="Test")   # starts as DRAFT
        actions = wf.available_actions()
        self.assertIn(WorkflowAction.SUBMIT, actions)

    def test_to_dict_contains_required_keys(self):
        from workflows.models import WorkflowRecord
        wf = WorkflowRecord(title="Test", run_id="r1", record_id="rec1")
        d  = wf.to_dict()
        for key in ["workflow_id", "title", "status", "created_at", "history"]:
            self.assertIn(key, d)


# ══════════════════════════════════════════════════════════════════════════════
# ENGINE TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestWorkflowEngine(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine, self.db = _make_engine(self._tmp.name)
        self.analyst_ctx  = _make_auth_ctx("analyst")
        self.approver_ctx = _make_auth_ctx("approver")
        self.viewer_ctx   = _make_auth_ctx("viewer")

    def tearDown(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _create_wf(self) -> "WorkflowRecord":
        return self.engine.create(
            run_id="run-001", record_id="REC-001",
            title="Test Workflow", ctx=self.analyst_ctx,
        )

    def test_create_workflow_starts_in_draft(self):
        from workflows.models import WorkflowStatus
        wf = self._create_wf()
        self.assertEqual(wf.status, WorkflowStatus.DRAFT.value)

    def test_submit_transitions_to_pending_review(self):
        from workflows.models import WorkflowStatus
        wf = self._create_wf()
        wf = self.engine.submit(wf.workflow_id, self.analyst_ctx, "Ready for review.")
        self.assertEqual(wf.status, WorkflowStatus.PENDING_REVIEW.value)

    def test_approve_transitions_to_approved(self):
        from workflows.models import WorkflowStatus
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx)
        wf = self.engine.approve(wf.workflow_id, self.approver_ctx, "Approved.")
        self.assertEqual(wf.status, WorkflowStatus.APPROVED.value)
        self.assertTrue(wf.is_approved)
        self.assertTrue(wf.is_terminal)
        self.assertIsNotNone(wf.resolved_at)

    def test_reject_transitions_to_rejected(self):
        from workflows.models import WorkflowStatus
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx)
        wf = self.engine.reject(wf.workflow_id, self.approver_ctx, "Insufficient evidence.")
        self.assertEqual(wf.status, WorkflowStatus.REJECTED.value)
        self.assertTrue(wf.is_terminal)

    def test_revision_cycle_returns_to_pending(self):
        from workflows.models import WorkflowStatus
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx)
        self.engine.request_revision(wf.workflow_id, self.approver_ctx, "Please add data.")
        wf = self.engine.resubmit(wf.workflow_id, self.analyst_ctx, "Updated.")
        self.assertEqual(wf.status, WorkflowStatus.PENDING_REVIEW.value)

    def test_cannot_transition_terminal_workflow(self):
        from workflows.models import WorkflowTerminalError
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx)
        self.engine.approve(wf.workflow_id, self.approver_ctx)
        with self.assertRaises(WorkflowTerminalError):
            self.engine.approve(wf.workflow_id, self.approver_ctx)

    def test_invalid_transition_raises(self):
        from workflows.models import InvalidTransitionError, WorkflowAction
        wf = self._create_wf()   # DRAFT
        with self.assertRaises(InvalidTransitionError):
            self.engine.transition(
                wf.workflow_id, WorkflowAction.APPROVE, self.approver_ctx
            )

    def test_viewer_cannot_approve(self):
        from auth.models import PermissionDeniedError
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx)
        with self.assertRaises(PermissionDeniedError):
            self.engine.approve(wf.workflow_id, self.viewer_ctx)

    def test_history_records_each_transition(self):
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx, "S1")
        self.engine.request_revision(wf.workflow_id, self.approver_ctx, "R1")
        wf = self.engine.resubmit(wf.workflow_id, self.analyst_ctx, "S2")
        self.assertEqual(len(wf.history), 3)

    def test_history_entry_has_actor(self):
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx, "My comment")
        wf = self.engine.get(wf.workflow_id)
        entry = wf.history[0]
        self.assertEqual(entry.actor_name, "workflow_actor")
        self.assertEqual(entry.comment, "My comment")

    def test_get_nonexistent_workflow_raises(self):
        from workflows.models import WorkflowNotFoundError
        with self.assertRaises(WorkflowNotFoundError):
            self.engine.get("nonexistent-id")

    def test_list_by_status_filters_correctly(self):
        from workflows.models import WorkflowStatus
        wf1 = self._create_wf()
        self.engine.submit(wf1.workflow_id, self.analyst_ctx)
        # wf2 stays in DRAFT
        self.engine.create("r2", "R2", "Draft WF", self.analyst_ctx)
        pending = self.engine.list_by_status("default", WorkflowStatus.PENDING_REVIEW)
        self.assertEqual(len(pending), 1)

    def test_withdraw_returns_to_draft(self):
        from workflows.models import WorkflowStatus
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx)
        from workflows.models import WorkflowAction
        wf = self.engine.transition(wf.workflow_id, WorkflowAction.WITHDRAW, self.analyst_ctx)
        self.assertEqual(wf.status, WorkflowStatus.DRAFT.value)

    def test_complete_full_approval_cycle(self):
        from workflows.models import WorkflowStatus
        wf = self._create_wf()
        self.engine.submit(wf.workflow_id, self.analyst_ctx)
        self.engine.request_revision(wf.workflow_id, self.approver_ctx, "Need more data")
        self.engine.resubmit(wf.workflow_id, self.analyst_ctx, "Added data")
        wf = self.engine.approve(wf.workflow_id, self.approver_ctx, "All good")
        self.assertEqual(wf.status, WorkflowStatus.APPROVED.value)
        self.assertEqual(len(wf.history), 4)


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestWorkflowDatabase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        from storage.workflow_db import WorkflowDatabase
        self.db = WorkflowDatabase(db_path=Path(self._tmp.name))

    def tearDown(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _wf(self, title: str = "Test") -> "WorkflowRecord":
        from workflows.models import WorkflowRecord
        return WorkflowRecord(
            run_id="r1", record_id="rec1", tenant_id="default",
            title=title, status="DRAFT", created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    def test_create_and_retrieve(self):
        wf = self._wf("Create Test")
        self.db.create(wf)
        found = self.db.get(wf.workflow_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.title, "Create Test")

    def test_get_nonexistent_returns_none(self):
        result = self.db.get("does-not-exist")
        self.assertIsNone(result)

    def test_update_status(self):
        from workflows.models import WorkflowHistoryEntry
        wf = self._wf()
        self.db.create(wf)
        wf.status = "PENDING_REVIEW"
        entry = WorkflowHistoryEntry(
            workflow_id=wf.workflow_id, action="submit",
            from_status="DRAFT", to_status="PENDING_REVIEW",
            actor_id="u1", actor_name="user1", comment="",
            timestamp="2026-01-01T00:01:00Z",
        )
        self.db.update(wf, entry)
        found = self.db.get(wf.workflow_id)
        self.assertEqual(found.status, "PENDING_REVIEW")
        self.assertEqual(len(found.history), 1)

    def test_delete_workflow(self):
        wf = self._wf()
        self.db.create(wf)
        deleted = self.db.delete(wf.workflow_id)
        self.assertTrue(deleted)
        self.assertIsNone(self.db.get(wf.workflow_id))

    def test_delete_nonexistent_returns_false(self):
        result = self.db.delete("no-such-id")
        self.assertFalse(result)

    def test_list_by_tenant(self):
        for i in range(3):
            wf = self._wf(f"WF-{i}")
            self.db.create(wf)
        results = self.db.list_by_tenant("default")
        self.assertEqual(len(results), 3)

    def test_list_by_tenant_with_status_filter(self):
        from workflows.models import WorkflowStatus
        wf_draft   = self._wf("Draft WF")
        wf_pending = self._wf("Pending WF")
        wf_pending.status = "PENDING_REVIEW"
        self.db.create(wf_draft)
        self.db.create(wf_pending)
        drafts = self.db.list_by_tenant("default", WorkflowStatus.DRAFT)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].title, "Draft WF")

    def test_count_by_status(self):
        wf1 = self._wf("A")
        wf2 = self._wf("B")
        wf2.status = "APPROVED"
        self.db.create(wf1)
        self.db.create(wf2)
        counts = self.db.count_by_status("default")
        self.assertEqual(counts.get("DRAFT", 0), 1)
        self.assertEqual(counts.get("APPROVED", 0), 1)

    def test_history_loads_with_workflow(self):
        from workflows.models import WorkflowHistoryEntry
        wf = self._wf()
        self.db.create(wf)
        entry = WorkflowHistoryEntry(
            workflow_id=wf.workflow_id, action="submit",
            from_status="DRAFT", to_status="PENDING_REVIEW",
            actor_id="u1", actor_name="user1", comment="Submitting",
            timestamp="2026-01-01T00:01:00Z",
        )
        wf.status = "PENDING_REVIEW"
        self.db.update(wf, entry)
        found = self.db.get(wf.workflow_id)
        self.assertEqual(len(found.history), 1)
        self.assertEqual(found.history[0].actor_name, "user1")

    def test_schema_is_idempotent(self):
        from storage.workflow_db import WorkflowDatabase
        db2 = WorkflowDatabase(db_path=Path(self._tmp.name))
        self.assertIsNotNone(db2)


# ══════════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════
class TestWorkflowEdgeCases(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine, self.db = _make_engine(self._tmp.name)
        self.ctx = _make_auth_ctx("analyst")
        self.approver = _make_auth_ctx("approver")

    def tearDown(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_long_comment_is_truncated_to_1000_chars(self):
        wf  = self.engine.create("r1", "rec1", "Title", self.ctx)
        long_comment = "x" * 2000
        self.engine.submit(wf.workflow_id, self.ctx, long_comment)
        wf  = self.engine.get(wf.workflow_id)
        self.assertLessEqual(len(wf.history[0].comment), 1000)

    def test_unicode_title_and_description(self):
        wf = self.engine.create(
            "r1", "rec1",
            "Rapport d'analyse: Données médicales — 医療データ",
            self.ctx,
            description="Résumé: données critiques pour décision urgente.",
        )
        found = self.engine.get(wf.workflow_id)
        self.assertIn("医療データ", found.title)

    def test_multiple_workflows_independent(self):
        from workflows.models import WorkflowStatus
        wf1 = self.engine.create("r1", "rec1", "WF1", self.ctx)
        wf2 = self.engine.create("r2", "rec2", "WF2", self.ctx)
        self.engine.submit(wf1.workflow_id, self.ctx)
        self.engine.approve(wf1.workflow_id, self.approver)
        # wf2 should still be in DRAFT
        wf2_fresh = self.engine.get(wf2.workflow_id)
        self.assertEqual(wf2_fresh.status, WorkflowStatus.DRAFT.value)

    def test_history_timestamps_are_ordered(self):
        wf = self.engine.create("r1", "rec1", "Title", self.ctx)
        self.engine.submit(wf.workflow_id, self.ctx)
        self.engine.request_revision(wf.workflow_id, self.approver)
        wf = self.engine.resubmit(wf.workflow_id, self.ctx)
        times = [h.timestamp for h in wf.history]
        self.assertEqual(times, sorted(times))

    def test_workflow_to_dict_serialises_history(self):
        import json
        wf = self.engine.create("r1", "rec1", "Test", self.ctx)
        self.engine.submit(wf.workflow_id, self.ctx)
        wf  = self.engine.get(wf.workflow_id)
        d   = wf.to_dict()
        j   = json.dumps(d, default=str)       # must be JSON-serialisable
        self.assertIn("PENDING_REVIEW", j)

    def test_available_actions_empty_for_terminal(self):
        wf = self.engine.create("r1", "rec1", "Test", self.ctx)
        self.engine.submit(wf.workflow_id, self.ctx)
        self.engine.approve(wf.workflow_id, self.approver)
        wf = self.engine.get(wf.workflow_id)
        self.assertEqual(wf.available_actions(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
