"""Handcrafted steganalysis features (used by the Random Forest and the anomaly model).

All features are computed from pixel data only - no knowledge of any key, payload
or of StegoLab's frame format. Groups:

1. **LSB statistics** (per R/G/B channel)
   - Westfeld-Pfitzmann chi-square attack p-value (pairs-of-values equalisation)
   - pair-of-values asymmetry ratio
   - Sample Pairs Analysis (Dumitrescu-Wu-Wang 2003) embedding-rate estimate
   - LSB-plane horizontal correlation
2. **Noise residuals** - first-order difference histogram (green channel), KB high-pass
   and median-filter residual moments on luma.
3. **SPAM-lite** - first-order Markov transition matrix of truncated pixel differences
   (T = 2), averaged over horizontal and vertical directions (Pevný et al. 2010).
4. **Block-DCT statistics** - 8×8 grid-aligned DCT magnitudes per frequency band, a
   *histogram periodicity* score per low/mid frequency (detects quantisation lattices left by
   JPEG or QIM), and grid blockiness.
5. **Haar DWT statistics** - log-magnitude and kurtosis per subband for 3 levels and
   histogram periodicity for the level-2/3 detail bands.
6. **Global** - luma entropy, mean, std, saturation and histogram-gap ratio.
"""

from __future__ import annotations

import math

import numpy as np
import pywt
from scipy.fft import dctn
from scipy.ndimage import convolve, median_filter
from scipy.stats import chi2

_LUMA = np.array([0.299, 0.587, 0.114])
_KB = np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]], dtype=np.float64) / 4.0
_PERIODIC_POSITIONS = [(u, v) for u in range(5) for v in range(5) if 1 <= u + v <= 4]  # 14 low/mid AC terms
_EPS = 1e-12


# --------------------------------------------------------------------------- helpers


def _kurtosis(x: np.ndarray) -> float:
    x = x.ravel().astype(np.float64)
    m = x.mean()
    v = x.var()
    if v < _EPS:
        return 0.0
    return float(((x - m) ** 4).mean() / (v * v) - 3.0)


def periodicity(values: np.ndarray, limit: int = 96) -> tuple[float, float]:
    """Comb-structure score of a coefficient histogram and its dominant period.

    The histogram (unit bins over ±limit) is detrended with a moving average so the
    broad Laplacian envelope of natural coefficients is removed; a quantisation lattice
    with step P then shows up as a spectral peak at frequency (2·limit+1)/P.
    Score = peak / mean magnitude inside the band of periods 4..48.
    """
    v = values[np.abs(values) <= limit]
    if v.size < 128:
        return 0.0, 0.0
    hist = np.bincount(np.rint(v).astype(np.int64) + limit, minlength=2 * limit + 1).astype(np.float64)
    kernel = np.ones(9) / 9.0
    detrended = hist - np.convolve(hist, kernel, mode="same")
    spectrum = np.abs(np.fft.rfft(detrended))
    n = hist.size
    k_lo, k_hi = max(1, int(n / 48)), min(spectrum.size - 1, int(n / 4))
    band = spectrum[k_lo : k_hi + 1]
    if band.size == 0 or band.mean() < _EPS:
        return 0.0, 0.0
    k_peak = int(np.argmax(band)) + k_lo
    return float(band.max() / band.mean()), float(n / k_peak)


# --------------------------------------------------------------------------- LSB group


def _chi_square_p(channel: np.ndarray) -> tuple[float, float]:
    hist = np.bincount(channel.ravel(), minlength=256).astype(np.float64)
    even, odd = hist[0::2], hist[1::2]
    expected = (even + odd) / 2.0
    mask = expected > 4
    if mask.sum() < 2:
        return 0.0, 0.0
    stat = float(np.sum((even[mask] - expected[mask]) ** 2 / expected[mask]))
    p_embed = float(chi2.sf(stat, df=int(mask.sum()) - 1))
    asym = float(np.mean(np.abs(even[mask] - odd[mask])) / (np.mean(even[mask] + odd[mask]) + _EPS))
    return p_embed, asym


