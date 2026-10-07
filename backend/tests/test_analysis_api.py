"""Steganalysis / forensics / attack / report / dashboard endpoints and server-side RBAC."""

from __future__ import annotations

import io
import json

import numpy as np
import pytest
from PIL import Image
from skimage import data as skdata
from sqlalchemy import select

from app.db.models import AnalysisRecord, AttackExperiment, AuditLog
from app.db.session import SessionLocal
from tests.conftest import auth_header, make_user


def _png(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def image_png() -> bytes:
    return _png(skdata.astronaut())


def _stego(client, token, image_png, algorithm):
    res = client.post(
        "/api/steganography/embed",
        headers=auth_header(token),
        files={"image": ("c.png", image_png, "image/png")},
        data={"algorithm": algorithm, "payload_type": "text", "message": "attack me", "key_mode": "passphrase", "passphrase": "attack-lab-pass"},
    ).json()["result"]
    return client.get(f"/api/artifacts/{res['artifacts']['stego']}", headers=auth_header(token)).content


# --------------------------------------------------------------------------- RBAC


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/forensics/analyze"),
        ("post", "/api/attacks/run"),
        ("post", "/api/attacks/batch"),
        ("post", "/api/experiments/run"),
        ("get", "/api/audit-logs"),
        ("get", "/api/admin/users"),
        ("get", "/api/admin/settings"),
        ("get", "/api/models"),
        ("get", "/api/reports"),
    ],
)
def test_user_role_is_denied_server_side(client, method, path):
    token = make_user(client, f"rbac-user-{path.replace('/', '-')}@example.com")
    kwargs = {"files": {"image": ("x.png", b"irrelevant", "image/png")}} if method == "post" and "experiments" not in path else {}
    if "experiments" in path:
        kwargs = {"json": {}}
    response = getattr(client, method)(path, headers=auth_header(token), **kwargs)
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        denied = db.scalars(select(AuditLog).where(AuditLog.action == "ACCESS_DENIED", AuditLog.result == "denied")).all()
        assert any(row.details.get("path") == path for row in denied)


def test_analyst_and_admin_permissions(client):
    analyst = make_user(client, "rbac-analyst@example.com", role="ANALYST")
    admin = make_user(client, "rbac-admin@example.com", role="ADMIN")
    assert client.get("/api/attacks/catalogue", headers=auth_header(analyst)).status_code == 200
    assert client.get("/api/models", headers=auth_header(analyst)).status_code == 200
    assert client.get("/api/audit-logs", headers=auth_header(analyst)).status_code == 403
    assert client.get("/api/admin/users", headers=auth_header(analyst)).status_code == 403
    assert client.get("/api/audit-logs", headers=auth_header(admin)).status_code == 200
    users = client.get("/api/admin/users", headers=auth_header(admin)).json()["items"]
    assert any(u["email"] == "rbac-analyst@example.com" for u in users)


def test_role_change_revokes_tokens_and_is_audited(client):
    admin = make_user(client, "rbac-admin2@example.com", role="ADMIN")
    user_token = make_user(client, "promote-me@example.com")
    target = next(u for u in client.get("/api/admin/users", headers=auth_header(admin)).json()["items"] if u["email"] == "promote-me@example.com")
    res = client.patch(f"/api/admin/users/{target['id']}", headers=auth_header(admin), json={"role": "ANALYST"})
    assert res.status_code == 200 and res.json()["role"] == "ANALYST"
    assert client.get("/api/auth/me", headers=auth_header(user_token)).status_code == 401  # old token revoked
    with SessionLocal() as db:
        assert db.scalars(select(AuditLog).where(AuditLog.action == "USER_UPDATED")).first() is not None


def test_admin_cannot_demote_self(client):
    admin = make_user(client, "self-demote@example.com", role="ADMIN")
    me = client.get("/api/auth/me", headers=auth_header(admin)).json()
    assert client.patch(f"/api/admin/users/{me['id']}", headers=auth_header(admin), json={"role": "USER"}).status_code == 422


# --------------------------------------------------------------------------- steganalysis


