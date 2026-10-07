"""Model evaluation: every metric shown in the UI is computed here from predictions.

Produces a JSON-serialisable report with
* multiclass metrics (accuracy, macro/per-class precision/recall/F1, one-vs-rest ROC-AUC),
* binary cover-vs-stego metrics using P(stego) = 1 - P(normal),
* confusion matrix and sklearn classification report,
* downsampled ROC curves (per class and binary),
* breakdowns by embedding utilisation and by cover-source variant (when a manifest is given).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
)

CLASSES = ("normal", "lsb", "dct", "dwt")
UTIL_BINS = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01))


def _curve(y_true: np.ndarray, score: np.ndarray, points: int = 120) -> dict[str, list[float]]:
    fpr, tpr, thresholds = roc_curve(y_true, score)
    if fpr.size > points:
        idx = np.unique(np.linspace(0, fpr.size - 1, points).astype(int))
        fpr, tpr, thresholds = fpr[idx], tpr[idx], thresholds[idx]
    thresholds = np.clip(thresholds, 0, 1)
    return {"fpr": fpr.round(5).tolist(), "tpr": tpr.round(5).tolist(), "thresholds": thresholds.round(5).tolist()}


def evaluate(y_true: np.ndarray, probs: np.ndarray, manifest: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    y_true = np.asarray(y_true, dtype=np.int64)
    probs = np.asarray(probs, dtype=np.float64)
    # Row-normalise: sklearn's multiclass AUC requires rows summing to exactly 1 (tile averages /
    # mixed-precision softmax can drift by ~1e-7). This never changes the arg-max decision.
    probs = probs / np.clip(probs.sum(axis=1, keepdims=True), 1e-12, None)
    y_pred = probs.argmax(axis=1)
    labels = list(range(len(CLASSES)))

    precision, recall, f1, support = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    try:
        auc_macro = float(roc_auc_score(y_true, probs, multi_class="ovr", average="macro", labels=labels))
    except ValueError:
        auc_macro = None
    per_class_auc = {}
    for i, name in enumerate(CLASSES):
        positives = (y_true == i).astype(int)
        per_class_auc[name] = float(roc_auc_score(positives, probs[:, i])) if 0 < positives.sum() < positives.size else None

    multiclass = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(np.mean(precision)),
        "recall_macro": float(np.mean(recall)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "roc_auc_macro_ovr": auc_macro,
        "per_class": {
            name: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
                "roc_auc": per_class_auc[name],
            }
            for i, name in enumerate(CLASSES)
        },
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "classification_report": classification_report(
            y_true, y_pred, labels=labels, target_names=list(CLASSES), zero_division=0, output_dict=True
        ),
    }

    # Binary cover vs stego
    is_stego = (y_true != 0).astype(int)
    p_stego = 1.0 - probs[:, 0]
    pred_stego = (y_pred != 0).astype(int)
    tp = int(np.sum((pred_stego == 1) & (is_stego == 1)))
    tn = int(np.sum((pred_stego == 0) & (is_stego == 0)))
    fp = int(np.sum((pred_stego == 1) & (is_stego == 0)))
    fn = int(np.sum((pred_stego == 0) & (is_stego == 1)))
    binary = {
        "accuracy": (tp + tn) / max(1, tp + tn + fp + fn),
        "precision": tp / max(1, tp + fp),
        "recall": tp / max(1, tp + fn),
        "detection_rate": tp / max(1, tp + fn),
        "false_positive_rate": fp / max(1, fp + tn),
        "f1": 2 * tp / max(1, 2 * tp + fp + fn),
        "roc_auc": float(roc_auc_score(is_stego, p_stego)) if 0 < is_stego.sum() < is_stego.size else None,
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }

    report: dict[str, Any] = {
        "samples": int(y_true.size),
        "classes": list(CLASSES),
        "multiclass": multiclass,
        "binary": binary,
        "roc_curves": {
            "binary": _curve(is_stego, p_stego),
            **{name: _curve((y_true == i).astype(int), probs[:, i]) for i, name in enumerate(CLASSES)},
        },
    }

    if manifest is not None:
        report["by_utilisation"] = _by_utilisation(y_true, y_pred, manifest)
        report["by_cover_variant"] = _by_variant(y_true, y_pred, manifest)
    return report


def _by_utilisation(y_true: np.ndarray, y_pred: np.ndarray, manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    util = np.array([float(row["utilisation"]) for row in manifest])
    rows = []
    for i, name in enumerate(CLASSES[1:], start=1):
        for lo, hi in UTIL_BINS:
            mask = (y_true == i) & (util >= lo) & (util < hi)
            n = int(mask.sum())
            if n == 0:
                continue
            rows.append(
                {
                    "technique": name,
                    "bin": f"{int(lo * 100)}-{min(100, int(hi * 100))}%",
                    "samples": n,
                    "detection_rate": float(np.mean(y_pred[mask] != 0)),
                    "technique_accuracy": float(np.mean(y_pred[mask] == i)),
                }
            )
    return rows


def _by_variant(y_true: np.ndarray, y_pred: np.ndarray, manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants = np.array([row["variant"] for row in manifest])
    rows = []
    for variant in sorted(set(variants.tolist())):
        covers = (variants == variant) & (y_true == 0)
        stegos = (variants == variant) & (y_true != 0)
        rows.append(
            {
                "variant": variant,
                "covers": int(covers.sum()),
                "false_positive_rate": float(np.mean(y_pred[covers] != 0)) if covers.any() else None,
                "stego": int(stegos.sum()),
                "detection_rate": float(np.mean(y_pred[stegos] != 0)) if stegos.any() else None,
                "accuracy": float(np.mean(y_pred[(variants == variant)] == y_true[(variants == variant)])),
            }
        )
    return rows


def save_plots(report: dict[str, Any], out_dir: Any, title: str) -> list[str]:
    """Confusion-matrix and ROC PNGs for the documentation (UI renders the JSON itself)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    written = []
    cm = np.array(report["multiclass"]["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(4.6, 4))
    ax.imshow(cm, cmap="Greys")
    ax.set_xticks(range(len(CLASSES)), CLASSES)
    ax.set_yticks(range(len(CLASSES)), CLASSES)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "black")
    ax.set_title(f"{title} - confusion matrix", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrix.png", dpi=150)
    plt.close(fig)
    written.append("confusion_matrix.png")

    fig, ax = plt.subplots(figsize=(4.6, 4))
    for name, curve in report["roc_curves"].items():
        ax.plot(curve["fpr"], curve["tpr"], label=name, linewidth=1.6 if name == "binary" else 1.0)
    ax.plot([0, 1], [0, 1], linestyle=":", color="grey")
    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.legend(fontsize=8)
    ax.set_title(f"{title} - ROC", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_dir / "roc_curve.png", dpi=150)
    plt.close(fig)
    written.append("roc_curve.png")
    return written
