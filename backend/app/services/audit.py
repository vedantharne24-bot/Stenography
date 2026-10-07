"""Audit logging of security-sensitive events.

Metadata is scrubbed of any key that could hold a secret before it is written,
so a careless caller cannot leak a password or message into the audit trail.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import AuditLog, User

log = get_logger("app.audit")


class AuditAction(str, enum.Enum):
    REGISTER = "REGISTER"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"
    TOKEN_REFRESH = "TOKEN_REFRESH"
    TOKEN_REUSE_DETECTED = "TOKEN_REUSE_DETECTED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    ACCESS_DENIED = "ACCESS_DENIED"
    IMAGE_ANALYSIS = "IMAGE_ANALYSIS"
    MODEL_USED = "MODEL_USED"
    FORENSIC_ANALYSIS = "FORENSIC_ANALYSIS"
    ENCRYPTION = "ENCRYPTION"
    EMBEDDING = "EMBEDDING"
    EXTRACTION = "EXTRACTION"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    DECRYPTION_SUCCESS = "DECRYPTION_SUCCESS"
    DECRYPTION_FAILURE = "DECRYPTION_FAILURE"
    ATTACK_RUN = "ATTACK_RUN"
    ATTACK_BATCH = "ATTACK_BATCH"
    EXPERIMENT_RUN = "EXPERIMENT_RUN"
    REPORT_GENERATED = "REPORT_GENERATED"
    REPORT_DOWNLOADED = "REPORT_DOWNLOADED"
    ARTIFACT_DOWNLOADED = "ARTIFACT_DOWNLOADED"
    DATA_DELETED = "DATA_DELETED"
    USER_UPDATED = "USER_UPDATED"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    MODEL_ACTIVATED = "MODEL_ACTIVATED"
    RETENTION_SWEEP = "RETENTION_SWEEP"


_SENSITIVE_FRAGMENTS = ("password", "passphrase", "secret", "token", "key", "message", "plaintext", "payload_data")


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for k, v in value.items():
            lowered = str(k).lower()
            if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS) and not lowered.endswith(
                ("_size", "_bytes", "_kind", "_hash", "_id", "_present")
            ):
                clean[str(k)] = "[redacted]"
            else:
                clean[str(k)] = _scrub(v, depth + 1)
        return clean
    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in value[:50]]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def record(
    db: Session,
    action: AuditAction,
    result: str,
    *,
    user: User | None = None,
    email: str | None = None,
    ip: str | None = None,
    commit: bool = True,
    **metadata: Any,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        user_email=(user.email if user else email),
        action=action.value,
        result=result,
        ip=ip,
        details=_scrub(metadata),
    )
    db.add(entry)
    if commit:
        db.commit()
    log.info("audit %s result=%s user=%s", action.value, result, entry.user_email or "-")
    return entry
