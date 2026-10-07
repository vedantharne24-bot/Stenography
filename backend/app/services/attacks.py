"""Attack Lab: controlled image transformations and their measured effect.

For every attack the service *recomputes* (never estimates):
* steganalysis on the attacked image (CNN P(stego), predicted technique),
* frame extraction + SHA-256 integrity, and decryption when a key is supplied,
* bit-error rate of the embedded frame (when geometry is preserved),
* MSE / PSNR / SSIM between the image before and after the attack.
"""

from __future__ import annotations

import io
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.core.streaming import Trace
from app.db.models import AttackExperiment, User
from app.services import audit, crypto, image_io, metrics, storage
from app.services.audit import AuditAction
from app.services.steganalysis import _thresholds, analyze_array
from app.services.stego import engine


@dataclass(frozen=True)
class AttackSpec:
    key: str
    label: str
    params: dict[str, tuple[float, float, float]]  # name -> (min, max, default)
    description: str


SPECS: dict[str, AttackSpec] = {
    s.key: s
    for s in (
        AttackSpec("jpeg", "JPEG compression", {"quality": (5, 100, 75)}, "Re-encode as baseline JPEG (4:2:0) at the given quality."),
        AttackSpec("gaussian_noise", "Gaussian noise", {"sigma": (0.1, 30, 2)}, "Add zero-mean Gaussian noise with standard deviation σ (grey levels)."),
        AttackSpec("salt_pepper", "Salt & pepper noise", {"amount": (0.0001, 0.2, 0.005)}, "Set a fraction of pixels to 0 or 255."),
        AttackSpec("blur", "Gaussian blur", {"kernel": (3, 15, 3)}, "Gaussian blur with an odd kernel size (σ derived by OpenCV)."),
        AttackSpec("median", "Median filter", {"kernel": (3, 7, 3)}, "Median filter with an odd kernel size."),
        AttackSpec("resize", "Resize", {"scale": (0.25, 2.0, 0.75), "restore": (0, 1, 1)}, "Rescale by a factor; with restore=1 the image is scaled back to its original size (keeps geometry)."),
        AttackSpec("crop", "Crop", {"ratio": (0.3, 0.99, 0.9)}, "Keep the top-left ratio×ratio region."),
        AttackSpec("brightness", "Brightness shift", {"delta": (-80, 80, 10)}, "Add a constant to every channel (clipped)."),
        AttackSpec("contrast", "Contrast change", {"factor": (0.3, 2.0, 1.1)}, "Scale deviations from mid-grey (128) by a factor."),
        AttackSpec("rotate", "Rotation", {"degrees": (-15, 15, 1)}, "Rotate about the centre, same canvas size (reflected border)."),
    )
}

DEFAULT_SUITE: list[tuple[str, dict[str, float]]] = [
    ("jpeg", {"quality": 95}), ("jpeg", {"quality": 90}), ("jpeg", {"quality": 80}), ("jpeg", {"quality": 70}), ("jpeg", {"quality": 50}),
    ("gaussian_noise", {"sigma": 1}), ("gaussian_noise", {"sigma": 3}), ("gaussian_noise", {"sigma": 8}),
    ("salt_pepper", {"amount": 0.001}), ("salt_pepper", {"amount": 0.01}),
    ("blur", {"kernel": 3}), ("blur", {"kernel": 5}), ("median", {"kernel": 3}),
    ("resize", {"scale": 0.75, "restore": 1}), ("resize", {"scale": 0.5, "restore": 1}),
    ("crop", {"ratio": 0.9}),
    ("brightness", {"delta": 10}), ("brightness", {"delta": -20}),
    ("contrast", {"factor": 0.9}), ("contrast", {"factor": 1.2}),
    ("rotate", {"degrees": 1}),
]  # fmt: skip


def _odd(value: float) -> int:
    k = int(round(value))
    return k if k % 2 == 1 else k + 1