def _spa(channel: np.ndarray) -> float:
    r = channel[:, :-1].astype(np.int64).ravel()
    s = channel[:, 1:].astype(np.int64).ravel()
    n = r.size
    s_even = (s & 1) == 0
    x = int(np.sum((s_even & (r < s)) | (~s_even & (r > s))))
    y = int(np.sum((s_even & (r > s)) | (~s_even & (r < s))))
    k = int(np.sum((r >> 1) == (s >> 1)))
    if k == 0:
        return 0.0
    a, b, c = 2.0 * k, 2.0 * (2 * x - n), float(y - x)
    disc = max(0.0, b * b - 4 * a * c)
    roots = ((-b + math.sqrt(disc)) / (2 * a), (-b - math.sqrt(disc)) / (2 * a))
    return float(np.clip(min(roots), -1.0, 1.0))


def _lsb_corr(channel: np.ndarray) -> float:
    plane = (channel & 1).astype(np.float64)
    a, b = plane[:, :-1].ravel(), plane[:, 1:].ravel()
    if a.std() < _EPS or b.std() < _EPS:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _lsb_features(rgb: np.ndarray) -> list[float]:
    out: list[float] = []
    for c in range(3):
        ch = rgb[..., c]
        p, asym = _chi_square_p(ch)
        out += [p, asym, _spa(ch), _lsb_corr(ch)]
    return out


# --------------------------------------------------------------------------- residual + SPAM


def _residual_features(rgb: np.ndarray, y: np.ndarray) -> list[float]:
    g = rgb[..., 1].astype(np.int64)
    d = g[:, 1:] - g[:, :-1]
    hist = [float(np.mean(d == k)) for k in (-2, -1, 0, 1, 2)]
    out = hist + [float(d.std()), _kurtosis(d)]
    kb = convolve(y, _KB, mode="reflect")
    med = y - median_filter(y, size=3, mode="reflect")
    for r in (kb, med):
        out += [float(r.std()), _kurtosis(r), float(np.mean(np.abs(r)))]
    return out


def _spam(rgb: np.ndarray, t: int = 2) -> list[float]:
    g = rgb[..., 1].astype(np.int64)
    mats = []
    for arr in (g, g.T):
        d = np.clip(arr[:, :-1] - arr[:, 1:], -t, t) + t
        a, b = d[:, :-1].ravel(), d[:, 1:].ravel()
        counts = np.zeros((2 * t + 1, 2 * t + 1))
        np.add.at(counts, (a, b), 1)
        mats.append(counts / (counts.sum(axis=1, keepdims=True) + _EPS))
    return list(((mats[0] + mats[1]) / 2.0).ravel())


# --------------------------------------------------------------------------- DCT / DWT


def _block_dct(y: np.ndarray) -> np.ndarray:
    nbh, nbw = y.shape[0] // 8, y.shape[1] // 8
    blocks = y[: nbh * 8, : nbw * 8].reshape(nbh, 8, nbw, 8).transpose(0, 2, 1, 3)
    return dctn(blocks, axes=(2, 3), norm="ortho").reshape(-1, 8, 8)


def _dct_features(y: np.ndarray) -> list[float]:
    coeffs = _block_dct(y)
    u, v = np.meshgrid(np.arange(8), np.arange(8), indexing="ij")
    band = u + v
    out: list[float] = []
    for lo, hi in ((1, 2), (3, 5), (6, 14)):
        mask = (band >= lo) & (band <= hi)
        sel = coeffs[:, mask]
        out += [float(np.log1p(np.mean(np.abs(sel)))), float(np.mean(np.abs(sel) < 0.5))]
    scores, periods = [], []
    for pu, pv in _PERIODIC_POSITIONS:
        score, period = periodicity(coeffs[:, pu, pv])
        scores.append(score)
        periods.append(period)
    out += scores
    out.append(float(np.median(periods)))
    # Blockiness: mean |step| across 8-px grid boundaries vs. inside blocks.
    dx = np.abs(np.diff(y, axis=1))
    cols = np.arange(dx.shape[1])
    boundary = dx[:, (cols % 8) == 7].mean() if np.any((cols % 8) == 7) else 0.0
    inside = dx[:, (cols % 8) != 7].mean()
    out.append(float(boundary / (inside + _EPS)))
    return out


