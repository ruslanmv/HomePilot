"""
Unit tests for ``voice_call.barge_in``.

Anchored to the contract in
``docs/analysis/voice-call-streaming-design.md`` § 4.3. Each test
names the exact invariant it protects so a regression points at the
broken guarantee, not at a generic symptom.
"""
from __future__ import annotations

import asyncio

import pytest

from app.voice_call import barge_in as bi


@pytest.fixture(autouse=True)
def _clean_registry():
    bi._reset_for_tests()
    yield
    bi._reset_for_tests()


# ── token semantics ──────────────────────────────────────────────────

def test_new_token_creates_uncancelled():
    """A fresh token starts with ``is_cancelled() == False``."""
    t = bi.new_token("sid_1", "turn_1")
    assert t.turn_id == "turn_1"
    assert t.is_cancelled() is False


def test_cancel_is_idempotent():
    """Setting an already-set ``asyncio.Event`` is a no-op — the
    second call from a doubled-up barge-in must not raise."""
    t = bi.new_token("sid_2", "turn_2")
    t.cancel()
    t.cancel()
    assert t.is_cancelled() is True


# ── cancel_active — the central guarantee ────────────────────────────

def test_cancel_active_with_matching_id_cancels():
    """Happy path: WS handler cancels the token for the turn it saw."""
    bi.new_token("sid_3", "turn_3")
    assert bi.cancel_active("sid_3", "turn_3") is True
    assert bi.get_active("sid_3").is_cancelled() is True


def test_cancel_active_with_stale_id_is_silent_noop():
    """Stale barge-in race (user interrupted turn A; by the time the
    signal arrived, turn B had already started) — must NOT cancel
    the currently-active turn. § 4.3 / § 6 'Barge-in fires but the
    turn is already over'."""
    bi.new_token("sid_4", "turn_A")  # active
    # Client thought it was barging in on turn_STALE.
    assert bi.cancel_active("sid_4", "turn_STALE") is False
    # The real active turn is still live.
    assert bi.get_active("sid_4").is_cancelled() is False


def test_cancel_active_with_no_turn_returns_false():
    assert bi.cancel_active("sid_never_started", "turn_x") is False


def test_new_token_replaces_prior_token():
    """Defensive — if a new turn starts without the previous one
    being cleared (an upstream bug) we don't leak the old token."""
    bi.new_token("sid_5", "turn_old")
    bi.new_token("sid_5", "turn_new")
    assert bi.get_active("sid_5").turn_id == "turn_new"


# ── clear_session ────────────────────────────────────────────────────

def test_clear_session_cancels_in_flight_turn():
    """WS close path — the streaming runner must exit promptly."""
    bi.new_token("sid_6", "turn_6")
    token = bi.get_active("sid_6")
    bi.clear_session("sid_6")
    assert token.is_cancelled() is True
    assert bi.get_active("sid_6") is None


def test_clear_session_is_noop_when_nothing_active():
    bi.clear_session("sid_never_had_anything")  # must not raise


# ── awaitable ────────────────────────────────────────────────────────

def test_token_wait_returns_when_cancelled():
    """Callers that prefer ``await token.wait()`` over polling get a
    normal return (no exception) on cancel."""

    async def _run() -> bool:
        token = bi.new_token("sid_7", "turn_7")

        async def _canceller() -> None:
            await asyncio.sleep(0.01)
            bi.cancel_active("sid_7", "turn_7")

        await asyncio.gather(token.wait(), _canceller())
        return token.is_cancelled()

    assert asyncio.run(_run()) is True
