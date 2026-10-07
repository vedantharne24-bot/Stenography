"""Wavelet-domain (DWT) steganography with QIM, using PyWavelets.

Algorithm
---------
1. Convert RGB to BT.601 luma Y and crop the analysis region to a multiple of
   ``2**level`` (required for an exact dyadic decomposition; the remainder is untouched).
2. Multi-level 2-D Haar decomposition ``pywt.wavedec2(Y, "haar", level=L)``:
   ``[cA_L, (cH_L, cV_L, cD_L), ..., (cH1, cV1, cD1)]``.
3. Embed one bit by QIM into every coefficient of the coarsest horizontal (cH_L)
   and vertical (cV_L) detail subbands. These represent structure at the
   ``2^L``-pixel scale: coarse enough to resist compression and noise, without
   touching the approximation band cA_L (which would produce visible blotches).
4. Reconstruct with ``pywt.waverec2``. The Haar filters are orthonormal, so the
   luma change ΔY equals the inverse transform of the coefficient deltas alone.
5. Add ΔY to R, G, B, round, clip, and run the QIM correction loop.

Capacity is ``2 · (H/2^L) · (W/2^L)`` bits.
"""

from __future__ import annotations

import numpy as np
import pywt

from app.services.stego.base import QimTransformAlgorithm

WAVELET = "haar"


class DwtAlgorithm(QimTransformAlgorithm):
    name = "dwt"
    algorithm_id = 3
    default_nsym = 32
    label = "Haar DWT QIM (coarse LH/HL luma subbands)"
    domain = "wavelet (DWT)"
    # Tuned on DIV2K/COCO crops to match DCT's visual quality (~43.5 dB PSNR);
    # see docs/TECHNICAL.md "Parameter selection" for the sweep.
    delta = 40.0
    level = 3

    @property
    def factor(self) -> int:
        return 2**self.level

    def _region(self, shape: tuple[int, ...]) -> tuple[int, int]:
        return (shape[0] // self.factor) * self.factor, (shape[1] // self.factor) * self.factor

    def capacity_slots(self, shape: tuple[int, ...]) -> int:
        h, w = self._region(shape)
        return int(2 * (h // self.factor) * (w // self.factor))

    def forward(self, y: np.ndarray) -> np.ndarray:
        h, w = self._region(y.shape)
        coeffs = pywt.wavedec2(y[:h, :w], WAVELET, level=self.level)
        c_h, c_v, _ = coeffs[1]
        return np.concatenate([c_h.reshape(-1), c_v.reshape(-1)])

    def inverse_delta(self, coeff_delta: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        h, w = self._region(shape)
        bh, bw = h // self.factor, w // self.factor
        half = bh * bw
        coarse = np.zeros((bh, bw))
        coeffs: list = [coarse, (coeff_delta[:half].reshape(bh, bw), coeff_delta[half:].reshape(bh, bw), coarse)]
        for lvl in range(self.level - 1, 0, -1):
            z = np.zeros((h // 2**lvl, w // 2**lvl))
            coeffs.append((z, z, z))
        region = pywt.waverec2(coeffs, WAVELET)
        out = np.zeros(shape, dtype=np.float64)
        out[:h, :w] = region[:h, :w]
        return out

    def describe(self) -> dict[str, object]:
        info = super().describe()
        info.update(
            {
                "wavelet": WAVELET,
                "level": self.level,
                "subbands": [f"LH{self.level} (cH{self.level})", f"HL{self.level} (cV{self.level})"],
                "qim_delta": self.delta,
            }
        )
        return info
