"""Captioning a slide (batch MS9, wave W3).

Three claims carry the server half of this batch.

**A slide is captioned once, however many times it is shown.** The presenter goes back to
slide 4; the timeline has to record that it was up again, and the vision model must not be
asked to describe the same picture a second time. The perceptual hash the client sends is what
makes the difference, and the reuse is scoped to one meeting — a 64-bit hash is small enough
that a collision across a whole install is not a thing to call impossible.

**Nothing here is remembered (D4).** ``analyze_image`` is called directly rather than through
``/v1/multimodal/analyze``, which is exactly the ``persist`` flag that endpoint carries: the
chat path writes its analysis into a conversation and hands it to the memory extractor, and
this path writes a caption onto one keyframe row.

**A caption is never worth a meeting.** No model, a timeout, a model that answered with an
apology — every one of them ends with a keyframe that has no caption and a meeting that is
still recording. The tests for those paths are the ones that matter, because a failure in a
best-effort path is invisible until someone reads the log.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_VISION_MODEL", "MULTIMODAL_MODEL"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.config as config
        import app.meetingsense.keyframes as keyframes
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.config = config
        self.keyframes = keyframes
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    mods = Modules()
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(mods.store, "_connect", _connect)
    mods.store.migrate()
    mods.session._SESSIONS.clear()
    return mods


class Vision:
    """A vision model that answers from a script and counts how often it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers) or ["A slide titled Q3 revenue, showing growth of 14%."]
        self.calls = []

    async def __call__(self, image_url, upload_path, **kwargs):
        self.calls.append({"url": image_url, "path": upload_path, **kwargs})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, dict):
            return answer
        return {"ok": True, "analysis_text": answer, "meta": {"model": "stub"}}


def meeting(mods, mid="m1"):
    mods.store.create_meeting(conversation_id="c1", meeting_id=mid, started_at=0.0)
    return mid


# ── clean_caption ───────────────────────────────────────────────────────────


class TestCleanCaption:
    def test_collapses_the_whitespace_a_model_answers_with(self, modules):
        text = modules.keyframes.clean_caption("  Q3 revenue.\n\n Growth of 14%.  ")
        assert text == "Q3 revenue. Growth of 14%."

    def test_a_refusal_is_not_a_caption(self, modules):
        # Storing one puts "I cannot see the image" in the meeting summary where a description
        # belongs — worse than a blank, because a blank is visibly missing.
        for refusal in ("I cannot see this image.", "Sorry, I am unable to help with that.",
                        "As an AI, I do not see any content."):
            assert modules.keyframes.clean_caption(refusal) == ""

    def test_a_refusal_word_inside_a_real_caption_is_left_alone(self, modules):
        # The check is on the opening, not on the text: a slide can legitimately be about an
        # apology, and dropping that caption would lose the one slide that mattered.
        text = modules.keyframes.clean_caption("A slide reading: we are sorry for the outage.")
        assert text.startswith("A slide reading")

    def test_a_long_answer_is_cut_at_a_word(self, modules):
        long = " ".join(["revenue"] * 200)
        text = modules.keyframes.clean_caption(long)
        assert len(text) <= modules.keyframes.MAX_CAPTION_CHARS + 1
        assert text.endswith("…")
        # Cut mid-word it reads as corrupted data rather than as a long answer.
        assert not text.rstrip("…").endswith("reven")

    def test_anything_that_is_not_text_is_nothing(self, modules):
        for value in (None, 42, {"caption": "x"}, "", "   "):
            assert modules.keyframes.clean_caption(value) == ""


# ── captioning one keyframe ─────────────────────────────────────────────────


