"""Upload validation and image encoding.

Validation pipeline (each step raises a specific, user-facing error):
1. size limit while streaming the upload (never buffer more than the limit)
2. extension allow-list
3. magic-byte sniffing - content must match the extension family
4. declared MIME type must agree with the sniffed type (if provided)
5. decompression-bomb guard (``Image.MAX_IMAGE_PIXELS``) + dimension bounds
6. ``Image.verify()`` for structural corruption, then a full decode (truncation)
7. colour-mode normalisation to 8-bit RGB (+ optional alpha kept aside)
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from fastapi import UploadFile
from PIL import ExifTags, Image, ImageCms, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import CorruptedFile, PayloadTooLarge, UnsupportedImage, ValidationFailed

ALLOWED_EXTENSIONS = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "bmp": "bmp", "webp": "webp", "tif": "tiff", "tiff": "tiff"}
MIME_FOR = {"png": "image/png", "jpeg": "image/jpeg", "bmp": "image/bmp", "webp": "image/webp", "tiff": "image/tiff"}
PIL_FORMAT = {"PNG": "png", "JPEG": "jpeg", "BMP": "bmp", "WEBP": "webp", "TIFF": "tiff", "MPO": "jpeg"}


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"BM"):
        return "bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


@dataclass
class LoadedImage:
    rgb: np.ndarray
    alpha: np.ndarray | None
    format: str
    original_mode: str
    width: int
    height: int
    file_size: int
    sha256: str
    filename: str
    icc_profile: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, ...]:
        return self.rgb.shape


async def read_upload(file: UploadFile, limit: int | None = None) -> bytes:
    limit = limit or get_settings().max_upload_size
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1 << 20)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise PayloadTooLarge(
                f"File exceeds the {limit // (1024 * 1024)} MB upload limit", details={"limit_bytes": limit}
            )
        chunks.append(chunk)
    if total == 0:
        raise ValidationFailed("Uploaded file is empty")
    return b"".join(chunks)


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _jpeg_quality_estimate(img: Image.Image) -> int | None:
    """Estimate libjpeg quality from the luminance quantisation table (forensic hint only)."""
    tables = getattr(img, "quantization", None)
    if not tables or 0 not in tables:
        return None
    std = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
           14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
           49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]  # fmt: skip
    table = list(tables[0])
    best, best_err = None, float("inf")
    for q in range(1, 101):
        scale = 5000 / q if q < 50 else 200 - 2 * q
        expected = [min(255, max(1, (s * scale + 50) // 100)) for s in std]
        err = sum(abs(a - b) for a, b in zip(sorted(table), sorted(expected)))
        if err < best_err:
            best, best_err = q, err
    return best


def _metadata(img: Image.Image, fmt: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"pil_format": img.format, "mode": img.mode, "dpi": None, "exif": {}, "text_chunks": []}
    if "dpi" in img.info:
        meta["dpi"] = [float(v) for v in img.info["dpi"]][:2]
    try:
        exif = img.getexif()
        interesting = {"Make", "Model", "Software", "DateTime", "Orientation", "Artist", "HostComputer"}
        for tag_id, value in exif.items():
            name = ExifTags.TAGS.get(tag_id, str(tag_id))
            if name in interesting:
                meta["exif"][name] = str(value)[:120]
        meta["exif_tag_count"] = len(exif)
    except Exception:  # noqa: BLE001 - malformed EXIF is itself a forensic note
        meta["exif_error"] = "EXIF block could not be parsed"
    if fmt == "png":
        meta["text_chunks"] = [k for k in img.info if isinstance(k, str) and k not in {"dpi", "icc_profile", "gamma"}][:20]
    if fmt == "jpeg":
        meta["jpeg_quality_estimate"] = _jpeg_quality_estimate(img)
        meta["progressive"] = bool(img.info.get("progressive") or img.info.get("progression"))
    icc = img.info.get("icc_profile")
    if icc:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            meta["icc_profile"] = ImageCms.getProfileDescription(profile).strip()[:80]
        except Exception:  # noqa: BLE001
            meta["icc_profile"] = "present (unparsed)"
    return meta


def load_image(data: bytes, filename: str, declared_mime: str | None = None) -> LoadedImage:
    settings = get_settings()
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedImage(
            f"Unsupported file extension '.{ext}'. Allowed: PNG, JPEG, BMP, WEBP, TIFF",
            details={"allowed": sorted(ALLOWED_EXTENSIONS)},
        )
    sniffed = sniff(data)
    if sniffed is None:
        raise UnsupportedImage("File content is not a recognised image format")
    if sniffed != ALLOWED_EXTENSIONS[ext]:
        raise UnsupportedImage(
            f"File extension '.{ext}' does not match its content ({sniffed.upper()})",
            details={"extension": ext, "content": sniffed},
        )
    if declared_mime and declared_mime not in ("application/octet-stream", MIME_FOR[sniffed]):
        if not (sniffed == "jpeg" and declared_mime == "image/jpg"):
            raise UnsupportedImage(f"Declared type {declared_mime} does not match content {MIME_FOR[sniffed]}")

    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            width, height = probe.size
            if getattr(probe, "n_frames", 1) > 1 and sniffed != "tiff":
                raise UnsupportedImage("Animated / multi-frame images are not supported")
            probe.verify()
            img = Image.open(io.BytesIO(data))
            img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise UnsupportedImage(
            f"Image exceeds the {settings.max_image_pixels:,}-pixel safety limit", details={"reason": "decompression_bomb"}
        ) from exc
    except UnidentifiedImageError as exc:
        raise CorruptedFile("Image could not be decoded (corrupted or unsupported encoding)") from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise CorruptedFile(f"Image is corrupted or truncated: {str(exc)[:120]}") from exc

    lo, hi = settings.min_image_dimension, settings.max_image_dimension
    if min(width, height) < lo or max(width, height) > hi:
        raise ValidationFailed(
            f"Image dimensions {width}×{height} are outside the supported range {lo}–{hi} px",
            details={"width": width, "height": height},
        )

    notes: list[str] = []
    mode = img.mode
    alpha: np.ndarray | None = None
    if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        alpha = np.asarray(rgba)[..., 3].copy()
        rgb_img = rgba.convert("RGB")
        notes.append("Alpha channel preserved separately; payload is carried in RGB only")
    elif mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        arr = np.asarray(img, dtype=np.float64)
        arr = (arr - arr.min()) / max(1e-9, arr.max() - arr.min()) * 255.0
        rgb_img = Image.fromarray(arr.astype(np.uint8)).convert("RGB")
        notes.append(f"High bit-depth image ({mode}) normalised to 8-bit")
    else:
        if mode not in ("RGB",):
            notes.append(f"Converted from {mode} to RGB")
        rgb_img = img.convert("RGB")

    return LoadedImage(
        rgb=np.asarray(rgb_img, dtype=np.uint8).copy(),
        alpha=alpha,
        format=sniffed,
        original_mode=mode,
        width=width,
        height=height,
        file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        filename=filename[:255],
        icc_profile=img.info.get("icc_profile"),
        metadata=_metadata(img, sniffed),
        warnings=notes,
    )


def encode_png(rgb: np.ndarray, alpha: np.ndarray | None = None, icc_profile: bytes | None = None) -> bytes:
    """Lossless PNG; only the ICC profile is carried over (other metadata is dropped for privacy)."""
    if alpha is not None:
        img = Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), mode="RGBA")
    else:
        img = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
    buf = io.BytesIO()
    kwargs: dict[str, Any] = {"format": "PNG", "optimize": False, "compress_level": 6}
    if icc_profile:
        kwargs["icc_profile"] = icc_profile
    img.save(buf, **kwargs)
    return buf.getvalue()


def encode_preview(rgb: np.ndarray, max_side: int = 1600) -> bytes:
    """Downscaled lossless PNG for UI display of large images (never used for analysis)."""
    img = Image.fromarray(rgb.astype(np.uint8))
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def decode_png_bytes(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint8)
