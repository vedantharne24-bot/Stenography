# Experiments

Every file here is produced by a script in `backend/pipeline/` from real data; nothing is edited by hand.

| File | Produced by | What it answers |
|---|---|---|
| [`qim_parameter_sweep.md`](qim_parameter_sweep.md) | development sweep (recorded during parameter selection) | Which QIM step Δ / DWT level gives the best quality-vs-JPEG-robustness trade-off |
| [`model_comparison.md`](model_comparison.md) / `.json` | `python -m pipeline.compare_models` | How every trained model version performs on the *same* current test split, on clean vs processed covers, and how often it false-alarms on benign processing |
| [`detector_false_positives_v1.0.0.json`](detector_false_positives_v1.0.0.json) | `python -m pipeline.detector_robustness` (writes `…_v<active version>.json`) | False-positive rate of the active model on clean held-out covers after JPEG, noise, blur and resizing — this snapshot is the study that exposed v1.0.0's cover-source mismatch; `model_comparison.md` repeats it for every version |
| `technique_comparison_relative_*.json` | `python -m pipeline.run_experiments` | LSB vs DCT vs DWT at a payload *relative* to each technique's capacity |
| `technique_comparison_absolute_*.json` | `python -m pipeline.run_experiments --payload-mode absolute` | LSB vs DCT vs DWT carrying the *same* message size — the fair test of detectability |

Methodology for each is documented in [`../TECHNICAL.md`](../TECHNICAL.md) (sections 5–10).

## How the model evolved (measured, not assumed)

1. **v1.0.0** — trained on clean covers only. 99.36 % accuracy on its clean test split, but the
   false-positive study showed it flagged 99 % of clean photos after mild Gaussian noise (as LSB)
   and 90 % after JPEG Q50 (as DCT): classic cover-source mismatch.
2. **Dataset v2** — added one processed carrier per source (noise, JPEG Q40–95, blur, resampling,
   JPEG+noise) *before* embedding, so every class shares the processing.
3. **v1.1.0** — same architecture on dataset v2: fixed the JPEG false alarms (90 % → 3 %) but not the
   noise ones (69–94 %). Diagnosis: linear high-pass inputs cannot see pixel parity, which is what
   separates LSB *replacement* from symmetric noise.
4. **v1.2.0** — adds Weighted-Stego residual channels (parity sign × prediction residual) to the
   spatial branch, learning rate 1e-3. On the same v2 test split (8,248 tiles): accuracy 94.6 % →
   **99.4 %**, false-positive rate 15.5 % → **1.1 %**, accuracy on processed covers 88.8 % → **99.5 %**.
   False alarms on noise-processed clean photos fell from 69–94 % to **2.3–4.7 %**, JPEG Q50 to 0.3 %.
   Low-payload LSB detection also improved (93.6 % → 96.5 % below 25 % utilisation).
   Full tables: [`model_comparison.md`](model_comparison.md).

Active models: StegoNet **v1.2.0** and Random Forest **v1.1.0** (activated from the Models page;
earlier versions stay registered for comparison and rollback).

## Research findings (LSB vs DCT vs DWT)

<!-- FINDINGS:START -->
### Same message for every technique — 64 bytes, 851 held-out images

| Metric | LSB | DCT | DWT |
|---|---|---|---|
| Payload embedded | 64 B | 64 B | 64 B |
| Capacity | 34825 B (2.984 bpp) | 636 B (0.051 bpp) | 172 B (0.011 bpp) |
| PSNR | 72.66 dB | 47.25 dB | 43.01 dB |
| SSIM | 1.0000 | 0.9919 | 0.9835 |
| Extraction success | 100.0% | 100.0% | 100.0% |
| AI detection (StegoNet) | 1.1% | 98.5% | 100.0% |
| Survival over attack suite | 4.0% | 60.2% | 77.2% |
| Embed / extract time | 0.3 / 0.2 ms | 11.6 / 2.2 ms | 14.0 / 2.8 ms |
| Balance score | 0.76 | 0.37 | 0.29 |

Cover false-positive rate on the same images: 0.82 %.

> On 851 held-out images (equal weights), LSB scores highest (0.76), then DCT (0.37) and DWT (0.29). Best capacity: LSB; best quality: LSB; most robust: DWT; hardest to detect: LSB (StegoNet detection ranged 1.1%–100.0%).

### Payload relative to each technique's capacity — 50 % of capacity, 851 held-out images

| Metric | LSB | DCT | DWT |
|---|---|---|---|
| Payload embedded | 17412 B | 318 B | 85 B |
| Capacity | 34825 B (2.984 bpp) | 636 B (0.051 bpp) | 172 B (0.011 bpp) |
| PSNR | 54.13 dB | 44.20 dB | 42.87 dB |
| SSIM | 0.9984 | 0.9843 | 0.9839 |
| Extraction success | 100.0% | 100.0% | 100.0% |
| AI detection (StegoNet) | 99.5% | 100.0% | 100.0% |
| Survival over attack suite | 1.5% | 58.5% | 77.2% |
| Embed / extract time | 2.6 / 1.0 ms | 14.5 / 3.4 ms | 14.2 / 2.8 ms |
| Balance score | 0.49 | 0.33 | 0.29 |

Cover false-positive rate on the same images: 0.82 %.

> On 851 held-out images (equal weights), LSB scores highest (0.49), then DCT (0.33) and DWT (0.29). Best capacity: LSB; best quality: LSB; most robust: DWT; hardest to detect: no meaningful difference (StegoNet detection ranged 99.5%–100.0%).
<!-- FINDINGS:END -->

## Interpretation — answering the research question

*Which technique gives the best balance between payload capacity, visual quality, robustness and AI detectability?*

**No technique dominates; the answer depends on the channel and the adversary.**

* **Capacity and quality** always favour **LSB** (≈ 3 bpp, ≥ 54 dB even at half capacity).
* **Robustness** always favours **DWT** (≈ 77 % survival over the attack suite), then DCT (≈ 59–60 %);
  LSB survives almost nothing lossy (1.5–4 %).
* **Detectability depends on payload *relative to capacity*.** Carrying the same 64-byte message,
  LSB used ≈ 0.2 % of its slots and StegoNet detected only 1.1 % of stego images, while the same
  message nearly filled DWT/DCT and was detected 98.5–100 % of the time. At 50 % of each technique's
  capacity, all three were detected ≥ 99.5 % — the difference is no longer meaningful.

Practical guidance derived from these measurements:

| Channel | Adversary | Choose |
|---|---|---|
| Lossless (PNG preserved) | AI steganalysis | **LSB** with a payload far below capacity |
| Lossy (re-compression, resizing) | integrity matters more than secrecy of the channel | **DWT** (accept that it will be detected) |
| JPEG-style re-encoding ≥ Q85 | moderate | **DCT** — the JPEG-native compromise |

Caveat: detectability is measured against StegoNet, a detector *trained on these exact embedders*
(targeted steganalysis — the worst case for the hider). An adversary without such a model would
detect less; one with a better model, more.
