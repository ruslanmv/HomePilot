"""Naming the speaker in a meeting that has only one audio source.

**The scenario.** Put a tab playing speech next to HomePilot, tick "Their audio" and untick
"My microphone", and record. The recorder opens the display share, gets one audio track, and
`pickAudioMode(system=True, mic=False)` reports ``system``. The graph is one channel wide, so
the WAV that reaches the server is mono.

`audio.tracks()` refuses to name a channel in a mono recording, and it is right to: a single
interleaved channel carries no evidence about who produced it. But the *session* has that
evidence, and has had it since the ``start`` frame — ``audio.mode`` says which sources were
granted. A meeting recording the display share alone is every word "them"; a meeting recording
the microphone alone is every word "me". Throwing that away meant:

- the live transcript labelled every line "Speaker";
- the meeting detail view labelled every line **"Them"** — including a microphone-only
  meeting, where it is wrong about every line it shows;
- and the presenter queue, which only acts on what "them" said, never fired in the one
  meeting shape where everything *is* them.

None of that is a transcription failure. The words were captured, transcribed and stored
correctly the whole time. It is an attribution failure, which is worse in notes than in a
transcript: "you said" and "they said" are what a summary is built out of.

Two channels stay as they were — the convention in `audio.py` owns that case, and it is
evidence rather than inference.
"""

from __future__ import annotations

import base64
import importlib

import pytest


@pytest.fixture
def routes(app):
    # Imported through the fixture: the `app` fixture purges and re-imports every `app.*`
    # module, so a module captured at collection time is not the one the route uses.
    return importlib.import_module("app.meetingsense.routes")


@pytest.fixture
def audio_wire(app):
    return importlib.import_module("app.meetingsense.audio")


def _wav(audio_wire, channels: int) -> str:
    """A WAV the real splitter will accept. The samples are irrelevant to attribution."""
    pcm = b"\x00\x00" * channels * 640
    return base64.b64encode(audio_wire.wrap_pcm16(pcm, rate=16000, channels=channels)).decode()


def _session(seen, mode):
    class Session:
        audio_mode = mode

        async def on_audio(self, frame):
            seen.append(("audio", frame.get("speaker")))

        async def on_partial(self, frame):
            seen.append(("partial", frame.get("speaker")))

    return Session()


class TestSpeakerForMode:
    """The rule on its own: which audio modes name a single speaker."""

    def test_a_display_share_alone_is_them(self, audio_wire):
        assert audio_wire.speaker_for_mode("system") == "them"

    def test_a_microphone_alone_is_me(self, audio_wire):
        assert audio_wire.speaker_for_mode("mic") == "me"

    def test_both_sources_name_nobody(self, audio_wire):
        # Two sources mixed down to one channel cannot be attributed, and the two-channel
        # case never reaches here — `tracks()` has already named both from the convention.
        assert audio_wire.speaker_for_mode("system+mic") is None

    def test_anything_unexpected_names_nobody(self, audio_wire):
        # An older client, a future mode, a typo. Guessing would put a confident "me" on
        # audio nobody promised was the microphone.
        for mode in (None, "", "none", "unknown", 7, ["system"]):
            assert audio_wire.speaker_for_mode(mode) is None


class TestMonoFramesAreAttributed:
    """The property that matters: what the session is told about each frame."""

    @pytest.mark.anyio
    async def test_a_system_only_meeting_labels_every_line_them(self, routes, audio_wire):
        # The reported scenario: a tab playing speech, no microphone.
        seen: list = []
        message = {"type": "audio", "format": "wav", "data_b64": _wav(audio_wire, 1)}

        await routes._handle_audio(_session(seen, "system"), message, 1)

        assert seen == [("audio", "them")]

    @pytest.mark.anyio
    async def test_a_mic_only_meeting_labels_every_line_me(self, routes, audio_wire):
        # The phone-on-the-table meeting. Labelling this "Them" — which the detail view did
        # for every unattributed line — is wrong about every word the user spoke.
        seen: list = []
        message = {"type": "audio", "format": "wav", "data_b64": _wav(audio_wire, 1)}

        await routes._handle_audio(_session(seen, "mic"), message, 1)

        assert seen == [("audio", "me")]

    @pytest.mark.anyio
    async def test_partials_are_attributed_the_same_way(self, routes, audio_wire):
        # A partial and the segment that replaces it must not change speaker mid-utterance.
        seen: list = []
        message = {
            "type": "audio",
            "format": "wav",
            "partial": True,
            "data_b64": _wav(audio_wire, 1),
        }

        await routes._handle_audio(_session(seen, "system"), message, 1)

        assert seen == [("partial", "them")]

    @pytest.mark.anyio
    async def test_a_stereo_frame_still_uses_the_channel_convention(self, routes, audio_wire):
        # Evidence beats inference: two channels are named by which channel they are.
        seen: list = []
        message = {"type": "audio", "format": "wav", "data_b64": _wav(audio_wire, 2)}

        await routes._handle_audio(_session(seen, "system+mic"), message, 2)

        assert seen == [("audio", "them"), ("audio", "me")]

    @pytest.mark.anyio
    async def test_a_frame_that_names_its_own_speaker_is_believed(self, routes, audio_wire):
        # The frame's own claim is more specific than the session's mode, and a client that
        # sends one has said something the mode cannot know.
        seen: list = []
        message = {
            "type": "audio",
            "format": "wav",
            "data_b64": _wav(audio_wire, 1),
            "speaker": "me",
        }

        await routes._handle_audio(_session(seen, "system"), message, 1)

        assert seen == [("audio", "me")]

    @pytest.mark.anyio
    async def test_a_session_that_never_said_its_mode_is_unchanged(self, routes, audio_wire):
        # Every client written before `audio.mode` existed, and every test stub. Unattributed
        # is the honest answer and was the behaviour before this.
        seen: list = []

        class Bare:
            async def on_audio(self, frame):
                seen.append(("audio", frame.get("speaker")))

        message = {"type": "audio", "format": "wav", "data_b64": _wav(audio_wire, 1)}

        await routes._handle_audio(Bare(), message, 1)

        assert seen == [("audio", None)]

    @pytest.mark.anyio
    async def test_a_silent_mono_frame_is_still_skipped(self, routes, audio_wire):
        # Attribution must not resurrect audio the energy hint said carried nothing.
        seen: list = []
        message = {
            "type": "audio",
            "format": "wav",
            "data_b64": _wav(audio_wire, 1),
            "energy": [0.0],
        }

        await routes._handle_audio(_session(seen, "system"), message, 1)

        assert seen == []
