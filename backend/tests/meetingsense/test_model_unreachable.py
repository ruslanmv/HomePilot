"""A meeting whose language model is not running.

**The reported failure.** Ollama was not up, so every notes window raised
``httpx.ConnectError: All connection attempts failed`` and the engine answered it with
``log.exception``. Two model calls per window, one traceback each, one window a minute: a
half-hour meeting wrote sixty stack traces into the log, and each one buried whatever real
failure came next. The meeting itself was fine — the transcript recorded and stored normally —
but nothing said so, and the user was left reading tracebacks to find out why there was no
recap.

Three things are wrong with treating that as an unexpected exception:

- **It is expected.** A self-hosted install where the model is not running is an ordinary
  state, not a bug. It is fixed by starting the model, and a stack trace does not say that.
- **It repeats.** Retrying a refused connection every window pays the timeout twice a minute
  for nothing.
- **It is invisible where it matters.** The absence of a recap looked identical to a meeting
  in which nothing was decided.

A model that *answers* with something unusable is the opposite on all three counts, so it
keeps its traceback. Telling the two apart is what this file is about.
"""

from __future__ import annotations

import importlib
import sqlite3

import pytest


@pytest.fixture
def engine_mod(app, tmp_path, monkeypatch):
    """The notes engine, with a real store behind it.

    Imported through the fixture because the `app` fixture purges and re-imports every `app.*`
    module, so a module captured at collection time is not the one under test. The store is a
    temporary SQLite file rather than a stub: `run()` persisting what it reports is half of
    what these tests are checking.
    """
    engine = importlib.import_module("app.meetingsense.notes_engine")
    store = importlib.import_module("app.meetingsense.store")
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(store, "_connect", _connect)
    store.migrate()
    return engine


class Unreachable(Exception):
    """Stands in for the transport error, matched by name exactly as the real one is."""


Unreachable.__name__ = "ConnectError"


def segments(count: int = 1):
    return [
        {"t0_ms": 1000 * i, "t1_ms": 1000 * i + 900, "speaker": "them", "text": f"line {i}"}
        for i in range(count)
    ]


def build(engine_mod, call, **kw):
    return engine_mod.NotesEngine("m1", call=call, **kw)


class TestClassification:
    def test_a_refused_connection_is_unreachable(self, engine_mod):
        assert engine_mod.classify_model_failure(Unreachable("refused")) \
            == engine_mod.MODEL_UNREACHABLE

    def test_it_is_found_through_the_cause_chain(self, engine_mod):
        # httpx raises ConnectError from httpcore.ConnectError from OSError, and the compute
        # router may wrap it again before it arrives.
        inner = Unreachable("All connection attempts failed")
        outer = RuntimeError("routing failed")
        outer.__cause__ = inner
        assert engine_mod.classify_model_failure(outer) == engine_mod.MODEL_UNREACHABLE

    def test_a_model_that_answered_badly_is_not(self, engine_mod):
        # Something was listening and what it said was wrong. That is a bug and keeps its
        # traceback — folding it in here would hide real breakage behind a friendly warning.
        assert engine_mod.classify_model_failure(ValueError("not JSON")) is None

    def test_a_cycle_in_the_chain_terminates(self, engine_mod):
        a = RuntimeError("a")
        b = RuntimeError("b")
        a.__cause__ = b
        b.__cause__ = a
        assert engine_mod.classify_model_failure(a) is None


