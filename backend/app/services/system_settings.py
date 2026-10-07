"""Admin-editable runtime configuration, persisted in ``system_settings``.

Environment variables provide the defaults; an administrator can override the
whitelisted keys below at runtime. Unknown keys are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.db.models import SystemSetting


@dataclass(frozen=True)
class SettingSpec:
    key: str
    kind: type
    description: str
    minimum: int | None = None
    maximum: int | None = None


SPECS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in (
        SettingSpec("allow_registration", bool, "Allow self-service account registration"),
        SettingSpec("temp_retention_hours", int, "Hours before temporary artifacts are purged", 1, 720),
        SettingSpec("max_upload_mb", int, "Maximum accepted upload size in MB", 1, 50),
        SettingSpec("risk_threshold_medium", int, "Risk score at which an image is MEDIUM risk", 1, 98),
        SettingSpec("risk_threshold_high", int, "Risk score at which an image is HIGH risk", 2, 99),
        SettingSpec("risk_threshold_critical", int, "Risk score at which an image is CRITICAL risk", 3, 100),
    )
}


def _defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "allow_registration": s.allow_registration,
        "temp_retention_hours": s.temp_retention_hours,
        "max_upload_mb": max(1, s.max_upload_size // (1024 * 1024)),
        "risk_threshold_medium": 35,
        "risk_threshold_high": 65,
        "risk_threshold_critical": 85,
    }


def get_all(db: Session) -> dict[str, Any]:
    values = _defaults()
    for row in db.query(SystemSetting).all():
        if row.key in SPECS:
            values[row.key] = row.value
    return values


def get_value(db: Session, key: str) -> Any:
    return get_all(db)[key]


def update(db: Session, changes: dict[str, Any], *, actor_email: str) -> dict[str, Any]:
    current = get_all(db)
    for key, value in changes.items():
        spec = SPECS.get(key)
        if spec is None:
            raise ValidationFailed(f"Unknown setting '{key}'")
        if spec.kind is bool:
            if not isinstance(value, bool):
                raise ValidationFailed(f"'{key}' must be a boolean")
        else:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationFailed(f"'{key}' must be an integer")
            if spec.minimum is not None and value < spec.minimum or spec.maximum is not None and value > spec.maximum:
                raise ValidationFailed(f"'{key}' must be between {spec.minimum} and {spec.maximum}")
        current[key] = value

    if not (current["risk_threshold_medium"] < current["risk_threshold_high"] < current["risk_threshold_critical"]):
        raise ValidationFailed("Risk thresholds must be strictly increasing: medium < high < critical")

    for key, value in changes.items():
        row = db.get(SystemSetting, key)
        if row is None:
            db.add(SystemSetting(key=key, value=value, updated_by=actor_email))
        else:
            row.value = value
            row.updated_by = actor_email
    db.commit()
    return current
