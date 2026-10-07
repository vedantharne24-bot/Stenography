"""Dashboard, history, reports, models, audit logs, administration and public endpoints."""

from __future__ import annotations

import base64
import random
import uuid
from datetime import datetime
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, Query, Request, Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require
from app.api.routes.auth import user_out
from app.core.errors import NotFound, ValidationFailed
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import client_ip, rate_limit
from app.core.streaming import Trace
from app.db.models import (
    AnalysisRecord,
    Artifact,
    AttackExperiment,
    AuditLog,
    ExperimentRun,
    ModelVersion,
    Report,
    Role,
    StegoOperation,
    User,
)
from app.ml import inference, registry
from app.schemas.auth import UserOut
from app.services import audit, crypto, dashboard, image_io, metrics, reports, storage, system_settings
from app.services.audit import AuditAction
from app.services.experiments import test_carriers
from app.services.steganalysis import _thresholds, analyze_array
from app.services.stego import engine

router = APIRouter(prefix="/api", tags=["records"])
_heavy = Depends(rate_limit("heavy", "rate_limit_heavy"))


def _page(page: int, size: int) -> tuple[int, int]:
    size = min(100, max(1, size))
    return max(0, (max(1, page) - 1) * size), size


# =========================================================================== dashboard


@router.get("/dashboard/stats")
def dashboard_stats(
    scope: Literal["auto", "personal", "global"] = "auto", days: int = Query(30, ge=1, le=365), user: User = CurrentUser, db: Session = DbSession
) -> dict[str, Any]:
    global_allowed = has_permission(user.role, Permission.DASHBOARD_GLOBAL)
    use_global = global_allowed and scope in ("auto", "global")
    return dashboard.stats(db, None if use_global else user.id, days)


# =========================================================================== history


def _analysis_row(r: AnalysisRecord) -> dict[str, Any]:
    return {
        "id": str(r.id), "type": "analysis", "source": r.source, "filename": r.filename, "file_hash": r.file_hash,
        "width": r.width, "height": r.height, "prediction": r.prediction, "technique": r.predicted_technique,
        "confidence": r.confidence, "risk_score": r.risk_score, "risk_level": r.risk_level, "model_version": r.model_version,
        "probabilities": r.probabilities, "artifacts": r.artifacts, "created_at": r.created_at.isoformat(),
    }  # fmt: skip


def _operation_row(o: StegoOperation) -> dict[str, Any]:
    return {
        "id": str(o.id), "type": "operation", "operation": o.operation, "algorithm": o.algorithm, "payload_kind": o.payload_kind,
        "payload_size": o.payload_size, "image": f"{o.image_width}×{o.image_height}", "capacity_bytes": o.capacity_bytes,
        "utilization": o.utilization, "psnr": o.psnr, "ssim": o.ssim, "mse": o.mse, "success": o.success, "error_code": o.error_code,
        "stego_hash": o.stego_hash, "artifacts": o.artifacts, "duration_ms": o.duration_ms, "created_at": o.created_at.isoformat(),
    }  # fmt: skip


def _attack_row(a: AttackExperiment) -> dict[str, Any]:
    return {
        "id": str(a.id), "type": "attack", "batch_id": str(a.batch_id) if a.batch_id else None, "attack": a.attack_type,
        "params": a.attack_parameters, "algorithm": a.algorithm, "source_image": a.source_image, "filename": a.source_filename,
        "detection_before": a.detection_probability_before, "detection_after": a.detection_probability,
        "extraction_success": a.extraction_success, "integrity": a.integrity_status, "decryption": a.decryption_status,
        "ber": a.bit_error_rate, "psnr": a.psnr, "ssim": a.ssim, "created_at": a.created_at.isoformat(),
    }  # fmt: skip