def _dwt_features(y: np.ndarray) -> list[float]:
    h, w = (y.shape[0] // 8) * 8, (y.shape[1] // 8) * 8
    coeffs = pywt.wavedec2(y[:h, :w], "haar", level=3)
    out: list[float] = []
    for level_idx, details in enumerate(coeffs[1:]):  # level 3, 2, 1
        for band in details:
            out += [float(np.log1p(np.mean(np.abs(band)))), _kurtosis(band)]
        if level_idx < 2:  # periodicity for level-3 and level-2 H/V
            for band in details[:2]:
                out.append(periodicity(band.ravel())[0])
    return out


# --------------------------------------------------------------------------- global


def _global_features(rgb: np.ndarray, y: np.ndarray) -> list[float]:
    hist = np.bincount(np.clip(np.rint(y), 0, 255).astype(np.int64).ravel(), minlength=256).astype(np.float64)
    p = hist / hist.sum()
    entropy = float(-np.sum(p[p > 0] * np.log2(p[p > 0])))
    saturation = float(np.mean((rgb == 0) | (rgb == 255)))
    gaps = []
    for c in range(3):
        ch_hist = np.bincount(rgb[..., c].ravel(), minlength=256)
        nz = np.nonzero(ch_hist)[0]
        span = ch_hist[nz[0] : nz[-1] + 1] if nz.size else ch_hist
        gaps.append(float(np.mean(span == 0)))
    return [entropy, float(y.mean() / 255.0), float(y.std() / 255.0), saturation, float(np.mean(gaps))]


# --------------------------------------------------------------------------- public API


def feature_names() -> list[str]:
    names: list[str] = []
    for c in "RGB":
        names += [f"lsb_chi2_p_{c}", f"lsb_pov_asym_{c}", f"lsb_spa_{c}", f"lsb_hcorr_{c}"]
    names += [f"res_g_d{k:+d}" for k in (-2, -1, 0, 1, 2)] + ["res_g_std", "res_g_kurt"]
    for r in ("kb", "med"):
        names += [f"res_{r}_std", f"res_{r}_kurt", f"res_{r}_absmean"]
    names += [f"spam_{a}{b}" for a in range(5) for b in range(5)]
    for band in ("low", "mid", "high"):
        names += [f"dct_{band}_logmag", f"dct_{band}_zero"]
    names += [f"dct_period_{u}{v}" for u, v in _PERIODIC_POSITIONS] + ["dct_dominant_period", "dct_blockiness"]
    for level in (3, 2, 1):
        for band in ("H", "V", "D"):
            names += [f"dwt_L{level}{band}_logmag", f"dwt_L{level}{band}_kurt"]
        if level in (3, 2):
            names += [f"dwt_L{level}H_period", f"dwt_L{level}V_period"]
    names += ["glob_entropy", "glob_luma_mean", "glob_luma_std", "glob_saturation", "glob_hist_gaps"]
    return names


FEATURE_GROUPS = {
    "lsb": "LSB statistics",
    "res": "Noise residuals",
    "spam": "SPAM transitions",
    "dct": "Block-DCT",
    "dwt": "Wavelet",
    "glob": "Global",
}


def extract_features(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("expected uint8 RGB image")
    y = rgb.astype(np.float64) @ _LUMA
    values = (
        _lsb_features(rgb)
        + _residual_features(rgb, y)
        + _spam(rgb)
        + _dct_features(y)
        + _dwt_features(y)
        + _global_features(rgb, y)
    )
    arr = np.asarray(values, dtype=np.float64)
    return np.nan_to_num(arr, nan=0.0, posinf=1e6, neginf=-1e6)