def test_analysis_is_stored_and_audited(client, models_ready, image_png):
    token = make_user(client, "analysis@example.com")
    res = client.post("/api/steganalysis/analyze", headers=auth_header(token), files={"image": ("a.png", image_png, "image/png")}, data={"explain": "true"})
    assert res.status_code == 200, res.text
    result = res.json()["result"]
    assert result["model"]["version"] == "0.0.1"
    assert result["prediction"] in ("cover", "stego")
    assert sum(result["probabilities"].values()) == pytest.approx(1.0, abs=1e-4)
    assert 0 <= result["risk"]["score"] <= 100
    assert result["explanation"]["target_class"] in ("lsb", "dct", "dwt")
    assert {"heatmap", "overlay", "image_preview"} <= set(result["artifacts"])
    stages = {e["stage"] for e in res.json()["trace"]}
    assert {"model", "preprocess", "inference", "features", "signature", "risk", "explain"} <= stages
    with SessionLocal() as db:
        record = db.get(AnalysisRecord, __import__("uuid").UUID(result["analysis_id"]))
        assert record is not None and record.model_version == "0.0.1" and record.file_hash == result["image"]["sha256"]
        actions = {r.action for r in db.scalars(select(AuditLog).where(AuditLog.user_email == "analysis@example.com"))}
        assert {"IMAGE_ANALYSIS", "MODEL_USED"} <= actions


def test_stegolab_payload_signature_raises_risk_floor(client, models_ready, image_png):
    token = make_user(client, "signature@example.com")
    stego = _stego(client, token, image_png, "lsb")
    result = client.post("/api/steganalysis/analyze", headers=auth_header(token), files={"image": ("s.png", stego, "image/png")}, data={"explain": "false"}).json()["result"]
    assert result["signature"] == {"algorithm": "lsb", "integrity": "verified"}
    assert result["risk"]["score"] >= 97 and result["risk"]["level"] == "CRITICAL"


def test_forensics_report_contains_measured_sections(client, models_ready, image_png):
    analyst = make_user(client, "forensics@example.com", role="ANALYST")
    res = client.post("/api/forensics/analyze", headers=auth_header(analyst), files={"image": ("f.png", image_png, "image/png")})
    assert res.status_code == 200, res.text
    r = res.json()["result"]
    assert set(r["histograms"]) == {"R", "G", "B"} and len(r["histograms"]["R"]) == 256
    assert sum(r["histograms"]["G"]) == 512 * 512
    assert {"chi_square_embedding_probability", "spa_estimate"} <= set(r["lsb_analysis"]["R"])
    assert r["findings"] and r["disclaimer"]
    assert {"noise_residual", "lsb_plane"} <= set(r["artifacts"])


# --------------------------------------------------------------------------- attacks


def test_jpeg_attack_breaks_lsb_but_not_dct(client, models_ready, image_png):
    analyst = make_user(client, "attacks@example.com", role="ANALYST")
    lsb = _stego(client, analyst, image_png, "lsb")
    dct = _stego(client, analyst, image_png, "dct")
    params = json.dumps({"quality": 92})
    lsb_res = client.post("/api/attacks/run", headers=auth_header(analyst), files={"image": ("l.png", lsb, "image/png")}, data={"attack": "jpeg", "params": params, "secret": "attack-lab-pass"}).json()["result"]
    dct_res = client.post("/api/attacks/run", headers=auth_header(analyst), files={"image": ("d.png", dct, "image/png")}, data={"attack": "jpeg", "params": params, "secret": "attack-lab-pass"}).json()["result"]
    assert lsb_res["before"]["extraction"]["success"] is True
    assert lsb_res["after"]["extraction"]["success"] is False
    assert dct_res["after"]["extraction"]["success"] is True
    assert dct_res["after"]["extraction"]["decryption"] == "success"
    assert 0 <= dct_res["after"]["bit_error_rate"] < 0.05
    assert dct_res["after"]["quality"]["psnr"] > 30


