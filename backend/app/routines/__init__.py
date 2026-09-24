"""Routines — additive, user-scoped scheduled-action definitions.

The v1 module owns routine definitions and CRUD only. Execution is deliberately
separate so a future scheduler/worker can be enabled without changing the data
contract used by the web UI or companion clients.
"""

from .routes import router

__all__ = ["router"]
