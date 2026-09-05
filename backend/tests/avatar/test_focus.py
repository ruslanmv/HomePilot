"""B22 — focus streaks: the arithmetic, the category, and the day after.

The interesting tests are the calendar ones. A streak is entirely about which day it is, so
the arithmetic takes the date as an argument and these tests hand it a calendar — including
the two cases a clock-reading implementation cannot be asked about at all: a midnight, and a
gap.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import date, timedelta

import pytest

from app.avatar_director import focus
from app.avatar_director.protocol import ProtocolHandler

MON = date(2026, 9, 7)
TUE = MON + timedelta(days=1)
WED = MON + timedelta(days=2)
NEXT_MON = MON + timedelta(days=7)


def codeof(module) -> str:
    text = inspect.getsource(module)
    text = re.sub(r'"""[\s\S]*?"""', " ", text)
    text = re.sub(r"(^|[^:])#.*$", r"\1", text, flags=re.MULTILINE)
    return text


def fresh() -> focus.StreakRecord:
    return focus.StreakRecord(activity="focus")


class FakeLTM:
    """The subset of ``app.ltm`` a store touches, so these tests need no sqlite.

    Deliberately keyed the way the real one is — ``(project_id, category, key)`` — so a
    store that used the wrong key would fail here rather than in production.
    """

    def __init__(self):
        self.rows = {}
        self.categories = []

    def upsert_memory(self, project_id, category, key, value, **kwargs):
        self.categories.append(category)
        self.rows[(project_id, category, key, kwargs.get("user_id"))] = {"key": key, "value": value}
        return True

    def get_memories(self, project_id, category=None, user_id=None):
        return [
            row
            for (pid, cat, _key, uid), row in self.rows.items()
            if pid == project_id and (category is None or cat == category) and uid == user_id
        ]

    def delete_memory(self, project_id, category, key, user_id=None):
        return self.rows.pop((project_id, category, key, user_id), None) is not None


# ── the arithmetic ───────────────────────────────────────────────────────────


class TestAdvance:
    def test_the_first_block_ever_is_day_one(self):
        record = focus.advance(fresh(), MON)
        assert (record.days, record.blocks, record.blocks_today) == (1, 1, 1)
        assert record.last_day == MON.isoformat()

    def test_a_second_block_today_does_not_advance_the_day_count(self):
        # A streak counts days shown up, not work done. Otherwise one frantic afternoon
        # out-ranks a fortnight of mornings.
        record = focus.advance(focus.advance(fresh(), MON), MON)
        assert record.days == 1
        assert record.blocks == 2
        assert record.blocks_today == 2

    def test_a_block_the_next_day_advances_it(self):
        record = focus.advance(focus.advance(fresh(), MON), TUE)
        assert record.days == 2
        assert record.blocks_today == 1

    def test_three_days_running(self):
        record = fresh()
        for day in (MON, TUE, WED):
            record = focus.advance(record, day)
        assert record.days == 3
        assert record.best == 3

    def test_a_gap_resets_the_streak_to_one(self):
        record = fresh()
        for day in (MON, TUE, WED):
            record = focus.advance(record, day)
        record = focus.advance(record, NEXT_MON)
        assert record.days == 1

    def test_but_never_the_best(self):
        # The fortnight happened whether or not it is still happening.
        record = fresh()
        for day in (MON, TUE, WED):
            record = focus.advance(record, day)
        record = focus.advance(record, NEXT_MON)
        assert record.best == 3

    def test_blocks_are_cumulative_across_a_gap(self):
        record = fresh()
        for day in (MON, TUE, NEXT_MON):
            record = focus.advance(record, day)
        assert record.blocks == 3

    def test_it_returns_a_new_record_rather_than_mutating(self):
        # So a store that raises between the increment and the write cannot leave the
        # in-memory record ahead of the row.
        before = fresh()
        after = focus.advance(before, MON)
        assert before.days == 0
        assert after is not before

    def test_the_function_reads_no_clock(self):
        source = codeof(focus)
        for token in ["date.today", "datetime.now", "time.time", "utcnow"]:
            assert token not in source, f"focus.py reads {token} — the day must be an argument"

    def test_the_stripper_is_not_vacuous(self):
        assert "def advance(" in codeof(focus)


class TestParseDay:
    @pytest.mark.parametrize("value", ["", None, "not a day", "2026-13-45", 7])
    def test_a_value_that_will_not_parse_is_no_day_not_a_crash(self, value):
        assert focus.parse_day(value) is None

    def test_a_record_with_a_broken_last_day_starts_over_rather_than_raising(self):
        record = focus.StreakRecord(activity="focus", days=9, best=9, last_day="tuesday-ish")
        assert focus.advance(record, MON).days == 1


class TestIsLive:
    def test_a_streak_touched_today_is_live(self):
        assert focus.is_live(focus.advance(fresh(), MON), MON)

    def test_a_streak_touched_yesterday_is_still_live(self):
        # At 9am on Tuesday a Monday streak is alive and about to be continued. Showing a
        # zero every morning until the first block lands is the opposite of the point.
        assert focus.is_live(focus.advance(fresh(), MON), TUE)

    def test_a_streak_two_days_old_is_not(self):
        assert not focus.is_live(focus.advance(fresh(), MON), WED)

    def test_an_empty_record_is_not_live(self):
        assert not focus.is_live(fresh(), MON)

    def test_a_dead_streak_reports_zero_days_but_keeps_its_best(self):
        record = focus.advance(focus.advance(fresh(), MON), TUE)
        summary = focus.summarise(record, NEXT_MON)
        assert summary["days"] == 0
        assert summary["best"] == 2
        assert summary["live"] is False


# ── one more category, not one more store ────────────────────────────────────


class TestStore:
    def test_it_writes_to_the_focus_streak_category(self):
        ltm = FakeLTM()
        focus.StreakStore("p1", ltm=ltm).record_block("focus", MON)
        assert ltm.categories == [focus.CATEGORY]

    def test_the_category_is_declared_in_ltm(self):
        # A category the store writes but LTM does not know is a row nothing will validate.
        from app.ltm import VALID_CATEGORIES

        assert focus.CATEGORY in VALID_CATEGORIES

    def test_a_streak_survives_the_store_being_rebuilt(self):
        # "Recalled next session", as literally as a unit test can put it: a second store
        # over the same memory, holding nothing of its own.
        ltm = FakeLTM()
        focus.StreakStore("p1", ltm=ltm).record_block("focus", MON)
        focus.StreakStore("p1", ltm=ltm).record_block("focus", TUE)
        assert focus.StreakStore("p1", ltm=ltm).recall("focus", TUE) == {
            "activity": "focus",
            "days": 2,
            "best": 2,
            "blocks": 2,
            "live": True,
        }

    def test_an_absent_streak_is_zero_rather_than_none(self):
        assert focus.StreakStore("p1", ltm=FakeLTM()).get("focus").days == 0

    def test_streaks_are_per_persona(self):
        ltm = FakeLTM()
        focus.StreakStore("p1", ltm=ltm).record_block("focus", MON)
        assert focus.StreakStore("p2", ltm=ltm).get("focus").days == 0

    def test_streaks_are_per_user(self):
        ltm = FakeLTM()
        focus.StreakStore("p1", user_id="a", ltm=ltm).record_block("focus", MON)
        assert focus.StreakStore("p1", user_id="b", ltm=ltm).get("focus").days == 0

    def test_forgetting_the_persona_forgets_the_streak(self):
        # The reason this is a category rather than a table: the delete button the user
        # already has must reach it.
        ltm = FakeLTM()
        store = focus.StreakStore("p1", ltm=ltm)
        store.record_block("focus", MON)
        assert store.forget("focus")
        assert store.get("focus").days == 0

    def test_an_unknown_activity_is_refused(self):
        with pytest.raises(focus.FocusError) as caught:
            focus.StreakStore("p1", ltm=FakeLTM()).record_block("doomscrolling", MON)
        assert caught.value.code == "activity_unknown"

    def test_the_store_holds_nothing_of_its_own(self):
        # The moment it grows a cache it is the parallel store this batch rules out.
        source = codeof(focus)
        for token in ["self._cache", "self.rows", "sqlite", "open(", "Path("]:
            assert token not in source

    def test_a_row_that_will_not_parse_is_skipped_not_fatal(self):
        ltm = FakeLTM()
        ltm.rows[("p1", focus.CATEGORY, "focus", None)] = {"key": "focus", "value": "{not json"}
        assert focus.StreakStore("p1", ltm=ltm).all() == []

    def test_the_serialised_value_round_trips(self):
        record = focus.advance(fresh(), MON)
        row = {"key": "focus", "value": record.as_value()}
        assert focus.StreakRecord.from_row(row) == record

    def test_the_value_is_json_an_operator_can_read(self):
        payload = json.loads(focus.advance(fresh(), MON).as_value())
        assert payload["days"] == 1
        assert payload["last_day"] == MON.isoformat()


# ── the protocol seam ────────────────────────────────────────────────────────


class TestProtocolSeam:
    def make(self, ltm, when):
        return self.hello(
            ProtocolHandler(now=lambda: when, streaks=focus.StreakStore("p1", ltm=ltm))
        )

    @staticmethod
    def hello(handler):
        """A `streak` before `hello` is unauthenticated, like every other frame. Say hello."""
        handler.handle({"v": 1, "type": "hello", "client": "test", "auth": "token"})
        return handler

    def stamp(self, day):
        import datetime

        return datetime.datetime.combine(day, datetime.time(12, 0)).timestamp()

    def test_a_streak_frame_lands_in_long_term_memory(self):
        ltm = FakeLTM()
        handler = self.make(ltm, self.stamp(MON))
        handler.handle({"v": 1, "type": "streak", "activity": "focus", "value": 1})
        assert focus.StreakStore("p1", ltm=ltm).get("focus").days == 1

    def test_two_days_of_frames_make_a_two_day_streak(self):
        ltm = FakeLTM()
        self.make(ltm, self.stamp(MON)).handle({"v": 1, "type": "streak", "activity": "focus", "value": 1})
        self.make(ltm, self.stamp(TUE)).handle({"v": 1, "type": "streak", "activity": "focus", "value": 1})
        assert focus.StreakStore("p1", ltm=ltm).get("focus").days == 2

    def test_without_a_store_the_frame_behaves_exactly_as_it_did_before(self):
        handler = self.hello(ProtocolHandler())
        assert handler.handle({"v": 1, "type": "streak", "activity": "focus", "value": 4}) == []
        assert handler.state.streaks == {"focus": 4}

    def test_a_store_that_raises_does_not_cost_the_client_its_session(self):
        class Broken:
            def record_block(self, activity, today):
                raise RuntimeError("the disk is on fire")

        handler = self.hello(ProtocolHandler(streaks=Broken()))
        assert handler.handle({"v": 1, "type": "streak", "activity": "focus", "value": 1}) == []
        assert handler.state.streaks == {"focus": 1}

    def test_an_unknown_activity_from_a_client_is_survivable(self):
        ltm = FakeLTM()
        handler = self.make(ltm, self.stamp(MON))
        assert handler.handle({"v": 1, "type": "streak", "activity": "nonsense", "value": 1}) == []
        assert ltm.rows == {}

    def test_the_day_comes_from_the_handlers_own_clock(self):
        # Not date.today(): a session that opened before midnight and completes a block
        # after it should record the day the handler is told it is.
        ltm = FakeLTM()
        self.make(ltm, self.stamp(NEXT_MON)).handle({"v": 1, "type": "streak", "activity": "focus", "value": 1})
        assert focus.StreakStore("p1", ltm=ltm).get("focus").last_day == NEXT_MON.isoformat()
