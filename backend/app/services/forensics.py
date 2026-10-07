"""Forensic image analysis: metadata, statistics, LSB/DCT/DWT diagnostics, visual attacks, AI verdict.

Findings are phrased as evidence, never proof: metadata and individual statistics can be
explained by ordinary processing, so each finding states what it is *consistent with*.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pywt
from scipy.ndimage import convolve
from scipy.stats import kurtosis, skew

from app.core.streaming import Trace
from app.db.models import AnalysisRecord, User
from app.ml import features as feat
from app.services import audit, image_io, storage
from app.services.audit import AuditAction
from app.services.steganalysis import _thresholds, analyze_array

_KB = np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]], dtype=np.float64) / 4.0
_LUMA = np.array([0.299, 0.587, 0.114])


def _entropy(values: np.ndarray) -> float:
    hist = np.bincount(values.ravel(), minlength=256).astype(np.float64)
    p = hist / hist.sum()
    return float(-np.sum(p[p > 0] * np.log2(p[p > 0])))


def _channel_stats(ch: np.ndarray) -> dict[str, float]:
    f = ch.astype(np.float64).ravel()
    return {
        "mean": float(f.mean()),
        "std": float(f.std()),
        "min": int(ch.min()),
        "max": int(ch.max()),
        "skewness": float(skew(f)) if f.std() > 0 else 0.0,
        "kurtosis": float(kurtosis(f)) if f.std() > 0 else 0.0,
        "saturated_fraction": float(np.mean((ch == 0) | (ch == 255))),
        "entropy_bits": _entropy(ch),
    }


def _lsb_analysis(rgb: np.ndarray) -> dict[str, dict[str, float]]:
    out = {}
    for idx, name in enumerate("RGB"):
        ch = rgb[..., idx]
        p, asym = feat._chi_square_p(ch)
        out[name] = {
            "chi_square_embedding_probability": p,
            "pair_asymmetry": asym,
            "spa_estimate": feat._spa(ch),
            "ones_fraction": float(np.mean(ch & 1)),
            "lsb_horizontal_correlation": feat._lsb_corr(ch),
        }
    return out


def _dct_stats(y: np.ndarray) -> dict[str, Any]:
    coeffs = feat._block_dct(y)
    hist = {}
    for u, v in ((1, 2), (2, 2)):
        values = np.clip(np.rint(coeffs[:, u, v]), -40, 40).astype(int)
        hist[f"{u}{v}"] = np.bincount(values + 40, minlength=81).tolist()
    periodic = {f"{u}{v}": feat.periodicity(coeffs[:, u, v]) for u, v in feat._PERIODIC_POSITIONS}
    dx = np.abs(np.diff(y, axis=1))
    cols = np.arange(dx.shape[1])
    blockiness = float(dx[:, (cols % 8) == 7].mean() / (dx[:, (cols % 8) != 7].mean() + 1e-12))
    return {
        "blocks": int(coeffs.shape[0]),
        "blockiness": blockiness,
        "coefficient_histograms": {"range": [-40, 40], "positions": hist},
        "periodicity": {k: {"score": v[0], "period": v[1]} for k, v in periodic.items()},
        "max_periodicity": max(v[0] for v in periodic.values()),
    }


def _dwt_stats(y: np.ndarray) -> dict[str, Any]:
    h, w = (y.shape[0] // 8) * 8, (y.shape[1] // 8) * 8
    coeffs = pywt.wavedec2(y[:h, :w], "haar", level=3)
    out: dict[str, Any] = {}
    for level, details in zip((3, 2, 1), coeffs[1:]):
        for band_name, band in zip("HVD", details):
            score, period = feat.periodicity(band.ravel(), limit=128)
            out[f"L{level}{band_name}"] = {
                "mean_abs": float(np.mean(np.abs(band))),
                "std": float(band.std()),
                "periodicity": score,
                "period": period,
            }
    return out


def _findings(meta: dict[str, Any], lsb: dict[str, Any], dct: dict[str, Any], dwt: dict[str, Any], ai: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    def add(severity: str, title: str, detail: str) -> None:
        findings.append({"severity": severity, "title": title, "detail": detail})

    max_chi = max(v["chi_square_embedding_probability"] for v in lsb.values())
    max_spa = max(v["spa_estimate"] for v in lsb.values())
    if max_chi > 0.95 and max_spa > 0.05:
        add("high", "LSB pair equalisation", f"Chi-square attack p={max_chi:.3f} and SPA rate estimate {max_spa:.3f}: pairs of values are equalised, consistent with LSB replacement.")
    elif max_spa > 0.05:
        add("medium", "Elevated SPA estimate", f"Sample Pairs Analysis estimates an embedding rate of {max_spa:.3f} in at least one channel.")
    else:
        add("info", "LSB statistics nominal", f"Chi-square p ≤ {max_chi:.3f}, SPA ≤ {max_spa:.3f}: no LSB-replacement signature.")

    if dct["max_periodicity"] > 6:
        add("medium", "Periodic DCT coefficient histogram", f"Peak periodicity score {dct['max_periodicity']:.1f} indicates a quantisation lattice in 8×8 block coefficients - produced by JPEG compression or by QIM embedding.")
    if dct["blockiness"] > 1.15:
        add("info", "8×8 block grid visible", f"Blockiness ratio {dct['blockiness']:.2f}: image has passed through block-based (JPEG-like) compression.")
    dwt_peak = max(v["periodicity"] for v in dwt.values())
    if dwt_peak > 6:
        add("medium", "Periodic wavelet coefficients", f"Wavelet subband periodicity {dwt_peak:.1f} suggests quantised (QIM-style) detail coefficients.")

    exif = meta.get("exif") or {}
    if exif.get("Software"):
        add("info", "Editing software tag", f"EXIF Software = '{exif['Software']}'. Indicates processing, not steganography by itself.")
    if not exif and meta.get("pil_format") in ("JPEG",):
        add("info", "No EXIF in JPEG", "JPEG without EXIF is typical of re-saved or web-processed images; this alone is not evidence of hidden data.")
    if meta.get("text_chunks"):
        add("info", "PNG text chunks present", f"Keys: {', '.join(meta['text_chunks'][:6])}. Inspect for appended data.")

    level = ai["risk"]["level"]
    severity = {"LOW": "info", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "high"}[level]
    add(severity, f"AI verdict: {ai['prediction'].upper()}", f"StegoNet P(stego)={ai['p_stego']:.3f}, technique {ai['predicted_technique'].upper()}; combined risk {ai['risk']['score']:.1f} ({level}).")
    if ai.get("signature"):
        add("high", "StegoLab frame signature", f"A {ai['signature']['algorithm'].upper()} frame header is physically present (integrity {ai['signature']['integrity']}).")
    return findings


def _residual_image(y: np.ndarray) -> np.ndarray:
    residual = np.abs(convolve(y, _KB, mode="reflect"))
    scale = np.percentile(residual, 99.5) or 1.0
    grey = np.clip(residual / scale * 255.0, 0, 255).astype(np.uint8)
    return np.repeat(grey[..., None], 3, axis=2)


def run(trace: Trace, db, user: User, *, image_bytes: bytes, image_name: str, image_mime: str | None, ip: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    user = db.merge(user)
    with trace.span("validate", "Loading and validating image…"):
        image = image_io.load_image(image_bytes, image_name, image_mime)
    rgb = image.rgb
    y = rgb.astype(np.float64) @ _LUMA
    trace.step("hash", f"SHA-256 {image.sha256}")

    with trace.span("stats", "Computing pixel statistics, entropy and histograms…"):
        channels = {name: _channel_stats(rgb[..., i]) for i, name in enumerate("RGB")}
        histograms = {name: np.bincount(rgb[..., i].ravel(), minlength=256).tolist() for i, name in enumerate("RGB")}
        luma_entropy = _entropy(np.clip(np.rint(y), 0, 255).astype(np.uint8))
    with trace.span("lsb", "Running chi-square attack and Sample Pairs Analysis…"):
        lsb = _lsb_analysis(rgb)
    with trace.span("dct", "Computing block-DCT statistics…"):
        dct = _dct_stats(y)
    with trace.span("dwt", "Computing wavelet subband statistics…"):
        dwt = _dwt_stats(y)

    ai = analyze_array(rgb, trace, _thresholds(db), explain=True)

    with trace.span("store", "Rendering residual, LSB-plane and heatmap visualisations…"):
        lsb_plane = ((rgb & 1) * 255).astype(np.uint8)
        artifacts = {
            "preview": str(storage.save_artifact(db, user=user, kind="forensic_preview", data=image_io.encode_preview(rgb), mime="image/png").id),
            "noise_residual": str(storage.save_artifact(db, user=user, kind="noise_residual", data=image_io.encode_preview(_residual_image(y)), mime="image/png").id),
            "lsb_plane": str(storage.save_artifact(db, user=user, kind="lsb_plane", data=image_io.encode_preview(lsb_plane), mime="image/png").id),
        }
        if ai.heatmap is not None:
            from app.ml import inference

            artifacts["heatmap"] = str(storage.save_artifact(db, user=user, kind="gradcam_heatmap", data=image_io.encode_preview(inference.heatmap_rgb(ai.heatmap)), mime="image/png").id)
            artifacts["overlay"] = str(storage.save_artifact(db, user=user, kind="gradcam_overlay", data=image_io.encode_preview(inference.overlay(rgb, ai.heatmap)), mime="image/png").id)

    result = ai.result
    record = AnalysisRecord(
        user_id=user.id, source="forensics", file_hash=image.sha256, filename=image.filename,
        image_format=image.format, width=image.width, height=image.height, file_size=image.file_size,
        prediction=result["prediction"], confidence=result["confidence"], predicted_technique=result["predicted_technique"],
        probabilities=result["probabilities"], rf_probabilities=(result["rf"] or {}).get("probabilities"),
        anomaly_score=(result["rf"] or {}).get("anomaly"), risk_score=result["risk"]["score"], risk_level=result["risk"]["level"],
        risk_factors=result["risk"], payload_signature=result["signature"], model_name=result["model"]["name"],
        model_version=result["model"]["version"], inference_ms=sum(result["timings_ms"].values()), tiles=len(result["tiles"]),
        artifacts=artifacts,
    )  # fmt: skip
    findings = _findings(image.metadata, lsb, dct, dwt, result)
    record.details = {
        "explanation": result["explanation"],
        "rf_top_features": (result["rf"] or {}).get("top_features"),
        "rf_model": result["rf_model"],
        "p_stego": result["p_stego"],
        "technique_confidence": result["technique_confidence"],
        "findings": findings,
        "metadata": {k: image.metadata.get(k) for k in ("pil_format", "mode", "exif", "icc_profile", "jpeg_quality_estimate", "text_chunks")},
        "entropy_luma": luma_entropy,
        "lsb_analysis": lsb,
        "dct_summary": {"blockiness": dct["blockiness"], "max_periodicity": dct["max_periodicity"]},
    }
    db.add(record)
    audit.record(db, AuditAction.FORENSIC_ANALYSIS, "success", user=user, ip=ip, commit=False, analysis_id=str(record.id), image_hash=image.sha256, risk_level=result["risk"]["level"])
    audit.record(db, AuditAction.MODEL_USED, "success", user=user, ip=ip, commit=False, model=result["model"]["name"], version=result["model"]["version"])
    db.commit()
    trace.step("done", "Forensic analysis complete")

    return {
        "analysis_id": str(record.id),
        "file": {
            "filename": image.filename, "format": image.format, "file_size": image.file_size, "sha256": image.sha256,
            "width": image.width, "height": image.height, "megapixels": image.width * image.height / 1e6,
            "mode": image.original_mode, "warnings": image.warnings,
        },
        "metadata": image.metadata,
        "entropy": {"luma_bits": luma_entropy, **{name: channels[name]["entropy_bits"] for name in "RGB"}},
        "histograms": histograms,
        "pixel_stats": channels,
        "lsb_analysis": lsb,
        "dct_stats": dct,
        "dwt_stats": dwt,
        "ai": result,
        "findings": findings,
        "disclaimer": "Metadata and individual statistics can be explained by ordinary editing or compression; none of them alone proves the presence of hidden data.",
        "artifacts": artifacts,
        "duration_ms": (time.perf_counter() - started) * 1000,
    }
