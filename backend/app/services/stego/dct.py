"""Block-DCT (JPEG-domain style) steganography with QIM.

Algorithm
---------
1. Convert RGB to full-range BT.601 luma Y (the JPEG luma definition).
2. Tile Y into non-overlapping 8×8 blocks aligned to the image origin
   (the JPEG grid); a right/bottom remainder smaller than 8 px is left untouched.
3. Apply the orthonormal 2-D DCT-II to every block (``scipy.fft.dctn``).
4. In each block, embed one bit by QIM into each of five mid-frequency
   coefficients ``(1,2) (2,1) (2,2) (0,3) (3,0)`` (row, column).
   - Mid frequencies avoid the visually sensitive DC/low terms and the
     high terms that JPEG quantises most aggressively.
   - The set is symmetric under transposition, so flips/rotations used as
     training augmentation preserve the class signal.
5. Inverse DCT, add ΔY to R, G and B (Cb/Cr unchanged), round and clip, then run
   the QIM correction loop (see ``base.py``).

JPEG considerations
-------------------
The JPEG luminance quantisation steps for these positions are 10-16 at quality
50 and scale down as quality rises. With Δ = 24 the decision margin is Δ/4 = 6;
the margin-aware correction loop keeps embedded coefficients close to their
lattice points, and Reed-Solomon (32 parity symbols per 255-byte block) absorbs
residual bit errors. Robustness depends on image content (clipped/saturated
regions are the weak spot); the Attack Lab measures it per image rather than
assuming it. The parameter sweep is documented in docs/TECHNICAL.md.
"""

from __future__ import annotations

import numpy as np
from scipy.fft import dctn, idctn

from app.services.stego.base import QimTransformAlgorithm

BLOCK = 8
POSITIONS: tuple[tuple[int, int], ...] = ((1, 2), (2, 1), (2, 2), (0, 3), (3, 0))
_ROWS = np.array([p[0] for p in POSITIONS])
_COLS = np.array([p[1] for p in POSITIONS])


class DctAlgorithm(QimTransformAlgorithm):
    name = "dct"
    algorithm_id = 2
    default_nsym = 32
    label = "Block-DCT QIM (8×8 luma, mid-frequency)"
    domain = "frequency (DCT)"
    delta = 24.0

    @staticmethod
    def _grid(shape: tuple[int, ...]) -> tuple[int, int]:
        return shape[0] // BLOCK, shape[1] // BLOCK

    def capacity_slots(self, shape: tuple[int, ...]) -> int:
        nbh, nbw = self._grid(shape)
        return int(nbh * nbw * len(POSITIONS))

    def forward(self, y: np.ndarray) -> np.ndarray:
        nbh, nbw = self._grid(y.shape)
        blocks = y[: nbh * BLOCK, : nbw * BLOCK].reshape(nbh, BLOCK, nbw, BLOCK).transpose(0, 2, 1, 3)
        coeffs = dctn(blocks, axes=(2, 3), norm="ortho")
        return coeffs[:, :, _ROWS, _COLS].reshape(-1)

    def inverse_delta(self, coeff_delta: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        nbh, nbw = self._grid(shape)
        full = np.zeros((nbh, nbw, BLOCK, BLOCK), dtype=np.float64)
        full[:, :, _ROWS, _COLS] = coeff_delta.reshape(nbh, nbw, len(POSITIONS))
        blocks = idctn(full, axes=(2, 3), norm="ortho")
        out = np.zeros(shape, dtype=np.float64)
        out[: nbh * BLOCK, : nbw * BLOCK] = blocks.transpose(0, 2, 1, 3).reshape(nbh * BLOCK, nbw * BLOCK)
        return out

    def describe(self) -> dict[str, object]:
        info = super().describe()
        info.update({"block": BLOCK, "coefficients": [list(p) for p in POSITIONS], "qim_delta": self.delta})
        return info
