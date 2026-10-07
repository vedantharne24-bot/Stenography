"""Test fixtures: an isolated SQLite database and storage directory per test session."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="stegolab-test-"))
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "storage")
os.environ["SECRET_KEY"] = "test-secret-key-" + "x" * 32
os.environ["JWT_SECRET"] = "test-jwt-secret-" + "y" * 32
os.environ["RATE_LIMIT_AUTH"] = "1000"
os.environ["RATE_LIMIT_HEAVY"] = "1000"
# Cheaper KDF so the suite stays fast; production defaults are exercised in test_crypto.
os.environ["KDF_MEMORY_KIB"] = "8192"
os.environ["KDF_TIME_COST"] = "1"
# An isolated model registry (populated by the `models_ready` fixture) and CPU inference.
os.environ["MODEL_PATH"] = str(_TMP / "models")
os.environ["DATASET_DIR"] = str(_TMP / "dataset")
os.environ["DEVICE"] = "cpu"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402

STRONG_PASSWORD = "Correct-Horse-42"


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    Base.metadata.create_all(engine)
    yield
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.reset()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def models_ready() -> Path:
    """Write a real-format model registry: untrained StegoNet weights + a small fitted Random Forest.

    The point is to exercise the production loading / inference / explanation code paths,
    not to measure accuracy (that is the job of pipeline/evaluate_model.py).
    """
    import json

    import joblib
    import numpy as np
    import torch
    from sklearn.covariance import LedoitWolf
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler

    from app.ml.cnn import CLASSES, StegoNet, StegoNetConfig
    from app.ml.features import extract_features, feature_names
    from app.ml.registry import sync_registry_to_db
    from app.services import crypto
    from app.services.stego import engine

    root = Path(os.environ["MODEL_PATH"])
    cnn_dir = root / "steganalysis-cnn" / "0.0.1"
    rf_dir = root / "steganalysis-rf" / "0.0.1"
    cnn_dir.mkdir(parents=True, exist_ok=True)
    rf_dir.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(0)
    config = StegoNetConfig()
    torch.save({"state_dict": StegoNet(config).state_dict(), "config": config.to_dict(), "classes": list(CLASSES)}, cnn_dir / "model.pt")
    (cnn_dir / "card.json").write_text(json.dumps({"model_name": "steganalysis-cnn", "version": "0.0.1", "kind": "cnn", "framework": "pytorch", "weights_file": "model.pt", "trained_at": "2026-01-01T00:00:00+00:00"}))

    rng = np.random.default_rng(0)
    feats, labels = [], []
    for i in range(12):
        base = np.cumsum(rng.normal(0, 2, size=(256, 256, 3)), axis=1)
        cover = np.clip(base - base.min() + 40, 0, 215).astype(np.uint8)
        feats.append(extract_features(cover))
        labels.append(0)
        for label, algorithm in ((1, "lsb"), (2, "dct"), (3, "dwt")):
            cap = engine.capacity(algorithm, cover.shape)
            env = crypto.encrypt_payload(rng.bytes(max(1, cap.max_payload_bytes // 2)), crypto.Secret(raw_key=bytes(32))).envelope
            feats.append(extract_features(engine.embed(cover, env, algorithm).stego))
            labels.append(label)
    x, y = np.stack(feats), np.array(labels)
    rf = RandomForestClassifier(n_estimators=20, random_state=0).fit(x, y)
    scaler = StandardScaler().fit(x[y == 0])
    lw = LedoitWolf().fit(scaler.transform(x[y == 0]))
    z = scaler.transform(x[y == 0]) - lw.location_
    calibration = np.sort(np.sqrt(np.einsum("ij,jk,ik->i", z, lw.precision_, z)))
    joblib.dump({"model": rf, "classes": list(CLASSES), "feature_names": feature_names(),
                 "anomaly": {"scaler": scaler, "location": lw.location_, "precision": lw.precision_, "calibration": calibration}},
                rf_dir / "model.joblib")  # fmt: skip
    (rf_dir / "card.json").write_text(json.dumps({"model_name": "steganalysis-rf", "version": "0.0.1", "kind": "random_forest", "framework": "scikit-learn", "weights_file": "model.joblib"}))

    sync_registry_to_db()
    from app.ml.inference import models

    models.invalidate()
    return root


def register(client: TestClient, email: str, password: str = STRONG_PASSWORD, name: str = "Test User") -> dict:
    response = client.post("/api/auth/register", json={"name": name, "email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_user(client: TestClient, email: str, role: str = "USER") -> str:
    """Register a user, promote it via the DB if needed, and return a fresh access token."""
    from sqlalchemy import select

    from app.db.models import Role, User
    from app.db.session import SessionLocal

    register(client, email)
    if role != "USER":
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email))
            assert user is not None
            user.role = Role(role)
            db.commit()
    response = client.post("/api/auth/login", json={"email": email, "password": STRONG_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]
