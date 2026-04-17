"""
persona_call unit tests.

These tests exercise the *pure logic* of persona_call directly without
re-importing ``app.main``. Re-importing split the ``ProviderPolicy``
class in two and flaked downstream studio tests — so we import the
persona_call submodules directly, use ``monkeypatch`` to flip env
flags for the duration of one test only, and never touch the session-
scoped FastAPI app except in one flag-off HTTP check.

Seven test groups, each anchored to a rule from the research digest:

  1. Flag-off invariant — every HTTP path 404s.
  2. Phase machine — opening/topic/pre_closing/closed transitions.
  3. Anti-repetition ledger — recent acks / openers rolled + forbidden.
  4. Late-night brevity — context frame only fires at/after 22:00 local.
  5. Closing handshake — the one enforced state transition.
  6. Backchannel cadence — at most one per min_gap_ms, clause-triggered.
  7. Filler latency — >filler_emit_after_ms triggers exactly one filler.
  8. Persona-prompt invariance — turn.run_turn's system_prompt stays
     untouched; persona_call only uses ``additional_system``.
"""
from __future__ import annotations

import asyncio
import datetime as _dt

import pytest


# ── module-local imports — NO app.main reload ────────────────────────

from app.persona_call import (
    backchannel as bc_mod,
    closing as closing_mod,
    config as pc_config_mod,
    context as ctx_mod,
    directive as directive_mod,
    facets as facets_mod,
    latency as latency_mod,
    state as state_mod,
    store as pc_store,
)


@pytest.fixture
def flagged_cfg(monkeypatch) -> pc_config_mod.PersonaCallConfig:
    """Return a PersonaCallConfig with ENABLED=True and stable
    thresholds — monkeypatch auto-cleans env on teardown so later tests
    can't see our flags."""
    monkeypatch.setenv("PERSONA_CALL_ENABLED", "true")
    monkeypatch.setenv("PERSONA_CALL_APPLY", "true")
    monkeypatch.setenv("PERSONA_CALL_HAY_LATE_HOUR", "21")
    monkeypatch.setenv("PERSONA_CALL_LATE_HOUR", "22")
    monkeypatch.setenv("PERSONA_CALL_LATE_HOUR_END", "6")
    monkeypatch.setenv("PERSONA_CALL_FILLER_AFTER_MS", "80")
    monkeypatch.setenv("PERSONA_CALL_REASON_FALLBACK_TURN", "3")
    return pc_config_mod.load()


@pytest.fixture(autouse=True)
def _clean_persona_tables():
    """Wipe persona_call tables around every test so we never see
    state from another test leaking in."""
    pc_store.ensure_schema()
    pc_store._reset_for_tests()
    yield
    pc_store._reset_for_tests()


# ══════════════════════════════════════════════════════════════════════
# 1. Flag-off HTTP invariant
# ══════════════════════════════════════════════════════════════════════
# Relies on the session-scoped `app` fixture from conftest.py being
# initialized BEFORE persona_call tests flip any env flag. When the
# app was first imported, both flags were off (production default)
# → every /v1/persona-call/* path 404s on that cached app.

def test_flag_off_paths_return_404(client):
    for path in (
        "/v1/persona-call/facets/some_id",
        "/v1/persona-call/state/vcs_abc",
        "/v1/persona-call/last-directive/vcs_abc",
    ):
        r = client.get(path)
        assert r.status_code == 404, f"{path} → {r.status_code}"


# ══════════════════════════════════════════════════════════════════════
# 2. Phase machine
# ══════════════════════════════════════════════════════════════════════

