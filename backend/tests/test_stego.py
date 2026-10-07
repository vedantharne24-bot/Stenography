from __future__ import annotations

import io
import os

import numpy as np
import pytest
from PIL import Image
from skimage import data as skdata

from app.core.errors import InsufficientCapacity
from app.services import crypto, metrics
from app.services.stego import engine, framing

KEY = bytes(range(32))


@pytest.fixture(scope="module")
def astronaut() -> np.ndarray:
    return skdata.astronaut()  # 512x512 RGB natural photo


@pytest.fixture(scope="module")
def coffee() -> np.ndarray:
    return skdata.coffee()  # 400x600 RGB


def _envelope(n_bytes: int) -> bytes:
    return crypto.encrypt_payload(os.urandom(n_bytes), crypto.Secret(raw_key=KEY)).envelope


def _jpeg(rgb: np.ndarray, quality: int) -> np.ndarray:
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG", quality=quality)
    return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))


# --------------------------------------------------------------------------- framing


def test_slot_ordering_is_a_permutation():
    for n in (97, 1000, 196_608):
        idx = framing.slot_indices(n, 0, n)
        assert np.array_equal(np.sort(idx), np.arange(n))


def test_capacity_math_is_tight():
    for slots in (2_000, 40_960, 786_432):
        for nsym in (0, 32):
            max_env = framing.max_envelope_len(slots, nsym)
            assert framing.frame_bits_for_envelope(max_env, nsym) <= slots
            assert framing.frame_bits_for_envelope(max_env + 1, nsym) > slots


def test_header_reed_solomon_corrects_byte_errors():
    frame = framing.build_frame(b"E" * 100, algorithm_id=2, nsym=32)
    bits = frame.bits.copy()
    for byte in (0, 5, 9, 13, 17, 21, 22, 23):  # 8 corrupted header bytes = RS limit
        bits[byte * 8] ^= 1
    header = framing.parse_header(bits)
    assert header is not None and header.algorithm_id == 2 and header.corrected == 8


def test_body_digest_detects_corruption_without_ecc():
    frame = framing.build_frame(b"payload-bytes" * 10, algorithm_id=1, nsym=0)
    bits = frame.bits.copy()
    bits[framing.HEADER_BITS + 40] ^= 1
    header = framing.parse_header(bits)
    assert header is not None
    body = framing.parse_body(bits[framing.HEADER_BITS :], header)
    assert body.integrity == "failed" and body.envelope is None


# --------------------------------------------------------------------------- algorithms


@pytest.mark.parametrize("algorithm", ["lsb", "dct", "dwt"])
def test_roundtrip_with_auto_detection(astronaut, algorithm):
    cap = engine.capacity(algorithm, astronaut.shape)
    secret = crypto.Secret(raw_key=KEY)
    message = os.urandom(int(cap.max_payload_bytes * 0.5))
    sealed = crypto.encrypt_payload(message, secret)
    out = engine.embed(astronaut, sealed.envelope, algorithm)
    assert out.stego.dtype == np.uint8 and out.stego.shape == astronaut.shape

    found = engine.extract(out.stego)  # no algorithm hint
    assert found.algorithm == algorithm
    assert found.integrity == "verified"
    assert found.envelope == sealed.envelope
    assert crypto.decrypt_envelope(found.envelope, secret).content == message
    assert engine.bit_error_rate(out.stego, out.stego, algorithm) == 0.0


@pytest.mark.parametrize("algorithm,min_psnr", [("lsb", 50.0), ("dct", 40.0), ("dwt", 40.0)])
def test_visual_quality_bounds(astronaut, algorithm, min_psnr):
    cap = engine.capacity(algorithm, astronaut.shape)
    out = engine.embed(astronaut, _envelope(int(cap.max_payload_bytes * 0.5)), algorithm)
    quality = metrics.quality_report(astronaut, out.stego)
    assert quality["psnr"] is not None and quality["psnr"] > min_psnr
    assert quality["ssim"] > 0.95


def test_lsb_changes_each_value_by_at_most_one(coffee):
    out = engine.embed(coffee, _envelope(5_000), "lsb")
    diff = np.abs(out.stego.astype(int) - coffee.astype(int))
    assert diff.max() <= 1


def test_odd_dimensions_are_supported():
    rng = np.random.default_rng(0)
    base = np.cumsum(rng.normal(0, 3, size=(301, 457, 3)), axis=1)
    img = np.clip(base - base.min() + 30, 0, 225).astype(np.uint8)
    for algorithm in ("lsb", "dct", "dwt"):
        out = engine.embed(img, _envelope(200), algorithm)
        assert engine.extract(out.stego, algorithm).integrity == "verified"


def test_capacity_exceeded_raises(astronaut):
    cap = engine.capacity("dwt", astronaut.shape)
    with pytest.raises(InsufficientCapacity):
        engine.embed(astronaut, _envelope(cap.max_envelope_bytes + 500), "dwt")


def test_clean_cover_has_no_frame(astronaut):
    result = engine.extract(astronaut)
    assert result.integrity == "not_found" and result.tried == ["lsb", "dct", "dwt"]


def test_jpeg_robustness_ordering(astronaut):
    """LSB is fragile; the transform-domain methods survive moderate JPEG compression."""
    outcomes = {}
    for algorithm in ("lsb", "dct", "dwt"):
        out = engine.embed(astronaut, _envelope(300), algorithm)
        outcomes[algorithm] = engine.extract(_jpeg(out.stego, 90), algorithm).integrity
    assert outcomes["lsb"] != "verified"
    assert outcomes["dct"] == "verified"
    assert outcomes["dwt"] == "verified"


# --------------------------------------------------------------------------- metrics


def test_metrics_against_reference_implementation(astronaut):
    from skimage.metrics import structural_similarity

    rng = np.random.default_rng(1)
    noisy = np.clip(astronaut.astype(int) + rng.integers(-6, 7, astronaut.shape), 0, 255).astype(np.uint8)
    ours = metrics.ssim(astronaut, noisy)
    reference = structural_similarity(
        astronaut, noisy, channel_axis=-1, data_range=255, gaussian_weights=True, sigma=1.5, use_sample_covariance=False
    )
    assert abs(ours - reference) < 1e-6
    assert metrics.mse(astronaut, astronaut) == 0.0
    assert metrics.psnr(astronaut, astronaut) == float("inf")
    expected_mse = np.mean((astronaut.astype(float) - noisy.astype(float)) ** 2)
    assert metrics.mse(astronaut, noisy) == pytest.approx(expected_mse)
    assert metrics.psnr(astronaut, noisy) == pytest.approx(10 * np.log10(255**2 / expected_mse))
