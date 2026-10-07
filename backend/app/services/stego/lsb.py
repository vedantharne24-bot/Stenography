"""Spatial-domain LSB replacement over the R, G and B channels.

* Capacity: one bit per channel value -> ``H · W · 3`` slots.
* Slot ``k`` is the ``k``-th value of the row-major ``(H, W, 3)`` array, so the
  three channels of a pixel are interleaved and every channel is used.
* Embedding sets ``v = (v & 0xFE) | bit``; each value changes by at most 1, which
  bounds PSNR below by ~48.1 dB at 100 % utilisation (~51 dB at 50 %).
* No ECC by default: LSB is exact on lossless storage and is not meant to survive
  re-compression (the Attack Lab demonstrates this fragility).
"""

from __future__ import annotations

import numpy as np

from app.services.stego.base import StegoAlgorithm


class LsbAlgorithm(StegoAlgorithm):
    name = "lsb"
    algorithm_id = 1
    default_nsym = 0
    label = "LSB replacement (spatial, RGB)"
    domain = "spatial"

    def capacity_slots(self, shape: tuple[int, ...]) -> int:
        return int(shape[0] * shape[1] * 3)

    def embed(self, rgb: np.ndarray, slots: np.ndarray, bits: np.ndarray) -> np.ndarray:
        flat = np.ascontiguousarray(rgb).reshape(-1).copy()
        flat[slots] = (flat[slots] & np.uint8(0xFE)) | bits.astype(np.uint8)
        return flat.reshape(rgb.shape)

    def extract(self, rgb: np.ndarray, slots: np.ndarray) -> np.ndarray:
        return (np.ascontiguousarray(rgb).reshape(-1)[slots] & 1).astype(np.uint8)
