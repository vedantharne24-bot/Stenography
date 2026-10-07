"""Operation tracing and live event streaming.

Long-running operations record what they actually do through a ``Trace``. Each
``trace.step`` / ``trace.span`` call is emitted *at the moment the backend
performs that step*, so the console the user sees is a faithful log - not a
scripted animation.

Transport: if the client sends ``Accept: application/x-ndjson`` the response is
a stream of newline-delimited JSON events ending with a ``result`` or ``error``
event; otherwise the operation runs to completion and returns
``{"result": ..., "trace": [...]}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.session import SessionLocal

log = get_logger("app.operations")
NDJSON = "application/x-ndjson"


class Trace:
    def __init__(self, emit: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._emit = emit
        self._t0 = time.perf_counter()

    def step(self, stage: str, message: str, level: str = "info", **data: Any) -> None:
        event = {
            "type": "log",
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "elapsed_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            "stage": stage,
            "level": level,
            "message": message,
        }
        if data:
            event["data"] = data
        self.events.append(event)
        if self._emit:
            self._emit(event)

    @contextlib.contextmanager
    def span(self, stage: str, message: str, done: str | None = None) -> Iterator[dict[str, Any]]:
        """Emit ``message`` now and ``done`` (with measured duration) when the block exits."""
        self.step(stage, message)
        extra: dict[str, Any] = {}
        start = time.perf_counter()
        yield extra
        duration = round((time.perf_counter() - start) * 1000, 1)
        self.step(stage, done or f"{message.rstrip('.…')} complete", duration_ms=duration, **extra)


Operation = Callable[[Trace, Session], dict[str, Any]]


def _error_payload(exc: BaseException) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, AppError):
        return exc.status_code, {"code": exc.code, "message": exc.message, "details": exc.details}
    incident = uuid.uuid4().hex[:12]
    log.exception("Operation failed [incident=%s]", incident, exc_info=exc)
    return 500, {"code": "internal_error", "message": "An internal error occurred.", "details": {"incident": incident}}


def _run(operation: Operation, trace: Trace) -> dict[str, Any]:
    with SessionLocal() as db:
        return operation(trace, db)


async def run_operation(request: Request, operation: Operation) -> Any:
    if NDJSON not in request.headers.get("accept", ""):
        trace = Trace()
        result = await run_in_threadpool(_run, operation, trace)
        return JSONResponse({"result": result, "trace": trace.events})

    events: queue.Queue[dict[str, Any] | None] = queue.Queue()
    trace = Trace(emit=events.put)

    def worker() -> None:
        try:
            result = _run(operation, trace)
            events.put({"type": "result", "data": result})
        except BaseException as exc:  # noqa: BLE001 - reported to the client as an error event
            status, error = _error_payload(exc)
            trace.step("error", error["message"], level="error")
            events.put({"type": "error", "status": status, "error": error})
        finally:
            events.put(None)

    threading.Thread(target=worker, name="stegolab-op", daemon=True).start()

    async def stream() -> AsyncIterator[bytes]:
        while True:
            event = await asyncio.to_thread(events.get)
            if event is None:
                break
            yield (json.dumps(event, default=str) + "\n").encode()

    return StreamingResponse(stream(), media_type=NDJSON, headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