def test_attack_parameter_validation(client, models_ready, image_png):
    analyst = make_user(client, "attack-params@example.com", role="ANALYST")
    res = client.post("/api/attacks/run", headers=auth_header(analyst), files={"image": ("x.png", image_png, "image/png")}, data={"attack": "jpeg", "params": json.dumps({"quality": 500})})
    assert res.status_code == 422


def test_batch_robustness_records_every_attack(client, models_ready, image_png):
    analyst = make_user(client, "batch@example.com", role="ANALYST")
    stego = _stego(client, analyst, image_png, "dwt")
    suite = json.dumps([{"attack": "jpeg", "params": {"quality": 90}}, {"attack": "gaussian_noise", "params": {"sigma": 1}}, {"attack": "crop", "params": {"ratio": 0.8}}])
    res = client.post("/api/attacks/batch", headers=auth_header(analyst), files={"image": ("b.png", stego, "image/png")}, data={"suite": suite}).json()["result"]
    assert len(res["rows"]) == 3
    assert res["rows"][2]["bit_error_rate"] is None  # geometry changed by the crop
    with SessionLocal() as db:
        rows = db.scalars(select(AttackExperiment).where(AttackExperiment.batch_id == __import__("uuid").UUID(res["batch_id"]))).all()
        assert len(rows) == 3


# --------------------------------------------------------------------------- reports, dashboard, history


def test_report_pdf_generation_and_isolation(client, models_ready, image_png):
    analyst = make_user(client, "reporter@example.com", role="ANALYST")
    other = make_user(client, "other-analyst@example.com", role="ANALYST")
    analysis = client.post("/api/steganalysis/analyze", headers=auth_header(analyst), files={"image": ("r.png", image_png, "image/png")}).json()["result"]
    report = client.post(f"/api/reports/{analysis['analysis_id']}", headers=auth_header(analyst))
    assert report.status_code == 201
    body = report.json()
    pdf = client.get(f"/api/reports/{body['id']}/download", headers=auth_header(analyst))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    import hashlib

    assert hashlib.sha256(pdf.content).hexdigest() == body["sha256"] == pdf.headers["X-Report-SHA256"]
    assert client.get(f"/api/reports/{body['id']}/download", headers=auth_header(other)).status_code == 404
    assert client.post(f"/api/reports/{analysis['analysis_id']}", headers=auth_header(other)).status_code == 404


def test_dashboard_counts_come_from_the_database(client, models_ready, image_png):
    token = make_user(client, "dash@example.com")
    before = client.get("/api/dashboard/stats", headers=auth_header(token)).json()
    assert before["scope"] == "personal" and before["totals"]["images_analyzed"] == 0
    client.post("/api/steganalysis/analyze", headers=auth_header(token), files={"image": ("d.png", image_png, "image/png")}, data={"explain": "false"})
    after = client.get("/api/dashboard/stats", headers=auth_header(token)).json()
    assert after["totals"]["images_analyzed"] == 1
    assert after["recent"][0]["filename"] == "d.png"


def test_history_isolation_and_erasure(client, models_ready, image_png):
    alice = make_user(client, "hist-alice@example.com")
    bob = make_user(client, "hist-bob@example.com")
    client.post("/api/steganalysis/analyze", headers=auth_header(alice), files={"image": ("h.png", image_png, "image/png")}, data={"explain": "false"})
    assert client.get("/api/history?kind=analysis", headers=auth_header(alice)).json()["total"] == 1
    assert client.get("/api/history?kind=analysis", headers=auth_header(bob)).json()["total"] == 0
    assert client.get("/api/history?kind=analysis&all_users=true", headers=auth_header(bob)).status_code == 422
    erased = client.delete("/api/history", headers=auth_header(alice)).json()
    assert erased["analyses"] == 1 and erased["files"] >= 1
    assert client.get("/api/history?kind=analysis", headers=auth_header(alice)).json()["total"] == 0


def test_public_overview_needs_no_auth(client, models_ready):
    res = client.get("/api/public/overview")
    assert res.status_code == 200
    assert res.json()["models"]["steganalysis-cnn"]["version"] == "0.0.1"
