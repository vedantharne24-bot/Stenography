"""Research experiment: LSB vs DCT vs DWT on held-out images.

Research question: *which technique gives the best balance between payload capacity,
visual quality, robustness and AI detectability?*

For each held-out **test-split** carrier (never seen by the models in training) and each
algorithm the experiment measures, on real data:

* capacity (max plaintext bytes and bits per pixel),
* MSE / PSNR / SSIM at the configured payload,
* extraction success and computational cost (embed / extract wall time),
* AI detectability - StegoNet decision on the stego image (and false positives on covers),
* robustness - extraction survival over an attack suite.

Balance score (transparent; every term is a function of the measured table):

* capacity        = log10(payload bpp), min-max normalised across the three techniques
                    (capacities differ by orders of magnitude, so a log scale is used);
* quality         = clip((PSNR - 35 dB) / 20 dB, 0, 1) - a fixed reference range in which
                    35 dB is where artefacts start to become visible and 55 dB is imperceptible;
* robustness      = extraction survival rate over the attack suite (absolute, 0..1);
* undetectability = 1 - AI detection rate (absolute, 0..1).

Absolute scales are used wherever one exists, so tiny differences (e.g. 99.4 % vs 100 %
detection) are not stretched into a full 0..1 gap the way pure min-max scaling would.
The score is the weighted mean (default equal weights). The per-criterion winners are
reported alongside, because a single number hides trade-offs.
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.core.streaming import Trace
from app.db.models import ExperimentRun, User
from app.ml import inference
from app.services import audit, crypto, metrics
from app.services.attacks import apply_attack, normalise_params
from app.services.audit import AuditAction
from app.services.steganalysis import _thresholds, analyze_array
from app.services.stego import engine

DEFAULT_ATTACKS: list[tuple[str, dict[str, float]]] = [
    ("jpeg", {"quality": 90}),
    ("jpeg", {"quality": 75}),
    ("gaussian_noise", {"sigma": 2}),
    ("blur", {"kernel": 3}),
    ("resize", {"scale": 0.75, "restore": 1}),
    ("brightness", {"delta": 10}),
]
CRITERIA = ("capacity", "quality", "robustness", "undetectability")
QUALITY_RANGE_DB = (35.0, 55.0)
TIE_MARGIN = 0.02  # differences below 2 points of a 0..1 criterion are reported as a tie


def _winner_text(winner: str) -> str:
    return "no meaningful difference" if winner == "tie" else winner.upper()


def _normalise(summary: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Map the measured table to the four 0..1 criteria (see module docstring)."""
    out: dict[str, dict[str, float]] = {c: {} for c in CRITERIA}
    logs = {a: math.log10(s["capacity_bpp"]) for a, s in summary.items() if s["capacity_bpp"]}
    lo, hi = (min(logs.values()), max(logs.values())) if logs else (0.0, 0.0)
    q_lo, q_hi = QUALITY_RANGE_DB
    for a, s in summary.items():
        out["capacity"][a] = 0.0 if a not in logs else (1.0 if hi == lo else (logs[a] - lo) / (hi - lo))
        out["quality"][a] = 0.0 if s["psnr"] is None else min(1.0, max(0.0, (s["psnr"] - q_lo) / (q_hi - q_lo)))
        out["robustness"][a] = 0.0 if s["robustness"] is None else float(s["robustness"])
        out["undetectability"][a] = 0.0 if s["detection_rate"] is None else 1.0 - float(s["detection_rate"])
    return out


def test_carriers() -> list[Path]:
    """Held-out carriers: the generated test split if present, else the bundled demo set."""
    settings = get_settings()
    for folder in (settings.dataset_dir / "test_carriers", settings.demo_carriers_dir):
        found = sorted(folder.glob("*.png")) if folder.exists() else []
        if found:
            return found
    return []


def _payload_len(cap: engine.Capacity, mode: str, relative: float, absolute: int) -> int | None:
    if mode == "absolute":
        return absolute if absolute <= cap.max_payload_bytes else None
    return max(1, int(cap.max_payload_bytes * relative))


