"""
api/routers/auth_router.py
"""
try:
    from fastapi import APIRouter, Depends, HTTPException, Request, status
    from fastapi.responses import JSONResponse
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from api.schemas import (
    LoginRequest, RegisterRequest, TokenResponse,
    RefreshRequest, PasswordChangeRequest, LogoutResponse,
)
from api.dependencies import get_auth_service, get_current_user
from auth.auth_service import AuthService
from auth.models import (
    AuthContext, AuthError, InvalidCredentialsError,
    UserAlreadyExistsError, AccountLockedError, Role,
)
from core.logger import get_logger

log = get_logger(__name__)

if _HAS_FASTAPI:
    router = APIRouter(prefix="/auth", tags=["Authentication"])

    @router.post("/register", response_model=TokenResponse, status_code=201)
    def register(
        body:     RegisterRequest,
        request:  Request,
        auth_svc: AuthService = Depends(get_auth_service),
    ) -> TokenResponse:
        """Register a new user account and return a token pair."""
        try:
            role = Role(body.role)
        except ValueError:
            raise HTTPException(400, f"Invalid role '{body.role}'.")
        try:
            user = auth_svc.register(
                username=body.username, email=body.email,
                password=body.password, role=role, tenant_id=body.tenant_id,
            )
        except UserAlreadyExistsError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

        ctx, tokens = auth_svc.login(
            body.username, body.password, body.tenant_id,
            ip_address=request.client.host if request.client else "",
        )
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.access_expires_in,
            user=ctx.user.to_public_dict(),
        )

    @router.post("/login", response_model=TokenResponse)
    def login(
        body:     LoginRequest,
        request:  Request,
        auth_svc: AuthService = Depends(get_auth_service),
    ) -> TokenResponse:
        """Authenticate and return JWT access + refresh tokens."""
        try:
            ctx, tokens = auth_svc.login(
                username=body.username, password=body.password,
                tenant_id=body.tenant_id,
                ip_address=request.client.host if request.client else "",
                user_agent=request.headers.get("user-agent", ""),
            )
        except AccountLockedError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
        except InvalidCredentialsError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.access_expires_in,
            user=ctx.user.to_public_dict(),
        )

    @router.post("/refresh", response_model=TokenResponse)
    def refresh(
        body:     RefreshRequest,
        request:  Request,
        auth_svc: AuthService = Depends(get_auth_service),
    ) -> TokenResponse:
        """Rotate refresh token and return a new token pair."""
        try:
            ctx, tokens = auth_svc.refresh(
                body.refresh_token,
                ip_address=request.client.host if request.client else "",
            )
        except AuthError as exc:
            raise HTTPException(exc.status_code, str(exc))
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_in=tokens.access_expires_in,
            user=ctx.user.to_public_dict(),
        )

    @router.post("/logout", response_model=LogoutResponse)
    def logout(
        request:  Request,
        auth_svc: AuthService = Depends(get_auth_service),
        ctx:      AuthContext = Depends(get_current_user),
    ) -> LogoutResponse:
        """Revoke the current access token."""
        auth_header = request.headers.get("authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        auth_svc.logout(token)
        return LogoutResponse()

    @router.post("/password", status_code=204)
    def change_password(
        body:     PasswordChangeRequest,
        auth_svc: AuthService = Depends(get_auth_service),
        ctx:      AuthContext = Depends(get_current_user),
    ):
        """Change current user's password. Revokes all active sessions."""
        try:
            auth_svc.change_password(
                ctx.user.user_id, body.current_password, body.new_password
            )
        except InvalidCredentialsError:
            raise HTTPException(401, "Current password is incorrect.")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.get("/me")
    def me(ctx: AuthContext = Depends(get_current_user)) -> dict:
        """Return the current authenticated user's public profile."""
        return {
            "user": ctx.user.to_public_dict(),
            "permissions": [p.value for p in ctx.permissions],
        }
