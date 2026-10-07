"""Authentication workflows: registration, login with lockout, refresh-token rotation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthError, Conflict, Forbidden
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.db.models import RefreshSession, Role, User
from app.services import audit, system_settings
from app.services.audit import AuditAction

GENERIC_LOGIN_ERROR = "Invalid email or password"


@dataclass
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires: datetime


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; normalise everything to aware UTC for comparisons."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(db: Session, *, name: str, email: str, password: str, ip: str | None, role: Role = Role.USER) -> User:
    if not system_settings.get_value(db, "allow_registration") and role == Role.USER:
        raise Forbidden("Self-service registration is disabled by the administrator")
    email = normalize_email(email)
    validate_password_strength(password, email=email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise Conflict("An account with this email already exists")
    user = User(name=name.strip(), email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    audit.record(db, AuditAction.REGISTER, "success", user=user, ip=ip, commit=False, role=role.value)
    db.commit()
    return user


def issue_tokens(db: Session, user: User, *, ip: str | None, user_agent: str | None) -> IssuedTokens:
    settings = get_settings()
    access, expires_in = create_access_token(user.id, user.role.value, user.token_version)
    refresh = new_refresh_token()
    refresh_expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days)
    db.add(
        RefreshSession(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            expires_at=refresh_expires,
            ip=ip,
            user_agent=(user_agent or "")[:256],
        )
    )
    db.commit()
    return IssuedTokens(access, expires_in, refresh, refresh_expires)


def authenticate(db: Session, *, email: str, password: str, ip: str | None) -> User:
    settings = get_settings()
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    now = datetime.now(timezone.utc)

    if user is None:
        verify_password(DUMMY_PASSWORD_HASH, password)  # equalise timing
        audit.record(db, AuditAction.LOGIN_FAILURE, "failure", email=email, ip=ip, reason="unknown_account")
        raise AuthError(GENERIC_LOGIN_ERROR, code="invalid_credentials")

    locked_until = _as_aware(user.locked_until)
    if locked_until and locked_until > now:
        verify_password(DUMMY_PASSWORD_HASH, password)
        audit.record(db, AuditAction.LOGIN_FAILURE, "denied", user=user, ip=ip, reason="account_locked")
        raise AuthError(GENERIC_LOGIN_ERROR, code="invalid_credentials")

    if not verify_password(user.password_hash, password) or not user.is_active:
        reason = "inactive_account" if user.is_active is False else "bad_password"
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
            user.failed_login_count = 0
            reason = "locked_after_failures"
        audit.record(db, AuditAction.LOGIN_FAILURE, "failure", user=user, ip=ip, reason=reason)
        raise AuthError(GENERIC_LOGIN_ERROR, code="invalid_credentials")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login = now
    audit.record(db, AuditAction.LOGIN_SUCCESS, "success", user=user, ip=ip)
    return user


def rotate_refresh_token(db: Session, token: str, *, ip: str | None, user_agent: str | None) -> tuple[User, IssuedTokens]:
    now = datetime.now(timezone.utc)
    session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(token)))
    if session is None:
        raise AuthError("Session not found", code="invalid_refresh")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise AuthError("Session not valid", code="invalid_refresh")

    if session.revoked_at is not None:
        # A rotated-out token was presented again: treat as theft, revoke every session.
        revoke_all_sessions(db, user.id)
        audit.record(db, AuditAction.TOKEN_REUSE_DETECTED, "denied", user=user, ip=ip)
        raise AuthError("Session revoked", code="invalid_refresh")

    expires_at = _as_aware(session.expires_at)
    if expires_at is None or expires_at <= now:
        raise AuthError("Session expired", code="invalid_refresh")

    tokens = issue_tokens(db, user, ip=ip, user_agent=user_agent)
    new_session = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(tokens.refresh_token))
    )
    session.revoked_at = now
    session.replaced_by = new_session.id if new_session else None
    db.commit()
    return user, tokens


def revoke_refresh_token(db: Session, token: str) -> User | None:
    session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(token)))
    if session is None:
        return None
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return db.get(User, session.user_id)


def revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()


def change_password(db: Session, user: User, *, current: str, new: str, ip: str | None) -> None:
    if not verify_password(user.password_hash, current):
        audit.record(db, AuditAction.PASSWORD_CHANGED, "failure", user=user, ip=ip, reason="bad_current_password")
        raise AuthError("Current password is incorrect", code="invalid_credentials")
    validate_password_strength(new, email=user.email)
    user.password_hash = hash_password(new)
    user.token_version += 1  # invalidates outstanding access tokens
    db.commit()
    revoke_all_sessions(db, user.id)
    audit.record(db, AuditAction.PASSWORD_CHANGED, "success", user=user, ip=ip)
