"""Algorithm interface and the shared QIM machinery for transform-domain methods.

Every algorithm exposes a flat array of *slots* (LSB: pixel-channel values;
DCT: selected block coefficients; DWT: selected subband coefficients). The
framing layer decides which slot carries which bit.

Quantisation Index Modulation (QIM) - used by DCT and DWT
---------------------------------------------------------
For step Δ, bit 0 lives on the lattice ``kΔ`` and bit 1 on ``kΔ + Δ/2``.
Embedding moves a coefficient to the nearest point of the lattice for its bit
(max distortion Δ/2); extraction decodes ``round(c / (Δ/2)) mod 2``. A
perturbation smaller than Δ/4 never flips a bit, which is where the robustness
to rounding and mild JPEG compression comes from.

Because the stego image must be stored as 8-bit integers, rounding and clipping
can move a coefficient. ``qim_embed`` therefore re-measures the rendered image
and re-quantises any slot that decodes wrongly (a few iterations), leaving the
remainder to the Reed-Solomon layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

# Full-range BT.601 luma, as used by JPEG.
_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float64)


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb.astype(np.float64) @ _LUMA


class StegoAlgorithm(ABC):
    name: str
    algorithm_id: int
    default_nsym: int
    label: str
    domain: str

    @abstractmethod
    def capacity_slots(self, shape: tuple[int, ...]) -> int: ...

    @abstractmethod
    def embed(self, rgb: np.ndarray, slots: np.ndarray, bits: np.ndarray) -> np.ndarray: ...

    @abstractmethod
    def extract(self, rgb: np.ndarray, slots: np.ndarray) -> np.ndarray: ...

    def reader(self, rgb: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
        """Return ``slots -> bits`` for repeated reads (transform computed once)."""
        return lambda slots: self.extract(rgb, slots)

    def describe(self) -> dict[str, object]:
        return {"name": self.name, "label": self.label, "domain": self.domain, "ecc_parity": self.default_nsym}


def qim_quantize(values: np.ndarray, bits: np.ndarray, delta: float) -> np.ndarray:
    offset = bits.astype(np.float64) * (delta / 2.0)
    return np.round((values - offset) / delta) * delta + offset


def qim_decode(values: np.ndarray, delta: float) -> np.ndarray:
    return (np.rint(values / (delta / 2.0)).astype(np.int64) & 1).astype(np.uint8)


@dataclass
class QimStats:
    iterations: int
    residual_errors: int


class QimTransformAlgorithm(StegoAlgorithm):
    """QIM embedding on luminance in a linear transform domain.

    Subclasses implement ``forward`` (luma -> all slot coefficients) and
    ``inverse_delta`` (slot-coefficient deltas -> luma delta image). Since the
    transforms are linear and Cb/Cr are untouched, a luma change ΔY maps to the
    same change on R, G and B, so RGB' = RGB + ΔY exactly before rounding.
    """

    delta: float
    max_correction_rounds: int = 8
    # A slot is re-pushed if it sits farther than this fraction of Δ from its lattice
    # point - not only when it decodes wrongly - so bits keep a robustness margin.
    margin_fraction: float = 0.15
    last_stats: QimStats | None = None

    @abstractmethod
    def forward(self, y: np.ndarray) -> np.ndarray: ...

    @abstractmethod
    def inverse_delta(self, coeff_delta: np.ndarray, shape: tuple[int, int]) -> np.ndarray: ...

    def embed(self, rgb: np.ndarray, slots: np.ndarray, bits: np.ndarray) -> np.ndarray:
        h, w = rgb.shape[:2]
        work = rgb.astype(np.float64)
        coeffs = self.forward(luma(work))
        delta = np.zeros_like(coeffs)
        delta[slots] = qim_quantize(coeffs[slots], bits, self.delta) - coeffs[slots]
        work += self.inverse_delta(delta, (h, w))[..., None]
        out = np.clip(np.rint(work), 0, 255).astype(np.uint8)

        margin = self.margin_fraction * self.delta
        rounds = 0
        for rounds in range(1, self.max_correction_rounds + 1):
            current = self.forward(luma(out))[slots]
            target = qim_quantize(current, bits, self.delta)
            weak = (qim_decode(current, self.delta) != bits) | (np.abs(current - target) > margin)
            if not weak.any():
                break
            # Re-quantise only the weak slots, starting from the measured (rounded/clipped) value.
            delta = np.zeros_like(coeffs)
            delta[slots[weak]] = target[weak] - current[weak]
            work = out.astype(np.float64) + self.inverse_delta(delta, (h, w))[..., None]
            out = np.clip(np.rint(work), 0, 255).astype(np.uint8)
        current = self.forward(luma(out))[slots]
        errors = int((qim_decode(current, self.delta) != bits).sum())
        self.last_stats = QimStats(iterations=rounds, residual_errors=errors)
        return out

    def extract(self, rgb: np.ndarray, slots: np.ndarray) -> np.ndarray:
        return qim_decode(self.forward(luma(rgb))[slots], self.delta)

    def reader(self, rgb: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
        decoded = qim_decode(self.forward(luma(rgb)), self.delta)
        return lambda slots: decoded[slots]
