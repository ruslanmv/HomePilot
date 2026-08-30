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

__all__ = ["AvatarDirectorConfig", "load_config"]
