"""Dashboard aggregates - every figure is a database query over recorded operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.db.models import AnalysisRecord, AttackExperiment, ExperimentRun, ModelVersion, StegoOperation
from app.ml import registry

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def _scoped(stmt: Select, model: Any, user_id: uuid.UUID | None) -> Select:
    return stmt.where(model.user_id == user_id) if user_id is not None else stmt


def _model_summary(db: Session, name: str) -> dict[str, Any] | None:
    row = registry.active_version(db, name)
    if row is None:
        return None
    binary = (row.metrics or {}).get("binary", {})
    return {
        "id": str(row.id),
        "name": row.model_name,
        "version": row.version,
        "accuracy": row.accuracy,
        "f1": row.f1,
        "roc_auc": row.roc_auc,
        "precision": row.precision,
        "recall": row.recall,
        "binary_accuracy": binary.get("accuracy"),
        "detection_rate": binary.get("detection_rate"),
        "false_positive_rate": binary.get("false_positive_rate"),
        "trained_at": row.trained_at.isoformat() if row.trained_at else None,
    }


def stats(db: Session, user_id: uuid.UUID | None, days: int = 30) -> dict[str, Any]:
    A, S, X = AnalysisRecord, StegoOperation, AttackExperiment

    totals = db.execute(
        _scoped(
            select(
                func.count(A.id),
                func.sum(case((A.prediction == "stego", 1), else_=0)),
                func.avg(A.confidence),
                func.sum(case((A.risk_level.in_(("HIGH", "CRITICAL")), 1), else_=0)),
                func.avg(A.risk_score),
                func.avg(A.inference_ms),
            ),
            A,
            user_id,
        )
    ).one()
    total, stego, avg_conf, high_risk, avg_risk, avg_ms = totals
    total = int(total or 0)
    stego = int(stego or 0)

    op_counts = dict(
        db.execute(
            _scoped(select(S.operation, func.count(S.id)).where(S.success.is_(True)).group_by(S.operation), S, user_id)
        ).all()
    )
    failed_ops = db.scalar(_scoped(select(func.count(S.id)).where(S.success.is_(False)), S, user_id)) or 0
    attacks = db.scalar(_scoped(select(func.count(X.id)), X, user_id)) or 0
    experiments = db.scalar(_scoped(select(func.count(ExperimentRun.id)), ExperimentRun, user_id)) or 0

    since = datetime.now(timezone.utc) - timedelta(days=days)
    day = func.date(A.created_at)
    trend_rows = db.execute(
        _scoped(
            select(day, func.count(A.id), func.sum(case((A.prediction == "stego", 1), else_=0)), func.avg(A.risk_score))
            .where(A.created_at >= since)
            .group_by(day)
            .order_by(day),
            A,
            user_id,
        )
    ).all()
    trends = [
        {"date": str(d), "total": int(n), "stego": int(s or 0), "cover": int(n) - int(s or 0), "avg_risk": float(r or 0)}
        for d, n, s, r in trend_rows
    ]

    technique = dict(db.execute(_scoped(select(A.predicted_technique, func.count(A.id)).group_by(A.predicted_technique), A, user_id)).all())
    risk_levels = dict(db.execute(_scoped(select(A.risk_level, func.count(A.id)).group_by(A.risk_level), A, user_id)).all())
    bucket = func.floor(A.risk_score / 10)
    histogram_rows = dict(db.execute(_scoped(select(bucket, func.count(A.id)).group_by(bucket), A, user_id)).all())
    risk_histogram = [
        {"bin": f"{b * 10}-{b * 10 + 10}", "count": int(histogram_rows.get(b, 0) or 0) + (int(histogram_rows.get(10, 0) or 0) if b == 9 else 0)}
        for b in range(10)
    ]

    robustness_rows = db.execute(
        _scoped(
            select(
                X.attack_type,
                func.count(X.id),
                func.avg(case((X.extraction_success.is_(True), 1.0), else_=0.0)),
                func.avg(X.detection_probability),
                func.avg(X.psnr),
            ).group_by(X.attack_type),
            X,
            user_id,
        )
    ).all()
    robustness = [
        {"attack": a, "runs": int(n), "extraction_success": float(s or 0), "mean_detection": float(d or 0), "mean_psnr": None if p is None else float(p)}
        for a, n, s, d, p in robustness_rows
    ]

    algo_rows = db.execute(
        _scoped(
            select(S.algorithm, func.count(S.id), func.avg(S.psnr), func.avg(S.ssim), func.avg(S.utilization))
            .where(S.operation == "embed", S.success.is_(True))
            .group_by(S.algorithm),
            S,
            user_id,
        )
    ).all()
    algorithms = [
        {"algorithm": a, "count": int(n), "avg_psnr": None if p is None else float(p), "avg_ssim": None if s is None else float(s), "avg_utilization": None if u is None else float(u)}
        for a, n, p, s, u in algo_rows
    ]

    recent = db.scalars(_scoped(select(A).order_by(A.created_at.desc()).limit(8), A, user_id)).all()
    models = {name: _model_summary(db, name) for name in (registry.CNN_MODEL_NAME, registry.RF_MODEL_NAME)}
    model_count = db.scalar(select(func.count(ModelVersion.id))) or 0

    return {
        "scope": "global" if user_id is None else "personal",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "images_analyzed": total,
            "stego_detected": stego,
            "normal_images": total - stego,
            "detection_rate": (stego / total) if total else None,
            "average_confidence": None if avg_conf is None else float(avg_conf),
            "high_risk": int(high_risk or 0),
            "average_risk": None if avg_risk is None else float(avg_risk),
            "average_inference_ms": None if avg_ms is None else float(avg_ms),
            "encryption_operations": int(op_counts.get("embed", 0)),
            "extraction_operations": int(op_counts.get("extract", 0)),
            "failed_operations": int(failed_ops),
            "attack_experiments": int(attacks),
            "research_runs": int(experiments),
            "registered_model_versions": int(model_count),
        },
        "models": models,
        "trends": trends,
        "technique_distribution": [{"technique": t, "count": int(technique.get(t, 0))} for t in ("normal", "lsb", "dct", "dwt")],
        "risk_distribution": [{"level": lvl, "count": int(risk_levels.get(lvl, 0))} for lvl in RISK_LEVELS],
        "risk_histogram": risk_histogram,
        "attack_robustness": robustness,
        "algorithms": algorithms,
        "recent": [
            {
                "id": str(r.id),
                "filename": r.filename,
                "prediction": r.prediction,
                "technique": r.predicted_technique,
                "confidence": r.confidence,
                "risk_score": r.risk_score,
                "risk_level": r.risk_level,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in recent
        ],
    }