def normalise_params(attack: str, params: dict[str, Any]) -> dict[str, float]:
    spec = SPECS.get(attack)
    if spec is None:
        raise ValidationFailed(f"Unknown attack '{attack}'", details={"available": list(SPECS)})
    out: dict[str, float] = {}
    for name, (lo, hi, default) in spec.params.items():
        raw = params.get(name, default)
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(f"Parameter '{name}' must be numeric") from exc
        if not lo <= value <= hi:
            raise ValidationFailed(f"Parameter '{name}' must be between {lo} and {hi}")
        out[name] = value
    return out


def apply_attack(rgb: np.ndarray, attack: str, params: dict[str, float], seed: int = 1234) -> np.ndarray:
    rng = np.random.default_rng(seed)
    h, w = rgb.shape[:2]
    if attack == "jpeg":
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format="JPEG", quality=int(params["quality"]))
        return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
    if attack == "gaussian_noise":
        return np.clip(rgb + rng.normal(0, params["sigma"], rgb.shape), 0, 255).round().astype(np.uint8)
    if attack == "salt_pepper":
        out = rgb.copy()
        mask = rng.random((h, w))
        out[mask < params["amount"] / 2] = 0
        out[(mask >= params["amount"] / 2) & (mask < params["amount"])] = 255
        return out
    if attack == "blur":
        k = _odd(params["kernel"])
        return cv2.GaussianBlur(rgb, (k, k), 0)
    if attack == "median":
        return cv2.medianBlur(rgb, _odd(params["kernel"]))
    if attack == "resize":
        nw, nh = max(8, int(round(w * params["scale"]))), max(8, int(round(h * params["scale"])))
        interp = cv2.INTER_AREA if params["scale"] < 1 else cv2.INTER_CUBIC
        out = cv2.resize(rgb, (nw, nh), interpolation=interp)
        if params.get("restore", 1) >= 0.5:
            out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
        return out
    if attack == "crop":
        ch, cw = max(64, int(h * params["ratio"])), max(64, int(w * params["ratio"]))
        return np.ascontiguousarray(rgb[:ch, :cw])
    if attack == "brightness":
        return np.clip(rgb.astype(np.int16) + int(round(params["delta"])), 0, 255).astype(np.uint8)
    if attack == "contrast":
        return np.clip((rgb.astype(np.float64) - 128.0) * params["factor"] + 128.0, 0, 255).round().astype(np.uint8)
    if attack == "rotate":
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), params["degrees"], 1.0)
        return cv2.warpAffine(rgb, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    raise ValidationFailed(f"Unknown attack '{attack}'")


def _quality_vs_reference(before: np.ndarray, after: np.ndarray, attack: str, params: dict[str, float]) -> dict[str, Any]:
    if attack == "crop":
        reference = before[: after.shape[0], : after.shape[1]]
    elif before.shape != after.shape:
        reference = cv2.resize(before, (after.shape[1], after.shape[0]), interpolation=cv2.INTER_AREA)
    else:
        reference = before
    report = metrics.quality_report(reference, after)
    report["reference"] = "same region" if attack == "crop" else ("resampled original" if before.shape != after.shape else "original")
    return report


def _extraction(rgb: np.ndarray, algorithm: str | None, secret: crypto.Secret | None) -> dict[str, Any]:
    found = engine.extract(rgb, algorithm)
    out: dict[str, Any] = {
        "integrity": found.integrity,
        "algorithm": found.algorithm,
        "success": found.integrity == "verified",
        "ecc_corrected": found.body_corrected + found.header_corrected,
        "decryption": "not_attempted",
    }
    if found.integrity == "verified" and secret is not None and found.envelope is not None:
        try:
            crypto.decrypt_envelope(found.envelope, secret)
            out["decryption"] = "success"
        except Exception:  # noqa: BLE001 - any failure is reported, not raised
            out["decryption"] = "failed"
    return out


def evaluate_attack(
    stego: np.ndarray,
    baseline: dict[str, Any],
    attack: str,
    params: dict[str, float],
    *,
    secret: crypto.Secret | None,
    thresholds: dict[str, int],
    trace: Trace,
) -> tuple[dict[str, Any], np.ndarray]:
    t0 = time.perf_counter()
    attacked = apply_attack(stego, attack, params)
    quiet = Trace()  # inner analysis steps are not streamed for every attack in a batch
    analysis = analyze_array(attacked, quiet, thresholds, explain=False, use_rf=False, check_signature=False).result
    extraction = _extraction(attacked, baseline["extraction"]["algorithm"], secret)
    ber = engine.bit_error_rate(stego, attacked, baseline["extraction"]["algorithm"]) if baseline["extraction"]["algorithm"] else None
    quality = _quality_vs_reference(stego, attacked, attack, params)
    row = {
        "attack": attack,
        "label": SPECS[attack].label,
        "params": params,
        "shape": list(attacked.shape[:2]),
        "detection_probability": analysis["p_stego"],
        "predicted_technique": analysis["predicted_technique"],
        "prediction": analysis["prediction"],
        "extraction": extraction,
        "bit_error_rate": ber,
        "quality": quality,
        "ms": (time.perf_counter() - t0) * 1000,
    }
    trace.step(
        "attack",
        f"{SPECS[attack].label} {params}: P(stego) {analysis['p_stego']:.3f} · extraction {'SUCCESS' if extraction['success'] else 'FAILED'}"
        + (f" · BER {ber:.4f}" if ber is not None else ""),
        level="info" if extraction["success"] else "warn",
    )
    return row, attacked


def baseline_state(stego: np.ndarray, secret: crypto.Secret | None, thresholds: dict[str, int], trace: Trace) -> dict[str, Any]:
    with trace.span("baseline", "Baseline: steganalysis + extraction on the unmodified image…"):
        analysis = analyze_array(stego, Trace(), thresholds, explain=False, use_rf=False, check_signature=False).result
        extraction = _extraction(stego, None, secret)
    trace.step(
        "baseline",
        f"Before attack: P(stego) {analysis['p_stego']:.3f} · extraction {'SUCCESS' if extraction['success'] else extraction['integrity'].upper()}"
        + (f" ({extraction['algorithm'].upper()})" if extraction["algorithm"] else ""),
    )
    return {
        "detection_probability": analysis["p_stego"],
        "predicted_technique": analysis["predicted_technique"],
        "prediction": analysis["prediction"],
        "extraction": extraction,
        "model_version": analysis["model"]["version"],
    }


def _persist(db: Session, user: User, batch_id: uuid.UUID | None, image: image_io.LoadedImage, baseline: dict[str, Any], row: dict[str, Any], artifact_id: str | None) -> AttackExperiment:
    exp = AttackExperiment(
        user_id=user.id,
        batch_id=batch_id,
        source_image=image.sha256,
        source_filename=image.filename,
        algorithm=baseline["extraction"]["algorithm"],
        attack_type=row["attack"],
        attack_parameters=row["params"],
        detection_probability_before=baseline["detection_probability"],
        detection_probability=row["detection_probability"],
        predicted_technique=row["predicted_technique"],
        extraction_success=row["extraction"]["success"],
        integrity_status=row["extraction"]["integrity"],
        decryption_status=row["extraction"]["decryption"],
        bit_error_rate=row["bit_error_rate"],
        psnr=row["quality"]["psnr"],
        ssim=row["quality"]["ssim"],
        mse=row["quality"]["mse"],
        artifacts={"attacked": artifact_id} if artifact_id else {},
    )
    db.add(exp)
    return exp


def _secret(secret_value: str | None) -> crypto.Secret | None:
    return crypto.secret_from_user_input(secret_value) if secret_value else None


def run_single(trace: Trace, db: Session, user: User, *, image_bytes: bytes, image_name: str, image_mime: str | None, attack: str, params: dict[str, Any], secret_value: str | None, ip: str) -> dict[str, Any]:
    user = db.merge(user)
    clean = normalise_params(attack, params)
    with trace.span("validate", "Loading image…"):
        image = image_io.load_image(image_bytes, image_name, image_mime)
    thresholds = _thresholds(db)
    secret = _secret(secret_value)
    baseline = baseline_state(image.rgb, secret, thresholds, trace)
    with trace.span("attack", f"Applying {SPECS[attack].label}…"):
        row, attacked = evaluate_attack(image.rgb, baseline, attack, clean, secret=secret, thresholds=thresholds, trace=trace)
    artifact = storage.save_artifact(db, user=user, kind="attacked_image", data=image_io.encode_png(attacked), mime="image/png")
    preview_before = storage.save_artifact(db, user=user, kind="attack_before", data=image_io.encode_preview(image.rgb), mime="image/png")
    preview_after = storage.save_artifact(db, user=user, kind="attack_after", data=image_io.encode_preview(attacked), mime="image/png")
    exp = _persist(db, user, None, image, baseline, row, str(artifact.id))
    audit.record(db, AuditAction.ATTACK_RUN, "success", user=user, ip=ip, commit=False, attack=attack, params=clean, image_hash=image.sha256, extraction=row["extraction"]["integrity"])
    db.commit()
    return {
        "experiment_id": str(exp.id),
        "image": {"filename": image.filename, "sha256": image.sha256, "width": image.width, "height": image.height},
        "before": baseline,
        "after": row,
        "artifacts": {"attacked": str(artifact.id), "before_preview": str(preview_before.id), "after_preview": str(preview_after.id)},
    }


def run_batch(trace: Trace, db: Session, user: User, *, image_bytes: bytes, image_name: str, image_mime: str | None, suite: list[tuple[str, dict[str, Any]]] | None, secret_value: str | None, ip: str) -> dict[str, Any]:
    user = db.merge(user)
    plan = [(a, normalise_params(a, p)) for a, p in (suite or DEFAULT_SUITE)]
    if len(plan) > 40:
        raise ValidationFailed("At most 40 attacks per batch")
    with trace.span("validate", "Loading image…"):
        image = image_io.load_image(image_bytes, image_name, image_mime)
    thresholds = _thresholds(db)
    secret = _secret(secret_value)
    baseline = baseline_state(image.rgb, secret, thresholds, trace)
    batch_id = uuid.uuid4()
    rows = []
    trace.step("batch", f"Running {len(plan)} attacks…")
    for attack, params in plan:
        row, _ = evaluate_attack(image.rgb, baseline, attack, params, secret=secret, thresholds=thresholds, trace=trace)
        _persist(db, user, batch_id, image, baseline, row, None)
        rows.append(row)
    survived = sum(1 for r in rows if r["extraction"]["success"])
    detected = sum(1 for r in rows if r["prediction"] == "stego")
    audit.record(db, AuditAction.ATTACK_BATCH, "success", user=user, ip=ip, commit=False, attacks=len(rows), survived=survived, image_hash=image.sha256, batch_id=str(batch_id))
    db.commit()
    trace.step("done", f"Batch complete: payload survived {survived}/{len(rows)} attacks; detector flagged {detected}/{len(rows)}")
    return {
        "batch_id": str(batch_id),
        "image": {"filename": image.filename, "sha256": image.sha256, "width": image.width, "height": image.height},
        "before": baseline,
        "rows": rows,
        "summary": {
            "attacks": len(rows),
            "extraction_survival_rate": survived / len(rows),
            "detection_rate": detected / len(rows),
            "mean_psnr": float(np.mean([r["quality"]["psnr"] for r in rows if r["quality"]["psnr"] is not None])) if rows else None,
        },
    }


def catalogue() -> list[dict[str, Any]]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "description": s.description,
            "params": {name: {"min": lo, "max": hi, "default": d} for name, (lo, hi, d) in s.params.items()},
        }
        for s in SPECS.values()
    ]


AttackFn = Callable[[np.ndarray, str, dict[str, float]], np.ndarray]
