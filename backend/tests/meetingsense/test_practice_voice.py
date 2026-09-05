"""Practice, and the voice that reaches the call (batch MS27, wave W9).

Practice is the only mode that speaks aloud, and everything difficult about it is somebody
else's code: `voice_call/` owns turn-taking and barge-in, `voice/providers.py` owns which voice
you are entitled to, and the operating system owns whether audio can reach a microphone at all.

So most of these tests are about **not** reimplementing those. The rehearsal opens a voice-call
session through `create_session` so its policy check is the one that runs; barge-in goes
straight to the registry that already refuses stale turn ids; the TTS tier is `get_tts_provider`'s
choice and not a second entitlement decision.

The rest is the refusal. A browser cannot put sound into a meeting's microphone, and the
failure mode that matters is a rehearsal partner audible in the room but not in the call — a
feature that appears to work and does not. So it says which "no" it is, and the setup wizard
verifies rather than congratulating.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    import app.meetingsense.agent.practice as practice
    import app.meetingsense.agent.voice_out as voice_out
    import app.meetingsense.store as store_mod

    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(store_mod, "_connect", _connect)
    store_mod.migrate()
    store_mod.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
    return type("M", (), {"practice": practice, "voice": voice_out, "store": store_mod})


# ── the rehearsal brief ─────────────────────────────────────────────────────


class TestBrief:
    def test_a_rehearsal_is_set_up_and_read_back(self, mods):
        assert mods.practice.set_brief("m1", kind="interview", role="a sceptical CFO")
        assert mods.practice.brief("m1")["role"] == "a sceptical CFO"

    def test_a_bare_kind_is_enough(self, mods):
        # Demanding a paragraph before the user can start is how a rehearsal feature goes
        # unused.
        assert mods.practice.set_brief("m1", kind="exam")["kind"] == "exam"

    def test_an_unknown_shape_is_refused(self, mods):
        # A rehearsal nobody wrote a brief for is one the assistant improvises, which is how a
        # mock interview becomes an argument.
        assert mods.practice.set_brief("m1", kind="karaoke") is None
        assert mods.practice.brief("m1") is None

    def test_the_last_brief_wins(self, mods):
        mods.practice.set_brief("m1", kind="interview")
        mods.practice.set_brief("m1", kind="negotiation")
        assert mods.practice.brief("m1")["kind"] == "negotiation"

    def test_the_shape_is_matched_loosely(self, mods):
        assert mods.practice.set_brief("m1", kind="  Interview ")["kind"] == "interview"

    def test_no_brief_is_no_brief(self, mods):
        assert mods.practice.brief("m1") is None

    def test_deleting_the_meeting_takes_the_brief(self, mods):
        mods.practice.set_brief("m1", kind="interview")
        mods.store.delete_meeting("m1")
        assert mods.practice.brief("m1") is None


class TestSystemPrompt:
    def test_each_shape_has_its_own_paragraph(self, mods):
        seen = {mods.practice.system_prompt({"kind": k}) for k in mods.practice.KINDS}
        assert len(seen) == len(mods.practice.KINDS)

    def test_the_role_and_the_notes_land_in_it(self, mods):
        text = mods.practice.system_prompt(
            {"kind": "interview", "role": "a sceptical CFO", "notes": "unit economics"})
        assert "a sceptical CFO" in text and "unit economics" in text

    def test_it_always_says_to_stay_in_role(self, mods):
        for kind in mods.practice.KINDS:
            assert "in role" in mods.practice.system_prompt({"kind": kind})

    def test_no_brief_invents_no_interview(self, mods):
        assert mods.practice.system_prompt(None) == ""
        assert mods.practice.system_prompt({"kind": "karaoke"}) == ""


# ── opening the call ────────────────────────────────────────────────────────


class Calls:
    def __init__(self, session=None):
        self.made = []
        self.session = session if session is not None else {"id": "call_1", "resume_token": "SECRET"}

    def __call__(self, **kwargs):
        self.made.append(kwargs)
        return self.session


class TestOpenCall:
    def test_it_opens_through_voice_call(self, mods):
        # Not beside it: `voice_call` owns turn-taking, streaming, resume and the policy that
        # decides who may open a call.
        mods.practice.set_brief("m1", kind="interview")
        create = Calls()
        out = mods.practice.open_call("m1", user_id="u1", create=create, cfg=object())
        assert out["ok"] is True and out["call_id"] == "call_1"
        assert create.made[0]["entry_mode"] == "meetingsense_practice"

    def test_the_policy_check_is_theirs_not_ours(self, mods):
        # `create_session` gates on entitlement. A MeetingSense path that skipped it would be a
        # second door into the same room.
        mods.practice.set_brief("m1", kind="interview")

        def refuse(**kwargs):
            raise RuntimeError("voice calls are not enabled for this user")

        out = mods.practice.open_call("m1", user_id="u1", create=refuse, cfg=object())
        assert out["ok"] is False and "not enabled" in out["reason"]

    def test_the_resume_token_is_not_echoed_back(self, mods):
        # `create_session`'s own docstring: callers must keep it out of anything that lands in
        # a log, and a meeting frame is a thing that lands in a log.
        mods.practice.set_brief("m1", kind="interview")
        out = mods.practice.open_call("m1", user_id="u1", create=Calls(), cfg=object())
        assert "SECRET" not in repr(out)
        assert "resume_token" not in out

    def test_no_rehearsal_means_no_call(self, mods):
        create = Calls()
        out = mods.practice.open_call("m1", user_id="u1", create=create, cfg=object())
        assert out["ok"] is False
        assert create.made == []

    def test_an_install_with_no_voice_stack_says_so(self, mods):
        mods.practice.set_brief("m1", kind="interview")
        out = mods.practice.open_call("m1", user_id="u1", create=None)
        assert out["ok"] is False and "not available" in out["reason"]

    def test_a_session_with_no_id_is_not_a_call(self, mods):
        mods.practice.set_brief("m1", kind="interview")
        out = mods.practice.open_call("m1", user_id="u1", create=Calls(session={}), cfg=object())
        assert out["ok"] is False

    def test_the_call_is_recorded_against_the_meeting(self, mods):
        mods.practice.set_brief("m1", kind="interview")
        mods.practice.open_call("m1", user_id="u1", create=Calls(), cfg=object())
        assert mods.practice.calls("m1") == ["call_1"]


# ── barge-in ────────────────────────────────────────────────────────────────


class TestBargeIn:
    @pytest.fixture()
    def registry(self):
        import app.voice_call.barge_in as module

        module._reset_for_tests()
        return module

    def test_it_cancels_the_active_turn(self, mods, registry):
        async def scenario():
            token = registry.new_token("call_1", "turn_1")
            assert mods.practice.interrupt("call_1", registry=registry) is True
            assert token.is_cancelled() is True

        run(scenario())

    def test_a_stale_turn_id_is_a_silent_no_op(self, mods, registry):
        # The registry already refuses this, and MeetingSense must not second-guess it: a
        # barge-in racing a new turn would otherwise cancel the turn that just started.
        async def scenario():
            token = registry.new_token("call_1", "turn_2")
            assert mods.practice.interrupt("call_1", registry=registry, turn_id="turn_1") is False
            assert token.is_cancelled() is False

        run(scenario())

    def test_with_no_active_turn_there_is_nothing_to_interrupt(self, mods, registry):
        assert mods.practice.interrupt("call_1", registry=registry) is False

    def test_no_call_id_is_no_interrupt_and_no_lookup(self, mods, registry):
        # A fast path rather than a correctness guard — the registry would answer False for a
        # session it has never seen — so what it has to prove is that it *skips the lookup*.
        # A client that lost its call id sends a partial transcript per breath.
        looked = []

        class Counting:
            def get_active(self, sid):
                looked.append(sid)
                return None

            def cancel_active(self, sid, tid):
                looked.append(sid)
                return False

        assert mods.practice.interrupt("", registry=Counting()) is False
        assert mods.practice.interrupt("", registry=Counting(), turn_id="t1") is False
        assert looked == []

    def test_a_registry_that_raises_is_not_a_crash(self, mods):
        class Angry:
            def get_active(self, sid):
                raise RuntimeError("registry is gone")

        assert mods.practice.interrupt("call_1", registry=Angry()) is False

    def test_there_is_no_second_registry(self, mods):
        # A second place tracking which turn is live is a second answer to "is the assistant
        # still talking", and they would disagree exactly when it mattered.
        import inspect

        # The claim is that this module holds no turn state of its own, so the check is for
        # the things state is made of. ("cancel_active" contains "_active", which is why the
        # name of the registry function is not the thing being looked for.)
        source = inspect.getsource(mods.practice)
        for forbidden in ("asyncio.Event", "threading.Lock", "BargeInToken(", "_active[",
                          "_active =", "_active.get", "_active.pop"):
            assert forbidden not in source, f"practice.py keeps its own turn state: {forbidden}"


# ── the virtual microphone ──────────────────────────────────────────────────


class TestCapability:
    def test_a_browser_is_refused_with_a_reason_it_can_act_on(self, mods):
        out = mods.voice.capability(desktop=False)
        assert out["ok"] is False and out["reason"] == "browser"
        assert "desktop app" in out["detail"]

    def test_a_browser_is_not_offered_a_driver_it_cannot_use(self, mods):
        # Instructions the user cannot act on read as a wizard that did not understand the
        # question.
        assert "guide" not in mods.voice.capability(desktop=False)

    def test_the_desktop_with_no_device_gets_the_install_steps(self, mods):
        out = mods.voice.capability(desktop=True, devices=["MacBook Microphone"], system="Darwin")
        assert out["ok"] is False and out["reason"] == "no_virtual_device"
        assert out["guide"]["product"] == "BlackHole"
        assert out["guide"]["steps"]

    def test_the_desktop_with_a_device_is_ready(self, mods):
        out = mods.voice.capability(desktop=True, system="Darwin",
                                    devices=["MacBook Microphone", "BlackHole 2ch"])
        assert out["ok"] is True and out["device"] == "BlackHole 2ch"

    @pytest.mark.parametrize("system,device", [
        ("Windows", "CABLE Input (VB-Audio Virtual Cable)"),
        ("Windows", "Voicemeeter Input"),
        ("Darwin", "BlackHole 2ch"),
        ("Darwin", "Loopback Audio"),
        ("Linux", "virtual_mic"),
    ])
    def test_each_platform_recognises_its_own(self, mods, system, device):
        assert mods.voice.detect([device], system=system) == device

    def test_a_real_microphone_is_not_a_virtual_one(self, mods):
        assert mods.voice.detect(["MacBook Pro Microphone", "AirPods"], system="Darwin") is None

    def test_an_unknown_platform_gets_the_pulse_instructions(self, mods):
        # Anything that is not Windows or macOS and is running this is running something
        # PulseAudio-shaped.
        assert "null sink" in mods.voice.guide("Haiku")["product"]

    def test_no_devices_at_all(self, mods):
        assert mods.voice.detect([], system="Darwin") is None
        assert mods.voice.detect(["", "   "], system="Darwin") is None


# ── synthesis ───────────────────────────────────────────────────────────────


class Voice:
    def __init__(self, audio=b"RIFF...."):
        self.said = []
        self.audio = audio

    async def synth(self, text):
        self.said.append(text)
        return self.audio


class TestSynth:
    def test_it_speaks_through_the_provider_it_is_given(self, mods):
        voice = Voice()
        assert run(mods.voice.synth("hello there", provider=voice)) == b"RIFF...."
        assert voice.said == ["hello there"]

    def test_citations_are_not_read_aloud(self, mods):
        # MS13 asks for [hh:mm:ss] on anything quoted, which is right on a card and unreadable
        # out loud. "bracket zero zero twelve thirty bracket" is not a rehearsal partner.
        voice = Voice()
        run(mods.voice.synth("We agreed forty a seat [00:12:30] on Tuesday.", provider=voice))
        assert voice.said == ["We agreed forty a seat on Tuesday."]

    def test_a_monologue_is_cut(self, mods):
        voice = Voice()
        run(mods.voice.synth(" ".join(["word"] * 300), provider=voice))
        assert len(voice.said[0].split()) == mods.voice.MAX_SPOKEN_WORDS

    def test_nothing_to_say_asks_for_no_audio(self, mods):
        voice = Voice()
        assert run(mods.voice.synth("   ", provider=voice)) is None
        assert run(mods.voice.synth("[00:00:01]", provider=voice)) is None
        assert voice.said == []

    def test_a_provider_that_raises_is_silence_not_a_crash(self, mods):
        class Angry:
            async def synth(self, text):
                raise RuntimeError("the voice model is down")

        assert run(mods.voice.synth("hello", provider=Angry())) is None

    def test_the_tier_is_the_providers_choice_not_ours(self, mods, monkeypatch):
        # `providers.py`: "the quality tier is a server-side choice, never a client change".
        # A MeetingSense-specific voice selection would be a second place deciding what a user
        # is entitled to, which is the shape of every entitlement bug.
        import inspect

        source = inspect.getsource(mods.voice)
        assert "get_tts_provider" in source
        for forbidden in ("CloudNeuralTTSProvider", "TTS_BASE_URL", "get_tts_provider_by_name"):
            assert forbidden not in source

    def test_the_entitlement_is_passed_through(self, mods, monkeypatch):
        import app.voice.providers as providers

        seen = []
        monkeypatch.setattr(providers, "get_tts_provider",
                            lambda premium=False: seen.append(premium) or Voice())
        run(mods.voice.synth("hello", premium=True))
        run(mods.voice.synth("hello", premium=False))
        assert seen == [True, False]
