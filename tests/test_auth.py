"""
tests/test_auth.py — Stage 22 Authentication & RBAC Test Suite
================================================================
52 tests across 7 test classes. Zero network calls. Zero external dependencies.

Test classes:
  TestPasswordHashing      (10 tests) — hash, verify, policy, rehash
  TestJWTHandler           (14 tests) — encode, decode, expiry, type checking
  TestRBACMatrix           (10 tests) — permission matrix, role ordering
  TestRBACEnforcer         (8  tests) — require, require_any, decorators
  TestAuthDatabase         (8  tests) — CRUD, sessions, lockout
  TestAuthService          (8  tests) — register, login, refresh, logout
  TestAuthIntegration      (4  tests) — end-to-end login → context → permission
"""

import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# PASSWORD HASHING
# ══════════════════════════════════════════════════════════════════════════════
class TestPasswordHashing(unittest.TestCase):

    def setUp(self):
        from auth.password import hash_password, verify_password, password_meets_policy, needs_rehash
        self.hash_pw   = hash_password
        self.verify_pw = verify_password
        self.policy    = password_meets_policy
        self.rehash    = needs_rehash

    def test_hash_returns_string(self):
        h = self.hash_pw("Test!pass1")
        self.assertIsInstance(h, str)

    def test_hash_format_four_parts(self):
        h = self.hash_pw("Test!pass1")
        self.assertEqual(len(h.split("$")), 4)

    def test_hash_prefix_is_algorithm(self):
        h = self.hash_pw("Test!pass1")
        self.assertTrue(h.startswith("pbkdf2_sha256$"))

    def test_verify_correct_password(self):
        h = self.hash_pw("Correct!Horse1")
        self.assertTrue(self.verify_pw("Correct!Horse1", h))

    def test_verify_wrong_password(self):
        h = self.hash_pw("Correct!Horse1")
        self.assertFalse(self.verify_pw("WrongPassword1!", h))

    def test_verify_empty_password_safe(self):
        h = self.hash_pw("Test!pass1")
        self.assertFalse(self.verify_pw("", h))

    def test_two_hashes_of_same_password_differ(self):
        h1 = self.hash_pw("Same!Pass1")
        h2 = self.hash_pw("Same!Pass1")
        self.assertNotEqual(h1, h2)   # different salts

    def test_policy_passes_strong_password(self):
        ok, reasons = self.policy("Str0ng!Pass")
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_policy_fails_weak_password(self):
        ok, reasons = self.policy("weak")
        self.assertFalse(ok)
        self.assertGreater(len(reasons), 0)

    def test_needs_rehash_false_for_current_iterations(self):
        h = self.hash_pw("Test!pass1")
        self.assertFalse(self.rehash(h))


