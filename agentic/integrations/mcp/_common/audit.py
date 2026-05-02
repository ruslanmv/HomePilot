from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger('homepilot.mcp.audit')


def audit_event(event: str, **payload: Any) -> None:
    """Structured audit logger hook."""
    logger.info('audit_event=%s payload=%s', event, payload)
