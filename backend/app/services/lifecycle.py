"""Startup tasks and the background retention sweeper."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services import audit, storage
from app.services.audit import AuditAction

log = get_logger("app.lifecycle")


async def startup() -> None:
    settings = get_settings()
    log.info("StegoLab starting (env=%s, db=%s)", settings.app_env, settings.database_url.split("@")[-1])
    from app.ml import registry

    await asyncio.to_thread(registry.sync_registry_to_db)


def _sweep_once() -> int:
    with SessionLocal() as db:
        removed = storage.purge_expired(db)
        if removed:
            audit.record(db, AuditAction.RETENTION_SWEEP, "success", removed=removed)
        return removed


async def retention_loop() -> None:
    interval = max(60, get_settings().retention_sweep_minutes * 60)
    while True:
        try:
            removed = await asyncio.to_thread(_sweep_once)
            if removed:
                log.info("Retention sweep removed %d expired artifacts", removed)
        except Exception:  # pragma: no cover - the sweeper must never kill the app
            log.exception("Retention sweep failed")
        await asyncio.sleep(interval)
