"""Curiosity (B16) — the arithmetic, and the records living where the rest of memory does.

``test_curiosity_etiquette.py`` holds the mutes and the twenty-minute session. This file is
the scoring and the store, and the store half runs against a **real sqlite database** through
the real ``app.ltm`` — because "not a parallel store" is a claim about the actual store, and
a mock of ``ltm`` would prove only that this module can call a mock.
"""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from app import ltm
from app.avatar_director.curiosity import (
    CATEGORY,
    DAILY_DECAY,
    DISENGAGED_DELTA,
    ENGAGED_DELTA,
    FLOOR,
    MAX_RECORDS,
    CuriosityEngine,
    InterestRecord,
    InterestStore,
    clamp01,
    decay,
    engaged,
    median,
    score_turn,
)


# ── a real database, in a temp file ──────────────────────────────────────────


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """The persona_memory table, created exactly as storage.py creates it."""
    path = str(tmp_path / "ltm.sqlite3")
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS persona_memory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source_session TEXT,
            source_type TEXT DEFAULT 'inferred',
            visibility TEXT DEFAULT 'private',
            user_id TEXT,
            access_count INTEGER DEFAULT 0,
            last_access_at REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, category, key)
        )
        """
    )
    con.commit()
    con.close()
    monkeypatch.setattr(ltm, "_get_db_path", lambda: path)
    return path


@pytest.fixture()
def store(db):
    return InterestStore("kira")


@pytest.fixture()
def engine(store):
    clock = {"t": time.time()}
    eng = CuriosityEngine(store, now=lambda: clock["t"])
    eng.clock = clock
    return eng


# ── scoring: pure arithmetic, checked against §6.12 ──────────────────────────


class TestScoring:
    def test_engaged_needs_both_length_and_warmth(self):
        # Both, not either. A long angry reply is engagement with the argument, and treating
        # it as interest teaches a companion to keep poking a sore spot.
        assert engaged(reply_length=120, median_length=60, valence=0.4) is True
        assert engaged(reply_length=120, median_length=60, valence=-0.4) is False
        assert engaged(reply_length=20, median_length=60, valence=0.9) is False
        assert engaged(reply_length=60, median_length=60, valence=0.9) is False

    def test_the_deltas_are_the_ones_the_spec_names(self):
        assert score_turn(0.5, True) == pytest.approx(0.5 + ENGAGED_DELTA)
        assert score_turn(0.5, False) == pytest.approx(0.5 + DISENGAGED_DELTA)
        assert (ENGAGED_DELTA, DISENGAGED_DELTA) == (0.15, -0.10)

    def test_scoring_clamps_at_both_ends(self):
        assert score_turn(0.98, True) == 1.0
        assert score_turn(0.02, False) == 0.0
        for value in (-5, 5, 0.5):
            assert 0.0 <= clamp01(value) <= 1.0

    def test_decay_is_the_daily_rate(self):
        assert decay(1.0, 1) == pytest.approx(DAILY_DECAY)
        assert decay(1.0, 10) == pytest.approx(DAILY_DECAY**10)
        assert DAILY_DECAY == 0.98

    def test_decay_is_continuous_rather_than_a_daily_step(self):
        # A step function makes a topic touched at 23:59 and again at 00:01 lose a whole
        # day, which is how a companion quietly forgets something mentioned yesterday.
        half = decay(1.0, 0.5)
        assert decay(1.0, 1) < half < 1.0
        assert half == pytest.approx(DAILY_DECAY**0.5)

    def test_decay_of_nothing_is_nothing(self):
        assert decay(0.4, 0) == 0.4
        assert decay(0.4, -3) == 0.4

    def test_median_not_mean_sets_the_bar(self):
        # One 900-word message must not raise the bar for every message after it.
        assert median([10, 20, 30]) == 20
        assert median([10, 20, 30, 900]) == 25
        assert median([]) == 0.0

    def test_the_functions_touch_nothing(self):
        # Pure means pure: no clock, no store, no import that could reach either.
        import inspect

        from app.avatar_director import curiosity

        for fn in (engaged, score_turn, decay, median, clamp01):
            source = inspect.getsource(fn)
            for forbidden in ("time.", "self.", "store", "log."):
                assert forbidden not in source, f"{fn.__name__} names {forbidden}"
        assert curiosity.CATEGORY == "interest"


# ── the store is the existing memory ─────────────────────────────────────────


class TestStore:
    def test_a_record_is_a_row_in_persona_memory(self, store, db):
        store.save(InterestRecord(topic="user.hobby.aquarium", summary="Planning a visit", curiosity=0.72))

        con = sqlite3.connect(db)
        rows = con.execute("SELECT category, key, value FROM persona_memory").fetchall()
        con.close()

        assert len(rows) == 1
        assert rows[0][0] == CATEGORY
        assert rows[0][1] == "user.hobby.aquarium"
        assert json.loads(rows[0][2])["curiosity"] == 0.72

    def test_there_is_no_second_table(self, store, db):
        store.save(InterestRecord(topic="user.hobby.aquarium"))
        con = sqlite3.connect(db)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        # A parallel store is a second place a user's data hides from the delete button
        # they already have. There is exactly one table, and it is not ours.
        assert tables == {"persona_memory", "sqlite_sequence"}

    def test_the_category_is_declared_in_the_existing_module(self):
        assert CATEGORY in ltm.VALID_CATEGORIES

    def test_it_is_not_injected_into_the_system_prompt(self, store):
        # build_ltm_context walks an explicit category list; interests are not on it, so
        # adding the category changed no existing behaviour.
        store.save(InterestRecord(topic="user.hobby.aquarium", summary="Planning a visit"))
        ltm.upsert_memory("kira", "fact", "name", "Ruslan")
        context = ltm.build_ltm_context("kira")
        assert "Ruslan" in context
        assert "aquarium" not in context

    def test_forgetting_the_persona_forgets_its_interests(self, store):
        # The property that makes "inside the existing memory" worth insisting on.
        store.save(InterestRecord(topic="user.hobby.aquarium", summary="Planning a visit"))
        store.save(InterestRecord(topic="user.work.thesis", summary="Chapter three is stuck"))
        assert len(store.all()) == 2

        ltm.forget_all("kira")
        assert store.all() == []

    def test_round_tripping_keeps_every_field(self, store):
        original = InterestRecord(
            topic="user.work.thesis",
            summary="Writing up chapter three",
            curiosity=0.61,
            lastTouched="2026-08-28T18:20:00Z",
            openThread=True,
            sourceMsgIds=["m1", "m2"],
        )
        store.save(original)
        assert store.get("user.work.thesis") == original

    def test_a_row_that_is_not_json_is_skipped_rather_than_fatal(self, store):
        store.save(InterestRecord(topic="good"))
        ltm.upsert_memory("kira", CATEGORY, "broken", "not json at all")
        topics = {r.topic for r in store.all()}
        assert topics == {"good"}

    def test_saving_twice_updates_rather_than_duplicates(self, store, db):
        store.save(InterestRecord(topic="user.work.thesis", summary="Chapter three", curiosity=0.3))
        store.save(InterestRecord(topic="user.work.thesis", summary="Chapter three", curiosity=0.9))
        con = sqlite3.connect(db)
        count = con.execute("SELECT COUNT(*) FROM persona_memory WHERE category = ?", (CATEGORY,)).fetchone()[0]
        con.close()
        assert count == 1
        assert store.get("user.work.thesis").curiosity == 0.9

    def test_distinct_topics_survive_the_stores_own_dedup(self, store):
        """The existing LTM reinforces a near-duplicate value instead of inserting a second
        row — Jaccard over 3+ character tokens, written for prose. An interest record is
        JSON, so its field *names* are shared by every record; what tells two apart is the
        topic and summary inside it, which is why both are in the value and not only in the
        key. Two real topics differ; two with the same summary are, correctly, one thing."""
        store.save(InterestRecord(topic="user.hobby.aquarium", summary="Planning a visit to the new aquarium"))
        store.save(InterestRecord(topic="user.work.thesis", summary="Writing up chapter three"))
        store.save(InterestRecord(topic="user.pet.cat", summary="The cat is off her food again"))
        assert {r.topic for r in store.all()} == {"user.hobby.aquarium", "user.work.thesis", "user.pet.cat"}

    def test_it_prunes_rather_than_spending_the_whole_allowance(self, store):
        # The LTM caps a persona at 200 entries for everything it remembers. Curiosity may
        # not take all of it.
        for i in range(MAX_RECORDS + 15):
            store.save(InterestRecord(topic=f"user.topic.number{i:03d}", summary=f"Subject {i:03d}", curiosity=i / 100.0))
        assert len(store.all()) == MAX_RECORDS + 15

        dropped = store.prune()
        remaining = store.all()
        assert dropped == 15
        assert len(remaining) == MAX_RECORDS
        # The least interesting go first.
        assert min(r.curiosity for r in remaining) > 0.14


# ── the engine ───────────────────────────────────────────────────────────────


class TestEngine:
    def test_a_first_engaged_turn_creates_a_record(self, engine, store):
        record = engine.observe(
            "user.hobby.aquarium",
            reply_length=120,
            median_length=60,
            valence=0.5,
            summary="Planning a visit to the new aquarium",
            open_thread=True,
        )
        assert record.curiosity == pytest.approx(0.5 + ENGAGED_DELTA)
        assert store.get("user.hobby.aquarium").openThread is True

    def test_a_short_flat_reply_costs_interest(self, engine):
        engine.observe("user.work.thesis", reply_length=120, median_length=60, valence=0.5)
        after_up = engine.store.get("user.work.thesis").curiosity
        engine.observe("user.work.thesis", reply_length=5, median_length=60, valence=0.0)
        assert engine.store.get("user.work.thesis").curiosity < after_up

    def test_decay_is_applied_before_the_new_score_not_after(self, engine):
        # A topic untouched for a month must not collect a fresh +0.15 on top of a stale
        # high score; it decays to what it is now, and then the turn moves it.
        engine.observe("user.work.thesis", reply_length=120, median_length=60, valence=0.5)
        engine.clock["t"] += 30 * 86400
        engine.observe("user.work.thesis", reply_length=120, median_length=60, valence=0.5)

        stale_then_scored = decay(0.65, 30) + ENGAGED_DELTA
        assert engine.store.get("user.work.thesis").curiosity == pytest.approx(stale_then_scored, abs=0.02)

    def test_source_ids_are_bounded(self, engine):
        for i in range(40):
            engine.observe("user.work.thesis", reply_length=120, median_length=60, valence=0.5, message_id=f"m{i}")
        assert len(engine.store.get("user.work.thesis").sourceMsgIds) == 10
        assert engine.store.get("user.work.thesis").sourceMsgIds[-1] == "m39"

    def test_the_best_open_thread_is_the_most_curious_one(self, engine, store):
        store.save(InterestRecord(topic="user.hobby.aquarium", summary="The aquarium trip", curiosity=0.4, openThread=True))
        store.save(InterestRecord(topic="user.work.thesis", summary="Chapter three", curiosity=0.8, openThread=True))
        store.save(InterestRecord(topic="user.pet.cat", summary="The cat's appetite", curiosity=0.95, openThread=False))
        assert engine.best_open_thread().topic == "user.work.thesis"

    def test_a_closed_thread_is_never_asked_about(self, engine, store):
        store.save(InterestRecord(topic="user.work.thesis", summary="Chapter three", curiosity=0.99, openThread=False))
        assert engine.best_open_thread() is None

    def test_a_topic_that_decayed_to_nothing_stops_competing(self, engine, store):
        store.save(InterestRecord(topic="user.work.thesis", summary="Chapter three", curiosity=FLOOR / 2, openThread=True))
        assert engine.best_open_thread() is None

    def test_the_choice_is_deterministic_on_a_tie(self, engine, store):
        store.save(InterestRecord(topic="user.pet.zebra", summary="The zebra documentary", curiosity=0.7, openThread=True))
        store.save(InterestRecord(topic="user.food.apple", summary="The apple orchard trip", curiosity=0.7, openThread=True))
        assert engine.best_open_thread().topic == "user.food.apple"
        assert engine.best_open_thread().topic == "user.food.apple"
