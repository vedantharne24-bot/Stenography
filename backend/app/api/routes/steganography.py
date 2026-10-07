"""Secure steganography endpoints (encrypt, embed, extract, decrypt)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import DbSession, require
from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.core.permissions import Permission
from app.core.rate_limit import client_ip, rate_limit
from app.core.streaming import Trace, run_operation
from app.db.models import User
from app.services import image_io
from app.services import steganography as stego_service
from app.services.crypto import PayloadKind
from app.services.steganography import PayloadInput, SecretInput

router = APIRouter(prefix="/api/steganography", tags=["steganography"])
_heavy = Depends(rate_limit("heavy", "rate_limit_heavy"))

Algorithm = Literal["lsb", "dct", "dwt"]
KeyMode = Literal["passphrase", "generate", "key"]


async def _payload_from_form(payload_type: str, message: str | None, payload_file: UploadFile | None) -> PayloadInput:
    if payload_type == "text":
        if not message:
            raise ValidationFailed("Secret message is empty")
        if len(message) > stego_service.MAX_TEXT_CHARS:
            raise ValidationFailed(f"Message exceeds {stego_service.MAX_TEXT_CHARS:,} characters")
        return PayloadInput(kind=PayloadKind.TEXT, content=message.encode("utf-8"))
    if payload_file is None or not payload_file.filename:
        raise ValidationFailed("A payload file is required when payload_type=file")
    content = await image_io.read_upload(payload_file, get_settings().max_payload_file_size)
    return PayloadInput(kind=PayloadKind.FILE, content=content, filename=payload_file.filename)


@router.post("/capacity")
async def capacity(
    image: UploadFile = File(...),
    payload_filename: str | None = Form(None),
    user: User = Depends(require(Permission.STEGO_EMBED)),
) -> dict[str, Any]:
    data = await image_io.read_upload(image)
    loaded = await run_in_threadpool(image_io.load_image, data, image.filename or "upload", image.content_type)
    return {
        "image": {"width": loaded.width, "height": loaded.height, "format": loaded.format, "sha256": loaded.sha256, "warnings": loaded.warnings},
        "algorithms": stego_service.capacities(loaded, payload_filename),
    }


@router.post("/encrypt", dependencies=[_heavy])
async def encrypt(
    request: Request,
    payload_type: Literal["text", "file"] = Form("text"),
    message: str | None = Form(None),
    payload_file: UploadFile | None = File(None),
    key_mode: KeyMode = Form("passphrase"),
    passphrase: str | None = Form(None),
    user: User = Depends(require(Permission.STEGO_EMBED)),
) -> Any:
    payload = await _payload_from_form(payload_type, message, payload_file)
    secret = SecretInput(mode=key_mode, value=passphrase)
    ip = client_ip(request)
    return await run_operation(request, lambda trace, db: stego_service.encrypt_only(trace, db, db.merge(user), payload, secret, ip))


@router.post("/embed", dependencies=[_heavy])
async def embed(
    request: Request,
    image: UploadFile = File(...),
    algorithm: Algorithm = Form(...),
    payload_type: Literal["text", "file"] = Form("text"),
    message: str | None = Form(None),
    payload_file: UploadFile | None = File(None),
    key_mode: KeyMode = Form("passphrase"),
    passphrase: str | None = Form(None),
    user: User = Depends(require(Permission.STEGO_EMBED)),
) -> Any:
    image_bytes = await image_io.read_upload(image)
    payload = await _payload_from_form(payload_type, message, payload_file)
    secret = SecretInput(mode=key_mode, value=passphrase)
    ip = client_ip(request)
    name, mime = image.filename or "upload", image.content_type

    def operation(trace: Trace, db: Session) -> dict[str, Any]:
        return stego_service.embed(
            trace, db, user, image_bytes=image_bytes, image_name=name, image_mime=mime,
            algorithm=algorithm, payload=payload, secret_input=secret, ip=ip,
        )

    return await run_operation(request, operation)


@router.post("/extract", dependencies=[_heavy])
async def extract(
    request: Request,
    image: UploadFile = File(...),
    algorithm: Literal["auto", "lsb", "dct", "dwt"] = Form("auto"),
    secret: str | None = Form(None),
    user: User = Depends(require(Permission.STEGO_EXTRACT)),
) -> Any:
    image_bytes = await image_io.read_upload(image)
    ip = client_ip(request)
    name, mime = image.filename or "upload", image.content_type

    def operation(trace: Trace, db: Session) -> dict[str, Any]:
        return stego_service.extract(
            trace, db, user, image_bytes=image_bytes, image_name=name, image_mime=mime,
            algorithm=None if algorithm == "auto" else algorithm, secret_value=secret, ip=ip,
        )

    return await run_operation(request, operation)


class DecryptRequest(BaseModel):
    envelope_b64: str = Field(min_length=1, max_length=8_000_000)
    secret: str = Field(min_length=1, max_length=512)


@router.post("/decrypt", dependencies=[_heavy])
async def decrypt(body: DecryptRequest, request: Request, user: User = Depends(require(Permission.STEGO_EXTRACT))) -> Any:
    ip = client_ip(request)
    return await run_operation(
        request, lambda trace, db: stego_service.decrypt_only(trace, db, db.merge(user), body.envelope_b64, body.secret, ip)
    )


@router.get("/algorithms")
def algorithms(_: User = Depends(require(Permission.STEGO_EMBED)), db: Session = DbSession) -> list[dict[str, Any]]:
    from app.services.stego import engine

    return [engine.get_algorithm(name).describe() for name in engine.ALGORITHM_NAMES]
