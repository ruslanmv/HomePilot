"""Real timings from a remote speech endpoint (batch MS1-a).

Carried out of MS1 and finished here. Until now `OpenAICompatSTTProvider` inherited the base
class's one-span fallback, so **every** install with `STT_BASE_URL` set produced segments with
`t1: None` and reported `supports_segments: false`. Honest, and useless to W4: MS12 cites `t0`
per note and MS13 answers with timestamps.

The theme of this file is that `verbose_json` is a *documented* format, not a guaranteed one.
Between the OpenAI API, whisper.cpp's server, Groq and LocalAI — plus whatever proxy sits in
front of one — the same request comes back in several shapes, and the ones that matter are the
degraded ones. A provider that only works against a perfect response works against a demo.

The rule the tolerance follows: **a missing timestamp is better than a wrong one.** A segment
the server did not time is skipped rather than given `t0: 0`, because these end up cited in a
note, and a citation pointing at the wrong minute is worse than a note with no citation.
"""

from __future__ import annotations

import asyncio
import math

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("STT_BASE_URL", "STT_API_KEY", "STT_MODEL", "WHISPER_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def providers():
    """The live module, imported after conftest's `app.*` purge."""
    import app.voice.providers as module

    return module


@pytest.fixture()
def remote(providers, monkeypatch):
    monkeypatch.setenv("STT_BASE_URL", "https://speech.example/v1")
    monkeypatch.setenv("STT_MODEL", "whisper-1")
    return providers.OpenAICompatSTTProvider()


class FakeResponse:
    def __init__(self, payload=None, *, text=None, status=200):
        self._payload = payload
        self._text = text
        self.status = status
        self.text = text if text is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class FakeClient:
    """Stands in for httpx.AsyncClient, and records what was asked for."""

    posted: list = []

    def __init__(self, response):
        self._response = response

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers=None, files=None, data=None):
        FakeClient.posted.append({"url": url, "headers": headers, "data": data, "files": files})
        return self._response


@pytest.fixture()
def transport(monkeypatch):
    """Install a fake httpx whose response the test chooses."""
    import types

    FakeClient.posted = []

    def install(response):
        module = types.ModuleType("httpx")
        module.AsyncClient = FakeClient(response)
        monkeypatch.setitem(__import__("sys").modules, "httpx", module)
        return FakeClient.posted

    return install


# ── the verbose_json shapes, as a pure function ─────────────────────────────


VERBOSE = {
    "text": "the launch moves to October legal needs to sign off",
    "segments": [
        {"id": 0, "start": 0.0, "end": 2.4, "text": " the launch moves to October", "avg_logprob": -0.21},
        {"id": 1, "start": 2.6, "end": 5.1, "text": " legal needs to sign off", "avg_logprob": -0.35},
    ],
}