class TestCaption:
    def test_a_keyframe_is_captioned_and_the_slide_frame_says_so(self, modules):
        mid = meeting(modules)
        kid = modules.store.add_keyframe(mid, t_ms=5000, url="/files/a.jpg", hash="abcd")
        vision = Vision("A slide titled Q3 revenue.")

        frame = run(modules.keyframes.caption(mid, kid, url="/files/a.jpg", hash="abcd",
                                              t_ms=5000, analyze=vision))

        assert frame == {"type": "slide", "id": kid, "t": 5000, "url": "/files/a.jpg",
                         "caption": "A slide titled Q3 revenue.", "hash": "abcd", "reused": False}
        assert modules.store.get_keyframe(kid)["caption"] == "A slide titled Q3 revenue."

    def test_the_model_is_asked_about_a_slide_and_not_about_an_image(self, modules):
        # The default prompt produces "a computer screen showing a presentation with blue
        # text", which is true of every slide in the deck and therefore identifies none of
        # them. What makes a slide findable — by a reader and by MS13's retrieval — is its
        # title and the substance of what is on it.
        mid = meeting(modules)
        kid = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg")
        vision = Vision()
        run(modules.keyframes.caption(mid, kid, url="/files/a.jpg", analyze=vision))
        assert vision.calls[0]["user_prompt"] == modules.keyframes.SLIDE_PROMPT
        assert "meeting" in modules.keyframes.SLIDE_PROMPT.lower()

    def test_a_reshown_slide_reuses_the_caption_instead_of_the_model(self, modules):
        mid = meeting(modules)
        first = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg", hash="same")
        second = modules.store.add_keyframe(mid, t_ms=60_000, url="/files/b.jpg", hash="same")
        vision = Vision("The architecture diagram.", "A completely different answer.")

        run(modules.keyframes.caption(mid, first, url="/files/a.jpg", hash="same", analyze=vision))
        frame = run(modules.keyframes.caption(mid, second, url="/files/b.jpg", hash="same",
                                              t_ms=60_000, analyze=vision))

        # One model call for two showings — and, more importantly, one wording. Two strip
        # entries for one slide whose captions disagree read as two different slides.
        assert len(vision.calls) == 1
        assert frame["reused"] is True
        assert frame["caption"] == "The architecture diagram."
        assert modules.store.get_keyframe(second)["caption"] == "The architecture diagram."

    def test_a_different_slide_is_captioned_again(self, modules):
        mid = meeting(modules)
        first = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg", hash="aaaa")
        second = modules.store.add_keyframe(mid, t_ms=30_000, url="/files/b.jpg", hash="bbbb")
        vision = Vision("Slide one.", "Slide two.")

        run(modules.keyframes.caption(mid, first, url="/files/a.jpg", hash="aaaa", analyze=vision))
        frame = run(modules.keyframes.caption(mid, second, url="/files/b.jpg", hash="bbbb",
                                              analyze=vision))

        assert len(vision.calls) == 2
        assert frame["caption"] == "Slide two."
        assert frame["reused"] is False

    def test_reuse_does_not_cross_meetings(self, modules):
        # A 64-bit perceptual hash is small enough that "never collides" is not true, and the
        # cost of a collision across meetings is one meeting's caption on another's slide.
        one = meeting(modules, "m1")
        two = meeting(modules, "m2")
        a = modules.store.add_keyframe(one, t_ms=0, url="/files/a.jpg", hash="same")
        b = modules.store.add_keyframe(two, t_ms=0, url="/files/b.jpg", hash="same")
        vision = Vision("Meeting one's slide.", "Meeting two's slide.")

        run(modules.keyframes.caption(one, a, url="/files/a.jpg", hash="same", analyze=vision))
        frame = run(modules.keyframes.caption(two, b, url="/files/b.jpg", hash="same", analyze=vision))

        assert len(vision.calls) == 2
        assert frame["caption"] == "Meeting two's slide."

    def test_an_uncaptioned_earlier_frame_does_not_shadow_the_model(self, modules):
        # The first showing failed to caption — no model, a timeout. The second showing must
        # reach the model rather than copy the empty string and call it done.
        mid = meeting(modules)
        first = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg", hash="same")
        second = modules.store.add_keyframe(mid, t_ms=30_000, url="/files/b.jpg", hash="same")
        run(modules.keyframes.caption(mid, first, url="/files/a.jpg", hash="same",
                                      analyze=Vision({"ok": False, "error": "no model"})))
        vision = Vision("The architecture diagram.")
        frame = run(modules.keyframes.caption(mid, second, url="/files/b.jpg", hash="same",
                                              analyze=vision))
        assert len(vision.calls) == 1
        assert frame["caption"] == "The architecture diagram."

    @pytest.mark.parametrize("empty", [None, ""])
    def test_a_keyframe_with_no_hash_is_never_matched_to_another(self, modules, empty):
        # ``None`` and ``""`` are two different absences and only one of them is handled by
        # SQL: ``hash = NULL`` matches nothing, but ``hash = ''`` matches every other frame a
        # client sent an empty hash for. Without the guard, the first slide captioned in such
        # a meeting becomes the caption of every slide after it.
        mid = meeting(modules)
        first = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg", hash=empty)
        second = modules.store.add_keyframe(mid, t_ms=30_000, url="/files/b.jpg", hash=empty)
        vision = Vision("One.", "Two.")
        run(modules.keyframes.caption(mid, first, url="/files/a.jpg", hash=empty, analyze=vision))
        frame = run(modules.keyframes.caption(mid, second, url="/files/b.jpg", hash=empty,
                                              analyze=vision))
        assert len(vision.calls) == 2
        assert frame["caption"] == "Two."


