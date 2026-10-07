"""StegoNet - a multi-domain steganalysis CNN (cover / LSB / DCT / DWT).

Architecture
------------
Steganographic signals are ~1-3 grey levels against image content of ±100, so
generic vision CNNs learn content, not stego noise. StegoNet therefore starts
with three *fixed* analysis front-ends - one per embedding domain - and learns
everything after them:

1. **Spatial residual branch** - 10 SRM high-pass kernels (Fridrich & Kodovský
   2012) applied depth-wise to R, G, B (30 maps) and truncated to ±3 (TLU, as in
   Yedroudj-Net). Exposes LSB noise. Then 5 conv blocks → 16×16 map → GAP.
2. **Block-DCT branch** - luma through the 63 orthonormal 8×8 AC DCT basis
   functions at stride 8, i.e. exact JPEG-grid block coefficients. A learnable
   1×1 projection (initialised to select the 14 low/mid frequencies) feeds a
   *soft-histogram* layer (Gaussian bins with learnable centres/widths, cf. Wang
   et al., "Learnable Histogram", ECCV 2016). Spatially pooled bin activations
   are coefficient histograms, so quantisation lattices left by QIM are directly
   representable. → convs → 32×32 map → GAP.
3. **Wavelet branch** - level-2 and level-3 Haar detail coefficients (fixed
   stride-4 / stride-8 kernels), each through a soft-histogram layer. → convs → GAP.

The three pooled vectors are concatenated and classified by a small MLP. Fixed
front-ends run in float32; the learned trunk may use mixed precision.

Inputs are uint8-range RGB tensors (B, 3, H, W) with H, W multiples of 8
(≥ 64). Training uses 256×256 tiles; the network is fully convolutional + GAP,
so inference accepts other sizes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

CLASSES = ("normal", "lsb", "dct", "dwt")


@dataclass
class StegoNetConfig:
    srm_threshold: float = 3.0
    # Weighted-Stego residual channels (parity-aware; separates LSB replacement from symmetric
    # noise). Off by default so checkpoints trained without it (v1.0.0, v1.1.0) still load.
    ws_branch: bool = False
    ws_threshold: float = 8.0
    dct_projection: int = 16
    hist_bins: int = 25
    dct_hist_range: float = 48.0
    dwt_hist_range: float = 96.0
    width: int = 32
    dropout: float = 0.3
    num_classes: int = len(CLASSES)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- fixed filter banks


def srm_kernels() -> np.ndarray:
    """Ten representative SRM residual kernels (5×5, zero-padded)."""

    def pad(k: np.ndarray) -> np.ndarray:
        out = np.zeros((5, 5))
        r0, c0 = (5 - k.shape[0]) // 2, (5 - k.shape[1]) // 2
        out[r0 : r0 + k.shape[0], c0 : c0 + k.shape[1]] = k
        return out

    first = np.array([[0, 0, 0], [0, -1, 1], [0, 0, 0]], dtype=np.float64)
    second = np.array([[0, 0, 0], [1, -2, 1], [0, 0, 0]], dtype=np.float64) / 2
    third = np.array([[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 1, -3, 3, -1], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]], dtype=np.float64) / 3
    square3 = np.array([[-1, 2, -1], [2, -4, 2], [-1, 2, -1]], dtype=np.float64) / 4
    square5 = np.array(
        [[-1, 2, -2, 2, -1], [2, -6, 8, -6, 2], [-2, 8, -12, 8, -2], [2, -6, 8, -6, 2], [-1, 2, -2, 2, -1]], dtype=np.float64
    ) / 12
    edge3 = np.array([[-1, 2, -1], [2, -4, 2], [0, 0, 0]], dtype=np.float64) / 4
    kernels = [
        pad(first), pad(first.T), pad(second), pad(second.T), third, third.T,
        pad(square3), square5, pad(edge3), pad(np.rot90(edge3)),
    ]  # fmt: skip
    return np.stack(kernels)


def dct_basis() -> np.ndarray:
    """(64, 8, 8) orthonormal DCT-II basis; index u*8+v."""
    n = 8
    basis = np.zeros((64, n, n))
    for u in range(n):
        for v in range(n):
            au = math.sqrt(1 / n) if u == 0 else math.sqrt(2 / n)
            av = math.sqrt(1 / n) if v == 0 else math.sqrt(2 / n)
            for x in range(n):
                for y in range(n):
                    basis[u * 8 + v, x, y] = au * av * math.cos((2 * x + 1) * u * math.pi / 16) * math.cos((2 * y + 1) * v * math.pi / 16)
    return basis


def haar_detail_kernels(level: int) -> np.ndarray:
    """(3, s, s) kernels equal to pywt 'haar' level-``level`` details (H, V, D) on an s×s block."""
    s = 2**level
    half = s // 2
    norm = 1.0 / s
    top = np.vstack([np.ones((half, s)), -np.ones((half, s))]) * norm  # horizontal detail (cH)
    left = np.hstack([np.ones((s, half)), -np.ones((s, half))]) * norm  # vertical detail (cV)
    diag = top * np.sign(left)
    return np.stack([top, left, diag])


# --------------------------------------------------------------------------- layers


class SoftHistogram(nn.Module):
    """Per-channel Gaussian soft binning: (B,C,H,W) -> (B, C*bins, H, W)."""

    def __init__(self, channels: int, bins: int, value_range: float) -> None:
        super().__init__()
        centres = torch.linspace(-value_range, value_range, bins).repeat(channels, 1)
        self.centres = nn.Parameter(centres)  # (C, bins)
        self.log_width = nn.Parameter(torch.full((channels, bins), math.log(2 * value_range / (bins - 1) * 0.5)))
        self.channels, self.bins = channels, bins

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, c, h, w = x.shape
        diff = x.unsqueeze(2) - self.centres.view(1, c, self.bins, 1, 1)
        width = self.log_width.exp().view(1, c, self.bins, 1, 1)
        return torch.exp(-((diff / width) ** 2)).reshape(b, c * self.bins, h, w)


def conv_bn(cin: int, cout: int, k: int = 3, stride: int = 1) -> nn.Sequential:
    return nn.Sequential(nn.Conv2d(cin, cout, k, stride, k // 2, bias=False), nn.BatchNorm2d(cout), nn.ReLU(inplace=True))


class StegoNet(nn.Module):
    def __init__(self, config: StegoNetConfig | None = None) -> None:
        super().__init__()
        self.config = cfg = config or StegoNetConfig()

        # Fixed front-ends (registered as buffers: not trained, saved with the model).
        srm = torch.tensor(srm_kernels(), dtype=torch.float32).unsqueeze(1)  # (10,1,5,5)
        self.register_buffer("srm", srm.repeat(3, 1, 1, 1))  # depth-wise over RGB -> 30
        self.register_buffer("luma_w", torch.tensor([0.299, 0.587, 0.114]).view(1, 3, 1, 1))
        kb = torch.tensor([[-1.0, 2.0, -1.0], [2.0, 0.0, 2.0], [-1.0, 2.0, -1.0]]) / 4.0  # KB pixel predictor
        self.register_buffer("kb_pred", kb.view(1, 1, 3, 3).repeat(3, 1, 1, 1), persistent=False)
        self.register_buffer("dct", torch.tensor(dct_basis()[1:], dtype=torch.float32).unsqueeze(1))  # 63 AC
        self.register_buffer("haar2", torch.tensor(haar_detail_kernels(2), dtype=torch.float32).unsqueeze(1))
        self.register_buffer("haar3", torch.tensor(haar_detail_kernels(3), dtype=torch.float32).unsqueeze(1))

        w = cfg.width
        # 1) spatial residual branch
        self.spatial = nn.Sequential(
            conv_bn(30 + (3 if cfg.ws_branch else 0), w),
            conv_bn(w, w), nn.AvgPool2d(2),            # 128
            conv_bn(w, 2 * w), nn.AvgPool2d(2),        # 64
            conv_bn(2 * w, 4 * w), nn.AvgPool2d(2),    # 32
            conv_bn(4 * w, 4 * w), nn.AvgPool2d(2),    # 16
        )  # fmt: skip
        self.spatial_head = conv_bn(4 * w, 4 * w)  # Grad-CAM target (16x16 on a 256 tile)

        # 2) block-DCT branch
        self.dct_proj = nn.Conv2d(63, cfg.dct_projection, 1, bias=False)
        with torch.no_grad():
            self.dct_proj.weight.zero_()
            ac_index = [u * 8 + v - 1 for u in range(5) for v in range(5) if 1 <= u + v <= 4]
            for out_ch, idx in enumerate(ac_index[: cfg.dct_projection]):
                self.dct_proj.weight[out_ch, idx, 0, 0] = 1.0
        self.dct_hist = SoftHistogram(cfg.dct_projection, cfg.hist_bins, cfg.dct_hist_range)
        self.dct_trunk = nn.Sequential(
            conv_bn(cfg.dct_projection * cfg.hist_bins, 2 * w, k=1),
            conv_bn(2 * w, 2 * w),
        )
        self.dct_head = conv_bn(2 * w, 3 * w)  # Grad-CAM target (32x32 = one cell per 8x8 block)

        # 3) wavelet branch
        self.dwt2_hist = SoftHistogram(3, cfg.hist_bins, cfg.dwt_hist_range)
        self.dwt3_hist = SoftHistogram(3, cfg.hist_bins, cfg.dwt_hist_range)
        self.dwt2_trunk = nn.Sequential(conv_bn(3 * cfg.hist_bins, w, k=1), conv_bn(w, w, stride=2))
        self.dwt3_trunk = nn.Sequential(conv_bn(3 * cfg.hist_bins, w, k=1), conv_bn(w, w))
        self.dwt_head = conv_bn(2 * w, 3 * w)  # Grad-CAM target (32x32)

        features = 4 * w + 3 * w + 3 * w
        self.classifier = nn.Sequential(
            nn.Dropout(cfg.dropout), nn.Linear(features, 128), nn.ReLU(inplace=True), nn.Linear(128, cfg.num_classes)
        )

    # ------------------------------------------------------------------ front-ends (float32)
    def front_ends(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        x = x.float()
        t = self.config.srm_threshold
        residual = torch.clamp(F.conv2d(x, self.srm, padding=2, groups=3), -t, t)
        if self.config.ws_branch:
            # Weighted-Stego residual (Fridrich & Goljan 2004): (x - x̄)·(x - F(x)) with x̄ = x XOR 1.
            # Its mean is ~0 for any parity-symmetric process (noise, blur, JPEG) and grows with the
            # LSB-replacement rate. Rescaled to the SRM range so both inputs share one scale.
            parity = 2.0 * torch.remainder(x, 2.0) - 1.0
            prediction = F.conv2d(F.pad(x, (1, 1, 1, 1), mode="reflect"), self.kb_pred, groups=3)
            tw = self.config.ws_threshold
            ws = torch.clamp(parity * (x - prediction), -tw, tw) * (t / tw)
            residual = torch.cat([residual, ws], dim=1)
        luma = (x * self.luma_w).sum(dim=1, keepdim=True)
        dct = F.conv2d(luma, self.dct, stride=8)
        dwt2 = F.conv2d(luma, self.haar2, stride=4)
        dwt3 = F.conv2d(luma, self.haar3, stride=8)
        return residual, dct, dwt2, dwt3

    def forward(self, x: torch.Tensor, return_maps: bool = False):  # type: ignore[no-untyped-def]
        with torch.autocast(device_type=x.device.type, enabled=False):
            residual, dct, dwt2, dwt3 = self.front_ends(x)
            dct_h = self.dct_hist(torch.clamp(self.dct_proj(dct), -64, 64))
            dwt2_h = self.dwt2_hist(torch.clamp(dwt2, -128, 128))
            dwt3_h = self.dwt3_hist(torch.clamp(dwt3, -128, 128))

        spatial_map = self.spatial_head(self.spatial(residual))
        dct_map = self.dct_head(self.dct_trunk(dct_h))
        dwt_map = self.dwt_head(torch.cat([self.dwt2_trunk(dwt2_h), self.dwt3_trunk(dwt3_h)], dim=1))

        pooled = torch.cat([m.float().mean(dim=(2, 3)) for m in (spatial_map, dct_map, dwt_map)], dim=1)
        logits = self.classifier(pooled)
        if return_maps:
            return logits, {"spatial": spatial_map, "dct": dct_map, "dwt": dwt_map}
        return logits


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
