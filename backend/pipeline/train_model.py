"""Train the steganalysis models.

    python -m pipeline.train_model --model cnn            # StegoNet (GPU if available)
    python -m pipeline.train_model --model rf             # Random Forest + anomaly model
    python -m pipeline.train_model --model all

Outputs go to ``backend/models/<model-name>/<version>/``:
``model.pt`` / ``model.joblib``, ``card.json`` (provenance), ``metrics.json`` (held-out
*test* split), ``val_metrics.json``, ``history.json`` and PNG plots. The backend registers
these on startup; no metric is ever typed in by hand.
"""

from __future__ import annotations

import argparse
import math
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.common import (
    DATASET,
    MODELS,
    dataset_stats,
    display_path,
    environment,
    load_manifest,
    load_split,
    next_version,
    now_iso,
    sha256_file,
    write_json,
)

CNN_NAME = "steganalysis-cnn"
RF_NAME = "steganalysis-rf"


# =========================================================================== CNN


def d4(batch: np.ndarray, k: int) -> np.ndarray:
    """Apply one of the 8 dihedral transforms to (N, H, W, C) - preserves stego statistics."""
    out = np.rot90(batch, k % 4, axes=(1, 2))
    if k >= 4:
        out = out[:, :, ::-1]
    return np.ascontiguousarray(out)


class GroupDataset:
    """Item = one tile in all four versions [cover, lsb, dct, dwt] (keeps pairs together)."""

    def __init__(self, split: str, augment: bool) -> None:
        self.split, self.augment = split, augment
        self.x, y = load_split(split)
        groups = y.reshape(-1, 4)
        if not np.all(groups == np.arange(4)):
            raise ValueError(f"{split}: rows are not grouped as [normal, lsb, dct, dwt]")
        self.n = groups.shape[0]

    def __len__(self) -> int:
        return self.n

    def load(self, g: int, rng: np.random.Generator) -> np.ndarray:
        tiles = np.array(self.x[4 * g : 4 * g + 4])  # copy out of the read-only memmap
        return d4(tiles, int(rng.integers(8))) if self.augment else tiles


class ThreadedLoader:
    """Background-thread batch prefetcher.

    Batches are memmap slices + a flip/rotation, so threads are sufficient; this avoids
    spawning DataLoader worker processes that each re-import PyTorch (~1 GB RAM apiece on Windows).
    """

    def __init__(self, dataset: GroupDataset, batch_groups: int, seed: int, threads: int = 3, prefetch: int = 8) -> None:
        self.dataset, self.batch_groups, self.threads, self.prefetch = dataset, batch_groups, threads, prefetch
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.dataset) // self.batch_groups

    def _batch(self, groups: np.ndarray, seed: int):  # type: ignore[no-untyped-def]
        import torch

        rng = np.random.default_rng(seed)
        x = np.concatenate([self.dataset.load(int(g), rng) for g in groups])
        xb = torch.from_numpy(x).permute(0, 3, 1, 2)
        yb = torch.arange(4).repeat(len(groups))
        if torch.cuda.is_available():
            xb = xb.pin_memory()
        return xb, yb

    def __iter__(self):  # type: ignore[no-untyped-def]
        from concurrent.futures import ThreadPoolExecutor

        order = self.rng.permutation(len(self.dataset))
        batches = [order[i : i + self.batch_groups] for i in range(0, len(self) * self.batch_groups, self.batch_groups)]
        seeds = self.rng.integers(0, 2**31, size=len(batches))
        with ThreadPoolExecutor(self.threads) as pool:
            pending = [pool.submit(self._batch, batches[i], int(seeds[i])) for i in range(min(self.prefetch, len(batches)))]
            for i in range(len(batches)):
                result = pending[i].result()
                nxt = i + self.prefetch
                if nxt < len(batches):
                    pending.append(pool.submit(self._batch, batches[nxt], int(seeds[nxt])))
                pending[i] = None  # release memory
                yield result


