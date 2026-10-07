"""Structured logging setup.

Logs never include passwords, keys, secret messages or payload bytes - callers
pass only identifiers, sizes and outcomes.
"""

from __future__ import annotations

import logging
import sys


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extra = getattr(record, "ctx", None)
        return f"{base} {extra}" if extra else base


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Uvicorn access logs include query strings; keep them but at INFO only.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