class TestParser:
    def test_it_reads_real_boundaries(self, providers):
        spans = providers._spans_from_verbose_json(VERBOSE)
        assert [(s["t0"], s["t1"]) for s in spans] == [(0.0, 2.4), (2.6, 5.1)]

    def test_it_strips_the_leading_space_whisper_puts_on_every_segment(self, providers):
        # The wart `transcribe()` is frozen with — it joins these and gets a double space.
        # A transcript must not inherit it, which is why the stripping happens per span.
        spans = providers._spans_from_verbose_json(VERBOSE)
        assert spans[0]["text"] == "the launch moves to October"

    def test_confidence_is_read_the_way_the_local_provider_reads_it(self, providers):
        # Two providers reporting a number called `conf` that meant different things would be
        # worse than one of them reporting nothing.
        spans = providers._spans_from_verbose_json(VERBOSE)
        assert spans[0]["conf"] == round(math.exp(-0.21), 4)

    def test_a_server_that_omits_confidence_gets_none_not_a_flattering_default(self, providers):
        body = {"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}]}
        assert providers._spans_from_verbose_json(body)[0]["conf"] is None

    def test_an_untimed_segment_is_skipped_rather_than_given_zero(self, providers):
        # The rule: a missing timestamp beats a wrong one. These get cited in notes, and a
        # citation pointing at the wrong minute is worse than a note with no citation.
        body = {"segments": [{"text": "no timings here"}, {"start": 3.0, "end": 4.0, "text": "timed"}]}
        spans = providers._spans_from_verbose_json(body)
        assert [s["text"] for s in spans] == ["timed"]

    def test_a_backwards_span_is_dropped(self, providers):
        body = {"segments": [{"start": 9.0, "end": 2.0, "text": "impossible"}]}
        assert providers._spans_from_verbose_json(body) == []

    def test_non_numeric_timings_are_dropped(self, providers):
        # Some servers send strings. `float("2.4")` would work and hide the fact that this
        # server is not the one the format was tested against.
        body = {"segments": [{"start": "0.0", "end": "2.4", "text": "stringly typed"}]}
        assert providers._spans_from_verbose_json(body) == []

    def test_blank_segments_are_dropped(self, providers):
        body = {"segments": [{"start": 0.0, "end": 1.0, "text": "   "}]}
        assert providers._spans_from_verbose_json(body) == []

    @pytest.mark.parametrize(
        "body",
        [
            {},                                   # a server ignoring response_format
            {"text": "plain"},                    # the plain-json answer
            {"segments": None},                   # null rather than absent
            {"segments": "not a list"},           # a proxy that rewrote it
            {"segments": [None, 7, "junk"]},      # junk inside the list
            "a bare string",                      # not an object at all
            None,
        ],
    )
    def test_every_unusable_shape_returns_empty_rather_than_raising(self, providers, body):
        # Each of these is the caller's signal to degrade to one span. A raise here would take
        # down a meeting because a server answered in a documented-but-different way.
        assert providers._spans_from_verbose_json(body) == []


# ── the provider ────────────────────────────────────────────────────────────


class TestRemoteProvider:
    def test_it_now_claims_it_can_time(self, remote):
        # The question the status endpoint and the popover ask, answerable before any audio
        # has been sent — which is why it is a property and not discovered per call.
        assert remote.supports_segments is True

    def test_it_asks_for_verbose_json(self, remote, transport):
        posted = transport(FakeResponse(VERBOSE))
        run(remote.transcribe_segments(b"audio", fmt="wav"))
        assert posted[-1]["data"]["response_format"] == "verbose_json"
        assert posted[-1]["data"]["model"] == "whisper-1"

    def test_it_returns_real_spans(self, remote, transport):
        transport(FakeResponse(VERBOSE))
        spans = run(remote.transcribe_segments(b"audio"))
        assert [(s["t0"], s["t1"], s["text"]) for s in spans] == [
            (0.0, 2.4, "the launch moves to October"),
            (2.6, 5.1, "legal needs to sign off"),
        ]

    def test_a_server_without_segments_degrades_to_one_span(self, remote, transport):
        # An older whisper.cpp server, or a proxy that dropped the parameter. One honest span
        # is usable; a raise is not.
        transport(FakeResponse({"text": "everything in one piece"}))
        spans = run(remote.transcribe_segments(b"audio", duration_s=4.0))
        assert spans == [{"t0": 0.0, "t1": 4.0, "text": "everything in one piece", "conf": None}]

    def test_the_fallback_keeps_t1_none_when_nobody_measured_it(self, remote, transport):
        transport(FakeResponse({"text": "no duration given"}))
        assert run(remote.transcribe_segments(b"audio"))[0]["t1"] is None

    def test_a_server_answering_plain_text_does_not_crash(self, remote, transport):
        # `response_format` honoured as "text" rather than "verbose_json" — the body is not
        # JSON at all.
        transport(FakeResponse(None, text="just the words"))
        assert run(remote.transcribe_segments(b"audio")) == [
            {"t0": 0.0, "t1": None, "text": "just the words", "conf": None}
        ]

    def test_silence_returns_nothing_rather_than_an_empty_span(self, remote, transport):
        transport(FakeResponse({"text": "   ", "segments": []}))
        assert run(remote.transcribe_segments(b"audio")) == []

    def test_an_http_error_still_raises(self, remote, transport):
        # Tolerance is about response *shape*, not about failure. A 500 must not be quietly
        # turned into an empty transcript — the meeting would look silent.
        transport(FakeResponse({}, status=500))
        with pytest.raises(RuntimeError):
            run(remote.transcribe_segments(b"audio"))

    def test_the_api_key_travels_the_same_way_it_does_for_transcribe(self, providers, transport, monkeypatch):
        monkeypatch.setenv("STT_BASE_URL", "https://speech.example/v1")
        monkeypatch.setenv("STT_API_KEY", "sk-test")
        posted = transport(FakeResponse(VERBOSE))
        run(providers.OpenAICompatSTTProvider().transcribe_segments(b"audio"))
        assert posted[-1]["headers"]["Authorization"] == "Bearer sk-test"


class TestTranscribeIsUntouched:
    """§7: `transcribe()`'s behaviour is frozen. MS1-a adds a call site, it does not edit one."""

    def test_it_still_asks_for_the_default_format(self, remote, transport):
        # If this ever sends `response_format`, a voice call's return value has changed — and
        # that is the widening §0 forbids.
        posted = transport(FakeResponse({"text": "hello"}))
        run(remote.transcribe(b"audio"))
        assert "response_format" not in posted[-1]["data"]

    def test_it_still_returns_a_plain_string(self, remote, transport):
        transport(FakeResponse(VERBOSE))
        assert run(remote.transcribe(b"audio")) == VERBOSE["text"]


class TestWhatTheRestOfTheStackSeesNow:
    def test_the_status_endpoint_reports_the_new_capability(self, monkeypatch, tmp_path):
        # MS0's probe asks `supports_segments`, not "does the method exist". This is the value
        # the popover renders as "this provider does not report timings" — and no longer will.
        import app.meetingsense.routes as routes
        import app.voice.providers as providers

        monkeypatch.setenv("STT_BASE_URL", "https://speech.example/v1")
        monkeypatch.setattr(providers, "get_stt_provider", lambda: providers.OpenAICompatSTTProvider())
        info = routes.stt_capability()
        assert info["provider"] == "openai-compat"
        assert info["segments"] is True
        assert info["remote"] is True

    def test_the_endpoint_is_still_never_echoed(self, monkeypatch):
        # Unchanged by this batch, and worth re-asserting where the batch touched the provider:
        # the URL can carry a key.
        import app.meetingsense.routes as routes
        import app.voice.providers as providers

        monkeypatch.setenv("STT_BASE_URL", "https://user:secret@speech.example/v1")
        monkeypatch.setattr(providers, "get_stt_provider", lambda: providers.OpenAICompatSTTProvider())
        assert "secret" not in str(routes.stt_capability())
