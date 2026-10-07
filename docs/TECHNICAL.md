# StegoLab — Technical documentation

This document explains *how* every subsystem works and *where* each number shown in the
UI comes from. Code references are relative to `backend/`.

---

## 1. Cryptography

### 1.1 AES-256-GCM (`app/services/crypto.py`)

* **Cipher.** AES with a 256-bit key in Galois/Counter Mode — an AEAD construction that
  provides confidentiality *and* integrity/authenticity of the ciphertext and of any
  associated data. The implementation is OpenSSL via the `cryptography` package; no
  primitive is implemented by hand.
* **Nonce.** 96 bits from `secrets.token_bytes` (OS CSPRNG), fresh for every encryption.
  GCM security collapses on nonce reuse under one key; random 96-bit nonces combined with
  fresh per-message salts (passphrase mode) make reuse negligible.
* **Tag.** 128-bit authentication tag appended to the ciphertext. Any modified bit of
  ciphertext, tag, nonce, salt or KDF parameters makes decryption fail (`InvalidTag`),
  which the API reports as *"wrong key/passphrase or the payload was modified"* — GCM
  cannot (and should not) distinguish the two.
* **Associated data.** The 39-byte envelope header (magic, KDF id and parameters, salt,
  nonce) is passed as AAD, so an attacker cannot downgrade the KDF parameters or swap salts.

Envelope layout (big-endian):

| offset | size | field |
|---|---|---|
| 0 | 4 | magic `SLE1` |
| 4 | 1 | KDF id (0 = raw key, 1 = Argon2id) |
| 5 | 1 | Argon2 time cost |
| 6 | 4 | Argon2 memory cost (KiB) |
| 10 | 1 | Argon2 parallelism |
| 11 | 16 | salt |
| 27 | 12 | nonce |
| 39 | n+16 | ciphertext ‖ tag |

Plaintext (inside the ciphertext): `kind | flags | name_len | filename | SHA-256(content) | content`.
Content is zlib-compressed only when that makes it smaller (flag bit 0).

### 1.2 Key derivation

* **Passphrase mode — Argon2id** (`argon2.low_level.hash_secret_raw`, type ID): 64 MiB
  memory, 3 passes, 4 lanes, 128-bit random salt, 256-bit output. Argon2id won the
  Password Hashing Competition and resists GPU/ASIC cracking through memory hardness.
  The parameters travel in the (authenticated) header so they can be raised later
  without breaking old payloads; on decryption, out-of-range parameters from an
  untrusted header are refused (DoS guard).
* **Generated-key mode.** 32 bytes from the CSPRNG, shown once as `slk1_<base64url>`.
  Never stored or logged.
* **Account passwords** use Argon2id too (`app/core/security.py`, `argon2.PasswordHasher`,
  t=3, m=64 MiB, p=4), with transparent re-hashing when parameters change.

### 1.3 SHA-256 — two integrity layers

1. **Inner digest** — SHA-256 of the original content is sealed *inside* the ciphertext and
   re-checked after decryption. Placing it inside avoids leaking a plaintext hash that would
   let an observer confirm a guessed message.
2. **Frame digest** — the embedded bitstream carries `SHA-256(envelope)`. This lets the
   extractor (and the Attack Lab) report *Integrity VERIFIED/FAILED* **without the key**.

SHA-256 also fingerprints every uploaded image, stego output, PDF report and model weight
file. MD5 is not used anywhere.

---

## 2. Bitstream framing (`app/services/stego/framing.py`)

```
frame = HEADER(24 B) || BODY
HEADER = RS(8 data + 16 parity) of  "SG" | version | algorithm id | ECC nsym | body length (uint24)
BODY   = [Reed-Solomon in 255-byte blocks with nsym parity]( envelope || SHA-256(envelope) )
```

* The header is always Reed-Solomon protected (corrects up to 8 byte errors), so the
  format is detectable even after mild damage. A random image decodes to a valid header
  with probability ≈ 4·10⁻¹⁴, which is how extraction **auto-detects** LSB/DCT/DWT.
* DCT and DWT use 32 parity symbols per 255-byte block (corrects 16 byte errors/block);
  LSB uses none (it is exact on lossless storage and hopeless under re-compression anyway).
