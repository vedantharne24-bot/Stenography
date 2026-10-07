"""Account security primitives: password hashing, access tokens, refresh tokens.

* Passwords: Argon2id via ``argon2-cffi`` (memory-hard, salted, parameters embedded in the hash).
* Access tokens: short-lived HS256 JWTs carrying ``sub``, ``role`` and ``tv`` (token version).
* Refresh tokens: 256-bit random strings; only their SHA-256 is persisted (see ``RefreshSession``).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import AuthError, ValidationFailed

# OWASP-recommended Argon2id profile for interactive logins (~50 ms on a laptop).
_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

PASSWORD_MIN_LENGTH = 10
_PASSWORD_CLASSES = (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")


def validate_password_strength(password: str, *, email: str | None = None) -> None:
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > 256:
        problems.append("at most 256 characters")
    classes = sum(1 for pattern in _PASSWORD_CLASSES if re.search(pattern, password))
    if classes < 3:
        problems.append("at least three of: lowercase, uppercase, digit, symbol")
    if email and email.split("@", 1)[0].lower() in password.lower() and len(email.split("@", 1)[0]) >= 4:
        problems.append("must not contain your email name")
    if problems:
        raise ValidationFailed("Password does not meet policy", details={"requirements": problems})


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# A precomputed hash used to equalise timing when the account does not exist.
DUMMY_PASSWORD_HASH = _password_hasher.hash(secrets.token_urlsafe(16))


def create_access_token(user_id: uuid.UUID, role: str, token_version: int) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": secrets.token_hex(8),
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.access_token_minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Access token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid access token", code="invalid_token") from exc
    if payload.get("typ") != "access":
        raise AuthError("Invalid token type", code="invalid_token")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Keyed hash so a leaked database cannot be used to forge lookups."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()
