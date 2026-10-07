"""Steganalysis inference: tiling, CNN + Grad-CAM, Random Forest, anomaly model.

Pipeline for one image::

    RGB ─► 256×256 tiles on the 8-px grid (no resizing: resampling destroys stego noise)
        ├─► StegoNet ─► per-tile softmax ─► mean ─► P(normal, lsb, dct, dwt)
        │        └─► Grad-CAM on the three branch heads (optional)
        ├─► handcrafted features per tile ─► Random Forest ─► mean probabilities
        └─► Mahalanobis distance ─► percentile vs clean validation covers (anomaly)

Models are loaded once (lazily) from the *active* registry version and reused;
the version used is returned with every result so it can be stored.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.errors import ModelUnavailable
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.ml import registry
from app.ml.device import get_device

log = get_logger("app.ml.inference")
CLASSES = ("normal", "lsb", "dct", "dwt")
TILE = 256
GRID = 8


# --------------------------------------------------------------------------- tiling


def tile_origins(h: int, w: int, tile: int = TILE, max_tiles: int | None = None) -> list[tuple[int, int, int, int]]:
    """Grid-aligned tiles as (y, x, th, tw). Small images become one tile cropped to the 8-px grid."""
    if h < tile or w < tile:
        th, tw = (min(h, tile) // GRID) * GRID, (min(w, tile) // GRID) * GRID
        return [(0, 0, th, tw)]

    def starts(size: int) -> list[int]:
        out = list(range(0, size - tile + 1, tile))
        last = ((size - tile) // GRID) * GRID
        if out[-1] != last:
            out.append(last)
        return out

    tiles = [(y, x, tile, tile) for y in starts(h) for x in starts(w)]
    if max_tiles and len(tiles) > max_tiles:
        idx = np.unique(np.linspace(0, len(tiles) - 1, max_tiles).round().astype(int))
        tiles = [tiles[i] for i in idx]
    return tiles


# --------------------------------------------------------------------------- loaded models


@dataclass
class CnnHandle:
    model: Any
    version: str
    card: dict[str, Any]
    path: Path


@dataclass
class RfHandle:
    bundle: dict[str, Any]
    version: str
    card: dict[str, Any]


class ModelService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._cnn: CnnHandle | None = None
        self._rf: RfHandle | None = None

    def _active(self, model_name: str) -> registry.ModelDir | None:
        with SessionLocal() as db:
            row = registry.active_version(db, model_name)
            if row is None:
                return None
            return registry.find(row.model_name, row.version)

    def cnn(self) -> CnnHandle:
        target = self._active(registry.CNN_MODEL_NAME)
        if target is None or not target.weights_path.exists():
            raise ModelUnavailable(
                "No trained steganalysis CNN is registered. Run `python -m pipeline.train_model --model cnn`.",
                details={"model": registry.CNN_MODEL_NAME},
            )
        with self._lock:
            if self._cnn is None or self._cnn.version != target.version:
                import torch

                from app.ml.cnn import StegoNet, StegoNetConfig

                checkpoint = torch.load(target.weights_path, map_location="cpu", weights_only=True)
                model = StegoNet(StegoNetConfig(**checkpoint["config"]))
                model.load_state_dict(checkpoint["state_dict"])
                model.to(get_device()).eval()
                self._cnn = CnnHandle(model, target.version, target.card, target.path)
                log.info("Loaded %s v%s on %s", registry.CNN_MODEL_NAME, target.version, get_device())
            return self._cnn

    def rf(self) -> RfHandle | None:
        target = self._active(registry.RF_MODEL_NAME)
        if target is None or not target.weights_path.exists():
            return None
        with self._lock:
            if self._rf is None or self._rf.version != target.version:
                import joblib

                self._rf = RfHandle(joblib.load(target.weights_path), target.version, target.card)
                log.info("Loaded %s v%s", registry.RF_MODEL_NAME, target.version)
            return self._rf

    def invalidate(self) -> None:
        with self._lock:
            self._cnn = None
            self._rf = None

    @property
    def inference_lock(self) -> threading.Lock:
        return self._infer_lock


models = ModelService()


# --------------------------------------------------------------------------- results


@dataclass
class CnnResult:
    probabilities: dict[str, float]
    tile_probabilities: list[dict[str, Any]]
    version: str
    tiles: int
    ms: float


@dataclass
class Explanation:
    heatmap: np.ndarray  # float32 H×W in [0, 1]
    branch_share: dict[str, float]
    target_class: str
    tiles_explained: int
    ms: float


@dataclass
class RfResult:
    probabilities: dict[str, float]
    anomaly: float
    version: str
    top_features: list[dict[str, Any]] = field(default_factory=list)
    ms: float = 0.0


# --------------------------------------------------------------------------- CNN


def _tiles_tensor(rgb: np.ndarray, origins: list[tuple[int, int, int, int]]) -> Any:
    import torch

    crops = np.stack([rgb[y : y + th, x : x + tw] for y, x, th, tw in origins])
    return torch.from_numpy(crops).permute(0, 3, 1, 2)


def run_cnn(rgb: np.ndarray, batch: int = 32) -> CnnResult:
    import torch

    handle = models.cnn()
    device = get_device()
    origins = tile_origins(*rgb.shape[:2], max_tiles=get_settings().max_inference_tiles)
    t0 = time.perf_counter()
    probs: list[np.ndarray] = []
    with models.inference_lock, torch.no_grad():
        x_all = _tiles_tensor(rgb, origins)
        for start in range(0, x_all.shape[0], batch):
            xb = x_all[start : start + batch].to(device).float()
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = handle.model(xb)
            probs.append(torch.softmax(logits.float(), dim=1).cpu().numpy())
    p = np.concatenate(probs)
    mean = p.mean(axis=0)
    tiles = [
        {"y": y, "x": x, "h": th, "w": tw, "p_stego": float(1 - row[0]), "argmax": CLASSES[int(row.argmax())]}
        for (y, x, th, tw), row in zip(origins, p)
    ]
    return CnnResult(
        probabilities={c: float(v) for c, v in zip(CLASSES, mean)},
        tile_probabilities=tiles,
        version=handle.version,
        tiles=len(origins),
        ms=(time.perf_counter() - t0) * 1000,
    )


def explain(rgb: np.ndarray, target: str, chunk: int = 8) -> Explanation:
    """Grad-CAM (Selvaraju et al. 2017) on each branch head, stitched over tiles.

    The target is a *stego class logit*; the map shows regions whose features most
    increased that logit. It indicates where the network found evidence - not the exact
    pixels that carry hidden bits (the model was not trained for localisation).
    """
    import torch
    from torch.nn import functional as F

    handle = models.cnn()
    device = get_device()
    target_idx = CLASSES.index(target)
    h, w = rgb.shape[:2]
    origins = tile_origins(h, w, max_tiles=get_settings().max_inference_tiles)
    heat = np.zeros((h, w), dtype=np.float64)
    weight = np.zeros((h, w), dtype=np.float64)
    branch_totals = {"spatial": 0.0, "dct": 0.0, "dwt": 0.0}
    t0 = time.perf_counter()

    with models.inference_lock:
        x_all = _tiles_tensor(rgb, origins)
        for start in range(0, x_all.shape[0], chunk):
            xb = x_all[start : start + chunk].to(device).float()
            handle.model.zero_grad(set_to_none=True)
            logits, maps = handle.model(xb, return_maps=True)
            for m in maps.values():
                m.retain_grad()
            logits[:, target_idx].sum().backward()
            th, tw = xb.shape[2], xb.shape[3]
            combined = torch.zeros((xb.shape[0], 1, th, tw), device=device)
            for name, act in maps.items():
                grads = act.grad
                weights = grads.mean(dim=(2, 3), keepdim=True)
                cam = F.relu((weights * act).sum(dim=1, keepdim=True))
                branch_totals[name] += cam.detach().sum().item()
                combined += F.interpolate(cam, size=(th, tw), mode="bilinear", align_corners=False)
            cams = combined[:, 0].detach().cpu().numpy()
            for (y, x, _, _), cam in zip(origins[start : start + chunk], cams):
                heat[y : y + th, x : x + tw] += cam
                weight[y : y + th, x : x + tw] += 1
        handle.model.zero_grad(set_to_none=True)

    covered = weight > 0
    heat[covered] /= weight[covered]
    peak = heat.max()
    if peak > 0:
        heat /= peak
    total = sum(branch_totals.values())
    share = {k: (v / total if total > 0 else 0.0) for k, v in branch_totals.items()}
    return Explanation(
        heatmap=heat.astype(np.float32),
        branch_share=share,
        target_class=target,
        tiles_explained=len(origins),
        ms=(time.perf_counter() - t0) * 1000,
    )


# --------------------------------------------------------------------------- Random Forest + anomaly


def run_rf(rgb: np.ndarray) -> RfResult | None:
    from app.ml.features import extract_features

    handle = models.rf()
    if handle is None:
        return None
    t0 = time.perf_counter()
    origins = tile_origins(*rgb.shape[:2], max_tiles=min(16, get_settings().max_inference_tiles))
    feats = np.stack([extract_features(np.ascontiguousarray(rgb[y : y + th, x : x + tw])) for y, x, th, tw in origins])
    model = handle.bundle["model"]
    probs = model.predict_proba(feats).mean(axis=0)

    anomaly_cfg = handle.bundle["anomaly"]
    z = anomaly_cfg["scaler"].transform(feats) - anomaly_cfg["location"]
    dist = np.sqrt(np.einsum("ij,jk,ik->i", z, anomaly_cfg["precision"], z))
    calibration = anomaly_cfg["calibration"]
    anomaly = float(np.mean(np.searchsorted(calibration, dist, side="right") / calibration.size))

    # Per-image feature deviations (z-scores vs clean covers) for the most important features.
    names = handle.bundle["feature_names"]
    importances = model.feature_importances_
    mean_z = (anomaly_cfg["scaler"].transform(feats)).mean(axis=0)
    order = np.argsort(-importances)[:8]
    top = [
        {"feature": names[i], "importance": float(importances[i]), "value": float(feats[:, i].mean()), "z_vs_covers": float(mean_z[i])}
        for i in order
    ]
    return RfResult(
        probabilities={c: float(v) for c, v in zip(handle.bundle["classes"], probs)},
        anomaly=anomaly,
        version=handle.version,
        top_features=top,
        ms=(time.perf_counter() - t0) * 1000,
    )


# --------------------------------------------------------------------------- rendering


def heatmap_rgb(heat: np.ndarray) -> np.ndarray:
    """Map [0,1] -> 'inferno'-like colours without matplotlib (piecewise-linear LUT)."""
    stops = np.array([[0.0, 0, 0, 4], [0.25, 87, 16, 110], [0.5, 188, 55, 84], [0.75, 249, 142, 9], [1.0, 252, 255, 164]])
    v = np.clip(heat, 0, 1)
    out = np.zeros(v.shape + (3,), dtype=np.float64)
    for c in range(3):
        out[..., c] = np.interp(v, stops[:, 0], stops[:, c + 1])
    return out.astype(np.uint8)


def overlay(rgb: np.ndarray, heat: np.ndarray, alpha: float = 0.55) -> np.ndarray:
    colour = heatmap_rgb(heat).astype(np.float64)
    a = (alpha * np.clip(heat, 0, 1))[..., None]
    grey = rgb.astype(np.float64).mean(axis=2, keepdims=True) * 0.6
    return np.clip(grey * (1 - a) + colour * a, 0, 255).astype(np.uint8)