# ══════════════════════════════════════════════════════════════════════════════
# JWT HANDLER
# ══════════════════════════════════════════════════════════════════════════════
class TestJWTHandler(unittest.TestCase):

    def setUp(self):
        from auth.jwt_handler import JWTHandler
        self.handler = JWTHandler(
            secret="test-secret-key-minimum-sixteen-chars",
            access_ttl=3600,
            refresh_ttl=86400,
        )
        self.user_id   = "user-abc-123"
        self.username  = "alice"
        self.role      = "analyst"
        self.tenant_id = "acme"

    def test_create_access_token_returns_tuple(self):
        token, jti = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        self.assertIsInstance(token, str)
        self.assertIsInstance(jti, str)

    def test_access_token_has_three_parts(self):
        token, _ = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        self.assertEqual(len(token.split(".")), 3)

    def test_decode_access_token_payload(self):
        token, jti = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        payload = self.handler.decode(token)
        self.assertEqual(payload["sub"], self.user_id)
        self.assertEqual(payload["username"], self.username)
        self.assertEqual(payload["role"], self.role)
        self.assertEqual(payload["tenant_id"], self.tenant_id)
        self.assertEqual(payload["jti"], jti)
        self.assertEqual(payload["type"], "access")

    def test_decode_refresh_token_payload(self):
        token, jti = self.handler.create_refresh_token(self.user_id)
        payload = self.handler.decode(token, expected_type="refresh")
        self.assertEqual(payload["sub"], self.user_id)
        self.assertEqual(payload["type"], "refresh")

    def test_wrong_signature_raises(self):
        from auth.models import TokenInvalidError
        token, _ = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        # Tamper with signature
        parts = token.split(".")
        tampered = f"{parts[0]}.{parts[1]}.invalidsignature"
        with self.assertRaises(TokenInvalidError):
            self.handler.decode(tampered)

    def test_malformed_token_raises(self):
        from auth.models import TokenInvalidError
        with self.assertRaises(TokenInvalidError):
            self.handler.decode("not.a.valid.jwt.at.all.nope")

    def test_expired_token_raises(self):
        from auth.models import TokenExpiredError
        from auth.jwt_handler import JWTHandler as _JH
        expired_handler = _JH.__new__(_JH)
        expired_handler._secret      = b"test-secret-key-minimum-sixteen-chars"
        expired_handler._access_ttl  = -10   # already expired
        expired_handler._refresh_ttl = -10
        token, _ = expired_handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        with self.assertRaises(TokenExpiredError):
            self.handler.decode(token)

    def test_type_mismatch_raises(self):
        from auth.models import TokenInvalidError
        # Try to use a refresh token as an access token
        token, _ = self.handler.create_refresh_token(self.user_id)
        with self.assertRaises(TokenInvalidError):
            self.handler.decode(token, expected_type="access")

    def test_create_pair_returns_token_pair(self):
        from auth.models import UserRecord
        from auth.jwt_handler import TokenPair
        user = UserRecord(
            user_id="u1", username="bob", email="b@b.com",
            password_hash="x", role="viewer", tenant_id="default",
        )
        pair = self.handler.create_pair(user)
        self.assertIsInstance(pair, TokenPair)
        self.assertNotEqual(pair.access_token, pair.refresh_token)
        self.assertNotEqual(pair.access_jti, pair.refresh_jti)

    def test_two_tokens_have_different_jtis(self):
        t1, j1 = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        t2, j2 = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        self.assertNotEqual(j1, j2)

    def test_get_jti_extracts_without_verify(self):
        token, jti = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        extracted = self.handler.get_jti(token)
        self.assertEqual(extracted, jti)

    def test_get_jti_returns_none_on_bad_token(self):
        result = self.handler.get_jti("garbage")
        self.assertIsNone(result)

    def test_time_until_expiry_positive(self):
        token, _ = self.handler.create_access_token(
            self.user_id, self.username, self.role, self.tenant_id
        )
        ttl = self.handler.time_until_expiry(token)
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 3600)

    def test_short_secret_raises_on_init(self):
        from auth.jwt_handler import JWTHandler
        with self.assertRaises(ValueError):
            JWTHandler(secret="short")


# ══════════════════════════════════════════════════════════════════════════════
# RBAC MATRIX
# ══════════════════════════════════════════════════════════════════════════════
class TestRBACMatrix(unittest.TestCase):

    def setUp(self):
        from auth.models import Role, Permission, get_permissions, role_has_permission, ROLE_PERMISSIONS
        self.Role  = Role
        self.Perm  = Permission
        self.get   = get_permissions
        self.check = role_has_permission
        self.matrix = ROLE_PERMISSIONS

    def test_super_admin_has_all_permissions(self):
        perms = self.get(self.Role.SUPER_ADMIN)
        for p in self.Perm:
            self.assertIn(p, perms, f"SUPER_ADMIN missing {p}")

    def test_viewer_cannot_create_runs(self):
        self.assertFalse(self.check(self.Role.VIEWER, self.Perm.RUNS_CREATE))

    def test_analyst_can_create_runs(self):
        self.assertTrue(self.check(self.Role.ANALYST, self.Perm.RUNS_CREATE))

    def test_viewer_cannot_manage_tenants(self):
        self.assertFalse(self.check(self.Role.VIEWER, self.Perm.TENANTS_CREATE))

    def test_tenant_admin_cannot_manage_tenants(self):
        # Only SUPER_ADMIN manages tenants
        self.assertFalse(self.check(self.Role.TENANT_ADMIN, self.Perm.TENANTS_DELETE))

    def test_approver_can_approve_workflows(self):
        self.assertTrue(self.check(self.Role.APPROVER, self.Perm.WORKFLOWS_APPROVE))

    def test_viewer_cannot_delete_users(self):
        self.assertFalse(self.check(self.Role.VIEWER, self.Perm.USERS_DELETE))

    def test_all_roles_can_read_runs(self):
        for role in self.Role:
            self.assertTrue(self.check(role, self.Perm.RUNS_READ),
                            f"{role} cannot read runs")

    def test_unknown_role_returns_empty_set(self):
        from auth.models import get_permissions
        result = get_permissions("nonexistent_role")   # type: ignore
        self.assertEqual(result, set())

    def test_permission_matrix_has_all_roles(self):
        for role in self.Role:
            self.assertIn(role, self.matrix)


