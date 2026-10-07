"""Router registration."""

from __future__ import annotations

from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    from app.api.routes import analysis, records, steganography, system

    app.include_router(system.router)
    app.include_router(steganography.router)
    app.include_router(analysis.router)
    app.include_router(records.router)
