"""The voice uplink (B10) — mic to reply to gesture, and what happens when it can't.

B10 is an integration batch, so most of what is worth asserting is *negative*: that this
module does not transcribe, does not run a model, does not own cancellation, and refuses
cleanly when the thing it integrates with is not there. The turn runner is injected in
every test below, which is the same statement in a different form — if the uplink needed
to know how a turn is run, it could not be handed a fake one.

The two acceptance sentences B10 is bought on:

  * speech → reply → gesture end to end, which is ``test_speech_becomes_a_reply_and_a_gesture``;
  * declining the mic leaves every other channel working, which is the last class.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.avatar_director.config import AvatarDirectorConfig, VoiceConfig, load_config
from app.avatar_director.protocol import EMOTE_WHITELIST, ProtocolHandler
from app.avatar_director.rtc import VoiceUplink, split_emote_tags, webrtc_terminus


def uplink(*, reply="Hello.", media="transcript", terminus=None, enabled=True, fail=None, calls=None):
    """An uplink whose turn path is a fake. Records every call it was asked to make."""
    seen = calls if calls is not None else []

    async def run_turn(**kwargs):
        seen.append(kwargs)
        if fail is not None:
            raise fail
        return reply(kwargs["user_text"]) if callable(reply) else reply

    up = VoiceUplink(
        VoiceConfig(enabled=enabled, model="persona:kira", media=media),
        whitelist=EMOTE_WHITELIST,
        run_turn=run_turn,
        media_terminus=terminus,
        barge_in=None,
    )
    up.calls = seen
    return up


def negotiated(**kwargs):
    up = uplink(**kwargs)
    up.handle({"v": 1, "type": "voice_offer", "mode": kwargs.get("media", "transcript")})
    return up


async def _speak(up, text, final=True):
    """One utterance, all the way through: the sync part, then the awaited turn."""
    out = up.handle({"v": 1, "type": "voice_transcript", "text": text, "final": final})
    pending = up.take_pending()
    if pending is None:
        return out
    return out + await up.run_pending(pending)


def speak(up, text, final=True):
    """Sync wrapper. pytest-asyncio is not a dependency here and the voice_call tests
    next door drive their own loop the same way."""
    return asyncio.run(_speak(up, text, final))


def types(messages):
    return [m["type"] for m in messages]


# ── the tag split ────────────────────────────────────────────────────────────


class TestEmoteTags:
    """A ``say`` goes to the app's speakText, not through the chat tag parser. A tag left
    in the string is read aloud, so the split is the difference between a gesture and the
    avatar pronouncing punctuation."""

    def test_a_tag_becomes_a_gesture_and_leaves_the_speech(self):
        spoken, gestures = split_emote_tags("[[emote:happy 0.9]] Good to see you.", EMOTE_WHITELIST)
        assert spoken == "Good to see you."
        assert gestures == [{"name": "happy", "intensity": 0.9}]

    def test_a_tag_mid_sentence_does_not_leave_a_double_space(self):
        spoken, _ = split_emote_tags("Well [[emote:thinking]] that depends.", EMOTE_WHITELIST)
        assert spoken == "Well that depends."

    def test_intensity_is_optional(self):
        _, gestures = split_emote_tags("[[emote:wave]]hi", EMOTE_WHITELIST)
        assert gestures == [{"name": "wave", "intensity": 0.6}]

    def test_a_non_whitelisted_name_is_dropped_but_still_stripped(self):
        # Both halves matter: it must not gesture, and it must not be spoken either.
        spoken, gestures = split_emote_tags("[[emote:twerk 1.0]] Sure.", EMOTE_WHITELIST)
        assert gestures == []
        assert spoken == "Sure."
        assert "emote" not in spoken

    def test_several_tags_in_one_reply(self):
        spoken, gestures = split_emote_tags(
            "[[emote:surprised]] Oh! [[emote:celebrate 1]] That's wonderful.", EMOTE_WHITELIST
        )
        assert [g["name"] for g in gestures] == ["surprised", "celebrate"]
        assert spoken == "Oh! That's wonderful."

    def test_a_reply_with_no_tag_is_untouched(self):
        spoken, gestures = split_emote_tags("Just words.", EMOTE_WHITELIST)
        assert (spoken, gestures) == ("Just words.", [])

    def test_a_reply_that_is_only_a_tag_speaks_nothing(self):
        up = negotiated(reply="[[emote:wave]]")
        assert types(up.messages_for("[[emote:wave]]")) == ["intent", "voice_state"]


# ── end to end ───────────────────────────────────────────────────────────────


class TestSpokenTurn:
    def test_speech_becomes_a_reply_and_a_gesture(self):
        """The acceptance sentence. Text in, an intent and a say out, in that order."""
        up = negotiated(reply="[[emote:happy 0.8]] I missed you too.")
        out = speak(up, "I missed you")

        assert types(out) == ["voice_state", "intent", "say", "voice_state"]
        assert out[0]["state"] == "thinking"
        assert out[1] == {"v": 1, "type": "intent", "name": "happy", "intensity": 0.8, "source": "voice"}
        assert out[2] == {"v": 1, "type": "say", "text": "I missed you too.", "source": "voice"}
        assert out[3]["state"] == "listening"

    def test_the_turn_carries_the_user_text_and_the_configured_model(self):
        up = negotiated()
        speak(up, "what time is it")
        assert up.calls[0]["user_text"] == "what time is it"
        assert up.calls[0]["model"] == "persona:kira"

    def test_the_turn_is_marked_as_voice_in_chat(self):
        up = negotiated()
        speak(up, "hello")
        assert up.calls[0]["extra_headers"] == {"X-HomePilot-Source": "voice"}

    def test_the_gesture_source_is_voice_and_never_user(self):
        # §6.5 blocks NSFW for any intent whose source is not the user. A tag written by a
        # model is the model's tag whichever way the sentence reached it, so claiming
        # "user" here would open the gate the addendum spends a whole section closing.
        up = negotiated(reply="[[emote:flirt 1.0]] mm.")
        out = speak(up, "say something nice")
        assert [m["source"] for m in out if "source" in m] == ["voice", "voice"]

    def test_interim_text_runs_no_turn(self):
        up = negotiated()
        out = speak(up, "I mis", final=False)
        assert out == []
        assert up.calls == []

    def test_an_empty_final_runs_no_turn(self):
        up = negotiated()
        assert speak(up, "   ") == []
        assert up.calls == []

    def test_a_transcript_before_the_offer_is_refused_not_run(self):
        up = uplink()
        out = speak(up, "hello?")
        assert out[0]["code"] == "voice_not_negotiated"
        assert up.calls == []


# ── barge-in ─────────────────────────────────────────────────────────────────


class TestBargeIn:
    def test_speaking_over_her_drops_the_reply_that_was_already_coming(self):
        """The reply to the abandoned utterance is real, and answers a question that has
        been replaced. Speaking it late is worse than not speaking it."""
        up = negotiated(reply=lambda text: f"reply to {text}")

        up.handle({"v": 1, "type": "voice_transcript", "text": "first", "final": True})
        first = up.take_pending()

        # The user starts again before the first reply lands.
        up.handle({"v": 1, "type": "voice_transcript", "text": "second", "final": True})
        second = up.take_pending()

        assert asyncio.run(up.run_pending(first)) == []
        assert up.state.dropped_stale == 1

        out = asyncio.run(up.run_pending(second))
        assert [m for m in out if m["type"] == "say"][0]["text"] == "reply to second"

    def test_cancellation_is_delegated_never_reimplemented(self):
        """voice_call's registry owns this. The uplink asks it; it does not keep a second
        set of tokens, which is how the two would eventually disagree."""
        asked = []

        class Registry:
            def cancel_active(self, session_id, turn_id):
                asked.append((session_id, turn_id))
                return True

        up = negotiated()
        up._barge_in = Registry()
        up.handle({"v": 1, "type": "voice_transcript", "text": "one", "final": True})
        first_id = up.active.turn_id
        up.handle({"v": 1, "type": "voice_transcript", "text": "two", "final": True})

        assert asked == [(up.session_key, first_id)]

    def test_a_registry_that_refuses_does_not_stop_the_new_turn(self):
        class Hostile:
            def cancel_active(self, *_):
                raise RuntimeError("no such session")

        up = negotiated(reply="second reply")
        up._barge_in = Hostile()
        up.handle({"v": 1, "type": "voice_transcript", "text": "one", "final": True})
        up.take_pending()
        up.handle({"v": 1, "type": "voice_transcript", "text": "two", "final": True})
        out = asyncio.run(up.run_pending(up.take_pending()))
        assert [m for m in out if m["type"] == "say"][0]["text"] == "second reply"


# ── the media terminus ───────────────────────────────────────────────────────


class TestMedia:
    def test_transcript_mode_negotiates_with_nothing_to_negotiate(self):
        up = uplink()
        out = up.handle({"v": 1, "type": "voice_offer", "mode": "transcript"})
        assert types(out) == ["voice_answer", "voice_state"]
        assert out[0]["mode"] == "transcript"
        assert out[1]["state"] == "listening"

    def test_a_webrtc_offer_is_refused_by_name_when_no_terminus_is_installed(self):
        # Not ignored, not accepted-and-silent: a client that offered its microphone is told
        # what to offer instead. Same rule as B8's vision_unavailable.
        up = uplink()
        out = up.handle({"v": 1, "type": "voice_offer", "mode": "webrtc"})
        assert out[0]["type"] == "error"
        assert out[0]["code"] == "voice_media_unavailable"
        assert "transcript" in out[0]["msg"]
        assert up.state.negotiated is False

    def test_a_webrtc_offer_is_answered_when_one_is(self):
        class Terminus:
            def __init__(self):
                self.candidates = []
                self.closed = False

            def answer(self, sdp):
                return f"answer-to:{sdp}"

            def add_candidate(self, candidate):
                self.candidates.append(candidate)

            def close(self):
                self.closed = True

        terminus = Terminus()
        up = uplink(terminus=terminus)
        out = up.handle({"v": 1, "type": "voice_offer", "mode": "webrtc", "sdp": "offer"})
        assert out[0] == {"v": 1, "type": "voice_answer", "sdp": "answer-to:offer", "mode": "webrtc"}

        up.handle({"v": 1, "type": "voice_ice", "candidate": "cand-1"})
        assert terminus.candidates == ["cand-1"]

        up.handle({"v": 1, "type": "voice_end"})
        assert terminus.closed is True

    def test_ice_without_a_terminus_is_quietly_ignored(self):
        # Answering an error per trickled candidate would be noise, not information.
        up = negotiated()
        assert up.handle({"v": 1, "type": "voice_ice", "candidate": "x"}) == []

    def test_an_unknown_media_mode_is_named_in_the_refusal(self):
        up = uplink()
        out = up.handle({"v": 1, "type": "voice_offer", "mode": "carrier-pigeon"})
        assert out[0]["code"] == "voice_bad_mode"

    def test_this_module_ships_no_terminus(self):
        """B10 does not add aiortc to requirements. Without it there is no terminus, and
        the uplink says so rather than pretending."""
        assert webrtc_terminus(VoiceConfig(enabled=True, media="webrtc")) is None


# ── declining the mic ────────────────────────────────────────────────────────


class TestDecliningTheMic:
    """The other acceptance sentence. Every one of these is a negative assertion, because
    "leaves every other channel working" is only meaningful as a claim about what did *not*
    break."""

    def test_the_voice_gate_ships_off_and_is_not_implied_by_enabled(self, monkeypatch):
        for name in ("AVATAR_ENABLED", "AVATAR_VOICE_ENABLED"):
            monkeypatch.delenv(name, raising=False)
        assert load_config().voice.enabled is False
        monkeypatch.setenv("AVATAR_ENABLED", "true")
        assert load_config().voice.enabled is False

    def test_transcript_is_the_default_media_mode(self, monkeypatch):
        monkeypatch.delenv("AVATAR_VOICE_MEDIA", raising=False)
        assert load_config().voice.media == "transcript"

    def test_a_session_without_voice_still_serves_every_other_type(self):
        handler = ProtocolHandler(voice=None)
        handler.handle({"v": 1, "type": "hello", "auth": "t", "client": "3dac", "caps": []})

        assert handler.handle({"v": 1, "type": "ctx", "mode": "together", "activity": "watch", "attention": 0.5}) == []
        assert handler.state.mode == "together"
        assert handler.handle({"v": 1, "type": "user_event", "name": "media:paused"}) == []
        assert handler.state.last_event == "media:paused"
        assert handler.handle({"v": 1, "type": "streak", "activity": "walk", "value": 3}) == []
        assert handler.state.streaks == {"walk": 3}
        assert handler.handle({"v": 1, "type": "pong"}) == []

    def test_a_session_without_voice_refuses_voice_by_name_rather_than_ignoring_it(self):
        handler = ProtocolHandler(voice=None)
        handler.handle({"v": 1, "type": "hello", "auth": "t", "client": "3dac", "caps": []})
        out = handler.handle({"v": 1, "type": "voice_offer", "mode": "transcript"})
        assert out[0]["code"] == "voice_unavailable"
        # And it is a refusal, not the §6.9 ignore rule: this type is one we know.
        assert "voice_offer" not in handler.ignored

    def test_the_uplink_itself_refuses_while_the_flag_is_off(self):
        up = uplink(enabled=False)
        assert up.handle({"v": 1, "type": "voice_offer", "mode": "transcript"})[0]["code"] == "voice_unavailable"

    def test_a_failing_turn_is_reported_and_the_session_keeps_listening(self):
        # A chat endpoint having a bad minute must not disconnect a user whose screen,
        # gestures and idle behaviour are all still fine.
        up = negotiated(fail=RuntimeError("chat endpoint returned 503"))
        out = speak(up, "are you there")
        assert types(out) == ["voice_state", "error", "voice_state"]
        assert out[1]["code"] == "voice_turn_failed"
        assert out[2]["state"] == "listening"
        assert up.state.listening is True

    def test_ending_the_uplink_leaves_the_rest_of_the_session_alone(self):
        up = negotiated()
        out = up.handle({"v": 1, "type": "voice_end"})
        assert out[-1]["state"] == "idle"
        assert up.state.listening is False


# ── the shape of the integration ─────────────────────────────────────────────


class TestIntegrationDiscipline:
    def test_the_uplink_transcribes_nothing_itself(self):
        """A media terminus must hand back text from the existing STT provider. Nothing in
        this module may grow a transcribe path of its own — that is the review line the
        batch plan draws, and this is it as an assertion."""
        import app.avatar_director.rtc as rtc

        source = open(rtc.__file__, encoding="utf8").read()
        body = source.split('"""', 2)[2]  # skip the module docstring, which discusses it
        for forbidden in ("import whisper", "faster_whisper", "def transcribe"):
            assert forbidden not in body

    def test_importing_the_uplink_costs_no_transport_and_no_chat_path(self):
        """The lazy imports are the reason ``avatar.enabled=false`` still means "imports
        nothing", and they are also what lets these tests run without httpx configured.

        Checked in a fresh interpreter rather than against this process's ``sys.modules``:
        another test file importing ``voice_call`` would otherwise make this pass or fail
        depending on collection order, which is a test that reports on the suite rather
        than on the module.
        """
        import subprocess
        import sys

        probe = (
            "import sys; import app.avatar_director.rtc as rtc;"
            "print(rtc.__name__ in sys.modules,"
            "'app.voice_call.turn' in sys.modules,"
            "'aiortc' in sys.modules,"
            "'fastapi' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
            check=True,
        )
        assert out.stdout.split() == ["True", "False", "False", "False"]

    def test_the_voice_types_are_additions_and_break_no_existing_shape(self):
        from app.avatar_director.protocol import CLIENT_TYPES, SERVER_TYPES

        for older in ("hello", "ctx", "user_event", "vision_ask", "chat_meta", "pong"):
            assert older in CLIENT_TYPES
        for older in ("intent", "say", "scene", "error", "ping", "display", "adult_ack"):
            assert older in SERVER_TYPES
        assert {"voice_offer", "voice_transcript"} <= CLIENT_TYPES
        assert {"voice_answer", "voice_state"} <= SERVER_TYPES

    def test_the_key_set_grew_by_exactly_the_voice_block(self):
        keys = set(AvatarDirectorConfig().as_dict())
        assert {"voice.enabled", "voice.model", "voice.media"} <= keys
        assert len(keys) == 11
