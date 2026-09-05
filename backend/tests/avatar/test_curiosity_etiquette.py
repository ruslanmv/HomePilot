"""The silences (B16).

§6.12 gives curiosity a budget and four hard mutes. The budget is the easy part. The mutes
are what decide whether a companion is warm or is a notification with a face, so every one
of them is a **negative assertion** here: the event that should silence her is fired, an
initiative is asked for, and the test fails if anything comes back.

The last block is the twenty-minute session — a scripted transcript with all the ordinary
awkwardness in it (a phone call, a meditation, a film) replayed second by second, asserting
that every moment she spoke was a moment she was allowed to. It is the machine half of the
acceptance; the human half is a person sitting the session, and no test can stand in for
that. See `docs/AVATAR_DIRECTOR_BATCHES.md`.
"""

from __future__ import annotations

import pytest

from app.avatar_director.config import AvatarDirectorConfig, CuriosityConfig
from app.avatar_director.curiosity import (
    ATTENTION_MUTE,
    SILENT_SCENES,
    CuriosityEngine,
    InitiativeScheduler,
    InterestRecord,
    InterestStore,
)


class MemoryStore(InterestStore):
    """The store, in a dict. The sqlite path is proved in `test_curiosity.py`; here the
    subject is the scheduler, and a database would only slow the twenty-minute replay."""

    def __init__(self) -> None:
        super().__init__("kira")
        self.records: dict = {}

    def all(self):
        return list(self.records.values())

    def get(self, topic):
        return self.records.get(topic)

    def save(self, record):
        self.records[record.topic] = record
        return record

    def forget(self, topic):
        return self.records.pop(topic, None) is not None


OPENINGS = ["media:paused", "media:cut", "gaze:user-look-avatar>1500", "user:silent>12000"]

#: Enough open threads that a test about budget or timing is not secretly a test about the
#: one-question-per-topic rule.
MANY_TOPICS = tuple((f"user.topic.number{i:02d}", 0.9 - i / 100.0) for i in range(12))


def scheduler(*, budget=4, min_gap_ms=90000, topics=(("user.hobby.aquarium", 0.7),), warm=True):
    """`warm` skips past the settling-in period, which has its own tests below. Without it
    every test here would secretly also be a test of that one rule."""
    clock = {"t": 1000.0}
    store = MemoryStore()
    for topic, curiosity in topics:
        store.save(InterestRecord(topic=topic, summary=f"About {topic}", curiosity=curiosity, openThread=True))

    config = AvatarDirectorConfig(
        enabled=True, curiosity=CuriosityConfig(session_budget=budget, min_gap_ms=min_gap_ms)
    )
    engine = CuriosityEngine(store, now=lambda: clock["t"])
    sched = InitiativeScheduler(engine, config, now=lambda: clock["t"])
    sched.set_openings(OPENINGS)
    sched.clock = clock
    sched.advance = lambda seconds: clock.__setitem__("t", clock["t"] + seconds)
    if warm:
        sched.advance(sched.min_session_age_ms / 1000 + 1)
    return sched


def opened(sched, name="media:paused"):
    """The polite moment §6.12 waits for."""
    sched.on_user_event(name)
    return sched


# ── the four mutes, each as a negative assertion ─────────────────────────────


