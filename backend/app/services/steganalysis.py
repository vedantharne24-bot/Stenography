"""AI steganalysis workflow (model inference + explanation + risk), with persistence."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.streaming import Trace
from app.db.models import AnalysisRecord, User
from app.ml import inference, registry
from app.services import audit, image_io, risk, storage, system_settings
from app.services.audit import AuditAction
from app.services.stego import engine

CLASSES = inference.CLASSES


@dataclass
class ArrayAnalysis:
    result: dict[str, Any]
    heatmap: np.ndarray | None


def _thresholds(db: Session) -> dict[str, int]:
    values = system_settings.get_all(db)
    return {k: int(values[k]) for k in ("risk_threshold_medium", "risk_threshold_high", "risk_threshold_critical")}


def analyze_array(
    rgb: np.ndarray,
    trace: Trace,
    thresholds: dict[str, int],
    *,
    explain: bool = True,
    use_rf: bool = True,
    check_signature: bool = True,
) -> ArrayAnalysis:
    timings: dict[str, float] = {}
    with trace.span("model", "Loading StegoNet model…") as info:
        handle = inference.models.cnn()
        info.update(version=handle.version)
    origins = inference.tile_origins(*rgb.shape[:2])
    trace.step("preprocess", f"Preprocessing: {len(origins)} tile(s) of ≤256 px on the 8-px grid (no resampling)")

    with trace.span("inference", "Running CNN inference…") as info:
        cnn = inference.run_cnn(rgb)
        info.update(tiles=cnn.tiles)
    timings["cnn"] = cnn.ms
    probs = cnn.probabilities
    for name in CLASSES:
        trace.step("inference", f"{name.upper()} probability: {probs[name]:.3f}")

    rf_result = None
    if use_rf:
        with trace.span("features", "Extracting handcrafted features + Random Forest…") as info:
            rf_result = inference.run_rf(rgb)
            if rf_result:
                info.update(anomaly=round(rf_result.anomaly, 3))
        if rf_result:
            timings["rf"] = rf_result.ms
            trace.step("features", f"RF P(stego) {1 - rf_result.probabilities['normal']:.3f} · anomaly percentile {rf_result.anomaly:.3f}")
        else:
            trace.step("features", "Random Forest not trained - skipped", level="warn")

    signature = None
    if check_signature:
        with trace.span("signature", "Scanning for StegoLab frame signatures (LSB/DCT/DWT decoders)…"):
            found = engine.extract(rgb)
        if found.found:
            signature = {"algorithm": found.algorithm, "integrity": found.integrity}
            trace.step("signature", f"Frame header found ({found.algorithm.upper()}), integrity {found.integrity.upper()}", level="warn")
        else:
            trace.step("signature", "No StegoLab frame header present")

    argmax = max(CLASSES, key=lambda c: probs[c])
    p_stego = 1.0 - probs["normal"]
    prediction = "cover" if argmax == "normal" else "stego"
    technique_conf = (probs[argmax] / p_stego) if prediction == "stego" and p_stego > 0 else None
    trace.step("decision", f"Classification: {prediction.upper()}" + (f" · technique {argmax.upper()}" if prediction == "stego" else ""))

    risk_result = risk.compute_risk(
        p_cnn_stego=p_stego,
        p_rf_stego=None if rf_result is None else 1.0 - rf_result.probabilities["normal"],
        anomaly=None if rf_result is None else rf_result.anomaly,
        signature=signature,
        thresholds=thresholds,
    )
    trace.step("risk", f"Risk score {risk_result.score:.1f} → {risk_result.level}")

    heat = None
    explanation = None
    if explain:
        target = argmax if argmax != "normal" else max(CLASSES[1:], key=lambda c: probs[c])
        with trace.span("explain", f"Generating Grad-CAM for '{target}' evidence…"):
            exp = inference.explain(rgb, target)
        heat = exp.heatmap
        timings["gradcam"] = exp.ms
        explanation = {
            "method": "Grad-CAM over the spatial, block-DCT and wavelet branch heads",
            "target_class": exp.target_class,
            "branch_share": exp.branch_share,
            "tiles": exp.tiles_explained,
            "note": (
                "Highlights regions whose features most increased the "
                f"'{exp.target_class.upper()}' score. It shows where the model found evidence, "
                "not the exact pixels that carry hidden bits."
            ),
        }

    rf_model = None
    if rf_result:
        rf_model = {"name": registry.RF_MODEL_NAME, "version": rf_result.version}
    result = {
        "prediction": prediction,
        "confidence": probs[argmax],
        "p_stego": p_stego,
        "predicted_technique": argmax,
        "technique_confidence": technique_conf,
        "probabilities": probs,
        "rf": None
        if rf_result is None
        else {"probabilities": rf_result.probabilities, "anomaly": rf_result.anomaly, "top_features": rf_result.top_features},
        "signature": signature,
        "risk": risk_result.as_dict(),
        "model": {"name": registry.CNN_MODEL_NAME, "version": cnn.version},
        "rf_model": rf_model,
        "tiles": cnn.tile_probabilities,
        "explanation": explanation,
        "timings_ms": timings,
    }
    return ArrayAnalysis(result=result, heatmap=heat)


def analyze_upload(
    trace: Trace,
    db: Session,
    user: User,
    *,
    image_bytes: bytes,
    image_name: str,
    image_mime: str | None,
    explain: bool,
    ip: str,
    source: str = "steganalysis",
) -> dict[str, Any]:
    started = time.perf_counter()
    user = db.merge(user)
    with trace.span("validate", "Validating image…") as info:
        image = image_io.load_image(image_bytes, image_name, image_mime)
        info.update(width=image.width, height=image.height, format=image.format)
    trace.step("hash", f"SHA-256 calculated: {image.sha256[:16]}…")

    analysis = analyze_array(image.rgb, trace, _thresholds(db), explain=explain)
    result = analysis.result

    artifacts: dict[str, str] = {}
    with trace.span("store", "Storing analysis artefacts…"):
        artifacts["image_preview"] = str(
            storage.save_artifact(db, user=user, kind="analysis_preview", data=image_io.encode_preview(image.rgb), mime="image/png").id
        )
        if analysis.heatmap is not None:
            heat_png = image_io.encode_preview(inference.heatmap_rgb(analysis.heatmap))
            over_png = image_io.encode_preview(inference.overlay(image.rgb, analysis.heatmap))
            artifacts["heatmap"] = str(storage.save_artifact(db, user=user, kind="gradcam_heatmap", data=heat_png, mime="image/png").id)
            artifacts["overlay"] = str(storage.save_artifact(db, user=user, kind="gradcam_overlay", data=over_png, mime="image/png").id)

    record = AnalysisRecord(
        user_id=user.id,
        source=source,
        file_hash=image.sha256,
        filename=image.filename,
        image_format=image.format,
        width=image.width,
        height=image.height,
        file_size=image.file_size,
        prediction=result["prediction"],
        confidence=result["confidence"],
        predicted_technique=result["predicted_technique"],
        probabilities=result["probabilities"],
        rf_probabilities=(result["rf"] or {}).get("probabilities"),
        anomaly_score=(result["rf"] or {}).get("anomaly"),
        risk_score=result["risk"]["score"],
        risk_level=result["risk"]["level"],
        risk_factors=result["risk"],
        payload_signature=result["signature"],
        model_name=result["model"]["name"],
        model_version=result["model"]["version"],
        inference_ms=sum(result["timings_ms"].values()),
        tiles=len(result["tiles"]),
        artifacts=artifacts,
        details={
            "explanation": result["explanation"],
            "rf_top_features": (result["rf"] or {}).get("top_features"),
            "rf_model": result["rf_model"],
            "p_stego": result["p_stego"],
            "technique_confidence": result["technique_confidence"],
            "image_warnings": image.warnings,
        },
    )
    db.add(record)
    audit.record(
        db, AuditAction.IMAGE_ANALYSIS, "success", user=user, ip=ip, commit=False,
        analysis_id=str(record.id), image_hash=image.sha256, prediction=result["prediction"],
        risk_level=result["risk"]["level"], source=source,
    )
    audit.record(
        db, AuditAction.MODEL_USED, "success", user=user, ip=ip, commit=False,
        model=result["model"]["name"], version=result["model"]["version"],
        rf_version=(result["rf_model"] or {}).get("version"),
    )
    db.commit()
    trace.step("done", "Analysis complete")

    result.update(
        {
            "analysis_id": str(record.id),
            "image": {
                "filename": image.filename,
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "file_size": image.file_size,
                "sha256": image.sha256,
                "warnings": image.warnings,
            },
            "artifacts": artifacts,
            "created_at": record.created_at.isoformat(),
            "duration_ms": (time.perf_counter() - started) * 1000,
        }
    )
    return result
