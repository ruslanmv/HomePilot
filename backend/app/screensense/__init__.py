"""Remote screen capture — additive, non-destructive (batch RS1).

Lets somebody away from their desk ask their assistant to *look* at that computer: one
screenshot, taken on request, addressable afterwards so a follow-up question is answered
about the same picture rather than a new one.

Nothing in this package changes an existing route. It adds five of its own under
``/v1/screensense/`` and one directory under ``UPLOAD_DIR``. Deleting the package and its
one ``include_router`` line in ``main.py`` returns HomePilot to exactly what it was.
"""

from .routes import router  # noqa: F401

__all__ = ["router"]