class TestMutes:
    def test_she_does_not_speak_over_you(self):
        sched = opened(scheduler())
        sched.on_user_event("user:speaking")
        assert sched.due() is None
        assert sched.stats["refusals"] == {"user_speaking": 1}
        # And the budget was not spent on a turn she never took.
        assert sched.state.budget == 4

    def test_and_starts_again_when_you_stop(self):
        sched = opened(scheduler())
        sched.on_user_event("user:speaking")
        assert sched.due() is None
        sched.on_user_event("user:silent")
        assert sched.due() is not None

    def test_she_does_not_speak_when_the_activity_has_you(self):
        sched = opened(scheduler())
        sched.on_ctx({"attention": ATTENTION_MUTE})
        assert sched.due() is None
        assert "attention" in sched.stats["refusals"]

    def test_just_below_the_threshold_she_may(self):
        # A mute with no edge is a mute nobody can reason about.
        sched = opened(scheduler())
        sched.on_ctx({"attention": ATTENTION_MUTE - 0.01})
        assert sched.due() is not None

    def test_she_is_silent_in_a_meditation(self):
        sched = opened(scheduler())
        sched.on_ctx({"scene": "meditation"})
        assert sched.due() is None
        assert "scene" in sched.stats["refusals"]

    def test_every_scene_the_spec_silences_is_silenced(self):
        for scene in SILENT_SCENES:
            sched = opened(scheduler())
            sched.on_ctx({"scene": scene})
            assert sched.due() is None, scene

    def test_the_other_scenes_are_not_silenced(self):
        # Otherwise the rule is "scenes are quiet", which is not what §6.12 says.
        for scene in ("forest", "ocean", None):
            sched = opened(scheduler())
            sched.on_ctx({"scene": scene})
            assert sched.due() is not None, scene

    def test_leaving_the_meditation_lifts_it(self):
        sched = opened(scheduler())
        sched.on_ctx({"scene": "meditation"})
        assert sched.due() is None
        sched.on_ctx({"scene": None})
        opened(sched)
        assert sched.due() is not None

    def test_opting_out_means_out(self):
        sched = opened(scheduler())
        sched.on_user_event("curiosity:off")
        assert sched.due() is None
        assert "opted_out" in sched.stats["refusals"]

    def test_and_opting_back_in_means_in(self):
        sched = opened(scheduler())
        sched.on_user_event("curiosity:off")
        assert sched.due() is None
        sched.on_user_event("curiosity:on")
        assert sched.due() is not None

    def test_a_mute_beats_everything_else_including_a_perfect_opening(self):
        # The order matters: mutes are checked before the budget, so a muted session does
        # not spend budget it was never going to use.
        for setup in (
            lambda s: s.on_user_event("user:speaking"),
            lambda s: s.on_ctx({"attention": 1.0}),
            lambda s: s.on_ctx({"scene": "meditation"}),
            lambda s: s.on_user_event("curiosity:off"),
        ):
            sched = opened(scheduler(budget=99))
            setup(sched)
            assert sched.due() is None
            assert sched.state.budget == 99

    def test_she_does_not_greet_you_with_a_question(self):
        """Not one of §6.12's four mutes — this one came out of the twenty-minute replay,
        which opened an evening fifteen seconds in with "Mum's scan results are due this
        week". Correct by every other rule, and exactly what "felt intrusive" means."""
        sched = opened(scheduler(warm=False))
        assert sched.due() is None
        assert "too_early" in sched.stats["refusals"]

        sched.advance(sched.min_session_age_ms / 1000 + 1)
        opened(sched)
        assert sched.due() is not None

    def test_the_settling_in_period_comes_from_config(self):
        sched = scheduler(warm=False)
        assert sched.min_session_age_ms == 120000

    def test_every_mute_the_spec_lists_is_implemented(self):
        assert set(InitiativeScheduler.MUTES) == {"user_speaking", "attention", "scene", "opted_out"}


# ── the budget and the gap ───────────────────────────────────────────────────


