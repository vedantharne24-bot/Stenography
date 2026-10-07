"""Health check and owner-checked artifact downloads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import client_ip
from app.db.models import User
from app.ml import registry
from app.ml.device import device_info
from app.services import audit, storage
from app.services.audit import AuditAction

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = DbSession) -> dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # pragma: no cover - reported, not raised
        database = "unavailable"
    models = {}
    for name in (registry.CNN_MODEL_NAME, registry.RF_MODEL_NAME):
        row = registry.active_version(db, name) if database == "ok" else None
        models[name] = row.version if row else None
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "compute": device_info(),
        "models": models,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/artifacts/{artifact_id}")
def download_artifact(
    artifact_id: uuid.UUID, request: Request, download: bool = False, user: User = CurrentUser, db: Session = DbSession
) -> Response:
    artifact = storage.get_owned_artifact(db, artifact_id, user)
    data = storage.read_artifact_bytes(artifact)
    headers = {"Cache-Control": "private, no-store", "X-Artifact-SHA256": artifact.sha256}
    if download:
        ext = storage.MIME_EXT.get(artifact.mime, "bin")
        headers["Content-Disposition"] = f'attachment; filename="stegolab-{artifact.kind}-{artifact.id.hex[:8]}.{ext}"'
        audit.record(
            db, AuditAction.ARTIFACT_DOWNLOADED, "success", user=user, ip=client_ip(request), kind=artifact.kind,
            artifact_id=str(artifact.id),
        )
    return Response(content=data, media_type=artifact.mime, headers=headers)