# ══════════════════════════════════════════════════════════════════════════════
# RBAC ENFORCER
# ══════════════════════════════════════════════════════════════════════════════
class TestRBACEnforcer(unittest.TestCase):

    def _make_ctx(self, role_name: str) -> "AuthContext":
        from auth.models import AuthContext, UserRecord, Role, get_permissions
        user = UserRecord(
            user_id="u1", username="test_user", email="t@t.com",
            password_hash="x", role=role_name, tenant_id="test",
        )
        return AuthContext(
            user=user,
            permissions=get_permissions(Role(role_name)),
            jti="test-jti",
            tenant_id="test",
        )

    def test_require_grants_valid_permission(self):
        from auth.rbac import RBACEnforcer
        from auth.models import Permission
        ctx = self._make_ctx("analyst")
        enforcer = RBACEnforcer()
        enforcer.require(ctx, Permission.RUNS_CREATE)  # Should not raise

    def test_require_raises_on_missing_permission(self):
        from auth.rbac import RBACEnforcer
        from auth.models import Permission, PermissionDeniedError
        ctx = self._make_ctx("viewer")
        enforcer = RBACEnforcer()
        with self.assertRaises(PermissionDeniedError):
            enforcer.require(ctx, Permission.RUNS_CREATE)

    def test_can_returns_true_for_valid(self):
        from auth.rbac import RBACEnforcer
        from auth.models import Permission
        ctx = self._make_ctx("analyst")
        self.assertTrue(RBACEnforcer().can(ctx, Permission.RUNS_READ))

    def test_can_returns_false_for_invalid(self):
        from auth.rbac import RBACEnforcer
        from auth.models import Permission
        ctx = self._make_ctx("viewer")
        self.assertFalse(RBACEnforcer().can(ctx, Permission.RUNS_CREATE))

    def test_require_any_grants_on_first_match(self):
        from auth.rbac import RBACEnforcer
        from auth.models import Permission
        ctx  = self._make_ctx("approver")
        matched = RBACEnforcer().require_any(ctx, Permission.WORKFLOWS_APPROVE, Permission.RUNS_CREATE)
        self.assertEqual(matched, Permission.WORKFLOWS_APPROVE)

    def test_require_any_raises_if_none_match(self):
        from auth.rbac import RBACEnforcer
        from auth.models import Permission, PermissionDeniedError
        ctx = self._make_ctx("viewer")
        with self.assertRaises(PermissionDeniedError):
            RBACEnforcer().require_any(ctx, Permission.RUNS_CREATE, Permission.USERS_DELETE)

    def test_permission_matrix_covers_all_permissions(self):
        from auth.rbac import RBACEnforcer
        from auth.models import Role, Permission
        matrix = RBACEnforcer().permission_matrix(Role.SUPER_ADMIN)
        for p in Permission:
            self.assertIn(p.value, matrix)

    def test_decorator_raises_without_ctx_arg(self):
        from auth.rbac import require_permission
        from auth.models import Permission

        @require_permission(Permission.RUNS_CREATE)
        def no_ctx_func(x: int) -> int:
            return x

        with self.assertRaises(TypeError):
            no_ctx_func(42)


