"""Server-side file storage for generated artifacts.

* File names are random UUIDs generated here - user-supplied names never touch the filesystem.
* Every artifact is owned by a user and registered in the ``artifacts`` table.
* Temporary artifacts carry ``expires_at`` and are purged by the retention sweeper.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFound
from app.core.permissions import Permission, has_permission
from app.db.models import Artifact, User
from app.services import system_settings

MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "application/json": "json",
    "application/octet-stream": "bin",
}


def _root() -> Path:
    return get_settings().artifacts_dir.resolve()


def save_artifact(
    db: Session,
    *,
    user: User | None,
    kind: str,
    data: bytes,
    mime: str,
    temporary: bool = True,
    commit: bool = False,
) -> Artifact:
    ext = MIME_EXT.get(mime, "bin")
    artifact_id = uuid.uuid4()
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    rel = Path(day) / f"{artifact_id.hex}.{ext}"
    path = _root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)

    expires = None
    if temporary:
        hours = int(system_settings.get_value(db, "temp_retention_hours"))
        expires = datetime.now(timezone.utc) + timedelta(hours=hours)

    artifact = Artifact(
        id=artifact_id,
        user_id=user.id if user else None,
        kind=kind,
        rel_path=rel.as_posix(),
        mime=mime,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        is_temporary=temporary,
        expires_at=expires,
    )
    db.add(artifact)
    if commit:
        db.commit()
    else:
        db.flush()
    return artifact


def resolve_path(artifact: Artifact) -> Path:
    root = _root()
    path = (root / artifact.rel_path).resolve()
    if root not in path.parents:  # defence against a tampered rel_path
        raise NotFound("Artifact not found")
    return path


def get_owned_artifact(db: Session, artifact_id: uuid.UUID, user: User) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise NotFound("Artifact not found or expired")
    if artifact.user_id != user.id and not has_permission(user.role, Permission.HISTORY_ALL):
        raise NotFound("Artifact not found or expired")  # do not reveal existence
    expires = artifact.expires_at
    if expires is not None:
        expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise NotFound("Artifact not found or expired")
    if not resolve_path(artifact).exists():
        raise NotFound("Artifact file is no longer available")
    return artifact


def read_artifact_bytes(artifact: Artifact) -> bytes:
    return resolve_path(artifact).read_bytes()


def delete_artifact(db: Session, artifact: Artifact) -> None:
    try:
        resolve_path(artifact).unlink(missing_ok=True)
    except NotFound:
        pass
    db.delete(artifact)


def purge_expired(db: Session) -> int:
    now = datetime.now(timezone.utc)
    expired = db.scalars(select(Artifact).where(Artifact.expires_at.is_not(None), Artifact.expires_at <= now)).all()
    for artifact in expired:
        delete_artifact(db, artifact)
    db.commit()
    return len(expired)
