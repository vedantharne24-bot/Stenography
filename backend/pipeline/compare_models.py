"""Compare every trained model version on the *same* data and write a Markdown summary.

    python -m pipeline.compare_models --fp-images 300

For each CNN / RF version on disk:
* metrics on the current dataset's test split (identical images for every version);
* the benign-processing false-positive study on held-out clean covers (CNN versions).
Writes docs/experiments/model_comparison.md and .json, and refreshes the README results block.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pipeline.common import MODELS, ROOT, dataset_stats, load_manifest, load_split
from pipeline.evaluate_model import predict_cnn, predict_rf

TRANSFORMS = [
    ("none", {}),
    ("jpeg", {"quality": 90}),
    ("jpeg", {"quality": 75}),
    ("jpeg", {"quality": 50}),
    ("gaussian_noise", {"sigma": 1}),
    ("gaussian_noise", {"sigma": 2}),
    ("gaussian_noise", {"sigma": 3}),
    ("blur", {"kernel": 3}),
    ("resize", {"scale": 0.75, "restore": 1}),
]


def versions(model_name: str) -> list[str]:
    found = [d for d in (MODELS / model_name).glob("*.*.*") if (d / "card.json").exists()]
    return [d.name for d in sorted(found, key=lambda d: tuple(int(p) for p in d.name.split(".")))]


def _cnn(model_name: str, version: str):  # type: ignore[no-untyped-def]
    import torch

    from app.ml.cnn import StegoNet, StegoNetConfig

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(MODELS / model_name / version / "model.pt", map_location=device, weights_only=True)
    model = StegoNet(StegoNetConfig(**ckpt["config"])).to(device).eval()
    model.load_state_dict(ckpt["state_dict"])
    return model, device


def image_probs(model, device, rgb: np.ndarray) -> np.ndarray:  # type: ignore[no-untyped-def]
    """Tile-averaged softmax, identical to the production inference path."""
    import torch

    from app.ml.inference import tile_origins

    origins = tile_origins(*rgb.shape[:2])
    crops = np.stack([rgb[y : y + th, x : x + tw] for y, x, th, tw in origins])
    with torch.no_grad():
        x = torch.from_numpy(crops).permute(0, 3, 1, 2).to(device).float()
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            logits = model(x)
        return torch.softmax(logits.float(), 1).mean(0).cpu().numpy()


def fp_study(model_name: str, version: str, n: int, seed: int) -> list[dict[str, Any]]:
    from app.services.attacks import apply_attack, normalise_params
    from app.services.experiments import test_carriers

    model, device = _cnn(model_name, version)
    chosen = random.Random(seed).sample(test_carriers(), n)
    covers = [np.asarray(Image.open(p).convert("RGB")) for p in chosen]
    rows = []
    for attack, params in TRANSFORMS:
        preds = []
        for cover in covers:
            img = cover if attack == "none" else apply_attack(cover, attack, normalise_params(attack, params))
            preds.append(int(np.argmax(image_probs(model, device, img))))
        preds_arr = np.array(preds)
        rows.append({
            "transform": attack if attack == "none" else f"{attack} " + " ".join(f"{k}={v:g}" for k, v in params.items() if k != "restore"),
            "false_positive_rate": float(np.mean(preds_arr != 0)),
            "flagged_as": {c: int(np.sum(preds_arr == i)) for i, c in enumerate(("normal", "lsb", "dct", "dwt")) if i},
        })  # fmt: skip
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fp-images", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    from app.ml.evaluation import evaluate

    stats = dataset_stats()
    manifest = load_manifest("test")
    _, y = load_split("test")
    processed_mask = np.array([row["variant"].startswith("processed") for row in manifest])
    report: dict[str, Any] = {"dataset": {k: stats.get(k) for k in ("created_at", "images", "processed_covers", "carrier_variants")}, "models": []}

    for model_name, predict in (("steganalysis-cnn", predict_cnn), ("steganalysis-rf", predict_rf)):
        for version in versions(model_name):
            print(f"evaluating {model_name} v{version} …", flush=True)
            yt, probs = predict(MODELS / model_name / version, "test")
            full = evaluate(yt, probs, manifest)
            subsets = {}
            for name, mask in (("clean covers", ~processed_mask), ("processed covers", processed_mask)):
                if mask.any():
                    sub = evaluate(yt[mask], probs[mask])
                    subsets[name] = {"accuracy": sub["multiclass"]["accuracy"], "detection_rate": sub["binary"]["detection_rate"], "false_positive_rate": sub["binary"]["false_positive_rate"], "images": int(mask.sum())}
            entry = {
                "model": model_name,
                "version": version,
                "trained_on": json.loads((MODELS / model_name / version / "card.json").read_text()).get("dataset", {}).get("images"),
                "accuracy": full["multiclass"]["accuracy"],
                "f1_macro": full["multiclass"]["f1_macro"],
                "roc_auc": full["multiclass"]["roc_auc_macro_ovr"],
                "detection_rate": full["binary"]["detection_rate"],
                "false_positive_rate": full["binary"]["false_positive_rate"],
                "subsets": subsets,
                "by_utilisation": full.get("by_utilisation"),
            }
            if model_name == "steganalysis-cnn":
                entry["benign_processing_fp"] = fp_study(model_name, version, args.fp_images, args.seed)
            report["models"].append(entry)

    out_dir = ROOT / "docs" / "experiments"
    (out_dir / "model_comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_markdown(report, args.fp_images)
    (out_dir / "model_comparison.md").write_text(md, encoding="utf-8")
    refresh_readme(report)
    print(md)


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.2f}%"


def render_markdown(report: dict[str, Any], fp_images: int) -> str:
    lines = [
        "# Model comparison",
        "",
        "Generated by `python -m pipeline.compare_models`. Every version is evaluated on the **same** current",
        f"test split ({report['dataset']['images']['test']:,} tiles; dataset created {report['dataset']['created_at']}).",
        "",
        "## Test split (identical images for every version)",
        "",
        "| Model | Version | Accuracy | Macro F1 | ROC-AUC | Detection | FPR | Acc. clean covers | Acc. processed covers |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in report["models"]:
        s = m["subsets"]
        lines.append(
            f"| {m['model']} | {m['version']} | {_pct(m['accuracy'])} | {m['f1_macro']:.4f} | {m['roc_auc']:.4f} | {_pct(m['detection_rate'])} | "
            f"{_pct(m['false_positive_rate'])} | {_pct(s.get('clean covers', {}).get('accuracy'))} | {_pct(s.get('processed covers', {}).get('accuracy'))} |"
        )
    cnns = [m for m in report["models"] if "benign_processing_fp" in m]
    if cnns:
        lines += ["", f"## False positives on clean held-out covers after benign processing ({fp_images} images)", ""]
        lines.append("| Processing | " + " | ".join(f"StegoNet v{m['version']}" for m in cnns) + " |")
        lines.append("|---|" + "---|" * len(cnns))
        for i, row in enumerate(cnns[0]["benign_processing_fp"]):
            lines.append(f"| {row['transform']} | " + " | ".join(_pct(m["benign_processing_fp"][i]["false_positive_rate"]) for m in cnns) + " |")
    lines += ["", "## Detection rate by payload utilisation (test split)", ""]
    for m in cnns:
        if m.get("by_utilisation"):
            lines.append(f"**StegoNet v{m['version']}**: " + "; ".join(f"{r['technique'].upper()} {r['bin']} {_pct(r['detection_rate'])}" for r in m["by_utilisation"]))
            lines.append("")
    return "\n".join(lines) + "\n"


def refresh_readme(report: dict[str, Any]) -> None:
    readme = ROOT / "README.md"
    if not readme.exists():
        return
    rows = ["| Model | Version | Test accuracy | Macro F1 | ROC-AUC | Stego detection | False positives |", "|---|---|---|---|---|---|---|"]
    for m in report["models"]:
        rows.append(f"| {m['model']} | {m['version']} | {_pct(m['accuracy'])} | {m['f1_macro']:.4f} | {m['roc_auc']:.4f} | {_pct(m['detection_rate'])} | {_pct(m['false_positive_rate'])} |")
    block = "\n".join(rows) + "\n\nAll versions evaluated on the same current test split. Full comparison, including the false-positive study under benign processing: [`docs/experiments/model_comparison.md`](docs/experiments/model_comparison.md)."
    text = readme.read_text(encoding="utf-8")
    text = re.sub(r"<!-- RESULTS:START -->.*?<!-- RESULTS:END -->", f"<!-- RESULTS:START -->\n{block}\n<!-- RESULTS:END -->", text, flags=re.S)
    readme.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