@router.get("/history")
def history(
    kind: Literal["analysis", "operation", "attack"] = "analysis",
    page: int = 1,
    page_size: int = 20,
    q: str | None = Query(None, max_length=120),
    all_users: bool = False,
    user: User = Depends(require(Permission.HISTORY_OWN)),
    db: Session = DbSession,
) -> dict[str, Any]:
    if all_users and not has_permission(user.role, Permission.HISTORY_ALL):
        raise ValidationFailed("Viewing all users' history requires administrator rights")
    offset, size = _page(page, page_size)
    model, mapper, order = {
        "analysis": (AnalysisRecord, _analysis_row, AnalysisRecord.created_at),
        "operation": (StegoOperation, _operation_row, StegoOperation.created_at),
        "attack": (AttackExperiment, _attack_row, AttackExperiment.created_at),
    }[kind]
    stmt = select(model)
    if not all_users:
        stmt = stmt.where(model.user_id == user.id)
    if q:
        like = f"%{q.lower()}%"
        if kind == "analysis":
            stmt = stmt.where(or_(func.lower(AnalysisRecord.filename).like(like), AnalysisRecord.file_hash.like(like)))
        elif kind == "attack":
            stmt = stmt.where(or_(func.lower(AttackExperiment.source_filename).like(like), AttackExperiment.attack_type.like(like)))
        else:
            stmt = stmt.where(or_(StegoOperation.algorithm.like(like), StegoOperation.stego_hash.like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(order.desc()).offset(offset).limit(size)).all()
    return {"items": [mapper(r) for r in rows], "total": total, "page": page, "page_size": size}


@router.get("/history/analysis/{analysis_id}")
def analysis_detail(analysis_id: uuid.UUID, user: User = Depends(require(Permission.HISTORY_OWN)), db: Session = DbSession) -> dict[str, Any]:
    record = db.get(AnalysisRecord, analysis_id)
    if record is None or (record.user_id != user.id and not has_permission(user.role, Permission.HISTORY_ALL)):
        raise NotFound("Analysis not found")
    return {**_analysis_row(record), "rf_probabilities": record.rf_probabilities, "anomaly_score": record.anomaly_score,
            "risk": record.risk_factors, "signature": record.payload_signature, "details": record.details,
            "inference_ms": record.inference_ms, "tiles": record.tiles, "file_size": record.file_size, "image_format": record.image_format}  # fmt: skip


@router.delete("/history/{kind}/{item_id}", status_code=204)
def delete_item(kind: Literal["analysis", "operation", "attack"], item_id: uuid.UUID, request: Request, user: User = Depends(require(Permission.HISTORY_OWN)), db: Session = DbSession) -> Response:
    model = {"analysis": AnalysisRecord, "operation": StegoOperation, "attack": AttackExperiment}[kind]
    row = db.get(model, item_id)
    if row is None or row.user_id != user.id:
        raise NotFound("Item not found")
    for artifact_id in (row.artifacts or {}).values():
        try:
            artifact = db.get(Artifact, uuid.UUID(str(artifact_id)))
        except ValueError:
            artifact = None
        if artifact is not None and artifact.user_id == user.id:
            storage.delete_artifact(db, artifact)
    db.delete(row)
    audit.record(db, AuditAction.DATA_DELETED, "success", user=user, ip=client_ip(request), commit=False, kind=kind, item_id=str(item_id))
    db.commit()
    return Response(status_code=204)


@router.delete("/history", status_code=200)
def delete_all_my_data(request: Request, user: User = Depends(require(Permission.HISTORY_OWN)), db: Session = DbSession) -> dict[str, int]:
    """Right-to-erasure for analysis data. Audit records are retained (security requirement)."""
    counts: dict[str, int] = {}
    for name, model in (("analyses", AnalysisRecord), ("operations", StegoOperation), ("attacks", AttackExperiment), ("experiments", ExperimentRun), ("reports", Report)):
        counts[name] = db.execute(delete(model).where(model.user_id == user.id)).rowcount or 0
    artifacts = db.scalars(select(Artifact).where(Artifact.user_id == user.id)).all()
    for artifact in artifacts:
        storage.delete_artifact(db, artifact)
    counts["files"] = len(artifacts)
    audit.record(db, AuditAction.DATA_DELETED, "success", user=user, ip=client_ip(request), commit=False, scope="all", **counts)
    db.commit()
    return counts


# =========================================================================== reports


def _report_row(r: Report) -> dict[str, Any]:
    return {"id": str(r.id), "title": r.title, "analysis_id": str(r.analysis_id) if r.analysis_id else None, "sha256": r.sha256,
            "summary": r.summary, "created_at": r.created_at.isoformat(), "artifact_id": str(r.artifact_id)}  # fmt: skip


@router.post("/reports/{analysis_id}", status_code=201)
def create_report(analysis_id: uuid.UUID, request: Request, user: User = Depends(require(Permission.REPORTS_GENERATE)), db: Session = DbSession) -> dict[str, Any]:
    return _report_row(reports.generate(db, user, analysis_id, client_ip(request)))


@router.get("/reports")
def list_reports(page: int = 1, page_size: int = 20, user: User = Depends(require(Permission.REPORTS_GENERATE)), db: Session = DbSession) -> dict[str, Any]:
    offset, size = _page(page, page_size)
    stmt = select(Report).where(Report.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Report.created_at.desc()).offset(offset).limit(size)).all()
    return {"items": [_report_row(r) for r in rows], "total": total, "page": page, "page_size": size}


