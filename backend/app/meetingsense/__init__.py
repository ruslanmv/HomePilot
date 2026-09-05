"""MeetingSense — screen + audio → live transcript, slides and notes (design Part 1).

Additive and flag-gated (``MEETINGSENSE_ENABLED``, default off). Named ``meetingsense`` and
placed beside ``avatar_director`` rather than under ``services/``: ``backend/app/avatar/`` is
already the avatar *image* generation package, and ``services/`` at the repo root holds only
the teams relay. The frozen naming decisions in ``docs/design/MEETINGSENSE_BATCHES.md`` §0
say where each subsystem lives; this package follows them.

Golden rule for every batch here, the same one ``avatar_director`` and ``ltm`` carry:
**ADDITIVE ONLY.** Transcription reuses ``backend/app/voice/providers.py``, slide captions
reuse ``multimodal.analyze_image``, memory extends ``ltm`` with new categories rather than a
parallel store, and the MCP surface registers through the existing Context Forge registry.
Nothing here re-implements a subsystem that exists.

Importing this package costs one router module and a dataclass. The session machinery that
needs WebSockets arrives in MS3 and is imported lazily then, so an install that never turns
MeetingSense on never loads it.
"""

from .routes import router  # noqa: F401
