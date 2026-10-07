"""Secure-hide and extraction workflows.

Privacy rules enforced here:
* plaintext messages/files are never written to disk or the database - only sizes and hashes;
* generated keys are returned once in the response and never stored or logged;
* recovered payloads are returned inline (base64) instead of being stored as artifacts.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.errors import DecryptionFailure, ValidationFailed
from app.core.streaming import Trace
from app.db.models import StegoOperation, User
from app.services import audit, crypto, image_io, metrics, storage
from app.services.audit import AuditAction
from app.services.crypto import PayloadKind, Secret
from app.services.stego import engine

MAX_TEXT_CHARS = 200_000


@dataclass
class PayloadInput:
    kind: PayloadKind
    content: bytes
    filename: str | None = None


@dataclass
class SecretInput:
    mode: str  # passphrase | generate | key
    value: str | None = None


def resolve_secret(secret_input: SecretInput) -> tuple[Secret, str | None]:
    """Return the secret plus the one-time display string of a generated key."""
    if secret_input.mode == "generate":
        key, encoded = crypto.generate_raw_key()
        return Secret(raw_key=key), encoded
    if not secret_input.value:
        raise ValidationFailed("A passphrase or key is required")
    return crypto.secret_from_user_input(secret_input.value), None


def _image_summary(image: image_io.LoadedImage) -> dict[str, Any]:
    return {
        "filename": image.filename,
        "format": image.format,
        "width": image.width,
        "height": image.height,
        "file_size": image.file_size,
        "sha256": image.sha256,
        "mode": image.original_mode,
        "warnings": image.warnings,
    }


def capacities(image: image_io.LoadedImage, filename: str | None = None) -> list[dict[str, Any]]:
    out = []
    for name in engine.ALGORITHM_NAMES:
        cap = engine.capacity(name, image.shape, filename).as_dict()
        cap["info"] = engine.get_algorithm(name).describe()
        out.append(cap)
    return out


def _encrypt_traced(trace: Trace, payload: PayloadInput, secret: Secret, mode: str) -> crypto.EncryptionResult:
    """Encrypt while emitting one log line per phase, timed by the crypto layer itself."""
    if mode == "generate":
        trace.step("crypto", "Generated 256-bit key from the OS CSPRNG (shown once, never stored)")
    else:
        params = crypto.KdfParams.from_settings()
        trace.step("crypto", f"Deriving key with Argon2id ({params.memory_kib // 1024} MiB, t={params.time_cost}, p={params.parallelism})…")

    def progress(phase: str, elapsed: float) -> None:
        if phase == "key_derivation" and mode != "generate":
            trace.step("crypto", "Argon2id key derived", duration_ms=round(elapsed, 1))
        elif phase == "encryption":
            trace.step("crypto", "Payload encrypted with AES-256-GCM (96-bit nonce, 128-bit tag)", duration_ms=round(elapsed, 1))

    return crypto.encrypt_payload(payload.content, secret, kind=payload.kind, filename=payload.filename, progress=progress)


# --------------------------------------------------------------------------- encrypt only


def encrypt_only(trace: Trace, db: Session, user: User, payload: PayloadInput, secret_input: SecretInput, ip: str) -> dict[str, Any]:
    secret, generated = resolve_secret(secret_input)
    sealed = _encrypt_traced(trace, payload, secret, secret_input.mode)
    trace.step("hash", f"SHA-256 envelope digest {sealed.envelope_sha256[:16]}…")
    audit.record(db, AuditAction.ENCRYPTION, "success", user=user, ip=ip, payload_size=len(payload.content), kdf=sealed.kdf)
    return {
        "envelope_b64": base64.b64encode(sealed.envelope).decode(),
        "envelope_bytes": len(sealed.envelope),
        "envelope_sha256": sealed.envelope_sha256,
        "content_sha256": sealed.content_sha256,
        "compressed": sealed.compressed,
        "kdf": sealed.kdf,
        "cipher": "AES-256-GCM",
        "generated_key": generated,
        "timings_ms": sealed.timings_ms,
    }


def decrypt_only(trace: Trace, db: Session, user: User, envelope_b64: str, secret_value: str, ip: str) -> dict[str, Any]:
    try:
        envelope = base64.b64decode(envelope_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValidationFailed("Envelope must be valid base64") from exc
    secret = crypto.secret_from_user_input(secret_value)
    try:
        with trace.span("crypto", "Authenticating and decrypting envelope…"):
            payload = crypto.decrypt_envelope(envelope, secret)
    except DecryptionFailure as exc:
        audit.record(db, AuditAction.DECRYPTION_FAILURE, "failure", user=user, ip=ip, reason=exc.message)
        raise
    audit.record(db, AuditAction.DECRYPTION_SUCCESS, "success", user=user, ip=ip, payload_size=len(payload.content))
    return _payload_out(payload)


def _payload_out(payload: crypto.DecryptedPayload) -> dict[str, Any]:
    return {
        "kind": payload.kind.name.lower(),
        "text": payload.text,
        "filename": payload.filename,
        "content_b64": None if payload.kind == PayloadKind.TEXT else base64.b64encode(payload.content).decode(),
        "size": len(payload.content),
        "content_sha256": payload.content_sha256,
        "integrity_verified": payload.integrity_verified,
        "kdf": payload.kdf,
    }


# --------------------------------------------------------------------------- embed


def embed(
    trace: Trace,
    db: Session,
    user: User,
    *,
    image_bytes: bytes,
    image_name: str,
    image_mime: str | None,
    algorithm: str,
    payload: PayloadInput,
    secret_input: SecretInput,
    ip: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    user = db.merge(user)
    with trace.span("validate", "Validating cover image…") as info:
        cover = image_io.load_image(image_bytes, image_name, image_mime)
        info.update(width=cover.width, height=cover.height, format=cover.format)
    trace.step("hash", f"Cover SHA-256 {cover.sha256[:16]}…")

    cap = engine.capacity(algorithm, cover.shape, payload.filename)
    trace.step(
        "capacity",
        f"{algorithm.upper()} capacity: {max(0, cap.max_payload_bytes):,} B payload ({cap.slots:,} carrier slots)",
    )

    secret, generated = resolve_secret(secret_input)
    sealed = _encrypt_traced(trace, payload, secret, secret_input.mode)
    trace.step("hash", f"Integrity hash SHA-256(envelope) = {sealed.envelope_sha256[:16]}…")
    audit.record(
        db, AuditAction.ENCRYPTION, "success", user=user, ip=ip, commit=False,
        payload_size=len(payload.content), payload_kind=payload.kind.name.lower(), kdf=sealed.kdf,
    )

    trace.step("embed", "Preparing frame (header + RS-ECC + digest)…")
    try:
        with trace.span("embed", f"Embedding encrypted payload via {algorithm.upper()}…") as info:
            outcome = engine.embed(cover.rgb, sealed.envelope, algorithm)
            info.update(utilization=round(outcome.utilization, 4))
    except Exception as exc:
        _record_failed_op(db, user, "embed", algorithm, cover, payload, getattr(exc, "code", "error"), started)
        audit.record(db, AuditAction.EMBEDDING, "failure", user=user, ip=ip, algorithm=algorithm, reason=str(exc)[:200])
        raise
    if outcome.qim:
        trace.step("embed", f"QIM correction converged in {outcome.qim.iterations} round(s), residual bit errors {outcome.qim.residual_errors}")
    trace.step("verify", "Self-check: frame re-extracted and SHA-256 verified on rendered image")

    with trace.span("metrics", "Calculating MSE / PSNR / SSIM…") as info:
        quality = metrics.quality_report(cover.rgb, outcome.stego)
        diff, amplified = metrics.difference_maps(cover.rgb, outcome.stego)
        info.update(psnr=quality["psnr"], ssim=round(quality["ssim"], 5))

    with trace.span("store", "Finalising stego image (lossless PNG)…"):
        stego_png = image_io.encode_png(outcome.stego, cover.alpha, cover.icc_profile)
        stego_art = storage.save_artifact(db, user=user, kind="stego_image", data=stego_png, mime="image/png")
        cover_art = storage.save_artifact(db, user=user, kind="cover_preview", data=image_io.encode_preview(cover.rgb), mime="image/png")
        stego_prev = storage.save_artifact(db, user=user, kind="stego_preview", data=image_io.encode_preview(outcome.stego), mime="image/png")
        diff_art = storage.save_artifact(db, user=user, kind="difference", data=image_io.encode_preview(np.repeat(diff.max(axis=2, keepdims=True), 3, axis=2)), mime="image/png")
        amp_art = storage.save_artifact(db, user=user, kind="difference_amplified", data=image_io.encode_preview(amplified), mime="image/png")

    duration = (time.perf_counter() - started) * 1000
    op = StegoOperation(
        user_id=user.id,
        operation="embed",
        algorithm=algorithm,
        payload_kind=payload.kind.name.lower(),
        payload_size=len(payload.content),
        envelope_size=len(sealed.envelope),
        image_width=cover.width,
        image_height=cover.height,
        image_size=cover.file_size,
        capacity_bytes=max(0, cap.max_payload_bytes),
        utilization=outcome.utilization,
        psnr=quality["psnr"],
        ssim=quality["ssim"],
        mse=quality["mse"],
        kdf=sealed.kdf,
        cover_hash=cover.sha256,
        stego_hash=stego_art.sha256,
        envelope_hash=sealed.envelope_sha256,
        success=True,
        duration_ms=duration,
        artifacts={
            "stego": str(stego_art.id),
            "cover_preview": str(cover_art.id),
            "stego_preview": str(stego_prev.id),
            "difference": str(diff_art.id),
            "difference_amplified": str(amp_art.id),
        },
    )
    db.add(op)
    audit.record(
        db, AuditAction.EMBEDDING, "success", user=user, ip=ip, commit=False,
        algorithm=algorithm, operation_id=str(op.id), payload_size=len(payload.content),
        psnr=quality["psnr"], stego_hash=stego_art.sha256,
    )
    db.commit()
    trace.step("done", f"Stego image ready · PSNR {quality['psnr']:.2f} dB · SSIM {quality['ssim']:.4f}" if quality["psnr"] else "Stego image ready")

    return {
        "operation_id": str(op.id),
        "algorithm": algorithm,
        "algorithm_info": engine.get_algorithm(algorithm).describe(),
        "cover": _image_summary(cover),
        "stego": {"sha256": stego_art.sha256, "size": stego_art.size, "format": "png"},
        "encryption": {
            "cipher": "AES-256-GCM",
            "kdf": sealed.kdf,
            "kdf_params": _kdf_params(sealed.envelope),
            "envelope_bytes": len(sealed.envelope),
            "envelope_sha256": sealed.envelope_sha256,
            "content_sha256": sealed.content_sha256,
            "compressed": sealed.compressed,
            "nonce_hex": sealed.envelope[27:39].hex(),
        },
        "generated_key": generated,
        "payload": {"kind": payload.kind.name.lower(), "size": len(payload.content), "filename": payload.filename},
        "capacity": cap.as_dict(),
        "frame_bits": outcome.frame_bits,
        "utilization": outcome.utilization,
        "quality": quality,
        "qim": {"iterations": outcome.qim.iterations, "residual_errors": outcome.qim.residual_errors} if outcome.qim else None,
        "artifacts": op.artifacts,
        "timings_ms": {**sealed.timings_ms, **outcome.timings_ms, "total": duration},
    }


def _kdf_params(envelope: bytes) -> dict[str, int] | None:
    kdf_id, params, _, _ = crypto.parse_header(envelope)
    if kdf_id != crypto.KdfId.ARGON2ID:
        return None
    return {"time_cost": params.time_cost, "memory_kib": params.memory_kib, "parallelism": params.parallelism}


def _record_failed_op(db: Session, user: User, op: str, algorithm: str, image: image_io.LoadedImage, payload: PayloadInput | None, code: str, started: float) -> None:
    db.add(
        StegoOperation(
            user_id=user.id,
            operation=op,
            algorithm=algorithm,
            payload_kind=payload.kind.name.lower() if payload else "text",
            payload_size=len(payload.content) if payload else 0,
            image_width=image.width,
            image_height=image.height,
            image_size=image.file_size,
            cover_hash=image.sha256,
            success=False,
            error_code=str(code)[:48],
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    )
    db.commit()


# --------------------------------------------------------------------------- extract


def extract(
    trace: Trace,
    db: Session,
    user: User,
    *,
    image_bytes: bytes,
    image_name: str,
    image_mime: str | None,
    algorithm: str | None,
    secret_value: str | None,
    ip: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    user = db.merge(user)
    with trace.span("validate", "Validating stego image…") as info:
        image = image_io.load_image(image_bytes, image_name, image_mime)
        info.update(width=image.width, height=image.height, format=image.format)
    trace.step("hash", f"Image SHA-256 {image.sha256[:16]}…")

    label = algorithm.upper() if algorithm else "auto-detect (LSB → DCT → DWT)"
    with trace.span("detect", f"Detecting frame format: {label}…") as info:
        found = engine.extract(image.rgb, algorithm)
        info.update(algorithm=found.algorithm, integrity=found.integrity)

    result: dict[str, Any] = {
        "operation_id": None,
        "image": _image_summary(image),
        "detected_algorithm": found.algorithm,
        "tried": found.tried,
        "integrity": {
            "status": found.integrity,
            "expected_sha256": found.expected_digest,
            "actual_sha256": found.actual_digest,
            "ecc_parity": found.ecc_parity,
            "header_symbols_corrected": found.header_corrected,
            "body_symbols_corrected": found.body_corrected,
            "notes": found.notes,
        },
        "envelope_bytes": len(found.envelope) if found.envelope else None,
        "decryption": {"status": "not_attempted", "message": None},
        "payload": None,
    }

    if found.integrity == "not_found":
        trace.step("detect", "No StegoLab frame found in this image", level="warn")
    elif found.integrity == "failed":
        trace.step("integrity", "SHA-256 mismatch - recovered ciphertext is corrupted", level="error")
        audit.record(db, AuditAction.INTEGRITY_FAILURE, "failure", user=user, ip=ip, commit=False, algorithm=found.algorithm, image_hash=image.sha256)
    else:
        trace.step("integrity", f"Integrity VERIFIED · {found.algorithm.upper()} frame, {found.body_corrected} symbol(s) corrected by ECC")
        if secret_value:
            try:
                secret = crypto.secret_from_user_input(secret_value)
                assert found.envelope is not None
                kdf_id, *_ = crypto.parse_header(found.envelope)
                stage_msg = "Deriving key with Argon2id and decrypting…" if kdf_id == crypto.KdfId.ARGON2ID else "Decrypting with supplied key…"
                with trace.span("crypto", stage_msg):
                    decrypted = crypto.decrypt_envelope(found.envelope, secret)
                result["decryption"] = {"status": "success", "message": "AES-256-GCM tag verified"}
                result["payload"] = _payload_out(decrypted)
                trace.step("crypto", f"Decryption SUCCESS · inner SHA-256 verified ({len(decrypted.content):,} bytes recovered)")
                audit.record(db, AuditAction.DECRYPTION_SUCCESS, "success", user=user, ip=ip, commit=False, payload_size=len(decrypted.content), algorithm=found.algorithm)
            except (DecryptionFailure, ValidationFailed) as exc:
                result["decryption"] = {"status": "failed", "message": exc.message}
                trace.step("crypto", f"Decryption FAILED · {exc.message}", level="error")
                audit.record(db, AuditAction.DECRYPTION_FAILURE, "failure", user=user, ip=ip, commit=False, algorithm=found.algorithm, reason=exc.message)
        else:
            trace.step("crypto", "No key supplied - payload left encrypted", level="warn")

    op = StegoOperation(
        user_id=user.id,
        operation="extract",
        algorithm=found.algorithm or (algorithm or "unknown"),
        payload_kind=(result["payload"] or {}).get("kind", "text"),
        payload_size=(result["payload"] or {}).get("size", 0),
        envelope_size=len(found.envelope) if found.envelope else 0,
        image_width=image.width,
        image_height=image.height,
        image_size=image.file_size,
        stego_hash=image.sha256,
        envelope_hash=found.actual_digest,
        success=result["decryption"]["status"] == "success",
        error_code=None if result["decryption"]["status"] == "success" else (found.integrity if found.integrity != "verified" else "decryption_" + result["decryption"]["status"]),
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    db.add(op)
    audit.record(
        db, AuditAction.EXTRACTION, "success" if found.integrity == "verified" else "failure", user=user, ip=ip, commit=False,
        algorithm=found.algorithm, integrity=found.integrity, image_hash=image.sha256,
    )
    db.commit()
    result["operation_id"] = str(op.id)
    result["timings_ms"] = {**found.timings_ms, "total": op.duration_ms}
    return result
