"""The STT capability layer (batch MS1).

MS1 is the plan's one sanctioned exception to additive-only: it edits
``backend/app/voice/providers.py``, which the voice backend shares. The narrower rule it
keeps instead is what most of this file checks — **no existing signature or default
changes** — because that is the only thing standing between "we added timestamps" and "we
broke voice calls".

Three things land, and each answers a real defect:

* ``transcribe_segments()`` keeps the ``seg.start`` / ``seg.end`` that ``transcribe()``
  joins away. Every design in this feature cites timestamps; nothing produced them.
* ``device`` reports where the model actually loaded. ``auto`` — which was already the
  default, contrary to what the batch plan first claimed — falls back to CPU *silently*
  when CUDA is present but unusable, and that silence is how someone concludes the latency
  budget is unachievable.
* ``get_stt_provider()`` caches. It used to build a fresh provider per call, and the model
  lives on the instance, so a caller fetching one per utterance reloaded it every time.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from app.voice import providers as P

STT_ENV = [
    "STT_BASE_URL",
    "STT_API_KEY",
    "STT_MODEL",
    "WHISPER_MODEL",
    "WHISPER_DEVICE",
    "WHISPER_COMPUTE",
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in STT_ENV:
        monkeypatch.delenv(name, raising=False)
    P.reset_stt_provider_cache()
    yield
    P.reset_stt_provider_cache()


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── the existing surface is untouched ───────────────────────────────────────


class TestNothingExistingChanged:
    def test_transcribe_keeps_its_exact_signature(self):
        # The voice backend calls this. A changed default or a new required argument would
        # be the "additive" claim quietly failing.
        sig = inspect.signature(P.STTProvider.transcribe)
        assert list(sig.parameters) == ["self", "audio", "fmt"]
        assert sig.parameters["fmt"].default == "wav"
        assert sig.parameters["fmt"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_transcribe_is_still_the_only_abstract_method(self):
        # If `transcribe_segments` were abstract, every provider written before MS1 — here
        # or in anyone's fork — would stop instantiating.
        assert P.STTProvider.__abstractmethods__ == frozenset({"transcribe"})

    def test_selection_order_is_unchanged(self, monkeypatch):
        monkeypatch.setenv("STT_BASE_URL", "https://api.example/v1")
        assert P.get_stt_provider().name == "openai-compat"

    def test_nothing_configured_is_still_the_null_provider(self):
        assert P.get_stt_provider().name == "null"

    def test_whisper_defaults_reproduce_the_old_call(self, monkeypatch):
        # Before MS1 the model was built as `WhisperModel(name)`. With no WHISPER_DEVICE or
        # WHISPER_COMPUTE set, the arguments MS1 passes must be the ones faster-whisper
        # would have chosen anyway, or an existing install changes behaviour on upgrade.
        monkeypatch.setenv("WHISPER_MODEL", "small")
        provider = P.WhisperLocalSTTProvider()
        assert provider.requested_device == "auto"
        assert provider.compute_type == "default"


# ── timed spans ─────────────────────────────────────────────────────────────


class _TextOnly(P.STTProvider):
    """A provider that can only produce text — the shape of every provider before MS1."""

    name = "text-only"

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str:
        return "the launch moves to October"


class TestSegments:
    def test_a_text_only_provider_degrades_to_one_span(self):
        spans = run(_TextOnly().transcribe_segments(b"x"))
        assert spans == [{"t0": 0.0, "t1": None, "text": "the launch moves to October", "conf": None}]

    def test_unknown_end_is_none_rather_than_a_guess(self):
        # `t1: None` says "this provider does not know". A zero, or the clip length assumed
        # from nowhere, would be a number a UI would happily render as fact.
        assert run(_TextOnly().transcribe_segments(b"x"))[0]["t1"] is None

    def test_a_caller_that_framed_the_audio_can_supply_the_span(self):
        # MeetingSense frames every utterance with its own VAD, so it knows the duration the
        # provider does not.
        spans = run(_TextOnly().transcribe_segments(b"x", duration_s=2.5))
        assert spans[0]["t0"] == 0.0
        assert spans[0]["t1"] == 2.5

    def test_empty_audio_yields_no_spans_not_an_empty_one(self):
        class Silent(_TextOnly):
            async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str:
                return "   "

        assert run(Silent().transcribe_segments(b"")) == []

    def test_a_text_only_provider_says_its_timings_are_not_measured(self):
        assert _TextOnly().supports_segments is False

    def test_every_provider_answers_the_call(self):
        # The method exists everywhere so a caller never branches; `supports_segments` is
        # what varies. Asking "does the method exist" would answer yes for all of them.
        for cls in (P.NullSTTProvider, P.OpenAICompatSTTProvider, P.WhisperLocalSTTProvider):
            assert callable(getattr(cls, "transcribe_segments", None))

    def test_the_local_provider_claims_measured_timings(self):
        assert P.WhisperLocalSTTProvider().supports_segments is True


class TestWhisperSpans:
    """The real span extraction, against a stand-in for faster-whisper's model."""

    class _Seg:
        def __init__(self, start, end, text, avg_logprob=-0.2):
            self.start, self.end, self.text, self.avg_logprob = start, end, text, avg_logprob

    class _Model:
        def __init__(self, segments):
            self._segments = segments
            self.model = type("Inner", (), {"device": "cpu"})()

        def transcribe(self, path):
            return iter(self._segments), {"language": "en"}

    def _provider(self, monkeypatch, segments):
        monkeypatch.setenv("WHISPER_MODEL", "small")
        provider = P.WhisperLocalSTTProvider()
        provider._model = self._Model(segments)
        provider.device = "cpu"
        return provider

    def test_start_and_end_survive(self, monkeypatch):
        provider = self._provider(
            monkeypatch,
            [self._Seg(0.0, 1.4, " so the launch moves"), self._Seg(1.4, 3.1, " to October")],
        )
        spans = run(provider.transcribe_segments(b"x"))
        assert [(s["t0"], s["t1"]) for s in spans] == [(0.0, 1.4), (1.4, 3.1)]
        assert [s["text"] for s in spans] == ["so the launch moves", "to October"]

    def test_transcribe_still_returns_the_joined_string(self, monkeypatch):
        # The two calls read the same model output; only one of them throws the timings away.
        #
        # Note the double space. faster-whisper's segment text carries a leading space, and
        # `" ".join(...)` adds another — so the original produced "hello  there" and this
        # asserts exactly that. Tidying it here would be a behaviour change in a path the
        # voice backend shares, which is the widening MS1 is explicitly not allowed to do.
        # `transcribe_segments` strips per span, so the transcript does not inherit it.
        provider = self._provider(
            monkeypatch, [self._Seg(0.0, 1.0, " hello"), self._Seg(1.0, 2.0, " there")]
        )
        assert run(provider.transcribe(b"x")) == "hello  there"

    def test_confidence_is_a_probability_not_a_log(self, monkeypatch):
        import math

        provider = self._provider(monkeypatch, [self._Seg(0.0, 1.0, " x", avg_logprob=-0.5)])
        conf = run(provider.transcribe_segments(b"x"))[0]["conf"]
        assert conf == pytest.approx(math.exp(-0.5), abs=1e-4)
        assert 0.0 <= conf <= 1.0

    def test_a_missing_confidence_stays_none(self, monkeypatch):
        seg = self._Seg(0.0, 1.0, " x")
        del seg.avg_logprob
        provider = self._provider(monkeypatch, [seg])
        assert run(provider.transcribe_segments(b"x"))[0]["conf"] is None

    def test_blank_segments_are_dropped(self, monkeypatch):
        provider = self._provider(
            monkeypatch, [self._Seg(0.0, 1.0, "  "), self._Seg(1.0, 2.0, " real")]
        )
        spans = run(provider.transcribe_segments(b"x"))
        assert [s["text"] for s in spans] == ["real"]


