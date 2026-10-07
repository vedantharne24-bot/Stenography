"""Authentication endpoints.

The access token is returned in the body (kept in memory by the SPA). The refresh
token lives only in an httpOnly, SameSite=Strict cookie scoped to ``/api/auth``;
refresh/logout additionally require the ``X-Requested-With`` header, which a
cross-site form cannot set (defence in depth against CSRF).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.permissions import permissions_for
from app.core.rate_limit import client_ip, rate_limit
from app.db.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import audit
from app.services import auth as auth_service
from app.services.audit import AuditAction

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "sl_refresh"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "stegolab"

_auth_limit = Depends(rate_limit("auth", "rate_limit_auth"))


def user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.role = user.role.value
    out.permissions = permissions_for(user.role)
    return out


def _set_refresh_cookie(response: Response, tokens: auth_service.IssuedTokens) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/auth",
    )


def _require_csrf_header(request: Request) -> None:
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise AuthError("Missing anti-CSRF header", code="csrf_check_failed")


def _token_response(response: Response, user: User, tokens: auth_service.IssuedTokens) -> TokenResponse:
    _set_refresh_cookie(response, tokens)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in, user=user_out(user))


@router.post("/register", response_model=TokenResponse, status_code=201, dependencies=[_auth_limit])
def register(body: RegisterRequest, request: Request, response: Response, db: Session = DbSession) -> TokenResponse:
    ip = client_ip(request)
    user = auth_service.register_user(db, name=body.name, email=body.email, password=body.password, ip=ip)
    tokens = auth_service.issue_tokens(db, user, ip=ip, user_agent=request.headers.get("user-agent"))
    return _token_response(response, user, tokens)


@router.post("/login", response_model=TokenResponse, dependencies=[_auth_limit])
def login(body: LoginRequest, request: Request, response: Response, db: Session = DbSession) -> TokenResponse:
    ip = client_ip(request)
    user = auth_service.authenticate(db, email=body.email, password=body.password, ip=ip)
    tokens = auth_service.issue_tokens(db, user, ip=ip, user_agent=request.headers.get("user-agent"))
    return _token_response(response, user, tokens)


@router.post("/refresh", response_model=TokenResponse, dependencies=[_auth_limit])
def refresh(request: Request, response: Response, db: Session = DbSession) -> TokenResponse:
    _require_csrf_header(request)
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AuthError("No session", code="no_session")
    user, tokens = auth_service.rotate_refresh_token(
        db, token, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return _token_response(response, user, tokens)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = DbSession) -> Response:
    _require_csrf_header(request)
    token = request.cookies.get(REFRESH_COOKIE)
    user = auth_service.revoke_refresh_token(db, token) if token else None
    if user is not None:
        audit.record(db, AuditAction.LOGOUT, "success", user=user, ip=client_ip(request))
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = CurrentUser) -> UserOut:
    return user_out(user)


@router.post("/change-password", status_code=204, dependencies=[_auth_limit])
def change_password(
    body: ChangePasswordRequest, request: Request, response: Response, user: User = CurrentUser, db: Session = DbSession
) -> Response:
    auth_service.change_password(db, user, current=body.current_password, new=body.new_password, ip=client_ip(request))
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    response.status_code = 204
    return response