def test_phase_machine_opens_and_enters_topic(flagged_cfg):
    env = ctx_mod.compute_env(
        tz="America/New_York",
        now=_dt.datetime(2025, 1, 1, 15, 0, tzinfo=_dt.timezone.utc),
    )
    sid = "vcs_test_phase_1"
    d0 = directive_mod.compose(
        session_id=sid, persona_id=None,
        user_text="hi", env=env, cfg=flagged_cfg,
    )
    assert d0.phase == "opening"
    assert d0.turn_index == 1
    assert "opening.summons_answer" in d0.post_directives
    d1 = directive_mod.compose(
        session_id=sid, persona_id=None,
        user_text="Hey, I'm calling about the invoice you sent.",
        env=env, cfg=flagged_cfg,
    )
    assert d1.phase == "topic", f"expected 'topic', got {d1.phase}"


def test_phase_machine_skips_how_are_you_when_rushed(flagged_cfg):
    env = ctx_mod.compute_env(
        tz="UTC",
        now=_dt.datetime(2025, 1, 1, 10, 0, tzinfo=_dt.timezone.utc),
    )
    sid = "vcs_test_phase_rush"
    directive_mod.compose(session_id=sid, persona_id=None,
                          user_text="hey", env=env, cfg=flagged_cfg)
    d = directive_mod.compose(
        session_id=sid, persona_id=None,
        user_text="Quick question — can I ask something fast?",
        env=env, cfg=flagged_cfg,
    )
    assert "opening.skip_how_are_you" in d.post_directives
    assert "opening.how_are_you_once" not in d.post_directives


# ══════════════════════════════════════════════════════════════════════
# 3. Anti-repetition ledger
# ══════════════════════════════════════════════════════════════════════

def test_repetition_ledger_forbids_recently_used_tokens(flagged_cfg):
    env = ctx_mod.compute_env(tz="UTC")
    sid = "vcs_test_repetition"
    pc_store.ensure_state(sid)
    pc_store.update_state(sid, recent_acks=["mm", "mm-hm"],
                          recent_openers=["mm"])
    d = directive_mod.compose(
        session_id=sid, persona_id=None,
        user_text="okay so tell me about your day",
        env=env, cfg=flagged_cfg,
    )
    assert "repeat.ledger" in d.post_directives
    lower = d.system_suffix.lower()
    assert "mm" in lower or "mm-hm" in lower


def test_record_persona_reply_rolls_ledger(flagged_cfg):
    env = ctx_mod.compute_env(tz="UTC")
    sid = "vcs_test_roll"
    directive_mod.compose(session_id=sid, persona_id=None,
                          user_text="hi", env=env, cfg=flagged_cfg)
    directive_mod.record_persona_reply(
        session_id=sid, persona_id=None,
        reply="mm yeah I hear you — what's up?",
        cfg=flagged_cfg,
    )
    s = pc_store.get_state(sid)
    assert "mm" in s["recent_acks"], s
    assert s["recent_openers"][0] == "mm"


# ══════════════════════════════════════════════════════════════════════
# 4. Late-night brevity
# ══════════════════════════════════════════════════════════════════════

def test_late_night_brevity_fires_at_22(flagged_cfg):
    late = ctx_mod.compute_env(
        tz="UTC",
        now=_dt.datetime(2025, 1, 1, 22, 0, tzinfo=_dt.timezone.utc),
    )
    early = ctx_mod.compute_env(
        tz="UTC",
        now=_dt.datetime(2025, 1, 1, 20, 0, tzinfo=_dt.timezone.utc),
    )
    d_late = directive_mod.compose(
        session_id="vcs_late", persona_id=None,
        user_text="tell me about yourself", env=late, cfg=flagged_cfg,
    )
    d_early = directive_mod.compose(
        session_id="vcs_early", persona_id=None,
        user_text="tell me about yourself", env=early, cfg=flagged_cfg,
    )
    assert "context.late_night_brevity" in d_late.post_directives
    assert "context.late_night_brevity" not in d_early.post_directives


# ══════════════════════════════════════════════════════════════════════
# 5. Closing handshake — the one enforced override
# ══════════════════════════════════════════════════════════════════════