class TestCaptionFailures:
    def test_no_vision_model_means_no_caption_and_no_error(self, modules):
        mid = meeting(modules)
        kid = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg", hash="x")
        assert run(modules.keyframes.caption(mid, kid, url="/files/a.jpg", hash="x")) is None
        assert not modules.store.get_keyframe(kid)["caption"]

    def test_a_model_that_answers_not_ok_stores_nothing(self, modules):
        mid = meeting(modules)
        kid = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg")
        vision = Vision({"ok": False, "error": "no vision model installed", "analysis_text": ""})
        assert run(modules.keyframes.caption(mid, kid, url="/files/a.jpg", analyze=vision)) is None
        assert not modules.store.get_keyframe(kid)["caption"]

    def test_a_failed_answer_that_still_carries_text_is_not_a_caption(self, modules):
        # `ok` is the field that says whether the answer is an answer. A request that timed
        # out part-way carries whatever arrived before it died, and storing that puts half a
        # sentence in the meeting summary — which reads as the slide rather than as a failure.
        mid = meeting(modules)
        kid = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg")
        vision = Vision({"ok": False, "error": "read timeout", "analysis_text": "A slide about"})
        assert run(modules.keyframes.caption(mid, kid, url="/files/a.jpg", analyze=vision)) is None
        assert not modules.store.get_keyframe(kid)["caption"]

    def test_a_model_that_raises_does_not(self, modules):
        mid = meeting(modules)
        kid = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg")
        vision = Vision(RuntimeError("the vision endpoint timed out"))
        assert run(modules.keyframes.caption(mid, kid, url="/files/a.jpg", analyze=vision)) is None
        assert not modules.store.get_keyframe(kid)["caption"]

    def test_a_refusal_is_not_stored_as_the_caption(self, modules):
        mid = meeting(modules)
        kid = modules.store.add_keyframe(mid, t_ms=0, url="/files/a.jpg")
        vision = Vision("I cannot see any image here.")
        assert run(modules.keyframes.caption(mid, kid, url="/files/a.jpg", analyze=vision)) is None
        assert not modules.store.get_keyframe(kid)["caption"]

    def test_the_upload_root_is_resolved_even_when_there_is_no_app(self, modules):
        # The module has to be importable and testable without FastAPI around it, the same way
        # retention is. `None` is a legitimate answer, not a crash.
        assert modules.keyframes.upload_path() is None or modules.keyframes.upload_path()


# ── the session path ────────────────────────────────────────────────────────


def live_session(mods, vision=None):
    cfg = mods.config.load_config()
    session = mods.session.MeetingSession(
        transport=mods.session.ListTransport(),
        config=cfg,
        vision=vision,
        now=lambda: 0.0,
    )
    return session