# ── device reporting ────────────────────────────────────────────────────────


class TestDevice:
    def test_device_is_none_before_the_model_loads(self, monkeypatch):
        # A different answer from "loaded on CPU", and worth keeping distinct: one means
        # nothing has been transcribed yet, the other is a performance problem.
        monkeypatch.setenv("WHISPER_MODEL", "small")
        assert P.WhisperLocalSTTProvider().device is None

    def test_the_requested_device_is_read_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL", "small")
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        monkeypatch.setenv("WHISPER_COMPUTE", "float16")
        provider = P.WhisperLocalSTTProvider()
        assert provider.requested_device == "cuda"
        assert provider.compute_type == "float16"

    def test_the_resolved_device_is_read_back_not_echoed(self, monkeypatch):
        # The whole point. Asking for `cuda` and being given `cpu` is exactly the case that
        # must be visible, so the reported device comes from the loaded model.
        monkeypatch.setenv("WHISPER_MODEL", "small")
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        provider = P.WhisperLocalSTTProvider()

        class Fake:
            def __init__(self, *a, **kw):
                self.model = type("Inner", (), {"device": "cpu"})()

            def transcribe(self, path):
                return iter(()), {}

        import sys
        import types

        module = types.ModuleType("faster_whisper")
        module.WhisperModel = Fake
        monkeypatch.setitem(sys.modules, "faster_whisper", module)

        provider._ensure_model()
        assert provider.requested_device == "cuda"
        assert provider.device == "cpu"


# ── caching ─────────────────────────────────────────────────────────────────


class TestCache:
    def test_the_same_configuration_returns_the_same_object(self, monkeypatch):
        # The defect this fixes: the model lives on the instance, so a new instance per call
        # meant reloading hundreds of megabytes for every utterance of a meeting.
        monkeypatch.setenv("WHISPER_MODEL", "small")
        assert P.get_stt_provider() is P.get_stt_provider()

    def test_a_changed_configuration_returns_a_new_object(self, monkeypatch):
        # Not a plain singleton. An operator who edits .env and restarts, or a test that
        # sets STT_BASE_URL, must not be served a provider built before the change.
        first = P.get_stt_provider()
        monkeypatch.setenv("STT_BASE_URL", "https://api.example/v1")
        second = P.get_stt_provider()
        assert first is not second
        assert second.name == "openai-compat"

    @pytest.mark.parametrize(
        "var,value",
        [
            ("STT_BASE_URL", "https://api.example/v1"),
            ("STT_MODEL", "whisper-1"),
            ("WHISPER_MODEL", "small"),
            ("WHISPER_DEVICE", "cuda"),
            ("WHISPER_COMPUTE", "int8"),
        ],
    )
    def test_every_key_variable_invalidates(self, monkeypatch, var, value):
        # WHISPER_DEVICE and WHISPER_COMPUTE are in the key even though they do not change
        # *which* provider is chosen: they change how it loads, and a cached model on the
        # wrong device is the bug this batch exists to make visible.
        first = P.get_stt_provider()
        monkeypatch.setenv(var, value)
        assert P.get_stt_provider() is not first

    def test_reset_drops_the_cache(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MODEL", "small")
        first = P.get_stt_provider()
        P.reset_stt_provider_cache()
        assert P.get_stt_provider() is not first