def _predict(model, split: str, device, batch_size: int = 64) -> tuple[np.ndarray, np.ndarray, float]:  # type: ignore[no-untyped-def]
    import torch
    from torch.nn import functional as F

    x, y = load_split(split)
    probs = np.zeros((len(y), 4), dtype=np.float64)
    total_loss = 0.0
    model.eval()
    with torch.no_grad():
        for start in range(0, len(y), batch_size):
            xb = torch.from_numpy(np.array(x[start : start + batch_size])).permute(0, 3, 1, 2).to(device).float()
            yb = torch.from_numpy(y[start : start + batch_size]).to(device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(xb)
            total_loss += float(F.cross_entropy(logits.float(), yb, reduction="sum"))
            probs[start : start + len(yb)] = torch.softmax(logits.float(), dim=1).cpu().numpy()
    return y, probs, total_loss / len(y)


def train_cnn(args: argparse.Namespace) -> Path:
    import torch
    from torch.nn import functional as F

    from app.ml.cnn import CLASSES, StegoNet, StegoNetConfig, count_parameters
    from app.ml.evaluation import evaluate, save_plots

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    torch.backends.cudnn.benchmark = True
    version = next_version(CNN_NAME, args.version)
    out = MODELS / CNN_NAME / version
    out.mkdir(parents=True, exist_ok=True)
    print(f"[cnn] training {CNN_NAME} v{version} on {device}")

    train_ds = GroupDataset("train", augment=True)
    loader = ThreadedLoader(train_ds, args.batch_groups, seed=args.seed, threads=args.workers)
    config = StegoNetConfig(ws_branch=not args.no_ws_branch)
    model = StegoNet(config).to(device)

    no_decay = [p for n, p in model.named_parameters() if p.ndim <= 1 or "centres" in n or "log_width" in n]
    decay = [p for n, p in model.named_parameters() if not (p.ndim <= 1 or "centres" in n or "log_width" in n)]
    optimizer = torch.optim.AdamW(
        [{"params": decay, "weight_decay": args.weight_decay}, {"params": no_decay, "weight_decay": 0.0}], lr=args.lr
    )
    steps_per_epoch = len(loader)
    total_steps = steps_per_epoch * args.epochs
    warmup = steps_per_epoch

    def lr_lambda(step: int) -> float:
        if step < warmup:
            return (step + 1) / warmup
        progress = (step - warmup) / max(1, total_steps - warmup)
        return 0.5 * (1 + math.cos(math.pi * min(1.0, progress)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
    history: list[dict[str, Any]] = []
    best = {"f1": -1.0, "epoch": -1, "loss": float("inf")}
    stale = 0
    started = time.time()

    for epoch in range(1, args.epochs + 1):
        model.train()
        t0 = time.time()
        run_loss, run_correct, seen = 0.0, 0, 0
        for xb, yb in loader:
            xb = xb.to(device, non_blocking=True).float()
            yb = yb.to(device, non_blocking=True)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(xb)
                loss = F.cross_entropy(logits.float(), yb, label_smoothing=args.label_smoothing)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            scheduler.step()
            run_loss += loss.item() * len(yb)
            run_correct += int((logits.argmax(1) == yb).sum())
            seen += len(yb)

        y_val, p_val, val_loss = _predict(model, "val", device)
        from sklearn.metrics import f1_score

        val_pred = p_val.argmax(1)
        val_f1 = float(f1_score(y_val, val_pred, average="macro"))
        val_acc = float(np.mean(val_pred == y_val))
        record = {
            "epoch": epoch,
            "train_loss": run_loss / seen,
            "train_accuracy": run_correct / seen,
            "val_loss": val_loss,
            "val_accuracy": val_acc,
            "val_f1_macro": val_f1,
            "lr": scheduler.get_last_lr()[0],
            "seconds": round(time.time() - t0, 1),
        }
        history.append(record)
        improved = val_f1 > best["f1"] + 1e-4 or (abs(val_f1 - best["f1"]) <= 1e-4 and val_loss < best["loss"])
        if improved:
            best = {"f1": val_f1, "epoch": epoch, "loss": val_loss}
            torch.save({"state_dict": model.state_dict(), "config": config.to_dict(), "classes": list(CLASSES)}, out / "model.pt")
            stale = 0
        else:
            stale += 1
        print(
            f"[cnn] epoch {epoch:02d} train_loss={record['train_loss']:.4f} train_acc={record['train_accuracy']:.4f} "
            f"val_loss={val_loss:.4f} val_acc={val_acc:.4f} val_f1={val_f1:.4f} ({record['seconds']}s)"
            + ("  *best*" if improved else ""),
            flush=True,
        )
        write_json(out / "history.json", {"history": history, "best": best})
        if stale >= args.patience:
            print(f"[cnn] early stopping: no val F1 improvement for {args.patience} epochs")
            break

    duration = time.time() - started
    checkpoint = torch.load(out / "model.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])

    y_val, p_val, _ = _predict(model, "val", device)
    write_json(out / "val_metrics.json", evaluate(y_val, p_val, load_manifest("val")))
    y_test, p_test, test_loss = _predict(model, "test", device)
    report = evaluate(y_test, p_test, load_manifest("test"))
    report["split"] = "test"
    report["loss"] = test_loss
    write_json(out / "metrics.json", report)
    plots = save_plots(report, out, f"StegoNet v{version}")
    _training_curves(history, out)

    stats = dataset_stats()
    card = {
        "model_name": CNN_NAME,
        "display_name": "StegoNet (multi-domain CNN)",
        "version": version,
        "kind": "cnn",
        "framework": "pytorch",
        "classes": list(CLASSES),
        "input": {"tile": 256, "channels": "RGB uint8", "grid_alignment": 8},
        "architecture": config.to_dict(),
        "parameters": count_parameters(model),
        "weights_file": "model.pt",
        "weights_sha256": sha256_file(out / "model.pt"),
        "trained_at": now_iso(),
        "training": {
            "epochs_run": len(history),
            "best_epoch": best["epoch"],
            "batch_size": args.batch_groups * 4,
            "optimizer": f"AdamW lr={args.lr} wd={args.weight_decay}",
            "schedule": "1-epoch linear warm-up, cosine decay",
            "label_smoothing": args.label_smoothing,
            "augmentation": "D4 dihedral group (8 flips/rotations), applied identically to each cover/stego group",
            "early_stopping": f"val macro-F1, patience {args.patience}",
            "duration_s": round(duration, 1),
            "device": str(device),
        },
        "dataset": {
            "path": display_path(DATASET),
            "sources": stats["sources"],
            "images": stats["images"],
            "leakage_check": stats["leakage_check"],
            "created_at": stats["created_at"],
        },
        "environment": environment(),
        "artifacts": ["metrics.json", "val_metrics.json", "history.json", *plots, "training_curves.png"],
    }
    write_json(out / "card.json", card)
    _summary("cnn", report)
    return out


def _training_curves(history: list[dict[str, Any]], out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    epochs = [h["epoch"] for h in history]
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.2))
    axes[0].plot(epochs, [h["train_loss"] for h in history], label="train")
    axes[0].plot(epochs, [h["val_loss"] for h in history], label="val")
    axes[0].set_title("loss", fontsize=9)
    axes[1].plot(epochs, [h["train_accuracy"] for h in history], label="train acc")
    axes[1].plot(epochs, [h["val_accuracy"] for h in history], label="val acc")
    axes[1].plot(epochs, [h["val_f1_macro"] for h in history], label="val macro-F1")
    axes[1].set_title("accuracy / F1", fontsize=9)
    for ax in axes:
        ax.legend(fontsize=7)
        ax.set_xlabel("epoch")
    fig.tight_layout()
    fig.savefig(out / "training_curves.png", dpi=150)
    plt.close(fig)


# =========================================================================== Random Forest


def _feature_chunk(args: tuple[str, int, int]) -> np.ndarray:
    from app.ml.features import extract_features

    split, start, stop = args
    x, _ = load_split(split)
    return np.stack([extract_features(np.asarray(x[i])) for i in range(start, stop)])


def compute_features(split: str, workers: int) -> np.ndarray:
    cache = DATASET / "features" / f"{split}_features.npy"
    _, y = load_split(split)
    if cache.exists():
        feats = np.load(cache)
        if feats.shape[0] == y.shape[0]:
            print(f"[rf] {split}: loaded cached features {feats.shape}")
            return feats
    cache.parent.mkdir(exist_ok=True)
    chunk = 256
    jobs = [(split, s, min(len(y), s + chunk)) for s in range(0, len(y), chunk)]
    t0 = time.time()
    with mp.Pool(workers) as pool:
        parts = pool.map(_feature_chunk, jobs)
    feats = np.concatenate(parts)
    np.save(cache, feats)
    print(f"[rf] {split}: extracted {feats.shape} in {time.time() - t0:.0f}s")
    return feats


def train_rf(args: argparse.Namespace) -> Path:
    import joblib
    from sklearn.covariance import LedoitWolf
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    from app.ml.evaluation import CLASSES, evaluate, save_plots
    from app.ml.features import FEATURE_GROUPS, feature_names

    version = next_version(RF_NAME, args.version)
    out = MODELS / RF_NAME / version
    out.mkdir(parents=True, exist_ok=True)
    print(f"[rf] training {RF_NAME} v{version}")
    started = time.time()

    feats = {split: compute_features(split, args.feature_workers) for split in ("train", "val", "test")}
    labels = {split: load_split(split)[1] for split in ("train", "val", "test")}

    rf = RandomForestClassifier(
        n_estimators=args.trees, max_features="sqrt", min_samples_leaf=1, n_jobs=-1, random_state=args.seed
    )
    rf.fit(feats["train"], labels["train"])

    # Anomaly model: Mahalanobis distance to the clean-cover feature distribution
    # (Ledoit-Wolf shrinkage), calibrated to a percentile on held-out *validation* covers.
    scaler = StandardScaler().fit(feats["train"][labels["train"] == 0])
    lw = LedoitWolf().fit(scaler.transform(feats["train"][labels["train"] == 0]))

    def distance(f: np.ndarray) -> np.ndarray:
        z = scaler.transform(f) - lw.location_
        return np.sqrt(np.einsum("ij,jk,ik->i", z, lw.precision_, z))

    calibration = np.sort(distance(feats["val"][labels["val"] == 0]))

    def anomaly_score(f: np.ndarray) -> np.ndarray:
        return np.searchsorted(calibration, distance(f), side="right") / calibration.size

    test_anomaly = anomaly_score(feats["test"])
    anomaly_auc = float(roc_auc_score((labels["test"] != 0).astype(int), test_anomaly))

    bundle = {
        "model": rf,
        "classes": list(CLASSES),
        "feature_names": feature_names(),
        "anomaly": {
            "scaler": scaler,
            "location": lw.location_,
            "precision": lw.precision_,
            "calibration": calibration,
        },
    }
    joblib.dump(bundle, out / "model.joblib", compress=3)

    val_report = evaluate(labels["val"], rf.predict_proba(feats["val"]), load_manifest("val"))
    write_json(out / "val_metrics.json", val_report)
    report = evaluate(labels["test"], rf.predict_proba(feats["test"]), load_manifest("test"))
    report["split"] = "test"
    importances = rf.feature_importances_
    order = np.argsort(-importances)
    report["feature_importance"] = [
        {"feature": feature_names()[i], "importance": float(importances[i])} for i in order[:30]
    ]
    groups: dict[str, float] = {}
    for name, value in zip(feature_names(), importances):
        label = FEATURE_GROUPS[name.split("_", 1)[0]]
        groups[label] = groups.get(label, 0.0) + float(value)
    report["feature_group_importance"] = groups
    report["anomaly_model"] = {
        "method": "Mahalanobis distance (Ledoit-Wolf shrinkage) to clean-cover features, percentile-calibrated on validation covers",
        "test_auc_cover_vs_stego": anomaly_auc,
        "calibration_samples": int(calibration.size),
    }
    write_json(out / "metrics.json", report)
    plots = save_plots(report, out, f"Random Forest v{version}")

    stats = dataset_stats()
    card = {
        "model_name": RF_NAME,
        "display_name": "Random Forest on handcrafted steganalysis features",
        "version": version,
        "kind": "random_forest",
        "framework": "scikit-learn",
        "classes": list(CLASSES),
        "input": {"tile": 256, "features": len(feature_names())},
        "hyperparameters": {"n_estimators": args.trees, "max_features": "sqrt", "min_samples_leaf": 1},
        "weights_file": "model.joblib",
        "weights_sha256": sha256_file(out / "model.joblib"),
        "trained_at": now_iso(),
        "training": {"duration_s": round(time.time() - started, 1)},
        "dataset": {"path": display_path(DATASET), "sources": stats["sources"], "images": stats["images"], "leakage_check": stats["leakage_check"]},
        "environment": environment(),
        "artifacts": ["metrics.json", "val_metrics.json", *plots],
    }
    write_json(out / "card.json", card)
    _summary("rf", report)
    print(f"[rf] anomaly model test AUC (cover vs stego): {anomaly_auc:.4f}")
    return out


def _summary(tag: str, report: dict[str, Any]) -> None:
    mc, bn = report["multiclass"], report["binary"]
    print(
        f"[{tag}] TEST accuracy={mc['accuracy']:.4f} macroF1={mc['f1_macro']:.4f} AUC={mc['roc_auc_macro_ovr']:.4f} | "
        f"binary acc={bn['accuracy']:.4f} detection={bn['detection_rate']:.4f} FPR={bn['false_positive_rate']:.4f}"
    )
    print(f"[{tag}] confusion matrix (rows=true {report['classes']}): {mc['confusion_matrix']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=["cnn", "rf", "all"], default="all")
    parser.add_argument("--version", default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--batch-groups", type=int, default=8, help="tiles per batch (each tile = 4 images)")
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--no-ws-branch", action="store_true", help="train without the Weighted-Stego residual input (v1.0/v1.1 architecture)")
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
    parser.add_argument("--workers", type=int, default=3, help="prefetch threads")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--trees", type=int, default=400)
    parser.add_argument("--feature-workers", type=int, default=max(1, (mp.cpu_count() or 4) - 4))
    args = parser.parse_args()

    if args.model in ("rf", "all"):
        train_rf(args)
    if args.model in ("cnn", "all"):
        train_cnn(args)


if __name__ == "__main__":
    main()
