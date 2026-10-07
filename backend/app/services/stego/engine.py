"""High-level embed / extract orchestration over the three algorithms."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from app.core.errors import InsufficientCapacity, IntegrityFailure, ValidationFailed
from app.services import crypto
from app.services.stego import framing
from app.services.stego.base import QimStats, QimTransformAlgorithm, StegoAlgorithm
from app.services.stego.dct import DctAlgorithm
from app.services.stego.dwt import DwtAlgorithm
from app.services.stego.lsb import LsbAlgorithm

ALGORITHM_CLASSES: dict[str, type[StegoAlgorithm]] = {
    "lsb": LsbAlgorithm,
    "dct": DctAlgorithm,
    "dwt": DwtAlgorithm,
}
ALGORITHM_NAMES = tuple(ALGORITHM_CLASSES)
_BY_ID = {cls.algorithm_id: name for name, cls in ALGORITHM_CLASSES.items()}


def get_algorithm(name: str) -> StegoAlgorithm:
    try:
        return ALGORITHM_CLASSES[name.lower()]()
    except KeyError as exc:
        raise ValidationFailed(f"Unknown algorithm '{name}'. Choose one of {list(ALGORITHM_CLASSES)}") from exc


# --------------------------------------------------------------------------- capacity


@dataclass
class Capacity:
    algorithm: str
    slots: int
    ecc_parity: int
    max_envelope_bytes: int
    max_payload_bytes: int  # uncompressed content that is guaranteed to fit

    def as_dict(self) -> dict[str, int | str]:
        return {
            "algorithm": self.algorithm,
            "slots": self.slots,
            "raw_capacity_bytes": self.slots // 8,
            "ecc_parity": self.ecc_parity,
            "max_envelope_bytes": max(0, self.max_envelope_bytes),
            "max_payload_bytes": max(0, self.max_payload_bytes),
        }


def capacity(name: str, shape: tuple[int, ...], filename: str | None = None) -> Capacity:
    alg = get_algorithm(name)
    slots = alg.capacity_slots(shape)
    max_env = framing.max_envelope_len(slots, alg.default_nsym)
    return Capacity(
        algorithm=alg.name,
        slots=slots,
        ecc_parity=alg.default_nsym,
        max_envelope_bytes=max_env,
        max_payload_bytes=max_env - crypto.envelope_overhead(filename),
    )


# --------------------------------------------------------------------------- embed


@dataclass
class EmbedOutcome:
    stego: np.ndarray
    algorithm: str
    capacity: Capacity
    frame_bits: int
    utilization: float
    qim: QimStats | None
    timings_ms: dict[str, float] = field(default_factory=dict)


def embed(rgb: np.ndarray, envelope: bytes, name: str) -> EmbedOutcome:
    alg = get_algorithm(name)
    cap = capacity(name, rgb.shape)
    t0 = time.perf_counter()
    frame = framing.build_frame(envelope, alg.algorithm_id, alg.default_nsym)
    if frame.bits.size > cap.slots:
        raise InsufficientCapacity(
            f"Payload needs {frame.bits.size // 8:,} bytes of carrier but {alg.name.upper()} offers "
            f"{cap.slots // 8:,} bytes in this image",
            details={
                "required_bits": int(frame.bits.size),
                "available_bits": cap.slots,
                "max_envelope_bytes": max(0, cap.max_envelope_bytes),
                "envelope_bytes": len(envelope),
            },
        )
    slots = framing.slot_indices(cap.slots, 0, frame.bits.size)
    t1 = time.perf_counter()
    stego = alg.embed(rgb, slots, frame.bits)
    t2 = time.perf_counter()

    # Self-check: the frame must decode from the rendered 8-bit image before we hand it out.
    check = extract(stego, name)
    t3 = time.perf_counter()
    if check.integrity != "verified" or check.envelope != envelope:
        raise IntegrityFailure(
            "Embedding could not be verified on the rendered image (carrier too saturated for this payload). "
            "Use a smaller payload, another algorithm, or a less saturated cover.",
            details={"algorithm": alg.name},
        )
    return EmbedOutcome(
        stego=stego,
        algorithm=alg.name,
        capacity=cap,
        frame_bits=int(frame.bits.size),
        utilization=frame.bits.size / cap.slots,
        qim=alg.last_stats if isinstance(alg, QimTransformAlgorithm) else None,
        timings_ms={
            "framing": (t1 - t0) * 1000,
            "embedding": (t2 - t1) * 1000,
            "verification": (t3 - t2) * 1000,
        },
    )


# --------------------------------------------------------------------------- extract


@dataclass
class ExtractOutcome:
    integrity: str  # verified | failed | not_found
    algorithm: str | None
    envelope: bytes | None = None
    body_len: int = 0
    ecc_parity: int = 0
    header_corrected: int = 0
    body_corrected: int = 0
    frame_bits: int = 0
    tried: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    expected_digest: str | None = None
    actual_digest: str | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.integrity != "not_found"


def extract(rgb: np.ndarray, name: str | None = None) -> ExtractOutcome:
    candidates = [name.lower()] if name else list(ALGORITHM_NAMES)
    tried: list[str] = []
    t0 = time.perf_counter()
    for candidate in candidates:
        alg = get_algorithm(candidate)
        n = alg.capacity_slots(rgb.shape)
        tried.append(alg.name)
        if n < framing.HEADER_BITS:
            continue
        read = alg.reader(rgb)
        header = framing.parse_header(read(framing.slot_indices(n, 0, framing.HEADER_BITS)))
        if header is None or header.algorithm_id != alg.algorithm_id:
            continue
        total_bits = framing.HEADER_BITS + framing.encoded_body_len(header.body_len, header.nsym) * 8
        if total_bits > n:
            return ExtractOutcome(
                integrity="failed",
                algorithm=alg.name,
                tried=tried,
                notes=["Header declares a payload larger than the carrier (image resized or cropped?)"],
                timings_ms={"extraction": (time.perf_counter() - t0) * 1000},
            )
        body_bits = read(framing.slot_indices(n, framing.HEADER_BITS, total_bits - framing.HEADER_BITS))
        body = framing.parse_body(body_bits, header)
        return ExtractOutcome(
            integrity=body.integrity,
            algorithm=alg.name,
            envelope=body.envelope,
            body_len=header.body_len,
            ecc_parity=header.nsym,
            header_corrected=header.corrected,
            body_corrected=body.corrected,
            frame_bits=total_bits,
            tried=tried,
            notes=body.notes,
            expected_digest=body.expected_digest,
            actual_digest=body.actual_digest,
            timings_ms={"extraction": (time.perf_counter() - t0) * 1000},
        )
    return ExtractOutcome(
        integrity="not_found",
        algorithm=None,
        tried=tried,
        notes=["No StegoLab frame header found with LSB, DCT or DWT decoders"],
        timings_ms={"extraction": (time.perf_counter() - t0) * 1000},
    )


def algorithm_from_id(algorithm_id: int) -> str | None:
    return _BY_ID.get(algorithm_id)


def bit_error_rate(reference: np.ndarray, attacked: np.ndarray, name: str) -> float | None:
    """Fraction of frame bits that differ after an attack (``None`` if geometry changed)."""
    if reference.shape != attacked.shape:
        return None
    alg = get_algorithm(name)
    n = alg.capacity_slots(reference.shape)
    ref_read = alg.reader(reference)
    header = framing.parse_header(ref_read(framing.slot_indices(n, 0, framing.HEADER_BITS)))
    if header is None:
        return None
    total = framing.HEADER_BITS + framing.encoded_body_len(header.body_len, header.nsym) * 8
    slots = framing.slot_indices(n, 0, total)
    before = ref_read(slots)
    after = alg.reader(attacked)(slots)
    return float(np.mean(before != after))
