# QIM parameter sweep (DCT / DWT)

Measured during development on 16 random 512×512 centre crops (8 DIV2K, 8 COCO val2017),
payload = 60 % of capacity (random bytes inside a real AES-256-GCM envelope), JPEG via Pillow
(default 4:2:0 subsampling). "Survive" = full frame recovered with SHA-256 verified after
decompression. BER = fraction of frame bits flipped (median / max over images).
Margin-aware correction loop enabled (re-push slots farther than 0.15·Δ from their lattice point).

## DCT (8×8 luma blocks, coefficients (1,2) (2,1) (2,2) (0,3) (3,0))

| Δ  | PSNR (dB) | SSIM   | Q95   | Q90   | Q85   | Q80   | Q75   | Q70   |
|----|-----------|--------|-------|-------|-------|-------|-------|-------|
| 20 | 45.44     | 0.9811 | 16/16 | 13/16 | 13/16 | 8/16  | 4/16  | 5/16  |
| **24** | **43.91** | **0.9741** | 16/16 | 16/16 | 16/16 | 9/16 | 5/16 | 5/16 |
| 28 | 42.59     | 0.9660 | 16/16 | 16/16 | 16/16 | 15/16 | 9/16  | 8/16  |

## DWT (Haar, coarsest LH/HL subbands)

| Level | Δ  | PSNR (dB) | SSIM   | Q95   | Q90   | Q85   | Q80   | Q75   | Q70   |
|-------|----|-----------|--------|-------|-------|-------|-------|-------|-------|
| 2     | 24 | 41.90     | 0.9612 | 16/16 | 11/16 | 0/16  | 0/16  | 0/16  | 0/16  |
| 2     | 28 | 40.75     | 0.9516 | 16/16 | 13/16 | 2/16  | 0/16  | 0/16  | 0/16  |
| 3     | 24 | 48.04     | 0.9903 | 14/16 | 13/16 | 1/16  | 0/16  | 0/16  | 0/16  |
| 3     | 32 | 45.10     | 0.9824 | 16/16 | 16/16 | 16/16 | 11/16 | 3/16  | 1/16  |
| **3** | **40** | **43.43** | **0.9753** | 16/16 | 16/16 | 16/16 | 16/16 | 14/16 | 10/16 |

## Selection

* **DCT Δ = 24** – survives JPEG ≥ Q85 on every test image at 43.9 dB.
* **DWT level 3, Δ = 40** – chosen to match DCT's visual quality (≈43.5 dB) so the two
  transform methods are compared at equal distortion; it trades capacity (2/64 bpp vs 5/64 bpp)
  for robustness (survives ≥ Q80).
* Level-2 DWT was rejected: at any Δ giving acceptable robustness its PSNR fell below 42 dB.

Before the margin-aware correction loop was added, DCT Δ = 24 survived Q90 on only 7/10 images;
failures were concentrated in images with clipped (0/255) pixels, where a coefficient decoded
correctly but sat on the decision boundary.
