"""
The ComfyUI ``/object_info`` cache, and the stall it used to cause.

── What broke ───────────────────────────────────────────────────────────────────────────────

The previous implementation used a 30-second timeout and, on failure, returned *before* setting
``_expires_at``. That left it at ``0.0`` and ``_nodes`` at ``None``, so both cache-validity
conditions failed on the next call, and the one after that, indefinitely. Every generated image
paid the full timeout again. Measured on the branch before this change::

    call 1:  10.23s  nodes=0  expires_at=0.0
    call 2:  10.06s  nodes=0  expires_at=0.0
    call 3:  10.06s  nodes=0  expires_at=0.0

That is the larger half of a ~45-second ``POST /chat`` on a machine where ComfyUI itself renders
in two seconds. It is also worst exactly when it hurts: ComfyUI answers ``/object_info`` from the
process running the workflow, so the endpoint is contended *while generating*, and a batch of
four paid it four times against a progressively busier server.

── What the request is for ──────────────────────────────────────────────────────────────────

It is diagnostic. Its entire job is turning a cryptic ``invalid_prompt`` into "install this
custom node package"; ``POST /prompt`` is the authoritative validator. So the governing rule for
everything below is that **no failure here may cost a generation anything**, and a short timeout
that fails is strictly better than a long one that succeeds.

Every test drives the cache through mocked transport rather than a real socket — these are
assertions about caching policy, not about the network.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.comfy_utils.object_info_cache import ComfyObjectInfoCache


NODES = {
    "LoadImage": {"input": {}, "output": {}},
    "SaveImage": {"input": {}, "output": {}},
    "KSampler": {"input": {}, "output": {}},
}


def _ok_client(payload=None, *, on_get=None):
    """A patchable ``httpx.Client`` context manager that answers with ``payload``."""
    resp = MagicMock()
    resp.json.return_value = NODES if payload is None else payload
    resp.raise_for_status = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.get = MagicMock(side_effect=on_get) if on_get else MagicMock(return_value=resp)
    factory = MagicMock(return_value=ctx)
    return factory, ctx


def _failing_client(exc=None):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.get = MagicMock(side_effect=exc or RuntimeError("connection refused"))
    return MagicMock(return_value=ctx), ctx


class TestSuccessPath:
    def test_a_successful_request_is_cached(self):
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            assert "KSampler" in cache.get_available_nodes()
        assert cache.last_status == "ok"

    def test_a_cache_hit_performs_no_request(self):
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
            cache.get_available_nodes()
            cache.get_available_nodes()
        assert factory.call_count == 1
        assert cache.hits == 2

    def test_invalidate_forces_one_more_request(self):
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
            cache.invalidate()
            cache.get_available_nodes()
        assert factory.call_count == 2

    def test_callers_cannot_mutate_the_cached_list(self):
        # `get_available_nodes` hands out a copy. Without that, one caller sorting or filtering
        # the result in place silently edits what every later caller sees.
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            first = cache.get_available_nodes()
            first.clear()
            assert "KSampler" in cache.get_available_nodes()


class TestFailureIsPaidForOnce:
    def test_a_failure_is_negative_cached(self):
        # THE regression. Three calls, one request — previously three requests, each paying the
        # full timeout, forever.
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0, failure_ttl_seconds=30.0)
        factory, _ = _failing_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            assert cache.get_available_nodes() == []
            assert cache.get_available_nodes() == []
            assert cache.get_available_nodes() == []
        assert factory.call_count == 1
        assert cache.negative_hits == 2
        assert cache.failures == 1

    def test_the_negative_entry_expires(self):
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0, failure_ttl_seconds=0.05)
        factory, _ = _failing_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
            time.sleep(0.08)
            cache.get_available_nodes()
        # Starting ComfyUI after HomePilot must not require a restart of HomePilot.
        assert factory.call_count == 2

    def test_a_failure_recovers_into_real_data(self):
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0, failure_ttl_seconds=0.05)
        bad, _ = _failing_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", bad):
            assert cache.get_available_nodes() == []
        time.sleep(0.08)
        good, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", good):
            assert "KSampler" in cache.get_available_nodes()
        assert cache.stats()["negative"] is False

    def test_stale_but_real_data_survives_a_later_failure(self):
        # A server that goes away must not take working node metadata with it. Stale metadata
        # is a better basis for a diagnostic than none.
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=0.05)
        good, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", good):
            cache.get_available_nodes()
        time.sleep(0.08)
        bad, _ = _failing_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", bad):
            assert "KSampler" in cache.get_available_nodes()
        assert cache.stats()["negative"] is False

    def test_a_stale_entry_is_also_not_re_fetched_per_call(self):
        # The same defect wearing a different hat: keeping stale data but leaving the clock at
        # zero means every subsequent call retries the network and pays the timeout again.
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=0.05, failure_ttl_seconds=30.0)
        good, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", good):
            cache.get_available_nodes()
        time.sleep(0.08)
        bad, bad_ctx = _failing_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", bad):
            for _ in range(5):
                cache.get_available_nodes()
        assert bad_ctx.get.call_count == 1


class TestBoundedTimeout:
    def test_the_request_timeout_is_short_by_default(self):
        cache = ComfyObjectInfoCache("http://mock:8188")
        assert cache.request_timeout_seconds <= 5.0

    def test_the_configured_timeout_reaches_httpx(self):
        cache = ComfyObjectInfoCache("http://mock:8188", request_timeout_seconds=3.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
        timeout = factory.call_args.kwargs["timeout"]
        assert timeout.read == 3.0
        # Connect is capped below the overall budget: a host that blackholes packets should
        # fail fast rather than spend the whole allowance on a handshake.
        assert timeout.connect == 2.0

    def test_a_tiny_timeout_is_floored_rather_than_zero(self):
        # `0` in httpx means "fail immediately", which would make the cache permanently
        # negative on a perfectly healthy server.
        cache = ComfyObjectInfoCache("http://mock:8188", request_timeout_seconds=0.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
        assert factory.call_args.kwargs["timeout"].read >= 0.1


class TestMonotonicClock:
    def test_expiry_does_not_use_the_wall_clock(self):
        # A wall clock can step backwards — NTP, a laptop waking, a container's clock settling —
        # and pin the cache as valid for as long as the correction was large.
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
            with patch("app.comfy_utils.object_info_cache.time.time", return_value=0.0):
                cache.get_available_nodes()
        assert factory.call_count == 1


class TestSingleFlight:
    def test_simultaneous_callers_trigger_one_refresh(self):
        # Without this, N concurrent generations each see an expired cache and each open a
        # request — against the endpoint already established as slow under load, making the
        # stampede worst exactly when the server can least afford it.
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0)
        barrier = threading.Barrier(8)

        def slow_get(*_a, **_k):
            time.sleep(0.05)
            resp = MagicMock()
            resp.json.return_value = NODES
            resp.raise_for_status = MagicMock()
            return resp

        factory, _ = _ok_client(on_get=slow_get)
        results: list[int] = []

        def worker():
            barrier.wait()
            results.append(len(cache.get_available_nodes()))

        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert factory.call_count == 1
        # And every waiter got the answer, rather than an empty list because it lost the race.
        assert results == [len(NODES)] * 8

    def test_a_failed_refresh_is_also_single_flight(self):
        cache = ComfyObjectInfoCache("http://mock:8188", failure_ttl_seconds=30.0)
        barrier = threading.Barrier(6)

        def slow_fail(*_a, **_k):
            time.sleep(0.05)
            raise RuntimeError("refused")

        factory, _ = _ok_client(on_get=slow_fail)

        def worker():
            barrier.wait()
            cache.get_available_nodes()

        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert factory.call_count == 1


class TestCacheOnlyMode:
    """``allow_network=False`` — the mode the image-generation path uses."""

    def test_it_never_opens_a_socket(self):
        cache = ComfyObjectInfoCache("http://mock:8188")
        factory, _ = _failing_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            assert cache.get_available_nodes(allow_network=False) == []
        assert factory.call_count == 0

    def test_it_serves_a_warmed_cache(self):
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300.0)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()  # warmup
        with patch("app.comfy_utils.object_info_cache.httpx.Client", _failing_client()[0]):
            assert "KSampler" in cache.get_available_nodes(allow_network=False)

    def test_it_serves_stale_data_rather_than_blocking(self):
        # Stale node metadata is a far better basis for a diagnostic than delaying a generation
        # to refresh it. The refresh happens off this path.
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=0.05)
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
        time.sleep(0.08)
        blocker, _ = _failing_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", blocker):
            assert "KSampler" in cache.get_available_nodes(allow_network=False)
        assert blocker.call_count == 0


class TestObservability:
    def test_stats_report_what_happened(self):
        # A cache whose failures are invisible is how a 30-second stall per image survived this
        # long. None of this changes behaviour; all of it is readable from a debug endpoint.
        cache = ComfyObjectInfoCache("http://mock:8188")
        factory, _ = _failing_client(TimeoutError("read timeout"))
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.get_available_nodes()
        stats = cache.stats()
        assert stats["last_status"] == "error"
        assert stats["last_error_type"] == "TimeoutError"
        assert stats["negative"] is True
        assert stats["failures"] == 1
        assert stats["last_duration_ms"] is not None

    def test_stats_never_trigger_a_fetch(self):
        cache = ComfyObjectInfoCache("http://mock:8188")
        factory, _ = _ok_client()
        with patch("app.comfy_utils.object_info_cache.httpx.Client", factory):
            cache.stats()
        assert factory.call_count == 0

    def test_repeated_failures_are_not_logged_per_call(self, caplog):
        # A server that is simply not running should not write a megabyte of identical warnings
        # over an afternoon — one line per failure window, not one per generated image.
        cache = ComfyObjectInfoCache("http://mock:8188", failure_ttl_seconds=0.02)
        factory, _ = _failing_client()
        with caplog.at_level("WARNING"), patch(
            "app.comfy_utils.object_info_cache.httpx.Client", factory
        ):
            for _ in range(5):
                cache.get_available_nodes()
        assert len([r for r in caplog.records if "/object_info" in r.getMessage()]) == 1
