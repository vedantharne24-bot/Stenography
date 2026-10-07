"""Bitstream framing shared by every embedding algorithm.

Frame = HEADER || BODY

HEADER - 8 data bytes protected by Reed-Solomon (16 parity symbols -> 24 bytes)::

    b"SG" | version(1) | algorithm id(1) | ECC parity symbols per block(1) | body length(3, uint24)

BODY - ``envelope || SHA-256(envelope)``, optionally Reed-Solomon encoded in
255-byte blocks with ``nsym`` parity symbols each.

The SHA-256 digest lets the extractor verify the integrity of the recovered
ciphertext *without* the decryption key (used by the Attack Lab); the AES-GCM
tag and the inner content hash then authenticate the plaintext.

Slot ordering: bit *i* of the frame is written to carrier slot
``(a*i + b) mod n`` where ``a`` is coprime with ``n`` and close to ``n/φ``
(a Weyl / Fibonacci-hashing sequence). This is a bijection that spreads the
payload uniformly over the whole image instead of filling it top-down. It is
public and provides dispersion only - confidentiality comes from AES-GCM.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import struct
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from reedsolo import ReedSolomonError, RSCodec

FRAME_MAGIC = b"SG"
FRAME_VERSION = 1
HEADER_DATA_LEN = 8
HEADER_NSYM = 16
HEADER_LEN = HEADER_DATA_LEN + HEADER_NSYM  # 24 bytes
HEADER_BITS = HEADER_LEN * 8
DIGEST_LEN = 32
RS_BLOCK = 255
MAX_BODY_LEN = (1 << 24) - 1
_GOLDEN = (math.sqrt(5) - 1) / 2


@lru_cache(maxsize=8)
def _codec(nsym: int) -> RSCodec:
    return RSCodec(nsym, nsize=RS_BLOCK)


# --------------------------------------------------------------------------- slot ordering


@lru_cache(maxsize=64)
def _affine_params(n: int) -> tuple[int, int]:
    a = max(1, int(round(n * _GOLDEN)))
    while math.gcd(a, n) != 1:
        a += 1
    b = (n * 7) // 13
    return a, b


def slot_indices(n_slots: int, start: int, count: int) -> np.ndarray:
    """Carrier slots holding frame bits ``start .. start+count-1``."""
    if start + count > n_slots:
        raise ValueError("frame exceeds carrier capacity")
    a, b = _affine_params(n_slots)
    i = np.arange(start, start + count, dtype=np.int64)
    # a, i < n <= 3 * MAX_IMAGE_PIXELS (~1e8), so a*i < 1e16 fits comfortably in int64.
    return (a * i + b) % n_slots


# --------------------------------------------------------------------------- bits <-> bytes


def bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: np.ndarray) -> bytes:
    return np.packbits(bits.astype(np.uint8)).tobytes()


# --------------------------------------------------------------------------- sizes


def encoded_body_len(body_len: int, nsym: int) -> int:
    if nsym == 0:
        return body_len
    return body_len + nsym * math.ceil(body_len / (RS_BLOCK - nsym))


def frame_bits_for_envelope(envelope_len: int, nsym: int) -> int:
    return (HEADER_LEN + encoded_body_len(envelope_len + DIGEST_LEN, nsym)) * 8


def max_envelope_len(capacity_bits: int, nsym: int) -> int:
    """Largest envelope that fits a carrier with ``capacity_bits`` slots (may be negative)."""
    available = capacity_bits // 8 - HEADER_LEN
    if available <= 0:
        return -DIGEST_LEN
    if nsym == 0:
        body = available
    else:
        data_per_block = RS_BLOCK - nsym
        full_blocks, rem = divmod(available, RS_BLOCK)
        body = full_blocks * data_per_block + max(0, rem - nsym)
    return min(body, MAX_BODY_LEN) - DIGEST_LEN


# --------------------------------------------------------------------------- build / parse


@dataclass
class Frame:
    bits: np.ndarray
    header: bytes
    body_len: int
    nsym: int


def build_frame(envelope: bytes, algorithm_id: int, nsym: int) -> Frame:
    body = envelope + hashlib.sha256(envelope).digest()
    if len(body) > MAX_BODY_LEN:
        raise ValueError("payload too large for frame header")
    header_data = FRAME_MAGIC + struct.pack(">BBB", FRAME_VERSION, algorithm_id, nsym) + len(body).to_bytes(3, "big")
    header = bytes(_codec(HEADER_NSYM).encode(header_data))
    encoded = bytes(_codec(nsym).encode(body)) if nsym else body
    return Frame(bits=bytes_to_bits(header + encoded), header=header, body_len=len(body), nsym=nsym)


@dataclass
class HeaderInfo:
    algorithm_id: int
    nsym: int
    body_len: int
    corrected: int


def parse_header(bits: np.ndarray) -> HeaderInfo | None:
    """Decode the 24-byte RS-protected header; ``None`` when no StegoLab frame is present."""
    if bits.size < HEADER_BITS:
        return None
    raw = bits_to_bytes(bits[:HEADER_BITS])
    try:
        decoded, _, errata = _codec(HEADER_NSYM).decode(raw)
    except ReedSolomonError:
        return None
    data = bytes(decoded)
    if data[:2] != FRAME_MAGIC or data[2] != FRAME_VERSION:
        return None
    algorithm_id, nsym = data[3], data[4]
    body_len = int.from_bytes(data[5:8], "big")
    if nsym >= RS_BLOCK - 1 or body_len <= DIGEST_LEN:
        return None
    return HeaderInfo(algorithm_id=algorithm_id, nsym=nsym, body_len=body_len, corrected=len(errata))


@dataclass
class BodyResult:
    envelope: bytes | None
    integrity: str  # verified | failed
    corrected: int = 0
    detail: str = ""
    expected_digest: str | None = None
    actual_digest: str | None = None
    notes: list[str] = field(default_factory=list)


def parse_body(bits: np.ndarray, header: HeaderInfo) -> BodyResult:
    raw = bits_to_bytes(bits)
    corrected = 0
    if header.nsym:
        try:
            decoded, _, errata = _codec(header.nsym).decode(raw)
            body = bytes(decoded)
            corrected = len(errata)
        except ReedSolomonError:
            # Too many symbol errors: fall back to the raw data bytes so the digest check reports failure.
            body = _strip_parity(raw, header.nsym)
            note = "Reed-Solomon decoding failed (errors exceed correction capacity)"
            return _verify(body, header, corrected, [note])
    else:
        body = raw
    return _verify(body[: header.body_len], header, corrected, [])


def _strip_parity(raw: bytes, nsym: int) -> bytes:
    out = bytearray()
    for start in range(0, len(raw), RS_BLOCK):
        block = raw[start : start + RS_BLOCK]
        out += block[: max(0, len(block) - nsym)]
    return bytes(out)


def _verify(body: bytes, header: HeaderInfo, corrected: int, notes: list[str]) -> BodyResult:
    body = body[: header.body_len]
    envelope, digest = body[:-DIGEST_LEN], body[-DIGEST_LEN:]
    actual = hashlib.sha256(envelope).digest()
    ok = len(body) == header.body_len and secrets.compare_digest(actual, digest)
    return BodyResult(
        envelope=envelope if ok else None,
        integrity="verified" if ok else "failed",
        corrected=corrected,
        detail="SHA-256 of recovered ciphertext matches embedded digest" if ok else "SHA-256 mismatch",
        expected_digest=digest.hex(),
        actual_digest=actual.hex(),
        notes=notes,
    )
