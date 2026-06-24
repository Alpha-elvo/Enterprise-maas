"""
api/main.py — FastAPI Application Factory
==========================================
Creates and configures the FastAPI application:
  • CORS middleware with configurable origins
  • Request ID middleware (X-Request-ID header)
  • Structured logging middleware
  • Global exception handlers (auth errors → proper HTTP codes)
  • All routers registered under /api/v1
  • OpenAPI schema with Bearer security

Usage:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
    uvicorn api.main:app --workers 4   # production
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

try:
    from fastapi import FastAPI, Request, Response, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.openapi.utils import get_openapi
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from config import config
from core.logger import get_logger
from auth.models import AuthError, PermissionDeniedError

log = get_logger(__name__)


def create_app() -> "FastAPI":
    """
    FastAPI application factory.
    Call once at startup; use the returned app instance everywhere.
    """
    if not _HAS_FASTAPI:
        raise RuntimeError(
            "FastAPI is required for the REST API. "
            "Install with: pip install fastapi uvicorn[standard]"
        )

    app = FastAPI(
        title=config.APP_TITLE,
        description=(
            "Enterprise Decision Intelligence Platform REST API. "
            "Authenticate via POST /api/v1/auth/login to obtain a Bearer token."
        ),
        version=config.APP_VERSION,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # Restrict to specific origins in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time"],
    )

    # ── Request ID + Timing middleware ────────────────────────────────────────
    @app.middleware("http")
    async def request_middleware(request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        start      = time.monotonic()
        response   = await call_next(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"]    = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        log.info(
            f"{request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method":     request.method,
                "path":       request.url.path,
                "status":     response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        return response

    # ── Global exception handlers ─────────────────────────────────────────────
    @app.exception_handler(AuthError)
    async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "ValidationError", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        log.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "InternalServerError",
                     "detail": "An unexpected error occurred."},
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    PREFIX = "/api/v1"

    from api.routers.auth_router import router as auth_router
    from api.routers.runs_router import (
        router       as runs_router,
        users_router,
        health_router,
    )

    app.include_router(auth_router,   prefix=PREFIX)
    app.include_router(runs_router,   prefix=PREFIX)
    app.include_router(users_router,  prefix=PREFIX)
    app.include_router(health_router, prefix=PREFIX)

    # ── OpenAPI Security scheme ───────────────────────────────────────────────
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
        schema["security"] = [{"BearerAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore

    # ── Root redirect ─────────────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": f"{config.APP_TITLE} v{config.APP_VERSION}",
                "docs": "/api/docs"}

    log.info(f"FastAPI app created — v{config.APP_VERSION}")
    return app


# Module-level app instance (used by uvicorn)
if _HAS_FASTAPI:
    app = create_app()
