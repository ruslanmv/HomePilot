"""Skipping a channel that carried no sound.

A stereo meeting frame is split into two tracks and each is transcribed. During a shared
video with nobody talking, the microphone channel is silence — so half the inference is spent
returning "". The client measures the peak per channel while it frames the audio, so the
server can skip that track without a second pass over the PCM.

The hint is an optimisation, so every test here is really about the same property: anything
unexpected must transcribe the audio rather than discard it.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def routes(app):
    # Imported through the fixture: the `app` fixture purges and re-imports every `app.*`
    # module, so a module captured at collection time is not the one the route uses.
    return importlib.import_module("app.meetingsense.routes")


class TestChannelIsSilent:
    def test_a_channel_the_client_measured_as_silent_is_skipped(self, routes):
        assert routes._channel_is_silent([0.4, 0.0], 1, 2) is True

    def test_a_channel_that_carried_sound_is_kept(self, routes):
        assert routes._channel_is_silent([0.4, 0.0], 0, 2) is False

    def test_quiet_is_not_silent(self, routes):
        # Distant dialogue or a quiet passage must still be transcribed. Only essentially
        # digital silence is skipped, an order of magnitude under the client's own floor.
        peak = routes.SILENT_CHANNEL_PEAK * 10
        assert routes._channel_is_silent([peak, peak], 0, 2) is False

    def test_no_hint_transcribes_everything(self, routes):
        # Every client before this hint existed sends no `energy`, and must keep working.
        assert routes._channel_is_silent(None, 0, 2) is False
        assert routes._channel_is_silent({}, 0, 2) is False
        assert routes._channel_is_silent("0,0", 0, 2) is False

    def test_a_length_mismatch_transcribes_everything(self, routes):
        # The split and the measurement disagree about the audio; guessing which is right
        # risks dropping the wrong channel.
        assert routes._channel_is_silent([0.0], 0, 2) is False
        assert routes._channel_is_silent([0.0, 0.0, 0.0], 0, 2) is False

    def test_a_non_number_transcribes_everything(self, routes):
        assert routes._channel_is_silent(["0.0", 0.4], 0, 2) is False
        assert routes._channel_is_silent([None, 0.4], 0, 2) is False
        # `True` is an int in Python and would compare below the floor as 1 > threshold is
        # False... it must not be read as a level at all.
        assert routes._channel_is_silent([True, 0.4], 0, 2) is False

    def test_an_index_past_the_hint_transcribes(self, routes):
        assert routes._channel_is_silent([0.0], 1, 1) is False

    def test_mono_silence_is_still_skipped(self, routes):
        # A single silent channel is the same waste, just smaller.
        assert routes._channel_is_silent([0.0], 0, 1) is True


class TestHandleAudioSkipsSilentTracks:
    """The property that matters: which tracks reach the session."""

    @staticmethod
    def _session(seen):
        class Session:
            async def on_audio(self, frame):
                seen.append(("audio", frame.get("speaker")))

            async def on_partial(self, frame):
                seen.append(("partial", frame.get("speaker")))

        return Session()

    @staticmethod
    def _stereo_wav(routes):
        """A two-channel WAV the real splitter will accept."""
        from app.meetingsense import audio as audio_wire

        # 40 ms of interleaved silence is enough: the splitter reads the header, and what the
        # samples contain is irrelevant to which tracks come out.
        pcm = b"\x00\x00" * 2 * 640
        return audio_wire.wrap_pcm16(pcm, rate=16000, channels=2)

    @pytest.mark.anyio
    async def test_a_silent_channel_never_reaches_the_transcriber(self, routes):
        import base64

        seen: list = []
        message = {
            "type": "audio",
            "format": "wav",
            "data_b64": base64.b64encode(self._stereo_wav(routes)).decode(),
            "energy": [0.4, 0.0],
        }

        await routes._handle_audio(self._session(seen), message, 2)

        assert len(seen) == 1
        assert seen[0][1] == "them"  # channel 0, the one with sound

    @pytest.mark.anyio
    async def test_both_channels_are_transcribed_without_a_hint(self, routes):
        import base64

        seen: list = []
        message = {
            "type": "audio",
            "format": "wav",
            "data_b64": base64.b64encode(self._stereo_wav(routes)).decode(),
        }

        await routes._handle_audio(self._session(seen), message, 2)

        assert len(seen) == 2

    @pytest.mark.anyio
    async def test_the_hint_applies_to_partials_too(self, routes):
        import base64

        seen: list = []
        message = {
            "type": "audio",
            "format": "wav",
            "partial": True,
            "data_b64": base64.b64encode(self._stereo_wav(routes)).decode(),
            "energy": [0.0, 0.4],
        }

        await routes._handle_audio(self._session(seen), message, 2)

        assert seen == [("partial", "me")]