* **Slot ordering.** Frame bit *i* goes to carrier slot `(a·i + b) mod n`, with `a` coprime to
  `n` and close to `n/φ` (Weyl / Fibonacci hashing). It is a bijection that disperses the
  payload uniformly over the image. It is public and provides dispersion only; secrecy comes
  from AES-GCM.
* Capacity is computed exactly (`max_envelope_len`), and embedding is verified by
  re-extracting from the rendered 8-bit image before the stego file is released.

---

## 3. Steganography algorithms

### 3.1 LSB (`stego/lsb.py`)

Each R, G, B value carries one bit: `v ← (v & 0xFE) | bit`. Capacity `H·W·3` bits; every value
changes by at most ±1 (PSNR ≥ 48.1 dB at 100 % utilisation). Fragile by design: any lossy
operation randomises the LSB plane.

### 3.2 DCT-domain QIM (`stego/dct.py`)

1. RGB → BT.601 luma Y (the JPEG definition).
2. 8×8 blocks on the JPEG grid; orthonormal 2-D DCT-II (`scipy.fft.dctn`).
3. One bit per coefficient at the mid-frequency positions **(1,2) (2,1) (2,2) (0,3) (3,0)** —
   5 bits per block (5/64 bpp). The set is symmetric under transposition, so the D4
   augmentations used in training preserve the class signal.
4. **Quantisation Index Modulation** with step Δ = 24: bit 0 → nearest multiple of Δ, bit 1 →
   nearest odd multiple of Δ/2. Decoding: `round(c / (Δ/2)) mod 2`. Any perturbation below Δ/4
   cannot flip a bit.
5. ΔY is added equally to R, G, B (Cb/Cr unchanged), then rounded and clipped.

### 3.3 DWT-domain QIM (`stego/dwt.py`)

Three-level 2-D Haar decomposition of luma (`pywt.wavedec2`); one bit per coefficient of the
coarsest horizontal and vertical detail subbands (LH3/HL3) by QIM with Δ = 40; inverse
transform with `pywt.waverec2`. Capacity 2/64 bpp. Coarse (8-pixel-scale) structure survives
compression better than fine detail.

### 3.4 Rounding/clipping correction

Writing transform-domain changes back to 8-bit pixels perturbs the coefficients (rounding)
and can truncate them entirely in saturated regions (clipping). After rendering, the encoder
re-measures every used coefficient and **re-pushes any slot that decodes wrongly or sits
farther than 0.15·Δ from its lattice point** (up to 8 rounds). The margin requirement matters:
before it was added, DCT payloads survived JPEG Q90 on 7/10 images; afterwards 16/16 at Q85.

### 3.5 Parameter selection

Δ values were chosen by a measured sweep on DIV2K/COCO crops — see
[`experiments/qim_parameter_sweep.md`](experiments/qim_parameter_sweep.md). DCT Δ=24 and
DWT level-3 Δ=40 give matched visual quality (~43.5–44 dB), so the two transform methods are
compared at equal distortion.

---

## 4. Image quality metrics (`app/services/metrics.py`)

* **MSE** — mean squared error over all pixels and channels.
* **PSNR** — `10·log10(255² / MSE)`; reported as ∞ for identical images.
* **SSIM** — Wang et al. 2004 with an 11×11 Gaussian window (σ = 1.5), K1 = 0.01, K2 = 0.03,
  averaged over channels. Verified in the test suite to match
  `skimage.metrics.structural_similarity` within 10⁻⁶.

---

## 5. Dataset (`pipeline/generate_dataset.py`)

| Item | Value |
|---|---|
| Sources | DIV2K train (800 lossless PNG) + COCO val2017 (5,000 JPEG) |
| Carriers | DIV2K: one 512×512 native crop (→ four 256 tiles); COCO even ids: downscaled by a non-integer factor (erases the JPEG grid); COCO odd ids: native crop on the JPEG grid (hard negatives) |
| Processed covers (v2) | one extra 256×256 carrier per source, processed **before** embedding by one of: Gaussian noise (σ 0.5–3), JPEG (Q 40–95), Gaussian blur (σ 0.4–1), down/up resampling (×0.5–0.9), JPEG + noise. All four classes share the processing, so the model must separate stego noise from ordinary processing |
| Classes | normal, LSB, DCT, DWT — every tile appears in all four versions |
| Payload | real AES-256-GCM envelopes of random content; utilisation U[0.10, 1.00] of capacity |
| Split | **70 / 15 / 15 by source image**, stratified per source dataset, seeded |
| Leakage control | all tiles and all classes of a source stay in one split; the script asserts the source-id sets are disjoint |

