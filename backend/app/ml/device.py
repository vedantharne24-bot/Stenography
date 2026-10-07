"""Compute-device selection: CUDA when available (and allowed), otherwise CPU."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("app.ml.device")


@lru_cache
def get_device() -> Any:
    import torch

    preference = get_settings().device
    if preference == "cpu":
        device = torch.device("cpu")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        if preference == "cuda":
            log.warning("DEVICE=cuda requested but CUDA is unavailable - falling back to CPU")
        device = torch.device("cpu")
    log.info("Inference device: %s", device)
    return device


def device_info() -> dict[str, Any]:
    try:
        import torch
    except ImportError:  # pragma: no cover
        return {"framework": None, "device": "cpu", "cuda_available": False, "gpu_name": None}
    device = get_device()
    return {
        "framework": f"torch {torch.__version__}",
        "device": device.type,
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
    }