def _owned_report(db: Session, report_id: uuid.UUID, user: User) -> Report:
    report = db.get(Report, report_id)
    if report is None or (report.user_id != user.id and not has_permission(user.role, Permission.HISTORY_ALL)):
        raise NotFound("Report not found")
    return report


@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, user: User = Depends(require(Permission.REPORTS_GENERATE)), db: Session = DbSession) -> dict[str, Any]:
    return _report_row(_owned_report(db, report_id, user))


@router.get("/reports/{report_id}/download")
def download_report(report_id: uuid.UUID, request: Request, user: User = Depends(require(Permission.REPORTS_GENERATE)), db: Session = DbSession) -> Response:
    report = _owned_report(db, report_id, user)
    artifact = storage.get_owned_artifact(db, report.artifact_id, user)
    audit.record(db, AuditAction.REPORT_DOWNLOADED, "success", user=user, ip=client_ip(request), report_id=str(report.id))
    return Response(
        storage.read_artifact_bytes(artifact), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="stegolab-report-{report.id.hex[:8]}.pdf"', "X-Report-SHA256": report.sha256, "Cache-Control": "private, no-store"},
    )  # fmt: skip


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: uuid.UUID, request: Request, user: User = Depends(require(Permission.REPORTS_GENERATE)), db: Session = DbSession) -> Response:
    report = _owned_report(db, report_id, user)
    artifact = db.get(Artifact, report.artifact_id)
    db.delete(report)
    if artifact:
        storage.delete_artifact(db, artifact)
    audit.record(db, AuditAction.DATA_DELETED, "success", user=user, ip=client_ip(request), commit=False, kind="report", item_id=str(report_id))
    db.commit()
    return Response(status_code=204)


# =========================================================================== models


def _model_row(m: ModelVersion) -> dict[str, Any]:
    binary = (m.metrics or {}).get("binary", {})
    return {
        "id": str(m.id), "model_name": m.model_name, "version": m.version, "kind": m.kind, "framework": m.framework,
        "accuracy": m.accuracy, "precision": m.precision, "recall": m.recall, "f1": m.f1, "roc_auc": m.roc_auc,
        "binary": {k: binary.get(k) for k in ("accuracy", "detection_rate", "false_positive_rate", "roc_auc", "f1")},
        "is_active": m.is_active, "trained_at": m.trained_at.isoformat() if m.trained_at else None,
        "weights_sha256": m.weights_sha256, "created_at": m.created_at.isoformat(),
    }  # fmt: skip


@router.get("/models")
def list_models(_: User = Depends(require(Permission.MODELS_READ)), db: Session = DbSession) -> list[dict[str, Any]]:
    return [_model_row(m) for m in db.scalars(select(ModelVersion).order_by(ModelVersion.model_name, ModelVersion.created_at.desc())).all()]


