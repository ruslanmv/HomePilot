"""
Tests for the image-model warmup hook.

Best-practice contract: warmup is best-effort and NEVER blocks
startup, so every failure mode must be swallowed silently (WARN
log only).

These tests are intentionally black-box — they only control the
environment + the module-local deadline, never patch internals.
That keeps them robust against conftest's session-fixture module
purge, which has repeatedly broken tests that reach into
``app.*`` submodules by dotted path.
"""
from __future__ import annotations

import asyncio
import logging

import pytest


def test_warmup_enabled_default_true(monkeypatch):
    from app.warmup import warmup_enabled
    monkeypatch.delenv("INTERACTIVE_WARMUP_IMAGE", raising=False)
    assert warmup_enabled() is True


def test_warmup_enabled_explicit_falsy_opts_out(monkeypatch):
    from app.warmup import warmup_enabled
    for value in ["false", "0", "no", "off", "n"]:
        monkeypatch.setenv("INTERACTIVE_WARMUP_IMAGE", value)
        assert warmup_enabled() is False, value


def test_warmup_unknown_value_falls_back_to_default(monkeypatch):
    from app.warmup import warmup_enabled
    monkeypatch.setenv("INTERACTIVE_WARMUP_IMAGE", "maybe")
    assert warmup_enabled() is True


def test_warmup_skipped_when_disabled_returns_fast(monkeypatch):
    """Falsy env → warm_image_model_on_startup must early-out
    before hitting any I/O. If the early-out regresses, the
    function will block on a real ComfyUI / lookup and this
    test's 1.0s deadline will fire."""
    from app import warmup as warmup_mod
    monkeypatch.setenv("INTERACTIVE_WARMUP_IMAGE", "false")
    asyncio.run(
        asyncio.wait_for(warmup_mod.warm_image_model_on_startup(), timeout=1.0),
    )


def test_warmup_never_raises_on_missing_comfy(monkeypatch):
    """If ComfyUI isn't reachable (the default in CI), the
    warmup must still return cleanly — failures are logged at
    WARN, never propagated. Contract: startup stays green."""
    from app import warmup as warmup_mod
    monkeypatch.delenv("INTERACTIVE_WARMUP_IMAGE", raising=False)
    # Shrink the deadline so a no-comfy probe doesn't block the
    # test for 90s; we only care that the function returns.
    monkeypatch.setattr(warmup_mod, "_DEFAULT_WARMUP_TIMEOUT_S", 0.5)
    # Shrink the readiness probe too or the test waits 10 min for
    # the default _COMFY_READY_MAX_WAIT_S (600 s) before giving up.
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_MAX_WAIT_S", 0.3)
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_POLL_INTERVAL_S", 0.05)
    # Must complete within the timeout + a small slack.
    asyncio.run(
        asyncio.wait_for(warmup_mod.warm_image_model_on_startup(), timeout=5.0),
    )


def test_warmup_reports_to_logger(monkeypatch, caplog):
    """Best-practice: warmup must leave an audit trail (INFO or
    WARN) so operators can see whether the cold-load penalty
    was amortised at boot."""
    from app import warmup as warmup_mod
    monkeypatch.delenv("INTERACTIVE_WARMUP_IMAGE", raising=False)
    monkeypatch.setattr(warmup_mod, "_DEFAULT_WARMUP_TIMEOUT_S", 0.5)
    # Shrink the readiness probe too or the test waits 10 min for
    # the default _COMFY_READY_MAX_WAIT_S (600 s) before giving up.
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_MAX_WAIT_S", 0.3)
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_POLL_INTERVAL_S", 0.05)
    caplog.set_level(logging.INFO, logger="app.warmup")
    asyncio.run(
        asyncio.wait_for(warmup_mod.warm_image_model_on_startup(), timeout=5.0),
    )
    joined = " ".join(r.message for r in caplog.records).lower()
    assert "warmup" in joined


# ── Readiness probe ──────────────────────────────────────────────

def test_wait_for_comfy_returns_false_when_unreachable(monkeypatch):
    """When ComfyUI is offline, the probe loop must terminate on
    its own budget rather than hang startup."""
    from app import warmup as warmup_mod
    # Shrink the probe budget so the test doesn't wait the default
    # 10 minutes. A handful of short probes against a closed port
    # is enough to exercise the timeout path.
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_MAX_WAIT_S", 0.4)
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_POLL_INTERVAL_S", 0.1)
    result = asyncio.run(
        warmup_mod._wait_for_comfy_ready(
            "http://127.0.0.1:65432",  # reserved/closed
            max_wait_s=0.4,
            interval_s=0.1,
        ),
    )
    assert result is False


def test_wait_for_comfy_returns_true_on_200(monkeypatch):
    """When /system_stats responds 200, the loop returns True on
    the first probe. We stub httpx.AsyncClient so the test runs
    without a real ComfyUI."""
    from app import warmup as warmup_mod

    class _FakeResp:
        status_code = 200

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url):
            return _FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    result = asyncio.run(
        warmup_mod._wait_for_comfy_ready(
            "http://comfyui.local:8188",
            max_wait_s=2.0,
            interval_s=0.05,
        ),
    )
    assert result is True


def test_warm_image_model_on_startup_waits_for_comfy(monkeypatch):
    """Happy-path smoke: when INTERACTIVE_WARMUP_IMAGE is on and
    IMAGE_MODEL is set, the coroutine reaches the readiness probe
    before attempting run_workflow. We return early by making the
    probe report "not ready" so we don't need a real Comfy."""
    from app import warmup as warmup_mod
    monkeypatch.setenv("INTERACTIVE_WARMUP_IMAGE", "true")
    monkeypatch.setenv("IMAGE_MODEL", "dreamshaper_8.safetensors")
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_MAX_WAIT_S", 0.2)
    monkeypatch.setattr(warmup_mod, "_COMFY_READY_POLL_INTERVAL_S", 0.05)

    submit_called = {"n": 0}
    import app.comfy as comfy

    def should_not_fire(*a, **kw):
        submit_called["n"] += 1
        return {}
    monkeypatch.setattr(comfy, "run_workflow", should_not_fire)

    asyncio.run(
        asyncio.wait_for(warmup_mod.warm_image_model_on_startup(), timeout=3.0),
    )
    # Comfy wasn't reachable → readiness returned False →
    # run_workflow must NOT have been called. That's the fix:
    # no more "Connection refused" submit before ComfyUI is up.
    assert submit_called["n"] == 0
