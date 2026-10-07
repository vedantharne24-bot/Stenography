"""Model registry.

Pipeline: ``train_model.py`` / ``evaluate_model.py`` write
``models/<model_name>/<version>/{card.json, metrics.json, weights}``. On startup
the backend syncs those files into the ``model_versions`` table; the API serves
metrics from the database. Nothing here invents a metric - if a model directory
has no ``metrics.json`` the version is registered with null metrics.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import ModelVersion
from app.db.session import SessionLocal

log = get_logger("app.ml.registry")

CNN_MODEL_NAME = "steganalysis-cnn"
RF_MODEL_NAME = "steganalysis-rf"


@dataclass(frozen=True)
class ModelDir:
    model_name: str
    version: str
    path: Path
    card: dict[str, Any]
    metrics: dict[str, Any] | None

    @property
    def weights_path(self) -> Path:
        return self.path / self.card.get("weights_file", "model.pt")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Unreadable JSON at %s", path)
        return None


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.split("."):
        parts.append(int(piece) if piece.isdigit() else 0)
    return tuple(parts)


def discover() -> list[ModelDir]:
    root = get_settings().model_path
    found: list[ModelDir] = []
    if not root.exists():
        return found
    for model_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for version_dir in sorted((p for p in model_dir.iterdir() if p.is_dir()), key=lambda p: _version_key(p.name)):
            card = _read_json(version_dir / "card.json")
            if card is None:
                continue
            found.append(
                ModelDir(
                    model_name=card.get("model_name", model_dir.name),
                    version=card.get("version", version_dir.name),
                    path=version_dir,
                    card=card,
                    metrics=_read_json(version_dir / "metrics.json"),
                )
            )
    return found


def find(model_name: str, version: str) -> ModelDir | None:
    for item in discover():
        if item.model_name == model_name and item.version == version:
            return item
    return None


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _headline(metrics: dict[str, Any] | None) -> dict[str, float | None]:
    """Pick the headline numbers stored in dedicated columns from metrics.json."""
    if not metrics:
        return {"accuracy": None, "precision": None, "recall": None, "f1": None, "roc_auc": None}
    head = metrics.get("multiclass", metrics)
    return {
        "accuracy": head.get("accuracy"),
        "precision": head.get("precision_macro"),
        "recall": head.get("recall_macro"),
        "f1": head.get("f1_macro"),
        "roc_auc": head.get("roc_auc_macro_ovr"),
    }


def sync_registry_to_db(db: Session | None = None) -> int:
    own_session = db is None
    db = db or SessionLocal()
    try:
        count = 0
        for item in discover():
            row = db.scalar(
                select(ModelVersion).where(
                    ModelVersion.model_name == item.model_name, ModelVersion.version == item.version
                )
            )
            head = _headline(item.metrics)
            trained_at = item.card.get("trained_at")
            values: dict[str, Any] = {
                "kind": item.card.get("kind", "unknown"),
                "framework": item.card.get("framework", "unknown"),
                "metrics": item.metrics or {},
                "artifact_path": str(item.path.relative_to(get_settings().model_path.parent)),
                "weights_sha256": _sha256_file(item.weights_path),
                "trained_at": datetime.fromisoformat(trained_at) if trained_at else None,
                **head,
            }
            if row is None:
                db.add(ModelVersion(model_name=item.model_name, version=item.version, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            count += 1
        db.flush()

        # Exactly one active version per model name: keep an explicit choice, else newest.
        names = {row.model_name for row in db.scalars(select(ModelVersion)).all()}
        for name in names:
            rows = db.scalars(select(ModelVersion).where(ModelVersion.model_name == name)).all()
            available = [r for r in rows if find(r.model_name, r.version) is not None]
            for r in rows:
                if r not in available:
                    r.is_active = False
            if available and not any(r.is_active for r in available):
                newest = max(available, key=lambda r: _version_key(r.version))
                newest.is_active = True
        db.commit()
        if count:
            log.info("Model registry synced: %d version(s)", count)
        return count
    finally:
        if own_session:
            db.close()


def active_version(db: Session, model_name: str) -> ModelVersion | None:
    return db.scalar(
        select(ModelVersion).where(ModelVersion.model_name == model_name, ModelVersion.is_active.is_(True))
    )
