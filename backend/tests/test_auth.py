from __future__ import annotations

from sqlalchemy import select

from app.core.permissions import Permission, has_permission
from app.db.models import AuditLog, Role, User
from app.db.session import SessionLocal
from tests.conftest import STRONG_PASSWORD, auth_header, register

CSRF = {"X-Requested-With": "stegolab"}


def test_register_hashes_password_with_argon2id(client):
    body = register(client, "alice@example.com")
    assert body["user"]["role"] == "USER"
    assert "stego:embed" in body["user"]["permissions"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "alice@example.com"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert STRONG_PASSWORD not in user.password_hash


def test_register_rejects_weak_password_and_duplicates(client):
    weak = client.post("/api/auth/register", json={"name": "B", "email": "bob@example.com", "password": "short"})
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "validation_failed"
    register(client, "bob@example.com")
    dup = client.post("/api/auth/register", json={"name": "B", "email": "BOB@example.com", "password": STRONG_PASSWORD})
    assert dup.status_code == 409


def test_login_success_and_generic_failure(client):
    register(client, "carol@example.com")
    ok = client.post("/api/auth/login", json={"email": "carol@example.com", "password": STRONG_PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["token_type"] == "bearer"
    assert "sl_refresh" in ok.cookies

    wrong = client.post("/api/auth/login", json={"email": "carol@example.com", "password": "Wrong-Password-1"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong-Password-1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]  # no account enumeration


def test_account_lockout_after_repeated_failures(client):
    register(client, "dave@example.com")
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "dave@example.com", "password": "Wrong-Password-1"})
    locked = client.post("/api/auth/login", json={"email": "dave@example.com", "password": STRONG_PASSWORD})
    assert locked.status_code == 401
    with SessionLocal() as db:
        reasons = [
            row.details.get("reason")
            for row in db.scalars(select(AuditLog).where(AuditLog.user_email == "dave@example.com")).all()
        ]
    assert "locked_after_failures" in reasons and "account_locked" in reasons


def test_me_requires_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=auth_header("not-a-jwt")).status_code == 401
    token = register(client, "erin@example.com")["access_token"]
    me = client.get("/api/auth/me", headers=auth_header(token))
    assert me.status_code == 200 and me.json()["email"] == "erin@example.com"


def test_refresh_rotation_csrf_and_reuse_detection(client):
    register(client, "frank@example.com")
    first_cookie = client.cookies.get("sl_refresh")
    assert first_cookie

    assert client.post("/api/auth/refresh").status_code == 401  # missing anti-CSRF header

    rotated = client.post("/api/auth/refresh", headers=CSRF)
    assert rotated.status_code == 200
    second_cookie = client.cookies.get("sl_refresh")
    assert second_cookie and second_cookie != first_cookie

    # Replaying the rotated-out token is treated as theft: every session is revoked.
    client.cookies.set("sl_refresh", first_cookie, path="/api/auth")
    assert client.post("/api/auth/refresh", headers=CSRF).status_code == 401
    client.cookies.set("sl_refresh", second_cookie, path="/api/auth")
    assert client.post("/api/auth/refresh", headers=CSRF).status_code == 401
    with SessionLocal() as db:
        actions = [r.action for r in db.scalars(select(AuditLog).where(AuditLog.user_email == "frank@example.com"))]
    assert "TOKEN_REUSE_DETECTED" in actions


def test_logout_revokes_refresh_session(client):
    register(client, "gina@example.com")
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert client.post("/api/auth/refresh", headers=CSRF).status_code == 401


def test_change_password_invalidates_existing_access_tokens(client):
    token = register(client, "hank@example.com")["access_token"]
    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": STRONG_PASSWORD, "new_password": "Another-Strong-77"},
        headers=auth_header(token),
    )
    assert changed.status_code == 204
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 401
    relogin = client.post("/api/auth/login", json={"email": "hank@example.com", "password": "Another-Strong-77"})
    assert relogin.status_code == 200


def test_role_permission_matrix():
    assert has_permission(Role.USER, Permission.STEGO_EMBED)
    assert not has_permission(Role.USER, Permission.ATTACKS_RUN)
    assert not has_permission(Role.USER, Permission.AUDIT_READ)
    assert has_permission(Role.ANALYST, Permission.FORENSICS_RUN)
    assert has_permission(Role.ANALYST, Permission.REPORTS_GENERATE)
    assert not has_permission(Role.ANALYST, Permission.USERS_MANAGE)
    assert has_permission(Role.ADMIN, Permission.AUDIT_READ)
    assert has_permission(Role.ADMIN, Permission.SETTINGS_MANAGE)


def test_security_headers_present(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