class TestBudget:
    def test_the_budget_is_spent_and_then_she_stops(self):
        sched = scheduler(budget=2, min_gap_ms=0, topics=MANY_TOPICS)
        for _ in range(2):
            opened(sched)
            assert sched.due() is not None
        opened(sched)
        assert sched.due() is None
        assert sched.stats["refusals"].get("budget") == 1

    def test_exhausting_it_silences_the_rest_of_the_session(self):
        sched = scheduler(budget=1, min_gap_ms=0, topics=MANY_TOPICS)
        opened(sched)
        sched.due()
        for _ in range(50):
            sched.advance(600)
            opened(sched)
            assert sched.due() is None

    def test_a_budget_of_zero_is_silence_from_the_start(self):
        # Which is how a scene overlay mutes her (B14's meditation sets exactly this).
        sched = opened(scheduler(budget=0))
        assert sched.due() is None

    def test_the_gap_stops_four_interruptions_in_two_minutes(self):
        # A budget of four spent in the first two minutes is still four interruptions in
        # two minutes, which is the thing the budget was supposed to prevent.
        sched = scheduler(budget=4, min_gap_ms=90000, topics=MANY_TOPICS)
        opened(sched)
        assert sched.due() is not None

        sched.advance(30)
        opened(sched)
        assert sched.due() is None
        assert "too_soon" in sched.stats["refusals"]

        sched.advance(70)
        opened(sched)
        assert sched.due() is not None

    def test_the_gap_comes_from_config(self):
        sched = scheduler(min_gap_ms=1000, topics=MANY_TOPICS)
        opened(sched)
        sched.due()
        sched.advance(2)
        opened(sched)
        assert sched.due() is not None


# ── openings ─────────────────────────────────────────────────────────────────


class TestOpenings:
    def test_without_an_opening_she_says_nothing_at_all(self):
        sched = scheduler()
        assert sched.due() is None
        assert sched.stats["refusals"] == {"no_opening": 1}

    def test_every_opening_the_profile_lists_opens_it(self):
        for opening in OPENINGS:
            sched = scheduler()
            sched.on_user_event(opening.split(">")[0])
            assert sched.due() is not None, opening

    def test_an_event_that_is_not_an_opening_does_not_open_it(self):
        sched = scheduler()
        sched.on_user_event("media:playing")
        assert sched.due() is None

    def test_the_openings_come_from_the_profile_rather_than_from_here(self):
        # §6.12 says the openings are the active profile's, so a scene overlay changing them
        # changes what counts — which is only possible if they are not a constant here.
        sched = scheduler()
        sched.set_openings(["scene:enter"])
        sched.on_user_event("media:paused")
        assert sched.due() is None
        sched.on_user_event("scene:enter")
        assert sched.due() is not None

    def test_an_opening_is_spent_once(self):
        # Otherwise one polite moment licences every check that follows it, and "at a polite
        # moment" quietly becomes "from then on".
        sched = scheduler(budget=4, min_gap_ms=0, topics=MANY_TOPICS)
        opened(sched)
        assert sched.due() is not None
        assert sched.due() is None
        assert sched.stats["refusals"].get("no_opening") == 1

    def test_with_nothing_to_ask_about_an_opening_passes_quietly(self):
        sched = scheduler(topics=())
        opened(sched)
        assert sched.due() is None
        assert "nothing_to_ask" in sched.stats["refusals"]
        assert sched.state.budget == 4


# ── what it returns ──────────────────────────────────────────────────────────


