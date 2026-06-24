"""
api/routers/runs_router.py — Pipeline run endpoints
"""
try:
    from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from api.schemas import (
    RunCreateRequest, RunStatusResponse, RunListResponse,
    RunDetailResponse, PaginatedMeta,
)
from api.dependencies import get_auth_service, get_db, get_current_user, require, get_pagination
from auth.models import AuthContext, Permission
from core.logger import get_logger
from storage.database import Database

log = get_logger(__name__)

if _HAS_FASTAPI:
    router = APIRouter(prefix="/runs", tags=["Analysis Runs"])

    @router.post("", status_code=202)
    def create_run(
        body: RunCreateRequest,
        background_tasks: BackgroundTasks,
        ctx:  AuthContext = Depends(require(Permission.RUNS_CREATE)),
        db:   Database    = Depends(get_db),
    ) -> dict:
        """Submit a new multi-agent analysis run (executes asynchronously)."""
        import uuid
        from config import config
        run_id = str(uuid.uuid4())
        config.HIGH_IMPACT_THRESHOLD = body.threshold

        def _run_pipeline():
            from core.orchestrator import Orchestrator, DEFAULT_INPUT_MATRIX
            from core.models import DomainRecord
            records = None
            if body.records:
                records = [
                    DomainRecord(record_id=r.record_id, domain=r.domain,
                                 payload=r.payload, tenant_id=ctx.tenant_id)
                    for r in body.records
                ]
            orc = Orchestrator(tenant_id=ctx.tenant_id, db=db)
            orc.execute(records=records)

        background_tasks.add_task(_run_pipeline)
        return {"run_id": run_id, "status": "accepted",
                "message": "Run submitted. Poll /runs/{run_id} for status."}

    @router.get("", response_model=RunListResponse)
    def list_runs(
        ctx:        AuthContext = Depends(require(Permission.RUNS_READ)),
        db:         Database    = Depends(get_db),
        pagination              = Depends(get_pagination),
    ) -> RunListResponse:
        """List all runs for the current tenant, newest first."""
        all_runs = db.get_runs(ctx.tenant_id, limit=pagination.per_page * pagination.page)
        page_runs = all_runs[pagination.offset: pagination.offset + pagination.per_page]
        return RunListResponse(
            runs=[RunStatusResponse(
                run_id=r["run_id"], status=r["status"],
                tenant_id=r.get("tenant_id", ctx.tenant_id),
                started_at=r.get("started_at", ""),
                completed_at=r.get("completed_at"),
                total_records=r.get("total_records", 0),
                escalated=r.get("escalated", 0),
                errors=r.get("errors", 0),
                total_tokens=r.get("total_tokens", 0),
            ) for r in page_runs],
            meta=PaginatedMeta(
                page=pagination.page, per_page=pagination.per_page,
                total=len(all_runs),
                total_pages=max(1, (len(all_runs) + pagination.per_page - 1) // pagination.per_page),
            ),
        )

    @router.get("/{run_id}", response_model=RunDetailResponse)
    def get_run(
        run_id: str,
        ctx:    AuthContext = Depends(require(Permission.RUNS_READ)),
        db:     Database    = Depends(get_db),
    ) -> RunDetailResponse:
        """Retrieve full details of a specific run including per-record agent outputs."""
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run '{run_id}' not found.")
        records = db.get_records_for_run(run_id)
        summary = {}
        if run.get("summary_json"):
            import json
            try:
                summary = json.loads(run["summary_json"])
            except Exception:
                pass
        return RunDetailResponse(
            run_id=run["run_id"], status=run["status"],
            tenant_id=run.get("tenant_id", ctx.tenant_id),
            summary=summary, started_at=run.get("started_at", ""),
            completed_at=run.get("completed_at"),
            records=[r.get("result", {}) for r in records],
        )

    @router.delete("/{run_id}", status_code=204)
    def delete_run(
        run_id: str,
        ctx:    AuthContext = Depends(require(Permission.RUNS_DELETE)),
        db:     Database    = Depends(get_db),
    ):
        """Delete a run and all its associated records."""
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run '{run_id}' not found.")
        log.info("Run deleted", extra={"run_id": run_id, "deleted_by": ctx.user.user_id})


"""
api/routers/users_router.py — User management endpoints
"""
if _HAS_FASTAPI:
    users_router = APIRouter(prefix="/users", tags=["User Management"])

    @users_router.get("")
    def list_users(
        ctx:        AuthContext = Depends(require(Permission.USERS_READ)),
        pagination              = Depends(get_pagination),
    ) -> dict:
        from storage.auth_db import AuthDatabase
        db = AuthDatabase()
        users = db.list_users(
            tenant_id=ctx.tenant_id,
            limit=pagination.per_page,
            offset=pagination.offset,
        )
        total = db.count_users(ctx.tenant_id)
        return {
            "users": [u.to_public_dict() for u in users],
            "meta": {
                "page": pagination.page, "per_page": pagination.per_page,
                "total": total,
                "total_pages": max(1, (total + pagination.per_page - 1) // pagination.per_page),
            },
        }

    @users_router.get("/{user_id}")
    def get_user(
        user_id: str,
        ctx:     AuthContext = Depends(require(Permission.USERS_READ)),
    ) -> dict:
        from storage.auth_db import AuthDatabase
        db   = AuthDatabase()
        user = db.get_user_by_id(user_id)
        if not user or user.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "User not found.")
        return user.to_public_dict()

    @users_router.patch("/{user_id}")
    def update_user(
        user_id: str,
        body:    dict,
        ctx:     AuthContext = Depends(require(Permission.USERS_UPDATE)),
    ) -> dict:
        from storage.auth_db import AuthDatabase
        from auth.models import Role
        db   = AuthDatabase()
        user = db.get_user_by_id(user_id)
        if not user or user.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "User not found.")
        if "role" in body:
            try:
                user.role = Role(body["role"]).value
            except ValueError:
                raise HTTPException(400, f"Invalid role '{body['role']}'.")
        if "is_active" in body:
            user.is_active = bool(body["is_active"])
        if "email" in body:
            user.email = body["email"]
        db.update_user(user)
        return user.to_public_dict()

    @users_router.delete("/{user_id}", status_code=204)
    def delete_user(
        user_id: str,
        ctx:     AuthContext = Depends(require(Permission.USERS_DELETE)),
    ):
        from storage.auth_db import AuthDatabase
        db   = AuthDatabase()
        user = db.get_user_by_id(user_id)
        if not user or user.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "User not found.")
        db.delete_user(user_id)


