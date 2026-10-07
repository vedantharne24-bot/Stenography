"""Build the steganalysis dataset (cover / LSB / DCT / DWT).

    python -m pipeline.generate_dataset --covers ../data/covers --out ../data/dataset

Design
------
* **Sources** - DIV2K train (800 lossless PNG photos) and COCO val2017 (5,000 JPEG photos).
* **Carriers** - each source yields one *carrier* crop that is embedded exactly the way the
  application embeds a user image (real AES-256-GCM envelope -> frame -> LSB/DCT/DWT):
    - DIV2K: one 512×512 crop at native resolution -> later cut into four 256×256 tiles;
    - COCO, even index: resized by a random factor in [max(0.45, 257/min side), 0.6] (≤ 0.8;
      area interpolation) -> 256×256 crop.
      Non-integer downscaling erases the JPEG 8×8 grid, giving artefact-free covers;
    - COCO, odd index: native-resolution 256×256 crop on the JPEG grid. These covers keep
      JPEG quantisation traces and act as hard negatives for the DCT class.
* **Payload** - utilisation u ~ U[0.10, 1.00] of the carrier's slot capacity (clamped up to the
  minimum frame size). Embedding into the whole carrier before tiling means each 256 tile sees
  the same per-slot modification density the app produces on full-size images.
* **Splits** - 70/15/15 by *source image*, stratified per source dataset, seeded. All tiles and
  all four classes of one source stay in one split, so no source content leaks across splits.
  The script asserts that the source-id sets are disjoint.
* **Layout** - ``arrays/{split}_x.npy`` (N×256×256×3 uint8, memory-mappable) and
  ``arrays/{split}_y.npy``; rows are grouped [cover, lsb, dct, dwt] per tile so the trainer can
  keep cover/stego pairs in the same mini-batch. ``manifest.csv`` and ``stats.json`` describe
  every row; ``test_carriers/`` holds held-out cover carriers (PNG) for experiments and demos.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import multiprocessing as mp
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import crypto, metrics  # noqa: E402
from app.services.stego import engine, framing  # noqa: E402

LABELS = ("normal", "lsb", "dct", "dwt")
TILE = 256
SPLIT_FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}
UTIL_RANGE = (0.10, 1.00)
PROCESSING = ("noise", "jpeg", "blur", "resample", "jpeg_noise")
# Down-scaling factors stay non-integer and <= MAX_DOWNSCALE so the JPEG 8x8 grid is destroyed.
MIN_DOWNSCALE = 0.45
MAX_DOWNSCALE = 0.80


@dataclass(frozen=True)
class Source:
    index: int
    dataset: str
    path: str
    split: str
    variant: str  # native512 | downscaled | native_jpeg_grid


def _assign_splits(paths: list[Path], dataset: str, seed: int) -> list[tuple[Path, str]]:
    rng = np.random.default_rng([seed, {"div2k": 1, "coco": 2}[dataset]])
    order = rng.permutation(len(paths))
    n_train = int(round(len(paths) * SPLIT_FRACTIONS["train"]))
    n_val = int(round(len(paths) * SPLIT_FRACTIONS["val"]))
    out: list[tuple[Path, str]] = []
    for rank, idx in enumerate(order):
        split = "train" if rank < n_train else "val" if rank < n_train + n_val else "test"
        out.append((paths[idx], split))
    return out


def discover_sources(covers: Path, seed: int, limit: int | None) -> list[Source]:
    sources: list[Source] = []
    div2k = sorted((covers / "DIV2K_train_HR").glob("*.png"))
    coco = sorted((covers / "val2017").glob("*.jpg"))
    if limit:
        div2k, coco = div2k[: limit // 4 or 1], coco[: limit]
    for path, split in _assign_splits(div2k, "div2k", seed):
        sources.append(Source(len(sources), "div2k", str(path), split, "native512"))
    for i, (path, split) in enumerate(_assign_splits(coco, "coco", seed)):
        variant = "downscaled" if int(path.stem) % 2 == 0 else "native_jpeg_grid"
        sources.append(Source(len(sources), "coco", str(path), split, variant))
    return sources


def carrier_size(source: Source) -> int:
    return 512 if source.variant == "native512" else TILE


def _random_crop(rgb: np.ndarray, size: int, rng: np.random.Generator, grid: int = 8) -> np.ndarray | None:
    h, w = rgb.shape[:2]
    if h < size or w < size:
        return None
    y = int(rng.integers(0, (h - size) // grid + 1)) * grid
    x = int(rng.integers(0, (w - size) // grid + 1)) * grid
    return np.ascontiguousarray(rgb[y : y + size, x : x + size])


def load_carrier(source: Source, rng: np.random.Generator) -> np.ndarray | None:
    rgb = np.asarray(Image.open(source.path).convert("RGB"))
    if source.variant == "downscaled":
        h, w = rgb.shape[:2]
        lo = max(MIN_DOWNSCALE, (TILE + 1) / min(h, w))
        factor = float(rng.uniform(lo, max(lo, 0.60)))
        new = (max(TILE, int(round(w * factor))), max(TILE, int(round(h * factor))))
        rgb = cv2.resize(rgb, new, interpolation=cv2.INTER_AREA)
    return _random_crop(rgb, carrier_size(source), rng)


def _payload_for_utilisation(algorithm: str, shape: tuple[int, ...], utilisation: float, rng: np.random.Generator) -> bytes:
    alg = engine.get_algorithm(algorithm)
    slots = alg.capacity_slots(shape)
    target_bits = max(int(slots * utilisation), framing.frame_bits_for_envelope(crypto.envelope_overhead() + 1, alg.default_nsym))
    max_env = framing.max_envelope_len(min(target_bits, slots), alg.default_nsym)
    content_len = max(1, max_env - crypto.envelope_overhead())
    return rng.bytes(content_len)


def process_cover(rgb: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, str]:
    """Benign processing applied to a cover *before* embedding (cover-source diversity).

    Real covers are noisy, re-compressed, smoothed or resampled. Without such covers in
    training, a detector learns "extra noise = LSB" and "strong JPEG lattice = DCT" and
    raises false alarms on ordinary processed photos.
    """
    op = PROCESSING[int(rng.integers(len(PROCESSING)))]
    img = rgb.astype(np.float64)
    if op == "noise":
        out = img + rng.normal(0, rng.uniform(0.5, 3.0), img.shape)
    elif op == "blur":
        out = cv2.GaussianBlur(rgb, (0, 0), float(rng.uniform(0.4, 1.0))).astype(np.float64)
    elif op == "resample":
        h, w = rgb.shape[:2]
        scale = float(rng.uniform(0.5, 0.9))
        small = cv2.resize(rgb, (max(8, int(w * scale)), max(8, int(h * scale))), interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float64)
    else:  # jpeg / jpeg_noise
        quality = int(rng.integers(40, 96)) if op == "jpeg" else int(rng.integers(60, 96))
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format="JPEG", quality=quality)
        out = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), dtype=np.float64)
        if op == "jpeg_noise":
            out = out + rng.normal(0, rng.uniform(0.5, 2.0), out.shape)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8), op


def _embed_versions(carrier: np.ndarray, rng: np.random.Generator) -> tuple[dict, dict] | str:
    versions = {"normal": carrier}
    meta: dict[str, dict] = {"normal": {"utilisation": 0.0, "payload_bytes": 0, "envelope_bytes": 0, "psnr": None, "ssim": 1.0}}
    for algorithm in ("lsb", "dct", "dwt"):
        utilisation = float(rng.uniform(*UTIL_RANGE))
        content = _payload_for_utilisation(algorithm, carrier.shape, utilisation, rng)
        sealed = crypto.encrypt_payload(content, crypto.Secret(raw_key=rng.bytes(32)))
        try:
            outcome = engine.embed(carrier, sealed.envelope, algorithm)
        except Exception as exc:  # noqa: BLE001
            return f"embed {algorithm}: {type(exc).__name__}"
        versions[algorithm] = outcome.stego
        meta[algorithm] = {
            "utilisation": outcome.utilization,
            "payload_bytes": len(content),
            "envelope_bytes": len(sealed.envelope),
            "psnr": metrics.psnr(carrier, outcome.stego),
            "ssim": metrics.ssim(carrier, outcome.stego),
        }
    return versions, meta


def _tiles(versions: dict) -> list[dict]:
    size = versions["normal"].shape[0]
    return [
        {label: versions[label][ty : ty + TILE, tx : tx + TILE] for label in LABELS}
        for ty in range(0, size, TILE)
        for tx in range(0, size, TILE)
    ]


def process_source(args: tuple[Source, int, bool]) -> dict | None:
    source, seed, with_processed = args
    rng = np.random.default_rng([seed, source.index])
    try:
        carrier = load_carrier(source, rng)
    except Exception as exc:  # noqa: BLE001 - corrupt sources are skipped and counted
        return {"source": source, "error": f"{type(exc).__name__}: {exc}"}
    if carrier is None:
        return {"source": source, "error": "too small"}

    embedded = _embed_versions(carrier, rng)
    if isinstance(embedded, str):
        return {"source": source, "error": embedded}
    carriers = [{"variant": source.variant, "carrier": carrier, "tiles": _tiles(embedded[0]), "meta": embedded[1], "primary": True}]

    if with_processed:
        # A second 256x256 crop of the same source (so the same split), processed, then embedded.
        prng = np.random.default_rng([seed, source.index, 7])
        base = carrier if carrier.shape[0] == TILE else _random_crop(carrier, TILE, prng)
        assert base is not None
        processed, op = process_cover(base, prng)
        embedded_p = _embed_versions(processed, prng)
        if isinstance(embedded_p, str):
            return {"source": source, "error": embedded_p}
        carriers.append({"variant": f"processed:{op}", "carrier": processed, "tiles": _tiles(embedded_p[0]), "meta": embedded_p[1], "primary": False})
    return {"source": source, "carriers": carriers}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--covers", type=Path, default=root / "data" / "covers")
    parser.add_argument("--out", type=Path, default=root / "data" / "dataset")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 4))
    parser.add_argument("--limit", type=int, default=None, help="use only N COCO images (smoke test)")
    parser.add_argument("--samples-per-class", type=int, default=24)
    parser.add_argument("--no-processed", action="store_true", help="omit the processed-cover variant (dataset v1 behaviour)")
    args = parser.parse_args()
    with_processed = not args.no_processed

    started = time.time()
    sources = discover_sources(args.covers, args.seed, args.limit)
    if not sources:
        raise SystemExit(f"No cover images found under {args.covers}")
    print(f"{len(sources)} sources discovered; workers={args.workers}")

    # Pre-pass on image headers only, to size the output arrays exactly.
    tiles_per_source: dict[int, int] = {}
    for src in sources:
        with Image.open(src.path) as im:
            w, h = im.size
        need = carrier_size(src)
        ok = (min(w, h) * MAX_DOWNSCALE >= need + 1) if src.variant == "downscaled" else (min(w, h) >= need)
        tiles_per_source[src.index] = ((need // TILE) ** 2 + (1 if with_processed else 0)) if ok else 0

    out = args.out
    (out / "arrays").mkdir(parents=True, exist_ok=True)
    (out / "test_carriers").mkdir(exist_ok=True)
    (out / "samples").mkdir(exist_ok=True)
    capacity = {s: sum(tiles_per_source[x.index] for x in sources if x.split == s) * len(LABELS) for s in SPLIT_FRACTIONS}
    xs = {s: np.lib.format.open_memmap(out / "arrays" / f"{s}_x.npy", mode="w+", dtype=np.uint8, shape=(capacity[s], TILE, TILE, 3)) for s in SPLIT_FRACTIONS}
    ys = {s: np.full(capacity[s], -1, dtype=np.int64) for s in SPLIT_FRACTIONS}
    cursor = {s: 0 for s in SPLIT_FRACTIONS}

    manifest_rows: list[dict] = []
    errors: list[str] = []
    split_sources: dict[str, set[str]] = {s: set() for s in SPLIT_FRACTIONS}
    sample_counts = {label: 0 for label in LABELS}
    quality: dict[str, list[tuple[float, float, float]]] = {a: [] for a in ("lsb", "dct", "dwt")}
    variant_counts: dict[str, int] = {}

    work = [(src, args.seed, with_processed) for src in sources if tiles_per_source[src.index] > 0]
    with mp.Pool(args.workers) as pool:
        for done, result in enumerate(pool.imap(process_source, work, chunksize=4), start=1):
            if result is None:
                continue
            src: Source = result["source"]
            if "error" in result:
                errors.append(f"{Path(src.path).name}: {result['error']}")
                continue
            split = src.split
            split_sources[split].add(f"{src.dataset}:{Path(src.path).stem}")
            for entry in result["carriers"]:
                for algorithm in ("lsb", "dct", "dwt"):
                    m = entry["meta"][algorithm]
                    quality[algorithm].append((m["psnr"], m["ssim"], m["utilisation"]))
                family = entry["variant"].split(":")[0]
                variant_counts[entry["variant"]] = variant_counts.get(entry["variant"], 0) + 1
                for tile_idx, tile in enumerate(entry["tiles"]):
                    for label_id, label in enumerate(LABELS):
                        row = cursor[split]
                        if row >= capacity[split]:
                            raise RuntimeError("pre-pass under-estimated split size")
                        xs[split][row] = tile[label]
                        ys[split][row] = label_id
                        cursor[split] += 1
                        m = entry["meta"][label]
                        manifest_rows.append(
                            {
                                "split": split, "row": row, "label": label, "label_id": label_id,
                                "source_dataset": src.dataset, "source_id": Path(src.path).stem,
                                "variant": entry["variant"], "tile": tile_idx,
                                "carrier_size": entry["carrier"].shape[0],
                                "utilisation": round(m["utilisation"], 5), "payload_bytes": m["payload_bytes"],
                                "envelope_bytes": m["envelope_bytes"],
                                "carrier_psnr": None if m["psnr"] is None else round(m["psnr"], 4),
                                "carrier_ssim": round(m["ssim"], 6),
                            }
                        )
                        if split == "test" and entry["primary"] and sample_counts[label] < args.samples_per_class and tile_idx == 0:
                            Image.fromarray(tile[label]).save(out / "samples" / f"{label}_{src.dataset}_{Path(src.path).stem}.png")
                            sample_counts[label] += 1
                if split == "test" and family != "processed":
                    Image.fromarray(entry["carrier"]).save(out / "test_carriers" / f"{src.dataset}_{Path(src.path).stem}.png")
            if done % 250 == 0:
                rate = done / (time.time() - started)
                print(f"  {done}/{len(work)} sources ({rate:.1f}/s) {dict(cursor)}", flush=True)

    # Finalise: truncate unused rows (skipped/corrupt sources) and persist labels.
    for split in SPLIT_FRACTIONS:
        n = cursor[split]
        xs[split].flush()
        if n < capacity[split]:
            src_arr = np.load(out / "arrays" / f"{split}_x.npy", mmap_mode="r")
            final = np.lib.format.open_memmap(out / "arrays" / f"{split}_x.tmp.npy", mode="w+", dtype=np.uint8, shape=(n, TILE, TILE, 3))
            for start in range(0, n, 2048):
                final[start : start + 2048] = src_arr[start : min(n, start + 2048)]
            final.flush()
            del final, src_arr
            del xs[split]
            os.replace(out / "arrays" / f"{split}_x.tmp.npy", out / "arrays" / f"{split}_x.npy")
        np.save(out / "arrays" / f"{split}_y.npy", ys[split][:n])

    # Leakage check: a source may appear in exactly one split.
    overlaps = {
        f"{a}&{b}": len(split_sources[a] & split_sources[b])
        for i, a in enumerate(SPLIT_FRACTIONS) for b in list(SPLIT_FRACTIONS)[i + 1 :]
    }
    assert all(v == 0 for v in overlaps.values()), f"source leakage detected: {overlaps}"

    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    def summary(values: list[float]) -> dict[str, float]:
        arr = np.array(values, dtype=np.float64)
        return {"mean": float(arr.mean()), "std": float(arr.std()), "min": float(arr.min()), "max": float(arr.max())}

    stats = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "tile": TILE,
        "labels": list(LABELS),
        "split_fractions": SPLIT_FRACTIONS,
        "utilisation_range": UTIL_RANGE,
        "sources": {s: len(v) for s, v in split_sources.items()},
        "source_datasets": {
            ds: sum(1 for s in sources if s.dataset == ds and tiles_per_source[s.index] > 0) for ds in ("div2k", "coco")
        },
        "images": {s: int(cursor[s]) for s in SPLIT_FRACTIONS},
        "images_per_class": {
            s: {label: int(np.sum(ys[s][: cursor[s]] == i)) for i, label in enumerate(LABELS)} for s in SPLIT_FRACTIONS
        },
        "leakage_check": {"source_overlap": overlaps, "passed": True},
        "embedding_quality": {
            a: {"psnr": summary([q[0] for q in v]), "ssim": summary([q[1] for q in v]), "utilisation": summary([q[2] for q in v])}
            for a, v in quality.items() if v
        },
        "algorithms": {a: engine.get_algorithm(a).describe() for a in ("lsb", "dct", "dwt")},
        "processed_covers": with_processed,
        "processing_ops": list(PROCESSING) if with_processed else [],
        "carrier_variants": variant_counts,
        "skipped_sources": len(errors),
        "skipped_examples": errors[:20],
        "duration_s": round(time.time() - started, 1),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("sources", "images", "leakage_check", "skipped_sources", "duration_s")}, indent=2))


if __name__ == "__main__":
    main()
