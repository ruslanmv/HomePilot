"""Avatar Director — the HomePilot side of the Behavior Director (spec v1.1 §4B).

Named ``avatar_director`` and not ``avatar``: ``backend/app/avatar`` is already the
avatar *image* generation package (StyleGAN / hybrid). The route prefix ``/avatar`` is
free and is used as the spec specifies; only the Python package name differs. See
``docs/PATHMAP.md``.

**Nothing is mounted yet.** B0 lands the name and the configuration block; B8 adds
``session.py``, ``safety.py`` and the ``register(app, config)`` entry point that mounts
routes only when ``avatar.enabled`` is true. Importing this package today costs one
dataclass and reads a handful of environment variables — it has no FastAPI dependency,
no I/O and no side effects, which is what lets the config tests run without the backend
requirements installed.

Golden rule for every batch in this package: ADDITIVE ONLY. Curiosity records extend the
existing ``app.ltm`` store as new categories, motion reuses ``app.embodiment.motion_dsl``,
the mic path reuses ``app.voice_call``, and tool actions reuse the propose-only contract
in ``app.daypilot_bridge`` — none of them are re-implemented here.
"""

from .config import AvatarDirectorConfig, load_config

__all__ = ["AvatarDirectorConfig", "load_config", "register"]


def register(app, config=None) -> bool:
    """Mount the Avatar Director, if it is enabled. The one line ``main.py`` adds.

    Returns whether anything was mounted, so the caller can log it honestly.

    The import of :mod:`session` is **inside** the enabled branch on purpose. That module
    pulls in FastAPI's WebSocket machinery, and B8 is accepted on the claim that with
    ``avatar.enabled`` false no route is mounted *and nothing is imported* — a top-level
    import would quietly make the second half untrue. ``backend/app/voice_call`` guards
    itself the same way; this follows the house pattern rather than inventing one.
    """
    cfg = config or load_config()
    if not cfg.enabled:
        return False

    from .session import build_router, vision_service  # noqa: PLC0415 — deliberately lazy

    app.include_router(build_router(cfg))

    # B15's REST endpoint, mounted only when a vision model is configured. A route that
    # would answer every request with "not configured" is worse than no route: it looks
    # like a feature to anything probing the API surface.
    service = vision_service(cfg)
    if service is not None:
        from .vision import build_router as build_vision_router  # noqa: PLC0415

        app.include_router(build_vision_router(cfg, service=service))
    return True
