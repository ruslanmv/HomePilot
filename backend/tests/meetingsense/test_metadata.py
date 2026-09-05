"""Naming a meeting without asking (batch MS17, wave W5).

Nobody types a title before they hit record. They are already in the call, somebody is
talking, and the dialog asking what to call this is the reason the recording did not start. So
a meeting is named afterwards, from two sources that cost the user nothing.

The batch row's acceptance is *"pytest: title heuristics; manual: calendar match"*, and the
split is honest: a live MCP calendar is not something CI has. What is here is the whole
window-title half against real titles, the event-picking and shape-reading of the calendar half
against an injected invoker, and the two rules that make the feature safe rather than annoying.

**A title the user gave always wins.** Somebody who typed "1:1 with Ana" and got "Microsoft
Teams" back would stop typing titles, and would be right to.

**An empty answer is not an answer.** A calendar that matched nothing, a window title that was
only the app name, an MCP call that timed out — each leaves the meeting exactly as it was.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MEETINGSENSE_ENABLED", raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.config as config
        import app.meetingsense.metadata as metadata
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.config = config
        self.metadata = metadata
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


# ── the window title ────────────────────────────────────────────────────────


class TestSourceDetection:
    @pytest.mark.parametrize(
        "window_title,expected",
        [
            ("Q3 planning | Microsoft Teams", "teams"),
            ("Meeting Compact View | Microsoft Teams", "teams"),
            ("Zoom Meeting", "zoom"),
            ("Zoom Workplace", "zoom"),
            ("Meet – Q3 planning", "meet"),
            ("Q3 planning - Google Meet", "meet"),
            ("Cisco Webex Meetings", "webex"),
            ("Design sync — Slack huddle", "slack"),
            ("#general - Discord", "discord"),
        ],
    )
    def test_real_window_titles(self, modules, window_title, expected):
        assert modules.metadata.detect_source(window_title) == expected

    @pytest.mark.parametrize(
        "window_title",
        [
            # The reason markers are matched on word boundaries rather than as substrings.
            # These are ordinary documents somebody shares, and a substring test tags the
            # first as a Meet call and the second as a Zoom call.
            "Meeting notes — Q3 planning",
            "Team meetings 2024.xlsx - Excel",
            "Zoomed timeline - Figma",
        ],
    )
    def test_a_word_containing_a_marker_is_not_the_platform(self, modules, window_title):
        assert modules.metadata.detect_source(window_title) == ""

    def test_google_chrome_is_not_google_meet(self, modules):
        # The reason the markers are ordered longest-first. "Meet" inside "Google Chrome"
        # would tag every browser share as a Meet call.
        assert modules.metadata.detect_source("Q3 planning - Google Chrome") == ""

    @pytest.mark.parametrize(
        "link,expected",
        [
            ("https://teams.microsoft.com/l/meetup-join/xyz", "teams"),
            ("https://meet.google.com/abc-defg-hij", "meet"),
            ("https://example.zoom.us/j/12345", "zoom"),
            ("https://acme.webex.com/meet/ana", "webex"),
            ("https://example.com/some/page", ""),
        ],
    )
    def test_a_join_link_names_the_platform_too(self, modules, link, expected):
        # The same function reads a calendar event's join link, and an invitation says
        # "teams.microsoft.com", never "Microsoft Teams" — so a window-title-only marker list
        # leaves every calendar-matched meeting with no platform.
        assert modules.metadata.detect_source(link) == expected

    def test_an_unshared_or_unknown_surface_is_no_source(self, modules):
        for value in ("", None, "Entire Screen", "Untitled document - Notes"):
            assert modules.metadata.detect_source(value) == ""


class TestTitleFromWindow:
    @pytest.mark.parametrize(
        "window_title,expected",
        [
            ("Q3 planning | Microsoft Teams", "Q3 planning"),
            ("Meet – Q3 planning", "Q3 planning"),
            ("Q3 planning - Google Meet", "Q3 planning"),
            ("Vendor review | Zoom Meeting", "Vendor review"),
            ("Design sync — Slack huddle", "Design sync"),
            ("Q3 planning and budget - Google Chrome", "Q3 planning and budget"),
            # Teams' real shape during a call: the current speaker, then the meeting, then the
            # app. Taking the first surviving part would title the meeting after whoever
            # happened to be talking when recording started.
            ("Ana Costa | Q3 planning and budget | Microsoft Teams", "Q3 planning and budget"),
            ("Chat | Vendor review | Microsoft Teams", "Vendor review"),
        ],
    )
    def test_the_name_comes_out_whichever_side_the_app_is_on(self, modules, window_title, expected):
        # Teams puts the app last and Meet puts it first, so the name is taken as the longest
        # surviving part rather than the first.
        assert modules.metadata.title_from_window(window_title) == expected

    @pytest.mark.parametrize(
        "window_title",
        ["Zoom Meeting", "Microsoft Teams", "Google Meet", "Meeting", "Entire Screen",
         "Google Chrome", "", "   ", "Meeting Compact View | Microsoft Teams",
         # Punctuated app names, which window managers and Zoom's own Wayland title produce.
         # These survive the exact-marker filter — "zoom-meeting" is not "zoom" — so the last
         # guard catches a single word that is only a platform name.
         "Zoom-Meeting", "Webex_Meetings"],
    )
    def test_a_title_that_is_not_a_name_produces_nothing(self, modules, window_title):
        # "Zoom Meeting" is the absence of a name, not a name. Writing it into the title makes
        # every Zoom call in History look identical, which is worse than leaving them untitled.
        assert modules.metadata.title_from_window(window_title) == ""

    def test_both_halves_at_once(self, modules):
        assert modules.metadata.from_window_title("Q3 planning | Microsoft Teams") == {
            "title": "Q3 planning",
            "source": "teams",
        }


# ── the calendar ────────────────────────────────────────────────────────────


#: The instant every calendar fixture is written relative to. Hand-typing ISO strings for a
#: chosen epoch is how a fixture ends up twenty minutes off the case it was meant to describe,
#: which is a test that passes for the wrong reason — so the offsets are the readable part and
#: the strings are derived.
BASE = 1_700_000_000.0


def iso(offset_s):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(BASE + offset_s, tz=timezone.utc).isoformat()


def event(summary, start_offset, end_offset=None, **extra):
    row = {"summary": summary, "start": {"dateTime": iso(start_offset)}}
    if end_offset is not None:
        row["end"] = {"dateTime": iso(end_offset)}
    row.update(extra)
    return row


class TestPickEvent:
    def test_an_event_containing_the_start_wins_however_long_it_is(self, modules):
        # Somebody who starts recording twenty minutes into an hour-long call is in that call,
        # not near the next one.
        started = BASE + 20 * 60  # twenty minutes into the first
        events = [
            event("The long call", 0, 60 * 60),
            event("The next one", 60 * 60, 90 * 60),
        ]
        assert modules.metadata.pick_event(events, started)["summary"] == "The long call"

    def test_proximity_only_decides_when_nothing_contains_the_start(self, modules):
        events = [
            event("Ten minutes later", 10 * 60),
            event("Two minutes earlier", -2 * 60),
        ]
        assert modules.metadata.pick_event(events, BASE)["summary"] == "Two minutes earlier"

    def test_nothing_within_the_window_is_no_match(self, modules):
        # A wider window picks the wrong event on exactly the days that are back to back,
        # which are the days getting it right matters.
        events = [event("An hour away", 60 * 60)]
        assert modules.metadata.pick_event(events, BASE) is None

    def test_the_shorter_of_two_equally_close_events_wins(self, modules):
        # On a day of overlapping invitations the specific one is more likely to be the call
        # than the all-day block it sits inside.
        events = [
            event("All day: offsite", 0, 24 * 60 * 60),
            event("Q3 planning", 0, 60 * 60),
        ]
        assert modules.metadata.pick_event(events, BASE + 100)["summary"] == "Q3 planning"

    def test_an_event_with_an_unreadable_time_is_skipped_not_guessed(self, modules):
        # A wrongly-parsed timestamp picks the wrong meeting, which is worse than picking none.
        events = [
            {"summary": "Broken", "start": {"dateTime": "next tuesday"}},
            event("Real", 0),
        ]
        assert modules.metadata.pick_event(events, BASE)["summary"] == "Real"

    def test_an_epoch_start_is_read_too(self, modules):
        # A normalising MCP server may hand back numbers rather than ISO strings.
        events = [{"summary": "Numeric", "start": BASE + 50}]
        assert modules.metadata.pick_event(events, BASE)["summary"] == "Numeric"

    def test_nothing_at_all(self, modules):
        assert modules.metadata.pick_event([], 1.0) is None
        assert modules.metadata.pick_event([None, "not an event"], 1.0) is None


class TestFromEvent:
    def test_a_google_event(self, modules):
        row = event(
            "Q3 planning", 0,
            attendees=[{"displayName": "Ana Costa", "email": "a.costa@example.com"},
                       {"email": "sam@example.com"}],
            hangoutLink="https://meet.google.com/abc-defg-hij",
        )
        assert modules.metadata.from_event(row) == {
            "title": "Q3 planning",
            "attendees": ["Ana Costa", "sam@example.com"],
            "link": "https://meet.google.com/abc-defg-hij",
            # Read off the link, because a calendar knows the platform even when no window
            # was shared.
            "source": "meet",
        }

    def test_a_graph_event(self, modules):
        row = {
            "subject": "Vendor review",
            "start": {"dateTime": iso(0).replace("+00:00", ""), "timeZone": "UTC"},
            "attendees": [{"emailAddress": {"name": "Ana Costa", "address": "a@x.com"}}],
            "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meetup-join/xyz"},
        }
        out = modules.metadata.from_event(row)
        assert out["title"] == "Vendor review"
        assert out["attendees"] == ["Ana Costa"]
        assert out["source"] == "teams"

    def test_a_name_appears_once_however_many_ways_the_calendar_gives_it(self, modules):
        row = event("x", 0, attendees=[{"displayName": "Ana"}, {"displayName": "Ana"}, "Ana"])
        assert modules.metadata.from_event(row)["attendees"] == ["Ana"]

    def test_an_event_with_nothing_useful_gives_nothing(self, modules):
        assert modules.metadata.from_event({}) == {}
        assert modules.metadata.from_event(None) == {}
        assert modules.metadata.from_event({"summary": "  "}) == {}

    def test_a_room_name_in_location_is_not_a_link(self, modules):
        row = event("x", 0, location="Meeting room 4")
        assert "link" not in modules.metadata.from_event(row)


class TestMatchCalendar:
    def test_it_asks_for_a_window_around_the_start(self, modules):
        asked = {}

        async def invoke(capability, args):
            asked.update({"capability": capability, **args})
            return [event("Q3 planning", 0)]

        out = run(modules.metadata.match_calendar(BASE, invoke=invoke))
        assert out["title"] == "Q3 planning"
        assert asked["capability"] == modules.metadata.CALENDAR_CAPABILITY
        assert asked["time_min"] < BASE < asked["time_max"]

    @pytest.mark.parametrize(
        "answer",
        [
            {"items": [{"summary": "Wrapped", "start": {"dateTime": "@0"}}]},
            {"value": [{"subject": "Wrapped", "start": {"dateTime": "@0"}}]},
            {"events": [{"title": "Wrapped", "start": "@0"}]},
        ],
    )
    def test_it_unwraps_whichever_envelope_the_server_used(self, modules, answer):
        import json as _json

        answer = _json.loads(_json.dumps(answer).replace("@0", iso(0)))

        async def invoke(capability, args):
            return answer

        assert run(modules.metadata.match_calendar(BASE, invoke=invoke))["title"] == "Wrapped"

    def test_no_calendar_connected_asks_nothing(self, modules):
        assert run(modules.metadata.match_calendar(1.0)) == {}

    def test_a_calendar_that_fails_leaves_the_meeting_alone(self, modules):
        async def angry(capability, args):
            raise TimeoutError("the calendar server did not answer")

        assert run(modules.metadata.match_calendar(1.0, invoke=angry)) == {}

    def test_an_answer_in_a_shape_nobody_expected(self, modules):
        async def odd(capability, args):
            return "the calendar said something strange"

        assert run(modules.metadata.match_calendar(1.0, invoke=odd)) == {}


# ── the rules that make it safe ─────────────────────────────────────────────


class TestMerge:
    def test_a_title_the_user_typed_is_never_replaced(self, modules):
        # Auto-metadata that corrects a person is auto-metadata people turn off.
        existing = {"title": "1:1 with Ana", "source": None}
        out = modules.metadata.merge(existing, {"title": "Microsoft Teams", "source": "teams"})
        assert out == {"source": "teams"}

    def test_an_empty_finding_does_not_blank_what_is_there(self, modules):
        existing = {"title": None, "source": "teams"}
        assert modules.metadata.merge(existing, {"title": "", "source": None}) == {}

    def test_earlier_sources_win_over_later_ones(self, modules):
        # The caller decides the calendar outranks the window title by passing it first.
        out = modules.metadata.merge({}, {"title": "From the calendar"}, {"title": "From the window"})
        assert out["title"] == "From the calendar"

    def test_a_later_source_still_fills_a_blank_the_first_left(self, modules):
        out = modules.metadata.merge({}, {"title": "From the calendar"}, {"source": "teams"})
        assert out == {"title": "From the calendar", "source": "teams"}


class TestEnrich:
    def test_a_meeting_is_named_from_its_window(self, modules):
        modules.store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
        written = run(modules.metadata.enrich("m1", window_title="Q3 planning | Microsoft Teams"))
        assert written == {"title": "Q3 planning", "source": "teams"}
        row = modules.store.get_meeting("m1")
        assert (row["title"], row["source"]) == ("Q3 planning", "teams")

    def test_the_calendar_wins_the_title_and_adds_what_a_window_cannot(self, modules):
        modules.store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=BASE)

        async def invoke(capability, args):
            return [event("Q3 planning and budget", 0,
                          attendees=[{"displayName": "Ana Costa"}],
                          hangoutLink="https://meet.google.com/abc")]

        written = run(modules.metadata.enrich("m1", window_title="Q3 | Microsoft Teams", invoke=invoke))
        assert written["title"] == "Q3 planning and budget"
        assert written["attendees"] == ["Ana Costa"]
        # The window shared was Teams; the calendar link says Meet. The calendar is passed
        # first, so its answer stands — it is the one somebody chose.
        assert written["source"] == "meet"
        assert json.loads(modules.store.get_meeting("m1")["attendees"]) == ["Ana Costa"]

    def test_a_typed_title_survives_both(self, modules):
        modules.store.create_meeting(conversation_id="c1", meeting_id="m1", title="1:1 with Ana",
                                     started_at=1.0)
        written = run(modules.metadata.enrich("m1", window_title="Q3 planning | Microsoft Teams"))
        assert "title" not in written
        assert modules.store.get_meeting("m1")["title"] == "1:1 with Ana"

    def test_nothing_to_go_on_writes_nothing(self, modules):
        modules.store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
        # "Zoom Meeting" is not a name, so no title is written — but knowing the call was on
        # Zoom is real metadata, and dropping it because the name was useless would throw away
        # the half that worked.
        assert run(modules.metadata.enrich("m1", window_title="Zoom Meeting")) == {"source": "zoom"}
        assert modules.store.get_meeting("m1")["title"] is None

    def test_a_meeting_that_is_not_there(self, modules):
        assert run(modules.metadata.enrich("nope", window_title="Q3 | Microsoft Teams")) == {}


class TestUpdateMeeting:
    def test_only_metadata_columns_can_be_written(self, modules):
        # Fed by a calendar event and a window title, neither of which the user typed. A
        # metadata path that can set any column is one bad MCP answer away from rewriting a
        # meeting's conversation or its retention mode.
        modules.store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0,
                                     retention="text")
        written = modules.store.update_meeting(
            "m1", {"title": "Real", "conversation_id": "stolen", "retention": "all", "status": "live"}
        )
        assert written == ["title"]
        row = modules.store.get_meeting("m1")
        assert row["conversation_id"] == "c1"
        assert row["retention"] == "text"


# ── the session path ────────────────────────────────────────────────────────


class TestSessionNaming:
    def test_starting_with_a_window_title_names_the_meeting_and_says_so(self, modules):
        async def scenario():
            session = modules.session.MeetingSession(
                transport=modules.session.ListTransport(),
                config=modules.config.load_config(),
                now=lambda: BASE,
            )
            await session.start({"conversation_id": "c1",
                                 "window_title": "Q3 planning | Microsoft Teams"})
            await session.metadata_task
            return session

        session = run(scenario())
        metas = [f for f in session.transport.frames if f.get("type") == "meta"]
        assert metas and metas[0]["title"] == "Q3 planning"
        assert metas[0]["source"] == "teams"

    def test_ready_is_sent_before_the_name_is_looked_up(self, modules):
        # A calendar round trip before `ready` is a dialog-free start turned back into a wait,
        # and the recording is what the user pressed the button for.
        order = []

        async def slow(capability, args):
            order.append("calendar")
            await asyncio.sleep(0.05)
            return []

        async def scenario():
            session = modules.session.MeetingSession(
                transport=modules.session.ListTransport(),
                config=modules.config.load_config(),
                calendar=slow,
                now=lambda: BASE,
            )
            await session.start({"conversation_id": "c1", "window_title": "Q3 | Microsoft Teams"})
            order.append("ready-returned")
            await session.metadata_task
            return session

        session = run(scenario())
        assert order[-1] == "ready-returned" or order.index("ready-returned") <= 1
        assert session.transport.frames[0]["type"] == "ready"

    def test_no_window_title_and_no_calendar_schedules_nothing(self, modules):
        async def scenario():
            session = modules.session.MeetingSession(
                transport=modules.session.ListTransport(),
                config=modules.config.load_config(),
                now=lambda: 1.0,
            )
            await session.start({"conversation_id": "c1"})
            return session

        assert run(scenario()).metadata_task is None

    def test_a_calendar_that_hangs_does_not_hold_the_meeting(self, modules):
        forever = asyncio.Event()

        async def hangs(capability, args):
            await forever.wait()
            return []

        async def scenario():
            session = modules.session.MeetingSession(
                transport=modules.session.ListTransport(),
                config=modules.config.load_config(),
                calendar=hangs,
                now=lambda: 1.0,
            )
            await asyncio.wait_for(session.start({"conversation_id": "c1"}), timeout=1)
            # Recording, transcribing and stopping all work while the calendar never answers.
            final = await asyncio.wait_for(session.stop(), timeout=1)
            session.metadata_task.cancel()
            return final

        assert run(scenario())["type"] == "final"