@router.get("/models/{model_id}/metrics")
def model_metrics(model_id: uuid.UUID, _: User = Depends(require(Permission.MODELS_READ)), db: Session = DbSession) -> dict[str, Any]:
    m = db.get(ModelVersion, model_id)
    if m is None:
        raise NotFound("Model version not found")
    found = registry.find(m.model_name, m.version)
    extra: dict[str, Any] = {}
    if found:
        import json

        for name in ("history.json", "val_metrics.json"):
            path = found.path / name
            if path.exists():
                extra[name.split(".")[0]] = json.loads(path.read_text(encoding="utf-8"))
        extra["card"] = found.card
    return {**_model_row(m), "metrics": m.metrics, **extra}


@router.post("/models/{model_id}/activate")
def activate_model(model_id: uuid.UUID, request: Request, user: User = Depends(require(Permission.MODELS_MANAGE)), db: Session = DbSession) -> dict[str, Any]:
    m = db.get(ModelVersion, model_id)
    if m is None or registry.find(m.model_name, m.version) is None:
        raise NotFound("Model version not found on disk")
    for other in db.scalars(select(ModelVersion).where(ModelVersion.model_name == m.model_name)).all():
        other.is_active = other.id == m.id
    audit.record(db, AuditAction.MODEL_ACTIVATED, "success", user=user, ip=client_ip(request), commit=False, model=m.model_name, version=m.version)
    db.commit()
    inference.models.invalidate()
    return _model_row(m)


# =========================================================================== audit logs


@router.get("/audit-logs")
def audit_logs(
    page: int = 1, page_size: int = 50, action: str | None = None, result: str | None = None, user_query: str | None = Query(None, max_length=120),
    since: datetime | None = None, _: User = Depends(require(Permission.AUDIT_READ)), db: Session = DbSession,
) -> dict[str, Any]:  # fmt: skip
    offset, size = _page(page, page_size)
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if user_query:
        stmt = stmt.where(func.lower(AuditLog.user_email).like(f"%{user_query.lower()}%"))
    if since:
        stmt = stmt.where(AuditLog.timestamp >= since)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).offset(offset).limit(size)).all()
    actions = [a for (a,) in db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()]
    return {
        "items": [
            {"id": r.id, "timestamp": r.timestamp.isoformat(), "user": r.user_email, "action": r.action, "result": r.result, "ip": r.ip, "metadata": r.details}
            for r in rows
        ],
        "total": total, "page": page, "page_size": size, "actions": actions,
    }  # fmt: skip


# =========================================================================== administration


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


@router.get("/admin/users")
def admin_users(page: int = 1, page_size: int = 50, _: User = Depends(require(Permission.USERS_MANAGE)), db: Session = DbSession) -> dict[str, Any]:
    offset, size = _page(page, page_size)
    total = db.scalar(select(func.count(User.id))) or 0
    rows = db.scalars(select(User).order_by(User.created_at.desc()).offset(offset).limit(size)).all()
    counts = dict(db.execute(select(AnalysisRecord.user_id, func.count(AnalysisRecord.id)).group_by(AnalysisRecord.user_id)).all())
    return {"items": [{**user_out(u).model_dump(mode="json"), "analyses": int(counts.get(u.id, 0))} for u in rows], "total": total}


@router.patch("/admin/users/{user_id}", response_model=UserOut)
def admin_update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, actor: User = Depends(require(Permission.USERS_MANAGE)), db: Session = DbSession) -> UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("User not found")
    if target.id == actor.id and (body.role not in (None, Role.ADMIN) or body.is_active is False):
        raise ValidationFailed("Administrators cannot demote or disable their own account")
    changes: dict[str, Any] = {}
    if body.role is not None and body.role != target.role:
        changes["role"] = [target.role.value, body.role.value]
        target.role = body.role
    if body.is_active is not None and body.is_active != target.is_active:
        changes["is_active"] = [target.is_active, body.is_active]
        target.is_active = body.is_active
    if changes:
        target.token_version += 1  # force re-authentication with the new privileges
        audit.record(db, AuditAction.USER_UPDATED, "success", user=actor, ip=client_ip(request), commit=False, target=target.email, changes=changes)
    db.commit()
    return user_out(target)