"""
api/routers/health_router.py — Health and readiness endpoints
"""
if _HAS_FASTAPI:
    health_router = APIRouter(prefix="/health", tags=["Health"])

    @health_router.get("", response_model=None)
    def health() -> dict:
        """Liveness probe — always returns 200 if the process is running."""
        from datetime import datetime, timezone
        from config import config
        return {
            "status": "healthy",
            "version": config.APP_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @health_router.get("/ready")
    def readiness() -> dict:
        """
        Readiness probe — checks all downstream dependencies.
        Returns 503 if any critical dependency is unavailable.
        """
        from datetime import datetime, timezone
        from config import config
        from core.rate_limiter import groq_circuit_breaker
        components: dict = {}
        overall = "healthy"

        # Database
        try:
            from storage.database import Database
            Database().get_runs("default", limit=1)
            components["database"] = "ok"
        except Exception as exc:
            components["database"] = f"error: {exc}"
            overall = "degraded"

        # Circuit breaker
        cb_stats = groq_circuit_breaker.get_stats()
        components["circuit_breaker"] = cb_stats["state"]
        if cb_stats["state"] == "OPEN":
            overall = "degraded"

        # Cache
        from core.cache import get_cache
        components["cache"] = get_cache().stats()

        status_code = 200 if overall == "healthy" else 503
        return {
            "status": overall,
            "version": config.APP_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": components,
        }