class TestTheMeetingSurvives:
    @pytest.mark.anyio
    async def test_the_transcript_is_untouched_and_the_reason_is_recorded(self, engine_mod):
        async def call(*_args, **_kw):
            raise Unreachable("All connection attempts failed")

        engine = build(engine_mod, call)
        engine.add(segments(3))
        frame = await engine.run(force=True)

        assert engine.model_unavailable == engine_mod.MODEL_UNREACHABLE
        # A frame is still produced: "notes stopped" is news, and a card that shows nothing
        # cannot tell the user why there is nothing.
        assert frame is not None
        assert frame["model_unavailable"] == engine_mod.MODEL_UNREACHABLE
        assert engine.stored_notes()["model_unavailable"] == engine_mod.MODEL_UNREACHABLE

    @pytest.mark.anyio
    async def test_one_warning_per_outage_and_never_a_traceback(self, engine_mod, caplog):
        """The log volume *is* the bug: sixty tracebacks bury the next real failure."""
        async def call(*_args, **_kw):
            raise Unreachable("All connection attempts failed")

        clock = [1000.0]
        engine = build(engine_mod, call, now=lambda: clock[0])

        with caplog.at_level("DEBUG"):
            for _ in range(4):
                engine.add(segments())
                clock[0] += engine_mod.MODEL_RETRY_AFTER_S + 1
                await engine.run(force=True)

        assert not any(record.exc_info for record in caplog.records), \
            "an unreachable model is an expected state, not a stack trace"
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1, "one outage, one line — not one per window"
        assert "no language model reachable" in warnings[0].getMessage()
        # And it says the thing the user actually needs to know.
        assert "transcript is unaffected" in warnings[0].getMessage()

    @pytest.mark.anyio
    async def test_a_model_that_answers_badly_still_gets_its_traceback(self, engine_mod, caplog):
        async def call(*_args, **_kw):
            raise ValueError("exploded mid-generation")

        engine = build(engine_mod, call)
        engine.add(segments())
        with caplog.at_level("DEBUG"):
            await engine.run(force=True)

        assert any(record.exc_info for record in caplog.records), \
            "something answered and broke; that is a bug and wants a stack"
        assert engine.model_unavailable is None

    @pytest.mark.anyio
    async def test_a_resting_model_is_not_asked_again(self, engine_mod):
        # The retry window is what stops a stopped model costing two connection timeouts a
        # minute for the length of the meeting.
        calls = []

        async def call(*_args, **_kw):
            calls.append(1)
            raise Unreachable("refused")

        clock = [1000.0]
        engine = build(engine_mod, call, now=lambda: clock[0])
        engine.add(segments())
        await engine.run(force=True)
        first = len(calls)

        engine.add(segments())
        clock[0] += 1
        await engine.run(force=True)

        assert len(calls) == first, "a model that just refused must not be asked again"

    @pytest.mark.anyio
    async def test_one_window_costs_one_attempt_not_two(self, engine_mod):
        # Delta and recap are two calls. Once the first has established that nothing is
        # listening, the second is a guaranteed wait for the same answer.
        calls = []

        async def call(*_args, **_kw):
            calls.append(1)
            raise Unreachable("refused")

        engine = build(engine_mod, call)
        engine.add(segments())
        await engine.run(force=True)

        assert len(calls) == 1

    @pytest.mark.anyio
    async def test_notes_resume_when_the_model_comes_back(self, engine_mod):
        # The outage must not be sticky: the point of a retry window is that it ends.
        state = {"up": False}

        async def call(messages, **_kw):
            if not state["up"]:
                raise Unreachable("refused")
            return '{"summary": "we agreed on pricing"}'

        clock = [1000.0]
        engine = build(engine_mod, call, now=lambda: clock[0])
        engine.add(segments())
        await engine.run(force=True)
        assert engine.model_unavailable == engine_mod.MODEL_UNREACHABLE

        state["up"] = True
        clock[0] += engine_mod.MODEL_RETRY_AFTER_S + 1
        engine.add(segments())
        frame = await engine.run(force=True)

        assert engine.model_unavailable is None
        assert frame is not None
        assert frame["model_unavailable"] is None
        # And the reason is gone from what gets stored, not just from memory.
        assert "model_unavailable" not in engine.stored_notes()


class TestTheMeetingMessage:
    def test_an_empty_notes_record_still_shows_the_transcript(self, app):
        # The fallback preview used to be suppressed by a notes record that existed and said
        # nothing, so the message was a header, a count, and silence.
        finalize = importlib.import_module("app.meetingsense.finalize")
        message = finalize.meeting_message(
            {"id": "m1", "title": "Standup", "started_at": 0, "ended_at": 60},
            segments(2),
            [],
            notes={"summary": "", "decisions": [], "actions": [], "questions": [],
                   "recap": "", "model_unavailable": "model_unreachable"},
        )
        assert "line 0" in message
        assert "no language model was reachable" in message

    def test_real_notes_are_unaffected(self, app):
        finalize = importlib.import_module("app.meetingsense.finalize")
        message = finalize.meeting_message(
            {"id": "m1", "title": "Standup", "started_at": 0, "ended_at": 60},
            segments(2),
            [],
            notes={"summary": "", "decisions": [], "actions": [], "questions": [],
                   "recap": "we agreed on pricing"},
        )
        assert "we agreed on pricing" in message
        assert "no language model was reachable" not in message
