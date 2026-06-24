"""
api/schemas.py — REST API Request / Response Schemas
=====================================================
All Pydantic models used by FastAPI endpoints.
Separated from auth/models.py (domain) and core/models.py (pipeline).
Enforces strict validation at the API boundary; internal code uses dataclasses.

Naming convention:
  <Resource>CreateRequest  — POST body
  <Resource>UpdateRequest  — PUT / PATCH body
  <Resource>Response       — single resource response
  <Resource>ListResponse   — paginated list response
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field, field_validator
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False
    # Stub so imports don't crash when Pydantic is absent
    class BaseModel:  # type: ignore
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    def Field(*a, **kw): return None
    def field_validator(*a, **kw):
        def d(f): return f
        return d


# ══════════════════════════════════════════════════════════════════════════════
# COMMON
# ══════════════════════════════════════════════════════════════════════════════

class PaginationParams(BaseModel):
    page:     int = Field(default=1,   ge=1)
    per_page: int = Field(default=20,  ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class PaginatedMeta(BaseModel):
    page:        int
    per_page:    int
    total:       int
    total_pages: int


class HealthResponse(BaseModel):
    status:      str            # "healthy" | "degraded" | "unhealthy"
    version:     str
    timestamp:   str
    components:  Dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error:   str
    detail:  str       = ""
    code:    int       = 400


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username:  str = Field(..., min_length=1, max_length=64)
    password:  str = Field(..., min_length=1, max_length=128)
    tenant_id: str = Field(default="default", max_length=64)

    model_config = {"str_strip_whitespace": True} if _HAS_PYDANTIC else {}


class RegisterRequest(BaseModel):
    username:  str = Field(..., min_length=3, max_length=64)
    email:     str = Field(..., min_length=5, max_length=254)
    password:  str = Field(..., min_length=10, max_length=128)
    role:      str = Field(default="viewer")
    tenant_id: str = Field(default="default", max_length=64)

    model_config = {"str_strip_whitespace": True} if _HAS_PYDANTIC else {}


class TokenResponse(BaseModel):
    access_token:     str
    refresh_token:    str
    token_type:       str = "bearer"
    expires_in:       int          # seconds
    user:             Dict[str, Any]


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password:     str = Field(..., min_length=10, max_length=128)


class LogoutResponse(BaseModel):
    message: str = "Successfully logged out."


# ══════════════════════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════════════════════

class UserResponse(BaseModel):
    user_id:    str
    username:   str
    email:      str
    role:       str
    tenant_id:  str
    is_active:  bool
    created_at: str
    last_login: Optional[str] = None


class UserUpdateRequest(BaseModel):
    role:      Optional[str]  = None
    is_active: Optional[bool] = None
    email:     Optional[str]  = None


class UserListResponse(BaseModel):
    users: List[UserResponse]
    meta:  PaginatedMeta


# ══════════════════════════════════════════════════════════════════════════════
# RUNS
# ══════════════════════════════════════════════════════════════════════════════

class DomainRecordInput(BaseModel):
    record_id: str = Field(..., min_length=1, max_length=50)
    domain:    str = Field(..., min_length=1, max_length=100)
    payload:   str = Field(..., min_length=10, max_length=10_000)

    model_config = {"str_strip_whitespace": True} if _HAS_PYDANTIC else {}


class RunCreateRequest(BaseModel):
    records:   Optional[List[DomainRecordInput]] = None   # None = use default matrix
    threshold: int  = Field(default=7, ge=1, le=10)
    tenant_id: str  = Field(default="default")


class RunStatusResponse(BaseModel):
    run_id:      str
    status:      str
    tenant_id:   str
    started_at:  str
    completed_at: Optional[str] = None
    total_records: int          = 0
    escalated:   int            = 0
    errors:      int            = 0
    total_tokens: int           = 0


class RunListResponse(BaseModel):
    runs: List[RunStatusResponse]
    meta: PaginatedMeta


class RunDetailResponse(BaseModel):
    run_id:      str
    status:      str
    tenant_id:   str
    summary:     Dict[str, Any]
    started_at:  str
    completed_at: Optional[str] = None
    records:     List[Dict[str, Any]] = []


# ══════════════════════════════════════════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════════════════════════════════════════

class ReportSummaryResponse(BaseModel):
    run_id:   str
    domain:   str
    summary:  str
    findings: List[str] = []
    actions:  List[str] = []


class ExportFormat(BaseModel):
    format: str = Field(..., pattern="^(pdf|json|csv|excel)$")


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOWS
# ══════════════════════════════════════════════════════════════════════════════

class WorkflowCreateRequest(BaseModel):
    run_id:      str
    record_id:   str
    title:       str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    priority:    str = Field(default="MEDIUM")


class WorkflowActionRequest(BaseModel):
    action:  str    = Field(..., pattern="^(approve|reject|request_revision)$")
    comment: str    = Field(default="", max_length=1000)


class WorkflowResponse(BaseModel):
    workflow_id:  str
    run_id:       str
    record_id:    str
    title:        str
    status:       str
    priority:     str
    created_by:   str
    created_at:   str
    updated_at:   str
    history:      List[Dict[str, Any]] = []


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

class AnalyticsResponse(BaseModel):
    tenant_id:       str
    period_days:     int
    total_runs:      int
    total_records:   int
    escalation_rate: float
    avg_impact_score: float
    domain_breakdown: Dict[str, Any] = {}
    trend_data:      List[Dict[str, Any]] = []
    top_risks:       List[str] = []