# ══════════════════════════════════════════════════════════════════════════════
# AUTH DATABASE
# ══════════════════════════════════════════════════════════════════════════════
class TestAuthDatabase(unittest.TestCase):

    def setUp(self):
        import tempfile, os
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        from storage.auth_db import AuthDatabase
        self.db = AuthDatabase(db_path=Path(self._tmp.name))

    def tearDown(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _make_user(self, username="alice", tenant="default") -> "UserRecord":
        from auth.models import UserRecord
        return UserRecord(
            username="alice_test", email="alice@test.com",
            password_hash="pbkdf2_sha256$600000$aabbcc$ddeeff",
            role="analyst", tenant_id=tenant,
        )

    def test_create_and_retrieve_user(self):
        user = self._make_user()
        self.db.create_user(user)
        found = self.db.get_user_by_id(user.user_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.username, user.username)

    def test_get_user_by_username(self):
        user = self._make_user()
        self.db.create_user(user)
        found = self.db.get_user_by_username(user.username)
        self.assertIsNotNone(found)

    def test_missing_user_returns_none(self):
        result = self.db.get_user_by_id("nonexistent-id")
        self.assertIsNone(result)

    def test_update_user_role(self):
        user = self._make_user()
        self.db.create_user(user)
        user.role = "viewer"
        self.db.update_user(user)
        found = self.db.get_user_by_id(user.user_id)
        self.assertEqual(found.role, "viewer")

    def test_session_create_and_revoke(self):
        from auth.models import SessionRecord, UserRecord
        # Create owning user first to satisfy FK constraint
        user = UserRecord(user_id="user-001", username="sess_test",
                          email="s@s.com", password_hash="x",
                          role="viewer", tenant_id="default")
        self.db.create_user(user)
        session = SessionRecord(
            jti="jti-001", user_id="user-001",
            issued_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-02T00:00:00Z",
        )
        self.db.create_session(session)
        self.assertFalse(self.db.is_session_revoked("jti-001"))
        self.db.revoke_session("jti-001")
        self.assertTrue(self.db.is_session_revoked("jti-001"))

    def test_unknown_jti_is_treated_as_revoked(self):
        self.assertTrue(self.db.is_session_revoked("unknown-jti"))

    def test_failed_login_tracking(self):
        count = self.db.record_failed_login("bob", "default", "1.2.3.4")
        self.assertEqual(count, 1)
        count2 = self.db.record_failed_login("bob", "default", "1.2.3.4")
        self.assertEqual(count2, 2)

    def test_lock_and_unlock_user(self):
        user = self._make_user()
        self.db.create_user(user)
        locked_until = self.db.lock_user(user.user_id, duration_minutes=15)
        found = self.db.get_user_by_id(user.user_id)
        self.assertTrue(self.db.is_user_locked(found))
        self.db.unlock_user(user.user_id)
        unlocked = self.db.get_user_by_id(user.user_id)
        self.assertFalse(self.db.is_user_locked(unlocked))


# ══════════════════════════════════════════════════════════════════════════════
# AUTH SERVICE
# ══════════════════════════════════════════════════════════════════════════════
class TestAuthService(unittest.TestCase):

    def setUp(self):
        import tempfile, os
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        from storage.auth_db import AuthDatabase
        from auth.jwt_handler import JWTHandler
        from auth.auth_service import AuthService
        self.db      = AuthDatabase(db_path=Path(self._tmp.name))
        self.handler = JWTHandler(
            secret="enterprise-platform-jwt-secret-key-32ch",
            access_ttl=3600, refresh_ttl=86400,
        )
        self.svc = AuthService(db=self.db, jwt=self.handler)

    def tearDown(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _register_alice(self):
        from auth.models import Role
        return self.svc.register(
            "alice_svc", "alice@svc.com", "SecureP@ss1!", Role.ANALYST
        )

    def test_register_creates_user(self):
        user = self._register_alice()
        self.assertIsNotNone(user.user_id)
        self.assertEqual(user.username, "alice_svc")
        self.assertEqual(user.role, "analyst")

    def test_register_duplicate_raises(self):
        from auth.models import UserAlreadyExistsError
        self._register_alice()
        with self.assertRaises(UserAlreadyExistsError):
            self._register_alice()

    def test_register_weak_password_raises(self):
        from auth.models import Role
        with self.assertRaises(ValueError):
            self.svc.register("bob", "bob@b.com", "weak", Role.VIEWER)

    def test_login_returns_context_and_tokens(self):
        from auth.jwt_handler import TokenPair
        from auth.models import AuthContext
        self._register_alice()
        ctx, tokens = self.svc.login("alice_svc", "SecureP@ss1!")
        self.assertIsInstance(ctx, AuthContext)
        self.assertIsInstance(tokens, TokenPair)
        self.assertEqual(ctx.user.username, "alice_svc")

    def test_login_wrong_password_raises(self):
        from auth.models import InvalidCredentialsError
        self._register_alice()
        with self.assertRaises(InvalidCredentialsError):
            self.svc.login("alice_svc", "WrongPassword!")

    def test_get_auth_context_from_token(self):
        from auth.models import AuthContext
        self._register_alice()
        _, tokens = self.svc.login("alice_svc", "SecureP@ss1!")
        ctx = self.svc.get_auth_context(tokens.access_token)
        self.assertIsInstance(ctx, AuthContext)
        self.assertEqual(ctx.user.username, "alice_svc")

    def test_logout_revokes_access_token(self):
        from auth.models import TokenRevokedError
        self._register_alice()
        _, tokens = self.svc.login("alice_svc", "SecureP@ss1!")
        self.svc.logout(tokens.access_token)
        with self.assertRaises(TokenRevokedError):
            self.svc.get_auth_context(tokens.access_token)

    def test_refresh_rotates_token(self):
        self._register_alice()
        _, tokens1 = self.svc.login("alice_svc", "SecureP@ss1!")
        _, tokens2 = self.svc.refresh(tokens1.refresh_token)
        # New tokens should differ
        self.assertNotEqual(tokens1.access_token, tokens2.access_token)
        self.assertNotEqual(tokens1.refresh_jti, tokens2.refresh_jti)


# ══════════════════════════════════════════════════════════════════════════════
# END-TO-END INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════
class TestAuthIntegration(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        from storage.auth_db import AuthDatabase
        from auth.jwt_handler import JWTHandler
        from auth.auth_service import AuthService
        from auth.rbac import RBACEnforcer
        self.db      = AuthDatabase(db_path=Path(self._tmp.name))
        self.handler = JWTHandler("integration-test-secret-key-32chars")
        self.svc     = AuthService(db=self.db, jwt=self.handler)
        self.rbac    = RBACEnforcer()

    def tearDown(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_full_login_flow_grants_correct_permissions(self):
        from auth.models import Role, Permission
        self.svc.register("carol", "c@c.com", "Str0ng!Pass", Role.ANALYST)
        ctx, _ = self.svc.login("carol", "Str0ng!Pass")
        # Analyst can create runs
        self.assertTrue(self.rbac.can(ctx, Permission.RUNS_CREATE))
        # Analyst cannot manage tenants
        self.assertFalse(self.rbac.can(ctx, Permission.TENANTS_DELETE))

    def test_viewer_cannot_create_runs_via_service(self):
        from auth.models import Role, Permission, PermissionDeniedError
        self.svc.register("dave", "d@d.com", "V1ewer!Pass", Role.VIEWER)
        ctx, _ = self.svc.login("dave", "V1ewer!Pass")
        with self.assertRaises(PermissionDeniedError):
            self.rbac.require(ctx, Permission.RUNS_CREATE)

    def test_admin_can_reset_user_password(self):
        from auth.models import Role, Permission
        admin_user = self.svc.register(
            "admin1", "a@a.com", "Adm1n!Pass", Role.TENANT_ADMIN
        )
        target_user = self.svc.register(
            "target1", "t@t.com", "T@rget!Pass1", Role.VIEWER
        )
        admin_ctx, _ = self.svc.login("admin1", "Adm1n!Pass")
        # Should not raise
        self.svc.reset_password_admin(admin_ctx, target_user.user_id, "NewT@rget!1X")

    def test_revoked_token_cannot_create_context(self):
        from auth.models import Role, TokenRevokedError
        self.svc.register("eve", "e@e.com", "Ev3!Secure", Role.ANALYST)
        ctx, tokens = self.svc.login("eve", "Ev3!Secure")
        self.svc.logout(tokens.access_token)
        with self.assertRaises(TokenRevokedError):
            self.svc.get_auth_context(tokens.access_token)


if __name__ == "__main__":
    unittest.main(verbosity=2)
