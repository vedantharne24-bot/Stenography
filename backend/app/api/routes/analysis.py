"""Steganalysis, forensics, attack lab and research-experiment endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, require
from app.core.errors import NotFound, ValidationFailed
from app.core.permissions import Permission
from app.core.rate_limit import client_ip, rate_limit
from app.core.streaming import Trace, run_operation
from app.db.models import ExperimentRun, User
from app.services import attacks as attack_service
from app.services import experiments as experiment_service
from app.services import forensics as forensic_service
from app.services import image_io
from app.services import steganalysis as analysis_service

router = APIRouter(prefix="/api", tags=["analysis"])
_heavy = Depends(rate_limit("heavy", "rate_limit_heavy"))


@router.post("/steganalysis/analyze", dependencies=[_heavy])
async def analyze(
    request: Request,
    image: UploadFile = File(...),
    explain: bool = Form(True),
    user: User = Depends(require(Permission.ANALYSIS_RUN)),
) -> Any:
    data = await image_io.read_upload(image)
    name, mime, ip = image.filename or "upload", image.content_type, client_ip(request)

    def operation(trace: Trace, db: Session) -> dict[str, Any]:
        return analysis_service.analyze_upload(trace, db, user, image_bytes=data, image_name=name, image_mime=mime, explain=explain, ip=ip)

    return await run_operation(request, operation)


@router.post("/steganalysis/explain", dependencies=[_heavy])
async def explain(request: Request, image: UploadFile = File(...), user: User = Depends(require(Permission.ANALYSIS_RUN))) -> Any:
    """Same pipeline as /analyze with Grad-CAM forced on (kept as a separate, explicit endpoint)."""
    data = await image_io.read_upload(image)
    name, mime, ip = image.filename or "upload", image.content_type, client_ip(request)
    return await run_operation(
        request,
        lambda trace, db: analysis_service.analyze_upload(trace, db, user, image_bytes=data, image_name=name, image_mime=mime, explain=True, ip=ip),
    )


@router.post("/forensics/analyze", dependencies=[_heavy])
async def forensics(request: Request, image: UploadFile = File(...), user: User = Depends(require(Permission.FORENSICS_RUN))) -> Any:
    data = await image_io.read_upload(image)
    name, mime, ip = image.filename or "upload", image.content_type, client_ip(request)
    return await run_operation(
        request, lambda trace, db: forensic_service.run(trace, db, user, image_bytes=data, image_name=name, image_mime=mime, ip=ip)
    )


@router.get("/attacks/catalogue")
def attack_catalogue(_: User = Depends(require(Permission.ATTACKS_RUN))) -> dict[str, Any]:
    return {"attacks": attack_service.catalogue(), "default_suite": [{"attack": a, "params": p} for a, p in attack_service.DEFAULT_SUITE]}


@router.post("/attacks/run", dependencies=[_heavy])
async def run_attack(
    request: Request,
    image: UploadFile = File(...),
    attack: str = Form(...),
    params: str = Form("{}"),
    secret: str | None = Form(None),
    user: User = Depends(require(Permission.ATTACKS_RUN)),
) -> Any:
    data = await image_io.read_upload(image)
    try:
        parsed = json.loads(params)
        if not isinstance(parsed, dict):
            raise ValueError
    except ValueError as exc:
        raise ValidationFailed("params must be a JSON object") from exc
    name, mime, ip = image.filename or "upload", image.content_type, client_ip(request)
    return await run_operation(
        request,
        lambda trace, db: attack_service.run_single(
            trace, db, user, image_bytes=data, image_name=name, image_mime=mime, attack=attack, params=parsed, secret_value=secret, ip=ip
        ),
    )


@router.post("/attacks/batch", dependencies=[_heavy])
async def run_batch(
    request: Request,
    image: UploadFile = File(...),
    suite: str | None = Form(None),
    secret: str | None = Form(None),
    user: User = Depends(require(Permission.ATTACKS_RUN)),
) -> Any:
    data = await image_io.read_upload(image)
    plan = None
    if suite:
        try:
            raw = json.loads(suite)
            plan = [(str(item["attack"]), dict(item.get("params", {}))) for item in raw]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValidationFailed("suite must be a JSON list of {attack, params}") from exc
    name, mime, ip = image.filename or "upload", image.content_type, client_ip(request)
    return await run_operation(
        request,
        lambda trace, db: attack_service.run_batch(trace, db, user, image_bytes=data, image_name=name, image_mime=mime, suite=plan, secret_value=secret, ip=ip),
    )


class ExperimentRequest(BaseModel):
    images: int = Field(12, ge=3, le=60)
    payload_mode: str = Field("relative", pattern="^(relative|absolute)$")
    relative: float = Field(0.5, ge=0.05, le=1.0)
    absolute_bytes: int = Field(64, ge=1, le=100_000)
    seed: int = Field(0, ge=0, le=1_000_000)
    weights: dict[str, float] | None = None


@router.post("/experiments/run", dependencies=[_heavy])
async def run_experiment(body: ExperimentRequest, request: Request, user: User = Depends(require(Permission.EXPERIMENTS_RUN))) -> Any:
    ip = client_ip(request)
    if body.weights and any(k not in experiment_service.CRITERIA or v < 0 for k, v in body.weights.items()):
        raise ValidationFailed(f"weights keys must be among {experiment_service.CRITERIA} and non-negative")
    return await run_operation(
        request,
        lambda trace, db: experiment_service.run_comparison(
            trace, db, db.merge(user), images=body.images, payload_mode=body.payload_mode, relative=body.relative,
            absolute_bytes=body.absolute_bytes, seed=body.seed, weights=body.weights, ip=ip,
        ),
    )


@router.get("/experiments")
def list_experiments(limit: int = 20, user: User = Depends(require(Permission.EXPERIMENTS_RUN)), db: Session = DbSession) -> list[dict[str, Any]]:
    rows = db.scalars(select(ExperimentRun).order_by(ExperimentRun.created_at.desc()).limit(min(100, max(1, limit)))).all()
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "config": r.config,
            "ranking": (r.results or {}).get("ranking"),
            "answer": (r.results or {}).get("answer"),
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat(),
            "own": r.user_id == user.id,
        }
        for r in rows
    ]


@router.get("/experiments/{run_id}")
def get_experiment(run_id: str, _: User = Depends(require(Permission.EXPERIMENTS_RUN)), db: Session = DbSession) -> dict[str, Any]:
    import uuid

    try:
        row = db.get(ExperimentRun, uuid.UUID(run_id))
    except ValueError as exc:
        raise NotFound("Experiment not found") from exc
    if row is None:
        raise NotFound("Experiment not found")
    return {"run_id": str(row.id), "created_at": row.created_at.isoformat(), "duration_ms": row.duration_ms, "config": row.config, **(row.results or {})}