def run_comparison(
    trace: Trace,
    db: Session,
    user: User | None,
    *,
    images: int = 12,
    payload_mode: str = "relative",
    relative: float = 0.5,
    absolute_bytes: int = 64,
    seed: int = 0,
    weights: dict[str, float] | None = None,
    ip: str | None = None,
    source: str = "api",
) -> dict[str, Any]:
    if payload_mode not in ("relative", "absolute"):
        raise ValidationFailed("payload_mode must be 'relative' or 'absolute'")
    if not 0.05 <= relative <= 1.0:
        raise ValidationFailed("relative payload must be between 0.05 and 1.0")
    weights = weights or {c: 1.0 for c in CRITERIA}
    carriers = test_carriers()
    if not carriers:
        raise ValidationFailed("No held-out carriers found - run pipeline.generate_dataset or restore backend/demo_carriers")
    started = time.perf_counter()
    rng = random.Random(seed)
    chosen = rng.sample(carriers, min(images, len(carriers)))
    thresholds = _thresholds(db)
    model_version = inference.models.cnn().version
    attacks = [(a, normalise_params(a, p)) for a, p in DEFAULT_ATTACKS]
    trace.step("setup", f"{len(chosen)} held-out test carriers · payload {payload_mode} "
               + (f"{relative:.0%} of capacity" if payload_mode == "relative" else f"{absolute_bytes} B")
               + f" · {len(attacks)} attacks")  # fmt: skip

    per_algo: dict[str, dict[str, list[Any]]] = {
        a: {k: [] for k in ("capacity_bytes", "bpp", "payload_bytes", "psnr", "ssim", "mse", "embed_ms", "extract_ms",
                            "extracted", "detected", "technique_correct", "p_stego", "survived", "skipped")}  # fmt: skip
        for a in engine.ALGORITHM_NAMES
    }
    per_attack: dict[str, dict[str, list[bool]]] = {a: {} for a in engine.ALGORITHM_NAMES}
    cover_flags: list[bool] = []
    key = crypto.Secret(raw_key=bytes(rng.getrandbits(8) for _ in range(32)))

    for idx, path in enumerate(chosen, start=1):
        cover = np.asarray(Image.open(path).convert("RGB"))
        cover_result = analyze_array(cover, Trace(), thresholds, explain=False, use_rf=False, check_signature=False).result
        cover_flags.append(cover_result["prediction"] == "stego")
        for algorithm in engine.ALGORITHM_NAMES:
            bucket = per_algo[algorithm]
            cap = engine.capacity(algorithm, cover.shape)
            bucket["capacity_bytes"].append(max(0, cap.max_payload_bytes))
            bucket["bpp"].append(max(0, cap.max_payload_bytes) * 8 / (cover.shape[0] * cover.shape[1]))
            length = _payload_len(cap, payload_mode, relative, absolute_bytes)
            if length is None or length < 1:
                bucket["skipped"].append(True)
                continue
            content = bytes(rng.getrandbits(8) for _ in range(length))
            sealed = crypto.encrypt_payload(content, key)
            t0 = time.perf_counter()
            outcome = engine.embed(cover, sealed.envelope, algorithm)
            bucket["embed_ms"].append((time.perf_counter() - t0) * 1000)
            q = metrics.quality_report(cover, outcome.stego)
            bucket["payload_bytes"].append(length)
            bucket["psnr"].append(q["psnr"] if q["psnr"] is not None else 100.0)
            bucket["ssim"].append(q["ssim"])
            bucket["mse"].append(q["mse"])
            t1 = time.perf_counter()
            extracted = engine.extract(outcome.stego, algorithm)
            bucket["extract_ms"].append((time.perf_counter() - t1) * 1000)
            bucket["extracted"].append(extracted.integrity == "verified")
            ai = analyze_array(outcome.stego, Trace(), thresholds, explain=False, use_rf=False, check_signature=False).result
            bucket["detected"].append(ai["prediction"] == "stego")
            bucket["technique_correct"].append(ai["predicted_technique"] == algorithm)
            bucket["p_stego"].append(ai["p_stego"])
            for attack, params in attacks:
                label = f"{attack}:{','.join(f'{k}={v:g}' for k, v in params.items() if k != 'restore')}"
                ok = engine.extract(apply_attack(outcome.stego, attack, params), algorithm).integrity == "verified"
                per_attack[algorithm].setdefault(label, []).append(ok)
                bucket["survived"].append(ok)
        trace.step("progress", f"Image {idx}/{len(chosen)} ({path.stem}) measured", done=idx, total=len(chosen))

    def mean(values: list[Any]) -> float | None:
        return float(np.mean(values)) if values else None

    summary: dict[str, dict[str, Any]] = {}
    for algorithm, b in per_algo.items():
        summary[algorithm] = {
            "algorithm": algorithm,
            "label": engine.get_algorithm(algorithm).label,
            "images": len(b["psnr"]),
            "skipped": len(b["skipped"]),
            "capacity_bytes": mean(b["capacity_bytes"]),
            "capacity_bpp": mean(b["bpp"]),
            "payload_bytes": mean(b["payload_bytes"]),
            "psnr": mean(b["psnr"]),
            "psnr_std": float(np.std(b["psnr"])) if b["psnr"] else None,
            "ssim": mean(b["ssim"]),
            "mse": mean(b["mse"]),
            "extraction_success": mean(b["extracted"]),
            "detection_rate": mean(b["detected"]),
            "technique_accuracy": mean(b["technique_correct"]),
            "mean_p_stego": mean(b["p_stego"]),
            "robustness": mean(b["survived"]),
            "embed_ms": mean(b["embed_ms"]),
            "extract_ms": mean(b["extract_ms"]),
            "per_attack": {label: mean(v) for label, v in per_attack[algorithm].items()},
            "psnr_values": [round(v, 3) for v in b["psnr"]],
        }

    normalised = _normalise(summary)
    total_w = sum(weights.get(c, 0) for c in CRITERIA) or 1.0
    balance = {a: sum(weights.get(c, 0) * normalised[c][a] for c in CRITERIA) / total_w for a in summary}
    ranking = sorted(balance, key=balance.get, reverse=True)  # type: ignore[arg-type]
    # A criterion has a winner only if the techniques differ by at least TIE_MARGIN on it.
    winners = {
        c: (max(summary, key=lambda a, c=c: normalised[c][a]) if max(normalised[c].values()) - min(normalised[c].values()) >= TIE_MARGIN else "tie")
        for c in CRITERIA
    }
    detection_values = [s["detection_rate"] for s in summary.values() if s["detection_rate"] is not None]

    results = {
        "summary": summary,
        "cover_false_positive_rate": mean(cover_flags),
        "normalised": normalised,
        "weights": weights,
        "balance_score": balance,
        "ranking": ranking,
        "winners": winners,
        "answer": (
            f"On {len(chosen)} held-out images ({'equal' if len(set(weights.values())) == 1 else 'custom'} weights), "
            f"{ranking[0].upper()} scores highest ({balance[ranking[0]]:.2f}), then {ranking[1].upper()} "
            f"({balance[ranking[1]]:.2f}) and {ranking[2].upper()} ({balance[ranking[2]]:.2f}). Best capacity: "
            f"{_winner_text(winners['capacity'])}; best quality: {_winner_text(winners['quality'])}; most robust: "
            f"{_winner_text(winners['robustness'])}; hardest to detect: {_winner_text(winners['undetectability'])}"
            + (f" (StegoNet detection ranged {min(detection_values):.1%}–{max(detection_values):.1%})." if detection_values else ".")
        ),
        "methodology": __doc__,
        "attacks": [f"{a}:{p}" for a, p in attacks],
    }
    duration = (time.perf_counter() - started) * 1000
    run = ExperimentRun(
        user_id=user.id if user else None,
        kind="technique_comparison",
        config={
            "images": len(chosen), "payload_mode": payload_mode, "relative": relative, "absolute_bytes": absolute_bytes,
            "seed": seed, "source": source, "model_version": model_version, "scoring": "v2-absolute-scales",
            "carriers": [p.stem for p in chosen],
        },  # fmt: skip
        results=results,
        duration_ms=duration,
    )
    db.add(run)
    if user is not None:
        audit.record(db, AuditAction.EXPERIMENT_RUN, "success", user=user, ip=ip, commit=False, images=len(chosen), ranking=ranking)
    db.commit()
    trace.step("done", results["answer"])
    return {"run_id": str(run.id), "created_at": run.created_at.isoformat(), "duration_ms": duration, "config": run.config, **results}