class TestChoice:
    def test_it_returns_a_subject_and_not_a_sentence(self):
        # §6.12 leaves the wording to the persona LLM. Keeping generation out means no code
        # path can phrase something into existence past a mute.
        sched = opened(scheduler(topics=(("user.hobby.aquarium", 0.7),)))
        chosen = sched.due()
        assert set(chosen) == {"topic", "summary", "curiosity", "opening", "at"}
        assert chosen["topic"] == "user.hobby.aquarium"
        assert "say" not in chosen and "text" not in chosen

    def test_it_picks_the_most_curious_open_thread(self):
        sched = opened(
            scheduler(topics=(("user.hobby.aquarium", 0.4), ("user.work.thesis", 0.9), ("user.pet.cat", 0.6)))
        )
        assert sched.due()["topic"] == "user.work.thesis"

    def test_she_does_not_ask_the_same_question_twice_in_one_evening(self):
        """Argmax over a set that does not change picks the same topic every time. A
        companion who asks about the aquarium at 0:15, 2:30, 7:10 and 15:00 is the exact
        failure the twenty-minute review is meant to catch — and it did."""
        sched = scheduler(
            budget=4,
            min_gap_ms=0,
            topics=(("user.hobby.aquarium", 0.9), ("user.work.thesis", 0.8), ("user.pet.cat", 0.7)),
        )
        asked = []
        for _ in range(4):
            opened(sched)
            chosen = sched.due()
            if chosen:
                asked.append(chosen["topic"])

        assert asked == ["user.hobby.aquarium", "user.work.thesis", "user.pet.cat"]
        assert len(asked) == len(set(asked))

    def test_and_falls_silent_rather_than_repeating_itself(self):
        sched = scheduler(budget=4, min_gap_ms=0, topics=(("user.hobby.aquarium", 0.9),))
        opened(sched)
        assert sched.due() is not None
        opened(sched)
        assert sched.due() is None
        assert "nothing_to_ask" in sched.stats["refusals"]
        # And it did not spend budget on the turn it declined to take.
        assert sched.state.budget == 3

    def test_the_scheduler_has_no_clock_of_its_own(self):
        # "Consumes events only": no timer, no thread, nothing that could speak into a room
        # the client has not described in twenty minutes.
        import inspect

        from app.avatar_director import curiosity

        source = inspect.getsource(curiosity.InitiativeScheduler)
        for forbidden in ("Timer", "Thread", "sleep", "create_task", "asyncio"):
            assert forbidden not in source, forbidden


# ── twenty minutes ───────────────────────────────────────────────────────────


#: One evening, second by second. Times are seconds from the start of the session.
TWENTY_MINUTES = [
    (0, "ctx", {"activity": None, "attention": 0.2, "scene": None}),
    (15, "event", "user:silent"),
    (30, "event", "user:silent>12000"),  # a lull — the first polite moment
    (95, "event", "user:speaking"),  # they start telling a story
    (120, "event", "media:paused"),  # …and pause the film mid-sentence
    (150, "event", "user:silent"),
    (185, "event", "media:cut"),
    (240, "ctx", {"activity": "watch", "attention": 0.95, "scene": None}),  # gripped
    (300, "event", "media:cut"),
    (360, "event", "media:cut"),
    (420, "event", "media:paused"),
    (430, "ctx", {"activity": "watch", "attention": 0.4, "scene": None}),  # they look up
    (600, "ctx", {"activity": None, "attention": 0.1, "scene": "meditation"}),
    (620, "event", "user:silent>12000"),
    (700, "event", "media:paused"),
    (800, "event", "user:silent>12000"),
    (900, "ctx", {"activity": None, "attention": 0.2, "scene": None}),  # meditation ends
    (960, "event", "user:silent>12000"),
    (1020, "event", "user:speaking"),
    (1100, "event", "user:silent"),
    (1140, "event", "media:paused"),
    (1200, "event", "user:silent>12000"),
]


def replay(sched, script=TWENTY_MINUTES, seconds=1200):
    """Second by second, because `due` is asked on every tick in the real session too."""
    spoken = []
    pending = list(script)
    for second in range(seconds + 1):
        while pending and pending[0][0] <= second:
            _, kind, payload = pending.pop(0)
            if kind == "ctx":
                sched.on_ctx(payload)
            else:
                sched.on_user_event(str(payload).split(">")[0])
        sched.clock["t"] = 1000.0 + second
        chosen = sched.due()
        if chosen:
            # `second`, not `at`: the chosen dict carries its own `at` (the wall clock), and
            # spreading it over the replay's own key is how the first draft of this harness
            # reported second 30 as second 1030 and made a passing test out of nonsense.
            spoken.append({"second": second, "chosen": chosen, "state": dict(vars(sched.state))})
    return spoken


