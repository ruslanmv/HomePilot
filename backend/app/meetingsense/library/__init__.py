"""Meetings Library — the additive upgrade to the Meetings view (``MEETINGS_LIBRARY_UPGRADE``).

One library over every meeting (recorded live, imported, synced from a folder, scheduled, and
read-only Teams rooms), imports of Insta360 / AIRecord archives, audio and transcript files,
opt-in folder sync, and offline transcription through HomePilot's own speech provider.

See ``docs/meetings-library.md``.
"""

from . import jobs as _jobs
from . import sync as _sync
from .routes import router


async def _startup() -> None:
    _jobs.start_worker()
    _sync.start_sync_loop()


async def _shutdown() -> None:
    await _jobs.stop_worker()
    await _sync.stop_sync_loop()


router.add_event_handler("startup", _startup)
router.add_event_handler("shutdown", _shutdown)

__all__ = ["router"]