Embedding happens on the whole carrier before tiling, so each 256 tile sees the same
per-slot modification density the application produces on full-size images.

**Why processed covers exist (cover-source mismatch).** Model v1.0.0 was trained on clean
covers only. A dedicated false-positive study (`pipeline/detector_robustness.py`,
[`experiments/detector_false_positives_v1.0.0.json`](experiments/detector_false_positives_v1.0.0.json))
showed it flagged **99 %** of clean test covers after Gaussian noise σ = 2 (as LSB) and
**90 %** after JPEG Q50 (as DCT) — ordinary photos would raise alarms. Dataset v2 adds the
processed variants and v1.1.0 is trained on it; both versions are compared in
[`experiments/model_comparison.md`](experiments/model_comparison.md).
`data/dataset/stats.json` and `manifest.csv` describe every row.

---

## 6. Models

### 6.1 Handcrafted features + Random Forest (`app/ml/features.py`)

99 features in six groups: LSB statistics (Westfeld–Pfitzmann χ² p-value, pair-of-values
asymmetry, Sample Pairs Analysis estimate, LSB-plane correlation — per channel), noise-residual
moments, first-order SPAM transition matrix (T = 2), block-DCT band magnitudes and **histogram
periodicity** per low/mid frequency (detects quantisation lattices from JPEG or QIM), Haar
subband statistics and periodicity, and global statistics. A 400-tree Random Forest is trained
on the training split.

**Anomaly model.** Mahalanobis distance of an image's features to the clean-cover training
distribution (Ledoit–Wolf shrinkage covariance), converted to a percentile against held-out
*validation* covers. 0.95 means "more anomalous than 95 % of clean validation images".

### 6.2 StegoNet CNN (`app/ml/cnn.py`)

Stego signals are 1–3 grey levels under content of ±100, so the network starts with three
**fixed** front-ends — one per embedding domain — and learns everything after them:

| Branch | Fixed front-end | Learned part |
|---|---|---|
| Spatial residuals | 10 SRM high-pass kernels × RGB, truncated ±3 (TLU) | 5 conv-BN-ReLU blocks with average pooling → 16×16 map |
| Block-DCT | 63 orthonormal 8×8 AC DCT bases at stride 8 (= JPEG-grid block coefficients) | 1×1 projection (initialised to select 14 low/mid frequencies) → **soft-histogram** layer (Gaussian bins, learnable centres/widths) → convs → 32×32 map |
| Wavelet | Haar level-2 and level-3 detail kernels (verified equal to `pywt`) | soft histograms → convs → 32×32 map |

**Weighted-Stego residual channels (v1.2.0+).** Linear high-pass filters cannot see *parity*, so
a CNN with only SRM inputs confuses symmetric noise (sensor noise, re-noised photos) with LSB
replacement — v1.1.0 still flagged 69–94 % of noise-processed clean covers. LSB replacement is
asymmetric (even values only move up, odd values only down), which the Weighted-Stego statistic of
Fridrich & Goljan (2004) captures: `ws = (x − x̄)·(x − F(x))` with `x̄ = x XOR 1` and `F` the KB pixel
predictor. Its mean is ≈ 0 for any parity-symmetric process and grows with the LSB-replacement rate
(measured on held-out covers: +0.01…+0.04 for Gaussian noise σ = 1–3, +0.20 for 50 % LSB, +0.20 for
50 % LSB on a noisy cover). Three WS maps (one per channel, truncated to ±8 and rescaled to the SRM
range) are concatenated with the SRM residuals. The option is stored in the model config, so earlier
checkpoints still load unchanged.

Global average pooling of each branch → concatenation → MLP → 4-way softmax. 646,848 trainable
parameters (647,712 with WS channels). Pooled soft-histogram activations *are* coefficient histograms, so a
quantisation lattice is directly representable — which is exactly the trace QIM leaves.

