"""Independently evaluate a saved model version on a dataset split.

    python -m pipeline.evaluate_model                                  # latest CNN + RF, test split
    python -m pipeline.evaluate_model --model steganalysis-cnn --version 1.0.0 --split test
    python -m pipeline.evaluate_model --model steganalysis-rf --split val --no-write

Loads the *saved* weights (never retrains), predicts the split, recomputes every metric
with app.ml.evaluation, and (unless --no-write) rewrites metrics.json / plots for that
version and re-syncs the model registry so the API serves the new numbers.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.common import MODELS, load_manifest, load_split, write_json

CNN_NAME = "steganalysis-cnn"
RF_NAME = "steganalysis-rf"


def latest_version(model_name: str) -> str | None:
    versions = sorted(
        (tuple(int(p) for p in d.name.split(".")) for d in (MODELS / model_name).glob("*.*.*") if (d / "card.json").exists())
    )
    return ".".join(map(str, versions[-1])) if versions else None


def predict_cnn(path: Path, split: str, batch: int = 64) -> tuple[np.ndarray, np.ndarray]:
    import torch

    from app.ml.cnn import StegoNet, StegoNetConfig

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(path / "model.pt", map_location=device, weights_only=True)
    model = StegoNet(StegoNetConfig(**checkpoint["config"])).to(device).eval()
    model.load_state_dict(checkpoint["state_dict"])
    x, y = load_split(split)
    probs = np.zeros((len(y), 4))
    with torch.no_grad():
        for start in range(0, len(y), batch):
            xb = torch.from_numpy(np.array(x[start : start + batch])).permute(0, 3, 1, 2).to(device).float()
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(xb)
            probs[start : start + len(xb)] = torch.softmax(logits.float(), 1).cpu().numpy()
    return y, probs


def predict_rf(path: Path, split: str) -> tuple[np.ndarray, np.ndarray]:
    import joblib

    from pipeline.train_model import compute_features

    bundle = joblib.load(path / "model.joblib")
    feats = compute_features(split, workers=8)
    _, y = load_split(split)
    return y, bundle["model"].predict_proba(feats)


def evaluate_version(model_name: str, version: str, split: str, write: bool) -> dict[str, Any]:
    from app.ml.evaluation import evaluate, save_plots

    path = MODELS / model_name / version
    if not (path / "card.json").exists():
        raise SystemExit(f"{model_name} v{version} not found under {MODELS}")
    t0 = time.time()
    y, probs = predict_cnn(path, split) if model_name == CNN_NAME else predict_rf(path, split)
    report = evaluate(y, probs, load_manifest(split))
    report["split"] = split
    report["evaluated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report["evaluation_seconds"] = round(time.time() - t0, 1)
    if write:
        previous = json.loads((path / "metrics.json").read_text()) if (path / "metrics.json").exists() else {}
        for key in ("feature_importance", "feature_group_importance", "anomaly_model"):
            if key in previous and key not in report:
                report[key] = previous[key]  # training-time artefacts that evaluation does not recompute
        target = "metrics.json" if split == "test" else f"{split}_metrics.json"
        write_json(path / target, report)
        if split == "test":
            save_plots(report, path, f"{model_name} v{version}")
    mc, bn = report["multiclass"], report["binary"]
    print(
        f"{model_name} v{version} [{split}] acc={mc['accuracy']:.4f} macroF1={mc['f1_macro']:.4f} "
        f"AUC={mc['roc_auc_macro_ovr']:.4f} | detection={bn['detection_rate']:.4f} FPR={bn['false_positive_rate']:.4f}"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=[CNN_NAME, RF_NAME, "all"], default="all")
    parser.add_argument("--version", default=None, help="defaults to the latest version on disk")
    parser.add_argument("--split", choices=["train", "val", "test"], default="test")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    names = [CNN_NAME, RF_NAME] if args.model == "all" else [args.model]
    for name in names:
        version = args.version or latest_version(name)
        if version is None:
            print(f"{name}: no trained version found - skipping")
            continue
        evaluate_version(name, version, args.split, write=not args.no_write)
    if not args.no_write:
        from app.ml.registry import sync_registry_to_db

        sync_registry_to_db()


if __name__ == "__main__":
    main()
