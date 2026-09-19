"""
Caches ComfyUI ``/object_info`` results.

ComfyUI node availability changes only when the server restarts or custom nodes are added or
removed, so a coarse TTL is plenty. Everything interesting in this file is about what happens
when the request *fails*.

── The bug this file was rewritten to fix ───────────────────────────────────────────────────

The previous version used a 30-second timeout and, on failure, returned before touching
``_expires_at``. That left ``_expires_at`` at ``0.0`` and ``_nodes`` at ``None`` — so both
cache-validity conditions failed on the next call, and the one after that, forever. Every
generated image paid the full timeout again. Measured against a host that accepts no
connection::

    call 1:  10.23s  nodes=0  expires_at=0.0
    call 2:  10.06s  nodes=0  expires_at=0.0
    call 3:  10.06s  nodes=0  expires_at=0.0

That is not a cold-start cost, it is a per-image cost, and it is the larger half of a ~45-second
``POST /chat`` on a machine where ComfyUI itself renders in two seconds.

It is also worst exactly when it hurts most: ComfyUI serves ``/object_info`` from the same
process that runs the workflow, so the endpoint is contended *while generating*. A batch of four
paid it four times, each against a busier server.

── What this request is, and is not ─────────────────────────────────────────────────────────

It is **diagnostic**. Its whole job is turning a cryptic ``invalid_prompt`` into "install this
custom node package". ``POST /prompt`` remains the authoritative validator, so nothing here is
allowed to delay or block a generation: a short timeout that fails is strictly better than a
long one that succeeds, because the answer only improves an error message.

Hence: a bounded timeout, a negative cache so one failure is not re-paid per image, and
single-flight refresh so N concurrent callers make one request rather than N.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

#: How long a *failure* suppresses further attempts.
#:
#: Short enough that starting ComfyUI after HomePilot is noticed within a generation or two,
#: long enough that a server which is down stops costing anything measurable.
DEFAULT_FAILURE_TTL_S = 30.0

#: Ceiling on the diagnostic request itself. See the module docstring: this only improves an
#: error message, so seconds spent here are seconds stolen from a generation.
DEFAULT_REQUEST_TIMEOUT_S = 5.0


class ComfyObjectInfoCache:
    """
    Thin HTTP cache around ``GET <comfy_base_url>/object_info``.

    Usage::

        cache = ComfyObjectInfoCache("http://localhost:8188")
        nodes = cache.get_available_nodes()       # list[str]
        raw   = cache.get_raw()                    # full dict or None
    """

    def __init__(
        self,
        base_url: str,
        ttl_seconds: float = 300.0,
        *,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_S,
        failure_ttl_seconds: float = DEFAULT_FAILURE_TTL_S,
    ):
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.failure_ttl_seconds = failure_ttl_seconds

        self._expires_at: float = 0.0
        self._nodes: Optional[List[str]] = None
        self._raw: Optional[Dict[str, Any]] = None

        #: True when the current entry is a placeholder standing in for a failure rather than an
        #: answer from ComfyUI. Kept apart from `_nodes == []`, which is a legitimate — if odd —
        #: reply from a server with no nodes registered, and which callers may cache against.
        self._negative: bool = False

        # Single-flight. See `_refresh`.
        self._refresh_lock = threading.Lock()

        # ── Observability ────────────────────────────────────────────────────────────────
        # A cache whose failures are invisible is how a 30-second stall per image survived
        # this long. None of these affect behaviour; all of them are readable from a test or
        # a debug endpoint.
        self.last_status: Optional[str] = None          # "ok" | "error" | None
        self.last_duration_ms: Optional[float] = None
        self.last_error_type: Optional[str] = None
        self.hits: int = 0
        self.negative_hits: int = 0
        self.refreshes: int = 0
        self.failures: int = 0
        #: Monotonic stamp of the last emitted failure log, so a server that is simply off does
        #: not write a line per generated image.
        self._last_failure_log_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_available_nodes(self, *, force: bool = False, allow_network: bool = True) -> List[str]:
        """Return a list of registered ComfyUI node class names.

        ``allow_network=False`` answers from cache only — including a stale or empty one — and
        never opens a socket. That is the mode the image-generation path uses; see
        :func:`app.comfy.validate_workflow_nodes`.
        """
        self._refresh(force=force, allow_network=allow_network)
        return list(self._nodes) if self._nodes else []

    def get_raw(self, *, force: bool = False, allow_network: bool = True) -> Optional[Dict[str, Any]]:
        """Return the raw /object_info dict, or None if unreachable."""
        self._refresh(force=force, allow_network=allow_network)
        return self._raw

    def invalidate(self) -> None:
        """Force next call to re-fetch."""
        self._expires_at = 0.0

    def stats(self) -> Dict[str, Any]:
        """Everything known about how this cache has been behaving."""
        return {
            "base_url": self.base_url,
            "ttl_seconds": self.ttl_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "failure_ttl_seconds": self.failure_ttl_seconds,
            "cached": self._nodes is not None,
            "negative": self._negative,
            "node_count": len(self._nodes) if self._nodes else 0,
            "seconds_until_expiry": max(0.0, self._expires_at - time.monotonic()),
            "last_status": self.last_status,
            "last_duration_ms": self.last_duration_ms,
            "last_error_type": self.last_error_type,
            "hits": self.hits,
            "negative_hits": self.negative_hits,
            "refreshes": self.refreshes,
            "failures": self.failures,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_fresh(self) -> bool:
        # `time.monotonic()`, not `time.time()`: a wall clock can step backwards (NTP, a laptop
        # waking, a container's clock settling) and pin a cache as valid for as long as the
        # correction was large.
        return self._nodes is not None and time.monotonic() < self._expires_at

    def _refresh(self, *, force: bool = False, allow_network: bool = True) -> None:
        if not force and self._is_fresh():
            if self._negative:
                self.negative_hits += 1
            else:
                self.hits += 1
            return

        if not allow_network:
            # Cache-only. An expired entry is still served: stale node metadata is a far better
            # basis for a *diagnostic* than blocking a generation to refresh it, and an absent
            # one simply means callers skip the check and let `/prompt` validate.
            return

        # ── Single flight ────────────────────────────────────────────────────────────────
        # Without this, N simultaneous generations each see an expired cache and each open a
        # request — against the one endpoint already established as slow under load, making the
        # stampede worst precisely when the server can least afford it.
        with self._refresh_lock:
            # Re-check under the lock: whoever held it may have just filled the cache, and the
            # waiters' whole job now is to notice that and return.
            if not force and self._is_fresh():
                if self._negative:
                    self.negative_hits += 1
                else:
                    self.hits += 1
                return
            self._fetch_locked()

    def _fetch_locked(self) -> None:
        """One HTTP attempt. Caller holds `_refresh_lock`."""
        timeout = max(0.1, self.request_timeout_seconds)
        url = f"{self.base_url}/object_info"
        started = time.perf_counter()

        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout, connect=min(2.0, timeout)),
            ) as client:
                r = client.get(url)
                r.raise_for_status()
                raw = r.json()
        except Exception as exc:  # noqa: BLE001 — every failure mode gets the same treatment
            self._record_failure(exc, time.perf_counter() - started)
            return

        self.last_status = "ok"
        self.last_duration_ms = (time.perf_counter() - started) * 1000.0
        self.last_error_type = None
        self.refreshes += 1

        self._raw = raw
        self._nodes = list(raw.keys()) if isinstance(raw, dict) else []
        self._negative = False
        self._expires_at = time.monotonic() + self.ttl_seconds

    def _record_failure(self, exc: BaseException, duration_s: float) -> None:
        """Note the failure, and — the point of the rewrite — stop re-paying for it."""
        self.failures += 1
        self.last_status = "error"
        self.last_duration_ms = duration_s * 1000.0
        self.last_error_type = type(exc).__name__

        now = time.monotonic()
        had_real_data = self._nodes is not None and not self._negative
        if not had_real_data:
            # Nothing useful was ever cached, so cache the *absence*. This single assignment is
            # what the previous version omitted, and omitting it is what made every image pay
            # the timeout again.
            self._raw = None
            self._nodes = []
            self._negative = True
        # Either way the clock is reset: stale-but-real data also stops being re-fetched on
        # every call, which is the same defect wearing a different hat.
        self._expires_at = now + self.failure_ttl_seconds

        # One line per failure window, not one per generated image. A server that is simply not
        # running should not write a megabyte of identical tracebacks over an afternoon.
        if now - self._last_failure_log_at >= self.failure_ttl_seconds:
            self._last_failure_log_at = now
            log.warning(
                "comfy: /object_info unavailable at %s (%s after %.0fms); "
                "using %s for the next %.0fs. Node preflight is diagnostic only — "
                "generation continues and /prompt validates authoritatively.",
                self.base_url,
                self.last_error_type,
                self.last_duration_ms or 0.0,
                "stale cached metadata" if had_real_data else "no node metadata",
                self.failure_ttl_seconds,
            )
