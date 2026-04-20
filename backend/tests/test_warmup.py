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
    caplog.set_level(logging.INFO, logger="app.warmup")
    asyncio.run(
        asyncio.wait_for(warmup_mod.warm_image_model_on_startup(), timeout=5.0),
    )
    joined = " ".join(r.message for r in caplog.records).lower()
    assert "warmup" in joined