class TestSessionKeyframes:
    def test_a_keyframe_is_stored_and_then_captioned(self, modules):
        vision = Vision("The roadmap slide.")

        async def scenario():
            session = live_session(modules, vision)
            await session.start({"conversation_id": "c1", "watch": True})
            kid = await session.on_keyframe({"type": "keyframe", "t": 4000,
                                             "url": "/files/a.jpg", "hash": "abcd"})
            # The caption is not awaited by `on_keyframe` — it runs alongside the audio the
            # same frame loop is carrying, which is the whole reason it is a task.
            await session.drain_captions()
            return session, kid

        session, kid = run(scenario())
        assert modules.store.get_keyframe(kid)["caption"] == "The roadmap slide."
        slides = [f for f in session.transport.frames if f.get("type") == "slide"]
        assert [f["id"] for f in slides] == [kid]
        assert slides[0]["t"] == 4000

    def test_captioning_does_not_block_the_frame_loop(self, modules):
        # The claim `on_keyframe` makes: it returns before the model does. A meeting whose
        # transcript stalls for three seconds every time a slide changes is a worse meeting
        # than one whose captions arrive late.
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow(image_url, upload_path, **kwargs):
            started.set()
            await release.wait()
            return {"ok": True, "analysis_text": "Eventually."}

        async def scenario():
            session = live_session(modules, slow)
            await session.start({"conversation_id": "c1"})
            # wait_for, not a bare await: if `on_keyframe` were changed to await the model
            # inline this call would never return, and a hanging test says far less than a
            # failing one — MS3 learned that the same way.
            kid = await asyncio.wait_for(
                session.on_keyframe({"url": "/files/a.jpg", "t": 1000}), timeout=1
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            # on_keyframe has returned while the model is still thinking.
            assert modules.store.get_keyframe(kid)["caption"] in (None, "")
            release.set()
            await session.drain_captions()
            return kid

        kid = run(scenario())
        assert modules.store.get_keyframe(kid)["caption"] == "Eventually."

    def test_a_meeting_with_no_vision_records_slides_and_schedules_nothing(self, modules):
        async def scenario():
            session = live_session(modules, None)
            await session.start({"conversation_id": "c1"})
            kid = await session.on_keyframe({"url": "/files/a.jpg", "t": 1000, "hash": "z"})
            return session, kid

        session, kid = run(scenario())
        assert modules.store.get_keyframe(kid)["url"] == "/files/a.jpg"
        assert session.caption_tasks == []
        assert [f for f in session.transport.frames if f.get("type") == "slide"] == []

    def test_stop_waits_for_the_caption_the_summary_is_about_to_quote(self, modules):
        # finalize writes the summary message inside `stop`. A caption that lands a second
        # after it is a caption nobody reads.
        #
        # The stub sleeps, and has to: a vision call that returns without ever suspending is
        # finished by the first `await` anywhere inside `stop`, so a test written against an
        # instant model passes with the drain deleted. What is being asserted is that `stop`
        # waits for a model that is actually slow, which is every real one.
        async def slow(image_url, upload_path, **kwargs):
            await asyncio.sleep(0.05)
            return {"ok": True, "analysis_text": "The final slide."}

        async def scenario():
            session = live_session(modules, slow)
            await session.start({"conversation_id": "c1"})
            kid = await session.on_keyframe({"url": "/files/a.jpg", "t": 1000, "hash": "q"})
            await session.stop()
            return kid

        kid = run(scenario())
        assert modules.store.get_keyframe(kid)["caption"] == "The final slide."

    def test_a_hung_caption_is_abandoned_rather_than_holding_the_meeting_open(self, modules):
        forever = asyncio.Event()

        async def hangs(image_url, upload_path, **kwargs):
            await forever.wait()
            return {"ok": True, "analysis_text": "never"}

        async def scenario():
            session = live_session(modules, hangs)
            await session.start({"conversation_id": "c1"})
            await asyncio.wait_for(
                session.on_keyframe({"url": "/files/a.jpg", "t": 1000}), timeout=1
            )
            unfinished = await session.drain_captions(timeout=0.01)
            final = await session.stop()
            return unfinished, final

        unfinished, final = run(scenario())
        assert unfinished == 1
        assert final["type"] == "final"

    def test_a_keyframe_without_a_url_is_refused(self, modules):
        async def scenario():
            session = live_session(modules, Vision())
            await session.start({"conversation_id": "c1"})
            with pytest.raises(modules.session.MeetingSessionError) as exc:
                await session.on_keyframe({"t": 1000})
            return exc.value

        assert run(scenario()).code == "url_required"

    def test_the_slide_count_the_card_shows_counts_keyframes(self, modules):
        async def scenario():
            session = live_session(modules, None)
            await session.start({"conversation_id": "c1"})
            await session.on_keyframe({"url": "/files/a.jpg", "t": 1000})
            await session.on_keyframe({"url": "/files/b.jpg", "t": 20000})
            return await session.send_status()

        assert run(scenario())["slides"] == 2