**Training** (`pipeline/train_model.py`): batches of 8 tiles × 4 versions (cover/stego pairs in
the same batch), D4 dihedral augmentation applied identically to each group, AdamW
(lr 2·10⁻³, wd 10⁻⁴), one-epoch warm-up + cosine decay, label smoothing 0.05, bf16 autocast
on CUDA (fixed front-ends stay float32), gradient clipping, checkpoint on best validation
macro-F1, early stopping (patience 8). Data is streamed from memory-mapped arrays by a
background-thread prefetcher.

### 6.3 Inference (`app/ml/inference.py`)

Images are **never resized** (resampling destroys stego noise). They are cut into 256×256
tiles on the 8-pixel grid (aligned with the DCT/DWT grids); softmax outputs are averaged over
tiles (≤ 64 tiles; larger images are sampled uniformly). The decision rule is the arg-max class
— the same rule used for the reported test metrics. The model version is stored with every
analysis.

### 6.4 Explainability — Grad-CAM

Grad-CAM (Selvaraju et al. 2017) is computed on each branch head for the most likely *stego*
class, up-sampled, summed and stitched over tiles. The UI also reports each branch's share of
the evidence (spatial vs DCT vs wavelet). The heat-map shows **where the network found
evidence**; the model was not trained for localisation and does not claim to mark the exact
pixels carrying bits.

---

## 7. Evaluation (`app/ml/evaluation.py`, `pipeline/evaluate_model.py`)

All metrics are computed from predictions on the **test split** (never used for training or
checkpoint selection): accuracy, macro and per-class precision/recall/F1, one-vs-rest ROC-AUC,
confusion matrix, sklearn classification report, ROC curves, binary cover-vs-stego metrics
(detection rate, false-positive rate) using P(stego) = 1 − P(normal), detection broken down by
payload utilisation, and false-positive rate per cover-source variant. Results are written to
`backend/models/<model>/<version>/metrics.json`, registered in the database on API start-up,
and served by `/api/models/{id}/metrics`. `evaluate_model.py` re-computes them from the saved
weights at any time.

---

## 8. Risk score (`app/services/risk.py`)

```
evidence = Σ wᵢ·xᵢ / Σ wᵢ   (over available components)
  x_cnn     = 1 − P_cnn(normal)            w = 0.55
  x_rf      = 1 − P_rf(normal)             w = 0.25
  x_anomaly = anomaly percentile           w = 0.20
floor     = 0.97 if a StegoLab frame verifies, 0.85 if its header is present but the digest fails
risk      = 100 · max(evidence, floor)
level     = LOW < 35 ≤ MEDIUM < 65 ≤ HIGH < 85 ≤ CRITICAL   (thresholds admin-configurable)
```

Every factor, weight and contribution is returned by the API and shown in the UI and PDF.

---

## 9. Attack simulation (`app/services/attacks.py`)

JPEG (quality), Gaussian noise (σ), salt & pepper (fraction), Gaussian blur (kernel), median
filter, resize (scale, optionally restored to the original size), crop (top-left ratio),
brightness, contrast and rotation. For each attack the service re-runs the CNN, re-extracts
the frame (integrity + optional decryption), computes the frame **bit-error rate** when the
geometry is preserved, and MSE/PSNR/SSIM against the pre-attack image (or the matching region
for crops). Single attacks and batches are stored in `attack_experiments`.

---

## 10. Research comparison (`app/services/experiments.py`)

On held-out test carriers, for each technique: capacity (bytes, bpp), MSE/PSNR/SSIM at the
configured payload, extraction success, AI detection rate and technique identification,
robustness over an attack suite, and embed/extract time. The **balance score** averages four
0–1 criteria (configurable weights):

| Criterion | Mapping |
|---|---|
| capacity | log10(bpp), min-max across the techniques (capacities differ by orders of magnitude) |
| quality | clip((PSNR − 35 dB) / 20 dB, 0, 1) — fixed reference range |
| robustness | extraction survival rate over the attack suite (absolute) |
| undetectability | 1 − AI detection rate (absolute) |

Absolute scales are used wherever one exists so that small differences (e.g. 99.4 % vs 100 %
detection) are not stretched into a full 0–1 gap — an early version used pure min-max scaling
and over-rewarded LSB for exactly that reason. The per-criterion winners are reported with the
score because a single number hides trade-offs. `pipeline/run_experiments.py` runs the same
code over the whole test split.
