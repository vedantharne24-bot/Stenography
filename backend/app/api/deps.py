"""Request dependencies: database session, authenticated principal, permission checks."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import AuthError, Forbidden
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import client_ip
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.services import audit
from app.services.audit import AuditAction

DbSession = Depends(get_db)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Authentication required", code="not_authenticated")
    return token.strip()


def get_current_user(request: Request, db: Session = DbSession) -> User:
    payload = decode_access_token(_bearer_token(request))
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthError("Invalid access token", code="invalid_token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("Account not available", code="invalid_token")
    if payload.get("tv") != user.token_version:
        raise AuthError("Session has been revoked", code="token_revoked")
    request.state.user = user
    return user


CurrentUser = Depends(get_current_user)


def require(permission: Permission) -> Callable[..., User]:
    """Dependency enforcing a permission server-side; denials are audited."""

    def _dependency(request: Request, user: User = CurrentUser, db: Session = DbSession) -> User:
        if not has_permission(user.role, permission):
            audit.record(
                db,
                AuditAction.ACCESS_DENIED,
                "denied",
                user=user,
                ip=client_ip(request),
                permission=permission.value,
                path=request.url.path,
            )
            raise Forbidden(f"Your role ({user.role.value}) lacks permission '{permission.value}'")
        return user

    return _dependency
