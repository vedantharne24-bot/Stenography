"""Helpers shared by the training / evaluation / experiment scripts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

DATASET = Path(os.environ.get("DATASET_DIR", ROOT / "data" / "dataset"))
MODELS = Path(os.environ.get("MODEL_PATH", BACKEND / "models"))
SPLITS = ("train", "val", "test")


def load_split(split: str, dataset: Path = DATASET) -> tuple[np.ndarray, np.ndarray]:
    x = np.load(dataset / "arrays" / f"{split}_x.npy", mmap_mode="r")
    y = np.load(dataset / "arrays" / f"{split}_y.npy")
    if x.shape[0] != y.shape[0]:
        raise ValueError(f"{split}: image/label count mismatch")
    return x, y


def load_manifest(split: str, dataset: Path = DATASET) -> list[dict[str, Any]]:
    with open(dataset / "manifest.csv", newline="", encoding="utf-8") as fh:
        rows = [row for row in csv.DictReader(fh) if row["split"] == split]
    rows.sort(key=lambda r: int(r["row"]))
    return rows


def dataset_stats(dataset: Path = DATASET) -> dict[str, Any]:
    return json.loads((dataset / "stats.json").read_text(encoding="utf-8"))


def next_version(model_name: str, requested: str | None) -> str:
    if requested:
        return requested
    existing = sorted(
        tuple(int(p) for p in d.name.split(".")) for d in (MODELS / model_name).glob("*.*.*") if d.is_dir()
    )
    if not existing:
        return "1.0.0"
    major, minor, _ = existing[-1]
    return f"{major}.{minor + 1}.0"


def display_path(path: Path) -> str:
    """Repository-relative path for model cards, so they carry no machine-specific prefix."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment() -> dict[str, Any]:
    info: dict[str, Any] = {"python": platform.python_version(), "platform": platform.platform()}
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda"] = torch.version.cuda
        info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        pass
    import sklearn

    info["sklearn"] = sklearn.__version__
    return info


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=float), encoding="utf-8")
