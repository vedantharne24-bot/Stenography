"""Detector robustness to benign processing (false-positive study).

    python -m pipeline.detector_robustness --images 300

Applies benign transformations (JPEG at several qualities, resize, blur, noise) to held-out
*clean* test covers and measures how often the active StegoNet flags them as stego. Writes
docs/experiments/detector_false_positives.json. This quantifies a known limitation: the model
was trained on lossless/unprocessed covers, so processing it never saw can trigger alarms.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image

from pipeline.common import ROOT  # noqa: F401  (sets sys.path)

TRANSFORMS = [
    ("none", {}),
    ("jpeg", {"quality": 95}),
    ("jpeg", {"quality": 90}),
    ("jpeg", {"quality": 75}),
    ("jpeg", {"quality": 50}),
    ("resize", {"scale": 0.75, "restore": 1}),
    ("blur", {"kernel": 3}),
    ("gaussian_noise", {"sigma": 2}),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    from app.ml.inference import models, run_cnn
    from app.services.attacks import apply_attack, normalise_params
    from app.services.experiments import test_carriers

    carriers = test_carriers()
    chosen = random.Random(args.seed).sample(carriers, min(args.images, len(carriers)))
    results = []
    for attack, params in TRANSFORMS:
        flags, techniques = [], {"normal": 0, "lsb": 0, "dct": 0, "dwt": 0}
        p_values = []
        for path in chosen:
            cover = np.asarray(Image.open(path).convert("RGB"))
            image = cover if attack == "none" else apply_attack(cover, attack, normalise_params(attack, params))
            probs = run_cnn(image).probabilities
            predicted = max(probs, key=probs.get)
            techniques[predicted] += 1
            flags.append(predicted != "normal")
            p_values.append(1 - probs["normal"])
        row = {
            "transform": attack,
            "params": params,
            "images": len(chosen),
            "false_positive_rate": float(np.mean(flags)),
            "mean_p_stego": float(np.mean(p_values)),
            "predicted": techniques,
        }
        results.append(row)
        print(f"{attack:15s} {json.dumps(params):28s} FPR={row['false_positive_rate']:.3f} mean P(stego)={row['mean_p_stego']:.3f} {techniques}", flush=True)

    out = Path(__file__).resolve().parents[2] / "docs" / "experiments" / "detector_false_positives.json"
    version = models.cnn().version
    out = out.with_name(f"detector_false_positives_v{version}.json")
    out.write_text(json.dumps({"model": "steganalysis-cnn", "version": version, "images": len(chosen), "seed": args.seed, "results": results}, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
