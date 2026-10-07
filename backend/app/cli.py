"""Operational CLI.

    python -m app.cli bootstrap-admin          # create the admin from BOOTSTRAP_ADMIN_* in .env
    python -m app.cli set-role EMAIL ROLE      # USER | ANALYST | ADMIN
    python -m app.cli sync-models              # register trained models from MODEL_PATH
    python -m app.cli purge-expired            # run the retention sweeper once
    python -m app.cli import-experiments       # load docs/experiments/technique_comparison_*.json
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Role, User
from app.db.session import SessionLocal


def bootstrap_admin() -> int:
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        print("BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD are not set in backend/.env", file=sys.stderr)
        return 1
    from app.services.auth import normalize_email, register_user

    with SessionLocal() as db:
        email = normalize_email(settings.bootstrap_admin_email)
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            existing.role = Role.ADMIN
            db.commit()
            print(f"Admin account already exists: {email} (role ensured ADMIN)")
            return 0
        register_user(
            db,
            name=settings.bootstrap_admin_name,
            email=email,
            password=settings.bootstrap_admin_password,
            ip="cli",
            role=Role.ADMIN,
        )
        print(f"Created admin account {email} (password is in backend/.env)")
    return 0


def set_role(email: str, role: str) -> int:
    try:
        new_role = Role(role.upper())
    except ValueError:
        print(f"Unknown role {role}; choose from {[r.value for r in Role]}", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            print(f"No such user: {email}", file=sys.stderr)
            return 1
        user.role = new_role
        user.token_version += 1
        db.commit()
    print(f"{email} is now {new_role.value}")
    return 0


def import_experiments(folder: str | None) -> int:
    """Load published research runs (measured results) into the database, idempotently."""
    import json
    import uuid
    from datetime import datetime
    from pathlib import Path

    from app.db.models import ExperimentRun

    root = Path(folder) if folder else Path(__file__).resolve().parents[2] / "docs" / "experiments"
    files = sorted(root.glob("technique_comparison_*.json"))
    if not files:
        print(f"No technique_comparison_*.json files under {root}")
        return 0
    added = 0
    with SessionLocal() as db:
        for path in files:
            data = json.loads(path.read_text(encoding="utf-8"))
            run_id = uuid.UUID(data["run_id"])
            if db.get(ExperimentRun, run_id) is not None:
                continue
            keys = ("summary", "cover_false_positive_rate", "normalised", "weights", "balance_score", "ranking", "winners", "answer", "methodology", "attacks")
            db.add(
                ExperimentRun(
                    id=run_id,
                    user_id=None,
                    kind="technique_comparison",
                    config={**data["config"], "imported_from": path.name},
                    results={k: data[k] for k in keys if k in data},
                    duration_ms=data.get("duration_ms", 0.0),
                    created_at=datetime.fromisoformat(data["created_at"]),
                )
            )
            added += 1
        db.commit()
    print(f"Imported {added} research run(s) from {root}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap-admin")
    role = sub.add_parser("set-role")
    role.add_argument("email")
    role.add_argument("role")
    sub.add_parser("sync-models")
    sub.add_parser("purge-expired")
    imp = sub.add_parser("import-experiments")
    imp.add_argument("folder", nargs="?", default=None)
    args = parser.parse_args()

    if args.command == "bootstrap-admin":
        return bootstrap_admin()
    if args.command == "set-role":
        return set_role(args.email, args.role)
    if args.command == "sync-models":
        from app.ml.registry import sync_registry_to_db

        print(f"Synced {sync_registry_to_db()} model version(s)")
        return 0
    if args.command == "import-experiments":
        return import_experiments(args.folder)
    if args.command == "purge-expired":
        from app.services import storage

        with SessionLocal() as db:
            print(f"Removed {storage.purge_expired(db)} expired artifact(s)")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
