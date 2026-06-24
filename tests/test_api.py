"""
tests/test_api.py — Stage 23 FastAPI REST API Test Suite
=========================================================
Tests cover schemas, dependencies logic, and route contract validation.
All tests that require FastAPI are auto-skipped if it isn't installed.
Auth / DB logic is tested via unit mocks — no server needed.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    import fastapi
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

_SKIP = unittest.skipUnless(_HAS_FASTAPI, "FastAPI not installed")


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA VALIDATION (no FastAPI required — pure Pydantic)
# ══════════════════════════════════════════════════════════════════════════════

class TestAPISchemas(unittest.TestCase):
    """Validate Pydantic schemas independently of FastAPI."""

    def setUp(self):
        try:
            import pydantic
            self._pydantic = True
        except ImportError:
            self._pydantic = False

    def test_login_request_strips_whitespace(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import LoginRequest
        req = LoginRequest(username=" alice ", password="secret", tenant_id="corp")
        self.assertEqual(req.username, "alice")

    def test_run_create_request_default_threshold(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import RunCreateRequest
        req = RunCreateRequest()
        self.assertEqual(req.threshold, 7)

    def test_domain_record_input_validates_payload_length(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import DomainRecordInput
        try:
            from pydantic import ValidationError
            with self.assertRaises(ValidationError):
                DomainRecordInput(record_id="R1", domain="Test", payload="short")
        except ImportError:
            self.skipTest("Pydantic ValidationError not available")

    def test_pagination_params_offset(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import PaginationParams
        p = PaginationParams(page=3, per_page=20)
        self.assertEqual(p.offset, 40)

    def test_error_response_defaults(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import ErrorResponse
        err = ErrorResponse(error="NotFound")
        self.assertEqual(err.code, 400)
        self.assertEqual(err.detail, "")

    def test_workflow_action_valid_values(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import WorkflowActionRequest
        req = WorkflowActionRequest(action="approve", comment="Looks good")
        self.assertEqual(req.action, "approve")

    def test_token_response_default_type(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import TokenResponse
        t = TokenResponse(
            access_token="a", refresh_token="r",
            expires_in=1800, user={}
        )
        self.assertEqual(t.token_type, "bearer")

    def test_analytics_response_defaults(self):
        if not self._pydantic:
            self.skipTest("Pydantic not installed")
        from api.schemas import AnalyticsResponse
        a = AnalyticsResponse(
            tenant_id="t1", period_days=30, total_runs=5,
            total_records=25, escalation_rate=0.6, avg_impact_score=7.2
        )
        self.assertEqual(a.domain_breakdown, {})
        self.assertEqual(a.top_risks, [])


# ══════════════════════════════════════════════════════════════════════════════
# DEPENDENCIES (business logic, no HTTP layer)
# ══════════════════════════════════════════════════════════════════════════════

class TestDependencies(unittest.TestCase):

    def test_singleton_jwt_handler_is_reused(self):
        from api.dependencies import _jwt_handler
        h1 = _jwt_handler()
        h2 = _jwt_handler()
        self.assertIs(h1, h2)

    def test_get_auth_service_returns_auth_service(self):
        from api.dependencies import get_auth_service
        from auth.auth_service import AuthService
        svc = get_auth_service()
        self.assertIsInstance(svc, AuthService)

    def test_get_db_returns_database(self):
        from api.dependencies import get_db
        from storage.database import Database
        db = get_db()
        self.assertIsInstance(db, Database)


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI CLIENT TESTS
# ══════════════════════════════════════════════════════════════════════════════

@_SKIP
class TestHealthEndpoint(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from api.main import create_app
        cls.client = TestClient(create_app())

    def test_health_returns_200(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("version", data)

    def test_root_returns_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_openapi_schema_is_available(self):
        resp = self.client.get("/api/openapi.json")
        self.assertEqual(resp.status_code, 200)
        schema = resp.json()
        self.assertIn("paths", schema)
        self.assertIn("components", schema)


@_SKIP
class TestAuthEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        from fastapi.testclient import TestClient
        from api.dependencies import _auth_db, _jwt_handler, get_auth_service
        from storage.auth_db import AuthDatabase
        from auth.jwt_handler import JWTHandler
        from auth.auth_service import AuthService

        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        _db      = AuthDatabase(db_path=Path(cls._tmp.name))
        _jwt     = JWTHandler("test-api-secret-key-minimum-32chars")
        _svc     = AuthService(db=_db, jwt=_jwt)

        from api.main import create_app
        app = create_app()
        app.dependency_overrides[get_auth_service] = lambda: _svc

        cls.client = TestClient(app)
        cls._svc   = _svc

    @classmethod
    def tearDownClass(cls):
        import os
        try:
            os.unlink(cls._tmp.name)
        except OSError:
            pass

    def test_register_and_login(self):
        # Register
        resp = self.client.post("/api/v1/auth/register", json={
            "username":  "testuser_api",
            "email":     "api@test.com",
            "password":  "ApiT3st!Pass",
            "role":      "analyst",
            "tenant_id": "default",
        })
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)

    def test_login_wrong_password_returns_401(self):
        # Register first
        self.client.post("/api/v1/auth/register", json={
            "username": "wrong_pw_user",
            "email": "w@w.com",
            "password": "Valid!Pass1",
            "role": "viewer",
        })
        resp = self.client.post("/api/v1/auth/login", json={
            "username": "wrong_pw_user",
            "password": "WrongPassword!",
        })
        self.assertEqual(resp.status_code, 401)

    def test_protected_endpoint_without_token_returns_401(self):
        resp = self.client.get("/api/v1/auth/me")
        self.assertEqual(resp.status_code, 401)

    def test_me_endpoint_with_valid_token(self):
        # Register + login
        self.client.post("/api/v1/auth/register", json={
            "username": "me_endpoint_user",
            "email": "me@me.com",
            "password": "M3!EndpointPass",
            "role": "analyst",
        })
        login = self.client.post("/api/v1/auth/login", json={
            "username": "me_endpoint_user",
            "password": "M3!EndpointPass",
        })
        token = login.json()["access_token"]
        me = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me.status_code, 200)
        self.assertIn("user", me.json())
        self.assertIn("permissions", me.json())

    def test_duplicate_register_returns_409(self):
        payload = {"username": "dup_user", "email": "dup@dup.com",
                   "password": "Dup!Pass123", "role": "viewer"}
        self.client.post("/api/v1/auth/register", json=payload)
        resp = self.client.post("/api/v1/auth/register", json=payload)
        self.assertEqual(resp.status_code, 409)

    def test_runs_list_requires_auth(self):
        resp = self.client.get("/api/v1/runs")
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
