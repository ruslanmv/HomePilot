"""Whisper's captions for silence never reach a meeting transcript.

The reported meeting had "I'll see you in the next one. Bye." attributed to a person who never
said it — the caption Whisper writes over a quiet stretch of a call, learned from subtitled
video. See ``app/voice/transcript_quality.py`` for the three defences tested here.
"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from app.voice import transcript_quality as quality


def seg(text, *, no_speech=0.05, logprob=-0.2, ratio=1.4, start=0.0, end=1.5):
    return SimpleNamespace(text=text, no_speech_prob=no_speech, avg_logprob=logprob,
                           compression_ratio=ratio, start=start, end=end)


class TestTheSegmentFilter:
    @pytest.mark.parametrize("text", [
        "I'll see you in the next one. Bye.",
        "Thanks for watching!",
        "Please like and subscribe.",
        "Subtitles by the Amara.org community",
        "[Music]",
        "♪ ♪",
    ])
    def test_silence_captions_are_dropped_even_when_confident(self, text):
        assert not quality.keep(seg(text, logprob=-0.1))

    def test_a_real_thank_you_is_kept(self):
        assert quality.keep(seg("Thank you.", no_speech=0.02, logprob=-0.15))

    def test_a_doubtful_thank_you_over_noise_is_dropped(self):
        assert not quality.keep(seg("Thank you.", no_speech=0.45, logprob=-0.8))

    def test_the_models_own_no_speech_rule_applies_per_segment(self):
        assert not quality.keep(seg("so the plan is", no_speech=0.8, logprob=-0.9))
        assert quality.keep(seg("so the plan is", no_speech=0.8, logprob=-0.2))

    def test_a_repetition_loop_is_dropped(self):
        assert not quality.keep(seg("the the the the the the the the", ratio=3.1))

    def test_ordinary_speech_is_kept(self):
        assert quality.keep(seg("We are moving the beta to the twenty-eighth."))

    @pytest.mark.parametrize("text", [
        "Customers subscribe monthly to the basic plan.",
        "The translation from Spanish is ready for review.",
        "Translated by our team last week, so it should be fine.",
        "See you in the next meeting on Thursday.",
    ])
    def test_words_a_caption_uses_are_fine_in_a_sentence(self, text):
        assert quality.keep(seg(text))


class TestDecodingOptions:
    def test_only_options_the_installed_version_accepts_are_passed(self):
        def old_transcribe(audio, language=None, beam_size=5):
            return None

        assert quality.supported(old_transcribe, quality.MEETING_OPTIONS) == {}

        def new_transcribe(audio, language=None, condition_on_previous_text=True, no_speech_threshold=0.6):
            return None

        assert quality.supported(new_transcribe, quality.MEETING_OPTIONS) == {
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.6,
        }

    def test_a_gate_that_cannot_run_never_drops_a_clip(self, tmp_path):
        broken = tmp_path / "not-audio.wav"
        broken.write_bytes(b"this is not a wav file")
        assert quality.has_speech(str(broken)) is None


class FakeModel:
    """Records what the provider asked for and answers with scripted segments."""

    def __init__(self, segments, language="en", probability=0.97):
        self.segments = segments
        self.info = SimpleNamespace(language=language, language_probability=probability)
        self.kwargs = None

    def transcribe(self, path, language=None, condition_on_previous_text=True, no_speech_threshold=0.6,
                   log_prob_threshold=-1.0, compression_ratio_threshold=2.4):
        self.kwargs = {"language": language, "condition_on_previous_text": condition_on_previous_text}
        return iter(self.segments), self.info


def live_quality():
    """The module the provider will import *now* — other test files reload `app.voice`, and a
    patch on a stale module object would patch nothing."""
    return importlib.import_module("app.voice.transcript_quality")


@pytest.fixture()
def provider(monkeypatch):
    providers = importlib.import_module("app.voice.providers")

    p = providers.WhisperLocalSTTProvider.__new__(providers.WhisperLocalSTTProvider)
    p.device = "cpu"
    p.requested_device = "cpu"
    p._cpu_forced = True
    # The gate needs real audio; these tests are about what happens after it.
    monkeypatch.setattr(live_quality(), "has_speech", lambda path: True)
    return p


def run_with(provider, model, **kwargs):
    provider._ensure_model = lambda: model
    return asyncio.run(provider.transcribe_segments(b"RIFF", fmt="wav", duration_s=2.0, **kwargs))


class TestTheMeetingTranscriber:
    def test_captions_are_filtered_and_the_language_is_reported(self, provider):
        model = FakeModel([seg("Let us start with the roadmap."), seg("Thanks for watching!")])
        spans = run_with(provider, model)
        assert [s["text"] for s in spans] == ["Let us start with the roadmap."]
        assert spans[0]["lang"] == "en" and spans[0]["lang_p"] == pytest.approx(0.97)
        assert model.kwargs["condition_on_previous_text"] is False

    def test_a_locked_language_is_decoded_in_and_not_reported(self, provider):
        model = FakeModel([seg("Buongiorno a tutti.")], language="it")
        spans = run_with(provider, model, language="it")
        assert model.kwargs["language"] == "it"
        assert "lang" not in spans[0]

    def test_a_clip_with_no_speech_is_never_decoded(self, provider, monkeypatch):
        monkeypatch.setattr(live_quality(), "has_speech", lambda path: False)
        model = FakeModel([seg("Thank you.")])
        assert run_with(provider, model) == []
        assert model.kwargs is None

    def test_the_filter_can_be_switched_off(self, provider, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_SPEECH_FILTER", "0")
        model = FakeModel([seg("Thanks for watching!")])
        assert [s["text"] for s in run_with(provider, model)] == ["Thanks for watching!"]