class TestTwentyMinutes:
    def test_she_does_not_repeat_a_topic_across_the_whole_session(self):
        sched = scheduler(
            budget=4,
            min_gap_ms=90000,
            topics=(("user.hobby.aquarium", 0.7), ("user.work.thesis", 0.5), ("user.pet.cat", 0.6)),
        )
        topics = [m["chosen"]["topic"] for m in replay(sched)]
        assert len(topics) == len(set(topics)), topics

    def test_she_speaks_a_handful_of_times_in_twenty_minutes(self):
        sched = scheduler(
            budget=4,
            min_gap_ms=90000,
            topics=(("user.hobby.aquarium", 0.7), ("user.work.thesis", 0.5), ("user.pet.cat", 0.6)),
        )
        spoken = replay(sched)

        # Four is the budget. Fewer is fine; more is the bug this whole file is about.
        assert 1 <= len(spoken) <= 4

    def test_no_moment_she_spoke_was_a_moment_she_was_muted(self):
        # The machine half of "no moment felt intrusive". Every mute, checked at the exact
        # second she opened her mouth.
        sched = scheduler(budget=4, min_gap_ms=90000, topics=MANY_TOPICS)
        for moment in replay(sched):
            state = moment["state"]
            assert state["speaking"] is False, moment["second"]
            assert state["attention"] < ATTENTION_MUTE, moment["second"]
            assert (state["scene"] or "") not in SILENT_SCENES, moment["second"]
            assert state["opted_out"] is False, moment["second"]

    def test_she_says_nothing_at_all_during_the_meditation(self):
        sched = scheduler(budget=4, min_gap_ms=0, topics=MANY_TOPICS)
        spoken = replay(sched)
        # The meditation runs 600–900 s and contains three openings.
        assert [m for m in spoken if 600 <= m["second"] < 900] == []

    def test_she_says_nothing_while_they_are_gripped_by_the_film(self):
        sched = scheduler(budget=9, min_gap_ms=0, topics=MANY_TOPICS)
        spoken = replay(sched)
        # Attention is 0.95 from 240 s until they look up at 430 s, and three cuts happen
        # in that window — every one of them a polite moment in any other stretch.
        assert [m for m in spoken if 240 <= m["second"] < 430] == []

    def test_she_never_interrupts_a_sentence(self):
        sched = scheduler(budget=9, min_gap_ms=0, topics=MANY_TOPICS)
        spoken = replay(sched)
        # 95–150 s and 1020–1100 s are them talking. The pause at 120 s is an opening that
        # lands mid-story, which is exactly the moment a naive scheduler takes.
        assert [m for m in spoken if 95 <= m["second"] < 150 or 1020 <= m["second"] < 1100] == []

    def test_with_an_unlimited_budget_the_mutes_still_hold(self):
        # Separating the two: a session that is quiet only because it ran out of budget
        # would pass every test above and still be rude on the fifth turn.
        sched = scheduler(budget=999, min_gap_ms=0, topics=MANY_TOPICS)
        for moment in replay(sched):
            state = moment["state"]
            assert state["speaking"] is False, moment["second"]
            assert state["attention"] < ATTENTION_MUTE, moment["second"]
            assert (state["scene"] or "") not in SILENT_SCENES, moment["second"]

    def test_the_replay_is_not_vacuous(self):
        # Every test above is a "nothing happened" assertion, so the session has to be one
        # where something could have.
        sched = scheduler(budget=999, min_gap_ms=0, topics=MANY_TOPICS)
        spoken = replay(sched)
        assert len(spoken) >= 4, "the transcript offers too few openings to be a real test"

    def test_the_transcript_contains_the_awkward_moments_on_purpose(self):
        events = [payload for _, kind, payload in TWENTY_MINUTES if kind == "event"]
        contexts = [payload for _, kind, payload in TWENTY_MINUTES if kind == "ctx"]
        assert "user:speaking" in events
        assert any(c.get("scene") == "meditation" for c in contexts)
        assert any(c.get("attention", 0) >= ATTENTION_MUTE for c in contexts)
        # And an opening that lands mid-story, which is the trap.
        assert any(t for t, kind, payload in TWENTY_MINUTES if kind == "event" and payload == "media:paused" and 95 < t < 150)