@router.get("/admin/settings")
def get_settings_route(_: User = Depends(require(Permission.SETTINGS_MANAGE)), db: Session = DbSession) -> dict[str, Any]:
    values = system_settings.get_all(db)
    return {"values": values, "specs": {k: {"type": s.kind.__name__, "description": s.description, "min": s.minimum, "max": s.maximum} for k, s in system_settings.SPECS.items()}}


@router.patch("/admin/settings")
def update_settings_route(changes: dict[str, Any], request: Request, user: User = Depends(require(Permission.SETTINGS_MANAGE)), db: Session = DbSession) -> dict[str, Any]:
    values = system_settings.update(db, changes, actor_email=user.email)
    audit.record(db, AuditAction.SETTINGS_CHANGED, "success", user=user, ip=client_ip(request), changes=changes)
    return {"values": values}


@router.post("/admin/retention/sweep")
def retention_sweep(request: Request, user: User = Depends(require(Permission.SETTINGS_MANAGE)), db: Session = DbSession) -> dict[str, int]:
    removed = storage.purge_expired(db)
    audit.record(db, AuditAction.RETENTION_SWEEP, "success", user=user, ip=client_ip(request), removed=removed, manual=True)
    return {"removed": removed}


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.patch("/auth/me", response_model=UserOut)
def update_profile(body: ProfileUpdate, user: User = CurrentUser, db: Session = DbSession) -> UserOut:
    target = db.get(User, user.id)
    assert target is not None
    target.name = body.name.strip()
    db.commit()
    return user_out(target)


# =========================================================================== public (no auth)


@router.get("/public/overview")
def public_overview(db: Session = DbSession) -> dict[str, Any]:
    """Non-personal aggregates for the landing page: active model metrics and platform counters."""
    models: dict[str, Any] = {}
    for name in (registry.CNN_MODEL_NAME, registry.RF_MODEL_NAME):
        row = registry.active_version(db, name)
        if row is None:
            models[name] = None
            continue
        metrics = row.metrics or {}
        models[name] = {
            "version": row.version,
            "trained_at": row.trained_at.isoformat() if row.trained_at else None,
            "accuracy": row.accuracy, "f1": row.f1, "roc_auc": row.roc_auc,
            "binary": metrics.get("binary"),
            "per_class": (metrics.get("multiclass") or {}).get("per_class"),
            "confusion_matrix": (metrics.get("multiclass") or {}).get("confusion_matrix"),
            "by_utilisation": metrics.get("by_utilisation"),
            "samples": metrics.get("samples"),
        }  # fmt: skip
    latest = db.scalar(select(ExperimentRun).where(ExperimentRun.kind == "technique_comparison").order_by(ExperimentRun.created_at.desc()))
    counters = {
        "images_analyzed": db.scalar(select(func.count(AnalysisRecord.id))) or 0,
        "stego_detected": db.scalar(select(func.count(AnalysisRecord.id)).where(AnalysisRecord.prediction == "stego")) or 0,
        "embeddings": db.scalar(select(func.count(StegoOperation.id)).where(StegoOperation.operation == "embed", StegoOperation.success.is_(True))) or 0,
        "attack_runs": db.scalar(select(func.count(AttackExperiment.id))) or 0,
    }
    dataset = None
    try:
        import json

        from app.core.config import get_settings

        stats = json.loads((get_settings().dataset_dir / "stats.json").read_text(encoding="utf-8"))
        dataset = {k: stats.get(k) for k in ("sources", "images", "leakage_check", "embedding_quality", "source_datasets")}
    except (OSError, ValueError):
        pass
    return {
        "models": models,
        "counters": counters,
        "dataset": dataset,
        "algorithms": [engine.get_algorithm(n).describe() for n in engine.ALGORITHM_NAMES],
        "latest_experiment": None if latest is None else {
            "created_at": latest.created_at.isoformat(), "config": latest.config,
            "summary": {a: {k: v for k, v in s.items() if k not in ("psnr_values",)} for a, s in (latest.results or {}).get("summary", {}).items()},
            "ranking": (latest.results or {}).get("ranking"), "answer": (latest.results or {}).get("answer"),
            "balance_score": (latest.results or {}).get("balance_score"),
        },
    }  # fmt: skip


