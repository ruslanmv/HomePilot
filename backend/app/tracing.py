from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("homepilot")
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured JSON log line correlated by request id.

    Keep payloads metadata-only: no secrets, cookies, full prompts, or documents.
    """
    try:
        line = json.dumps({"event": event, "request_id": request_id_ctx.get(), **fields}, default=str)
    except Exception:
        line = json.dumps({"event": event, "request_id": request_id_ctx.get(), "log_error": True})
    # Print guarantees visibility in ``make start`` even when logger levels are
    # controlled by uvicorn/supervisord. Also send to the named logger for
    # deployments that collect structured logs.
    print(line)
    logger.info(line)
