"""Image-quality metrics computed on real pixel arrays.

* MSE  - mean squared error over all pixels and channels.
* PSNR - 10·log10(MAX² / MSE) with MAX = 255; ``inf`` when images are identical.
* SSIM - Wang et al. (2004): Gaussian window σ=1.5, K1=0.01, K2=0.03, averaged
  over channels. Matches ``skimage.metrics.structural_similarity`` with
  ``gaussian_weights=True, use_sample_covariance=False`` (verified in tests).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import gaussian_filter

_SIGMA = 1.5
_TRUNCATE = 3.5
_PAD = int(_TRUNCATE * _SIGMA + 0.5)  # 5 -> 11x11 window


def _as_float(a: np.ndarray) -> np.ndarray:
    return a.astype(np.float64, copy=False)


def mse(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")
    diff = _as_float(a) - _as_float(b)
    return float(np.mean(diff * diff))


def psnr(a: np.ndarray, b: np.ndarray, data_range: float = 255.0) -> float:
    err = mse(a, b)
    if err == 0:
        return math.inf
    return 10.0 * math.log10((data_range**2) / err)


def _ssim_channel(x: np.ndarray, y: np.ndarray, data_range: float) -> float:
    c1 = (0.01 * data_range) ** 2
    c2 = (0.03 * data_range) ** 2

    def blur(z: np.ndarray) -> np.ndarray:
        return gaussian_filter(z, sigma=_SIGMA, truncate=_TRUNCATE, mode="reflect")

    mu_x, mu_y = blur(x), blur(y)
    sxx = blur(x * x) - mu_x * mu_x
    syy = blur(y * y) - mu_y * mu_y
    sxy = blur(x * y) - mu_x * mu_y
    num = (2 * mu_x * mu_y + c1) * (2 * sxy + c2)
    den = (mu_x * mu_x + mu_y * mu_y + c1) * (sxx + syy + c2)
    ssim_map = num / den
    if ssim_map.shape[0] > 2 * _PAD and ssim_map.shape[1] > 2 * _PAD:
        ssim_map = ssim_map[_PAD:-_PAD, _PAD:-_PAD]
    return float(ssim_map.mean())


def ssim(a: np.ndarray, b: np.ndarray, data_range: float = 255.0) -> float:
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")
    x, y = _as_float(a), _as_float(b)
    if x.ndim == 2:
        return _ssim_channel(x, y, data_range)
    return float(np.mean([_ssim_channel(x[..., c], y[..., c], data_range) for c in range(x.shape[-1])]))


def quality_report(original: np.ndarray, modified: np.ndarray) -> dict[str, float | None]:
    p = psnr(original, modified)
    return {
        "mse": mse(original, modified),
        "psnr": None if math.isinf(p) else p,
        "psnr_infinite": math.isinf(p),
        "ssim": ssim(original, modified),
    }


def difference_maps(original: np.ndarray, modified: np.ndarray, amplification: float = 32.0) -> tuple[np.ndarray, np.ndarray]:
    """Absolute difference image and an amplified version for visual inspection."""
    diff = np.abs(_as_float(original) - _as_float(modified))
    plain = np.clip(diff, 0, 255).astype(np.uint8)
    amplified = np.clip(diff * amplification, 0, 255).astype(np.uint8)
    return plain, amplified
