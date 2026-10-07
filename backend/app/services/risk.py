"""Stego risk score - a transparent, documented combination of measured evidence.

    evidence = Σ wᵢ·xᵢ / Σ wᵢ          over the components that are available
        x_cnn     = 1 − P_cnn(normal)       StegoNet probability that the image carries a payload
        x_rf      = 1 − P_rf(normal)        Random-Forest probability (handcrafted features)
        x_anomaly = anomaly percentile      share of clean validation covers that look *less*
                                            anomalous than this image (Mahalanobis distance)
        weights   w_cnn = 0.55, w_rf = 0.25, w_anomaly = 0.20

    payload floor (only when a StegoLab frame is physically present):
        integrity-verified frame header + digest  -> score ≥ 97
        frame header found but digest mismatch     -> score ≥ 85

    risk = 100 · max(evidence, floor)

Levels use admin-configurable thresholds (defaults 35 / 65 / 85):
LOW < medium ≤ MEDIUM < high ≤ HIGH < critical ≤ CRITICAL.

The weights favour the CNN because it has the best measured accuracy; the RF
and the anomaly model are independent evidence that temper over-confident CNN
outputs. Nothing here is random: identical inputs produce identical scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

WEIGHTS = {"cnn": 0.55, "rf": 0.25, "anomaly": 0.20}
FLOOR_VERIFIED = 0.97
FLOOR_HEADER_ONLY = 0.85

RECOMMENDATIONS = {
    "LOW": "No strong evidence of hidden data. Retain normal handling; re-scan if the image's provenance changes.",
    "MEDIUM": "Some statistical evidence of embedding. Verify the image's source and compare against an original if available.",
    "HIGH": "Strong evidence of hidden data. Quarantine the file, preserve the original bytes (SHA-256 recorded), and escalate for forensic review.",
    "CRITICAL": "Near-certain covert payload. Block distribution, preserve evidence chain-of-custody, and attempt extraction with authorised keys.",
}


@dataclass
class RiskResult:
    score: float
    level: str
    evidence: float
    floor: float
    factors: list[dict[str, Any]] = field(default_factory=list)
    agreement: str | None = None
    recommendation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "evidence": self.evidence,
            "floor": self.floor,
            "factors": self.factors,
            "agreement": self.agreement,
            "recommendation": self.recommendation,
            "formula": "100 · max(Σ wᵢxᵢ / Σ wᵢ, payload floor)",
        }


def level_for(score: float, thresholds: dict[str, int]) -> str:
    if score >= thresholds["risk_threshold_critical"]:
        return "CRITICAL"
    if score >= thresholds["risk_threshold_high"]:
        return "HIGH"
    if score >= thresholds["risk_threshold_medium"]:
        return "MEDIUM"
    return "LOW"


def compute_risk(
    *,
    p_cnn_stego: float,
    p_rf_stego: float | None,
    anomaly: float | None,
    signature: dict[str, Any] | None,
    thresholds: dict[str, int],
) -> RiskResult:
    components = {"cnn": p_cnn_stego, "rf": p_rf_stego, "anomaly": anomaly}
    available = {k: v for k, v in components.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in available)
    evidence = sum(WEIGHTS[k] * float(v) for k, v in available.items()) / total_w if total_w else 0.0

    floor = 0.0
    if signature and signature.get("integrity") == "verified":
        floor = FLOOR_VERIFIED
    elif signature and signature.get("integrity") == "failed":
        floor = FLOOR_HEADER_ONLY

    labels = {
        "cnn": "StegoNet P(stego)",
        "rf": "Random Forest P(stego)",
        "anomaly": "Statistical anomaly percentile",
    }
    factors = [
        {
            "key": key,
            "label": labels[key],
            "value": None if value is None else float(value),
            "weight": WEIGHTS[key],
            "effective_weight": (WEIGHTS[key] / total_w) if value is not None and total_w else 0.0,
            "contribution": (WEIGHTS[key] * float(value) / total_w * 100) if value is not None and total_w else 0.0,
            "available": value is not None,
        }
        for key, value in components.items()
    ]
    factors.append(
        {
            "key": "payload_signature",
            "label": "StegoLab frame signature",
            "value": signature.get("integrity") if signature else None,
            "weight": None,
            "effective_weight": None,
            "contribution": floor * 100,
            "available": True,
        }
    )

    agreement = None
    if p_rf_stego is not None:
        same = (p_cnn_stego >= 0.5) == (p_rf_stego >= 0.5)
        agreement = "agree" if same else "disagree"

    score = round(100.0 * max(evidence, floor), 1)
    level = level_for(score, thresholds)
    return RiskResult(
        score=score,
        level=level,
        evidence=evidence,
        floor=floor,
        factors=factors,
        agreement=agreement,
        recommendation=RECOMMENDATIONS[level],
    )
