"""Preprocessing, model loading, inference, explanation, features, evaluation and risk scoring."""

from __future__ import annotations

import os

import numpy as np
import pytest
from skimage import data as skdata

from app.core.errors import ModelUnavailable
from app.ml import inference
from app.ml.evaluation import evaluate
from app.ml.features import extract_features, feature_names
from app.services import crypto, risk
from app.services.stego import engine

THRESHOLDS = {"risk_threshold_medium": 35, "risk_threshold_high": 65, "risk_threshold_critical": 85}


# --------------------------------------------------------------------------- preprocessing


@pytest.mark.parametrize("h,w", [(256, 256), (512, 768), (300, 457), (1000, 1333)])
def test_tiles_are_grid_aligned_and_cover_the_image(h, w):
    tiles = inference.tile_origins(h, w)
    assert all(y % 8 == 0 and x % 8 == 0 and th == tw == 256 for y, x, th, tw in tiles)
    covered = np.zeros((h, w), dtype=bool)
    for y, x, th, tw in tiles:
        covered[y : y + th, x : x + tw] = True
    # Only a sub-8px right/bottom margin may stay uncovered.
    assert covered[: (h // 8) * 8 - 7, : (w // 8) * 8 - 7].all()


def test_small_images_become_one_cropped_tile_and_tiles_are_capped():
    assert inference.tile_origins(100, 70) == [(0, 0, 96, 64)]
    assert len(inference.tile_origins(4000, 4000, max_tiles=16)) <= 16


# --------------------------------------------------------------------------- loading / inference


def test_model_unavailable_without_registry(monkeypatch):
    inference.models.invalidate()
    monkeypatch.setattr(inference.ModelService, "_active", lambda self, name: None)
    with pytest.raises(ModelUnavailable):
        inference.run_cnn(np.zeros((256, 256, 3), dtype=np.uint8))


def test_cnn_loads_from_registry_and_returns_distribution(models_ready):
    image = skdata.astronaut()
    result = inference.run_cnn(image)
    assert result.version == "0.0.1"
    assert result.tiles == len(inference.tile_origins(512, 512))
    assert set(result.probabilities) == {"normal", "lsb", "dct", "dwt"}
    assert sum(result.probabilities.values()) == pytest.approx(1.0, abs=1e-5)
    assert all(0.0 <= t["p_stego"] <= 1.0 for t in result.tile_probabilities)


def test_inference_is_deterministic(models_ready):
    image = skdata.coffee()
    a = inference.run_cnn(image).probabilities
    b = inference.run_cnn(image).probabilities
    assert a == pytest.approx(b, abs=1e-6)


def test_gradcam_heatmap_shape_and_branch_shares(models_ready):
    image = skdata.astronaut()[:300, :400].copy()
    explanation = inference.explain(image, "lsb")
    assert explanation.heatmap.shape == image.shape[:2]
    assert 0.0 <= float(explanation.heatmap.min()) and float(explanation.heatmap.max()) <= 1.0
    total = sum(explanation.branch_share.values())
    assert total == pytest.approx(1.0, abs=1e-6) or total == 0.0


def test_random_forest_and_anomaly(models_ready):
    rf = inference.run_rf(skdata.astronaut())
    assert rf is not None and rf.version == "0.0.1"
    assert sum(rf.probabilities.values()) == pytest.approx(1.0, abs=1e-6)
    assert 0.0 <= rf.anomaly <= 1.0
    assert len(rf.top_features) == 8


# --------------------------------------------------------------------------- features


def test_feature_vector_is_complete_and_finite():
    f = extract_features(skdata.astronaut()[:256, :256].copy())
    assert f.shape == (len(feature_names()),)
    assert np.isfinite(f).all()


def test_lsb_features_respond_to_lsb_embedding():
    cover = skdata.astronaut()[:256, :256].copy()
    cap = engine.capacity("lsb", cover.shape)
    env = crypto.encrypt_payload(os.urandom(int(cap.max_payload_bytes * 0.9)), crypto.Secret(raw_key=bytes(32))).envelope
    stego = engine.embed(cover, env, "lsb").stego
    names = feature_names()
    before, after = extract_features(cover), extract_features(stego)
    spa = names.index("lsb_spa_R")
    chi = names.index("lsb_chi2_p_R")
    assert after[spa] > before[spa] + 0.2  # SPA estimates a substantial change rate
    assert after[chi] > 0.9  # chi-square attack signals pair equalisation


# --------------------------------------------------------------------------- evaluation


def test_evaluation_metrics_on_known_predictions():
    y = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    perfect = np.eye(4)[y] * 0.97 + 0.01
    report = evaluate(y, perfect)
    assert report["multiclass"]["accuracy"] == 1.0
    assert report["multiclass"]["roc_auc_macro_ovr"] == pytest.approx(1.0)
    assert report["binary"]["false_positive_rate"] == 0.0

    # One cover misclassified as LSB, one DWT missed as normal.
    pred = perfect.copy()
    pred[0] = [0.1, 0.8, 0.05, 0.05]
    pred[7] = [0.7, 0.1, 0.1, 0.1]
    report = evaluate(y, pred)
    assert report["multiclass"]["accuracy"] == pytest.approx(6 / 8)
    assert report["binary"]["confusion"] == {"tp": 5, "tn": 1, "fp": 1, "fn": 1}
    assert report["binary"]["false_positive_rate"] == pytest.approx(0.5)
    assert report["multiclass"]["confusion_matrix"][0] == [1, 1, 0, 0]


# --------------------------------------------------------------------------- risk


def test_risk_formula_is_transparent_weighted_mean():
    r = risk.compute_risk(p_cnn_stego=0.8, p_rf_stego=0.6, anomaly=0.5, signature=None, thresholds=THRESHOLDS)
    expected = 100 * (0.55 * 0.8 + 0.25 * 0.6 + 0.20 * 0.5)
    assert r.score == pytest.approx(round(expected, 1))
    assert r.level == "HIGH"
    assert sum(f["contribution"] for f in r.factors if f["key"] != "payload_signature") == pytest.approx(expected, abs=0.05)


def test_risk_renormalises_missing_components_and_applies_floor():
    only_cnn = risk.compute_risk(p_cnn_stego=0.2, p_rf_stego=None, anomaly=None, signature=None, thresholds=THRESHOLDS)
    assert only_cnn.score == pytest.approx(20.0) and only_cnn.level == "LOW"
    floored = risk.compute_risk(p_cnn_stego=0.1, p_rf_stego=0.1, anomaly=0.1, signature={"algorithm": "lsb", "integrity": "verified"}, thresholds=THRESHOLDS)
    assert floored.score == pytest.approx(97.0) and floored.level == "CRITICAL"


# --------------------------------------------------------------------------- Weighted-Stego front-end


def test_ws_front_end_separates_lsb_from_noise():
    """The parity-aware channels must rise under LSB replacement but not under symmetric noise."""
    import torch

    from app.ml.cnn import StegoNet, StegoNetConfig

    net = StegoNet(StegoNetConfig(ws_branch=True)).eval()
    cover = skdata.astronaut()[:256, :256].copy()
    rng = np.random.default_rng(3)
    noisy = np.clip(np.rint(cover + rng.normal(0, 2, cover.shape)), 0, 255).astype(np.uint8)
    cap = engine.capacity("lsb", cover.shape)
    env = crypto.encrypt_payload(os.urandom(int(cap.max_payload_bytes * 0.5)), crypto.Secret(raw_key=bytes(32))).envelope
    stego = engine.embed(cover, env, "lsb").stego

    def ws_mean(img: np.ndarray) -> float:
        x = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float()
        with torch.no_grad():
            residual, *_ = net.front_ends(x)
        return float(residual[:, 30:].mean())  # last 3 channels are the WS maps

    assert ws_mean(stego) > ws_mean(cover) + 0.05
    assert abs(ws_mean(noisy) - ws_mean(cover)) < 0.03


def test_checkpoints_without_ws_branch_still_load():
    import torch

    from app.ml.cnn import StegoNet, StegoNetConfig

    legacy = StegoNet(StegoNetConfig())  # v1.0/v1.1 architecture
    state = legacy.state_dict()
    assert "kb_pred" not in state  # non-persistent constant buffer
    StegoNet(StegoNetConfig(**StegoNetConfig().to_dict())).load_state_dict(state)
    assert StegoNet(StegoNetConfig(ws_branch=True))(torch.zeros(1, 3, 64, 64)).shape == (1, 4)
