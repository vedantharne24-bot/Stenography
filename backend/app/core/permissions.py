"""Role-based access control.

Permissions are the unit of authorization; roles are bundles of permissions.
Routes declare the permission they need (``require(Permission.X)``) and the check
runs server-side on every request - the frontend only mirrors this map for UX.
"""

from __future__ import annotations

import enum

from app.db.models import Role


class Permission(str, enum.Enum):
    STEGO_EMBED = "stego:embed"
    STEGO_EXTRACT = "stego:extract"
    ANALYSIS_RUN = "analysis:run"
    HISTORY_OWN = "history:own"
    HISTORY_ALL = "history:all"
    FORENSICS_RUN = "forensics:run"
    ATTACKS_RUN = "attacks:run"
    EXPERIMENTS_RUN = "experiments:run"
    REPORTS_GENERATE = "reports:generate"
    DASHBOARD_GLOBAL = "dashboard:global"
    MODELS_READ = "models:read"
    MODELS_MANAGE = "models:manage"
    USERS_MANAGE = "users:manage"
    AUDIT_READ = "audit:read"
    SETTINGS_MANAGE = "settings:manage"


_USER = {
    Permission.STEGO_EMBED,
    Permission.STEGO_EXTRACT,
    Permission.ANALYSIS_RUN,
    Permission.HISTORY_OWN,
}

_ANALYST = _USER | {
    Permission.FORENSICS_RUN,
    Permission.ATTACKS_RUN,
    Permission.EXPERIMENTS_RUN,
    Permission.REPORTS_GENERATE,
    Permission.DASHBOARD_GLOBAL,
    Permission.MODELS_READ,
}

_ADMIN = _ANALYST | {
    Permission.HISTORY_ALL,
    Permission.MODELS_MANAGE,
    Permission.USERS_MANAGE,
    Permission.AUDIT_READ,
    Permission.SETTINGS_MANAGE,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.USER: frozenset(_USER),
    Role.ANALYST: frozenset(_ANALYST),
    Role.ADMIN: frozenset(_ADMIN),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for(role: Role) -> list[str]:
    return sorted(p.value for p in ROLE_PERMISSIONS.get(role, frozenset()))