def test_closing_handshake_two_phase(flagged_cfg):
    env = ctx_mod.compute_env(tz="UTC")
    sid = "vcs_close"
    directive_mod.compose(session_id=sid, persona_id=None,
                          user_text="I'm calling about the bill",
                          env=env, cfg=flagged_cfg)
    d1 = directive_mod.compose(session_id=sid, persona_id=None,
                               user_text="okay",
                               env=env, cfg=flagged_cfg)
    assert d1.phase == "pre_closing"
    assert "closing.pre_closing_handshake" in d1.post_directives
    assert "do not say 'goodbye'" in d1.system_suffix.lower()

    d2 = directive_mod.compose(session_id=sid, persona_id=None,
                               user_text="bye",
                               env=env, cfg=flagged_cfg)
    assert d2.phase == "closed"
    assert "closing.terminal" in d2.post_directives
    assert "two-part" in d2.system_suffix.lower()


# ══════════════════════════════════════════════════════════════════════
# 6. Backchannel cadence
# ══════════════════════════════════════════════════════════════════════

def test_backchannel_emit_decision(flagged_cfg):
    f = facets_mod.default_facets()
    assert bc_mod.should_emit(
        partial_text="hello",
        last_backchannel_ms=0, facets=f, cfg=flagged_cfg,
    ) is False
    assert bc_mod.should_emit(
        partial_text="so I went to the store, and then I realized",
        last_backchannel_ms=0, facets=f, cfg=flagged_cfg,
    ) is True
    import time
    now_ms = int(time.time() * 1000)
    assert bc_mod.should_emit(
        partial_text="so I went to the store, and then I realized",
        last_backchannel_ms=now_ms, facets=f, cfg=flagged_cfg,
    ) is False


def test_backchannel_token_avoids_last_used():
    f = facets_mod.default_facets()
    t = bc_mod.choose_token(f, recent_acks=["mm"], seed_utterance="so yeah")
    assert t is not None
    assert t.lower() != "mm"


# ══════════════════════════════════════════════════════════════════════
# 7. Filler latency
# ══════════════════════════════════════════════════════════════════════

def test_filler_emits_on_slow_turn(flagged_cfg):
    f = facets_mod.default_facets()

    async def _run():
        events = []

        async def capture(env):
            events.append(env)

        async with latency_mod.FillerScheduler(
            send=capture, facets=f, cfg=flagged_cfg, session_id="vcs_filler",
        ):
            await asyncio.sleep(0.2)
        assert any(e.get("type") == "assistant.filler" for e in events), events
        assert events[0]["payload"]["token"] in f.thinking_tokens

    asyncio.run(_run())


def test_filler_does_not_emit_on_fast_turn(flagged_cfg, monkeypatch):
    monkeypatch.setenv("PERSONA_CALL_FILLER_AFTER_MS", "500")
    cfg = pc_config_mod.load()
    f = facets_mod.default_facets()

    async def _run():
        events = []

        async def capture(env):
            events.append(env)

        async with latency_mod.FillerScheduler(
            send=capture, facets=f, cfg=cfg, session_id="vcs_fast",
        ):
            await asyncio.sleep(0.05)
        assert not any(e.get("type") == "assistant.filler" for e in events), events

    asyncio.run(_run())


# ══════════════════════════════════════════════════════════════════════
# 8. Persona-prompt invariance — the product promise
# ══════════════════════════════════════════════════════════════════════

def test_persona_call_never_overrides_system_prompt():
    """persona_call's composer MUST produce an `additional_system`
    (suffix), NEVER rewrite the persona's base system prompt."""
    import inspect
    from app.voice_call import turn

    params = inspect.signature(turn.run_turn).parameters
    assert "system_prompt" in params, \
        "turn.run_turn must still support system_prompt (unchanged)"
    assert "additional_system" in params, \
        "turn.run_turn must accept additional_system (persona_call hook)"

    fields = {
        f.name for f in directive_mod.ComposedDirective.__dataclass_fields__.values()
    }
    assert "system_suffix" in fields
    assert "system_prompt" not in fields, (
        "ComposedDirective must not carry a 'system_prompt' field — "
        "persona_call only composes a suffix, never a replacement prompt."
    )