class DemoRequest(BaseModel):
    algorithm: Literal["lsb", "dct", "dwt", "random"] = "random"


def _b64_png(rgb: np.ndarray) -> str:
    return "data:image/png;base64," + base64.b64encode(image_io.encode_preview(rgb, max_side=512)).decode()


@router.post("/public/demo", dependencies=[_heavy])
def public_demo(body: DemoRequest, request: Request, db: Session = DbSession) -> dict[str, Any]:
    """Live demonstration on a held-out test image: real encryption, embedding and analysis.

    Nothing user-supplied is processed and nothing is stored; the server picks a test-split
    carrier, hides a random message with a random key, and analyses cover and stego.
    """
    carriers = test_carriers()
    if not carriers:
        raise ValidationFailed("Demo unavailable: held-out test images have not been generated")
    rng = random.SystemRandom()
    path = rng.choice(carriers)
    algorithm = body.algorithm if body.algorithm != "random" else rng.choice(list(engine.ALGORITHM_NAMES))
    cover = np.asarray(Image.open(path).convert("RGB"))
    if cover.shape[0] > 256:
        y0 = rng.randrange(0, (cover.shape[0] - 256) // 8 + 1) * 8
        x0 = rng.randrange(0, (cover.shape[1] - 256) // 8 + 1) * 8
        cover = np.ascontiguousarray(cover[y0 : y0 + 256, x0 : x0 + 256])
    cap = engine.capacity(algorithm, cover.shape)
    message = rng.randbytes(max(1, int(cap.max_payload_bytes * rng.uniform(0.5, 0.9))))
    key, _ = crypto.generate_raw_key()
    sealed = crypto.encrypt_payload(message, crypto.Secret(raw_key=key))
    outcome = engine.embed(cover, sealed.envelope, algorithm)
    thresholds = _thresholds(db)
    trace = Trace()
    cover_result = analyze_array(cover, Trace(), thresholds, explain=True, use_rf=True, check_signature=False)
    stego_result = analyze_array(outcome.stego, trace, thresholds, explain=True, use_rf=True, check_signature=False)
    _, amplified = metrics.difference_maps(cover, outcome.stego, 48.0)
    audit.record(db, AuditAction.IMAGE_ANALYSIS, "success", ip=client_ip(request), source="public_demo", algorithm=algorithm)

    def pack(result: Any, image: np.ndarray) -> dict[str, Any]:
        r = result.result
        return {
            "prediction": r["prediction"], "p_stego": r["p_stego"], "predicted_technique": r["predicted_technique"],
            "probabilities": r["probabilities"], "rf": r["rf"], "risk": r["risk"], "model": r["model"],
            "explanation": r["explanation"],
            "overlay": _b64_png(inference.overlay(image, result.heatmap)) if result.heatmap is not None else None,
        }  # fmt: skip

    return {
        "carrier": path.stem,
        "algorithm": algorithm,
        "payload_bytes": len(message),
        "envelope_sha256": sealed.envelope_sha256,
        "utilization": outcome.utilization,
        "quality": metrics.quality_report(cover, outcome.stego),
        "images": {"cover": _b64_png(cover), "stego": _b64_png(outcome.stego), "difference": _b64_png(amplified)},
        "cover": pack(cover_result, cover),
        "stego": pack(stego_result, outcome.stego),
        "trace": trace.events,
    }
