"""
HomePilot voice-call — additive backend module.

Scope (MVP M1)
--------------
Purely additive feature. With ``VOICE_CALL_ENABLED=false`` (the default)
this package is never imported into the running app and the DB tables it
needs are never created — dropping the module directory is sufficient to
remove the feature entirely.

Public entry point is :func:`voice_call.router.build_router`; everything
else is internal. No existing backend module imports from this package.
"""
from __future__ import annotations

__all__ = ["config", "router"]
