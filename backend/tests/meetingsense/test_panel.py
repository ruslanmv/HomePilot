"""The meeting card on the avatar surface (batch MS20, wave W6).

The card already exists twice — `MeetingCard.tsx` and the summary message. This adds a third
*renderer*, not a third source, and the whole batch is what happens when a four-hundred segment
meeting meets a channel that caps a panel at twelve rows and 64 KB.

**A panel is a screen, not a document.** What is sent is a summary projection: what the meeting
is, what was decided, what is still open, what is on screen. The transcript is never rows —
a panel is not where anybody reads a transcript, and the web card, the export and MS13's `ask`
are all better at it.

**The limits are read, never copied.** A test asserts the cap comes from `panels.MAX_ROWS`
rather than from a number retyped here: two numbers for one rule is one number that drifts.

**What survives a trim is fixed.** The header card is built first and dropped last, because
every other row means less without it, and a panel whose first three rows reshuffle as the
meeting grows is one nobody can glance at.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MEETINGSENSE_ENABLED", raising=False)


class Modules:
    def __init__(self):
        import app.avatar_director.panels as panels
        import app.meetingsense.panel as panel
        import app.meetingsense.store as store

        self.panels = panels
        self.panel = panel
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
    return mods


NOTES = {
    "recap": "The team held enterprise pricing at forty a seat and pushed legal to October.",
    "decisions": [{"text": "Hold pricing at forty a seat", "t0": 600_000}],
    "actions": [{"text": "Send the vendor the revised terms", "owner": "Ana"},
                {"text": "Book the legal slot", "done": True}],
    "questions": [{"text": "Who signs off on the discount tier?", "resolved": False},
                  {"text": "Is October realistic?", "resolved": True}],
}


def seg(t0, text, speaker="them"):
    return {"t0_ms": t0, "t1_ms": t0 + 3_000, "text": text, "speaker": speaker}


def meeting(mods, mid="m1", *, title="Q3 planning", segments=(), keyframes=(), notes=None,
            started=1_700_000_000.0, ended=1_700_003_600.0):
    mods.store.create_meeting(conversation_id="c1", meeting_id=mid, title=title,
                              source="teams", started_at=started)
    if segments:
        mods.store.add_segments(mid, segments)
    for frame in keyframes:
        mods.store.add_keyframe(mid, **frame)
    if notes is not None:
        mods.store.save_notes(mid, notes)
    if ended:
        mods.store.end_meeting(mid, ended_at=ended)
    return mid


# ── the acceptance criterion ────────────────────────────────────────────────


class TestABigMeetingFits:
    def four_hundred(self, mods):
        rows = [seg(i * 9_000, f"a routine point number {i} about the quarter and the plan")
                for i in range(400)]
        frames = [{"t_ms": i * 60_000, "url": f"/files/{i}.jpg", "hash": f"h{i}",
                   "caption": f"Slide number {i} about the roadmap"} for i in range(40)]
        return meeting(mods, segments=rows, keyframes=frames, notes=NOTES)

    def test_a_four_hundred_segment_meeting_is_a_legal_panel(self, modules):
        # The batch's acceptance, and the reason the module exists at all.
        mid = self.four_hundred(modules)
        data = modules.panel.project(
            modules.store.get_meeting(mid), modules.store.get_segments(mid),
            modules.store.get_keyframes(mid), modules.store.get_notes(mid),
        )
        assert modules.panels.validate("cards", data) == []

    def test_and_is_not_four_hundred_rows(self, modules):
        mid = self.four_hundred(modules)
        data = modules.panel.project(
            modules.store.get_meeting(mid), modules.store.get_segments(mid),
            modules.store.get_keyframes(mid), modules.store.get_notes(mid),
        )
        assert len(data["cards"]) <= modules.panels.MAX_ROWS["cards"]

    def test_the_whole_message_crosses_the_wire(self, modules):
        mid = self.four_hundred(modules)
        message = modules.panel.display(mid)
        assert message["type"] == "display"
        assert message["kind"] == "cards"
        assert modules.panels.measure(message) <= modules.panels.DEFAULT_MAX_KB * 1024

    def test_the_transcript_is_never_rows(self, modules):
        # A panel is not where a transcript is read. At most the last couple of lines go, so
        # a live panel does not look frozen; everything else is the web card's job.
        mid = self.four_hundred(modules)
        data = modules.panel.project(
            modules.store.get_meeting(mid), modules.store.get_segments(mid),
            modules.store.get_keyframes(mid), modules.store.get_notes(mid),
        )
        spoken = [c for c in data["cards"] if "stamp" in c]
        assert len(spoken) <= modules.panel.PREVIEW_LINES
        assert "point number 5 " not in " ".join(c["body"] for c in data["cards"])


# ── the cap ─────────────────────────────────────────────────────────────────


class TestTheCap:
    def test_it_is_read_from_the_panel_channel_not_retyped(self, modules, monkeypatch):
        # Two numbers for one rule is one number that drifts. If the renderer's cap moves,
        # this moves with it rather than starting to send panels that are refused.
        monkeypatch.setitem(modules.panels.MAX_ROWS, "cards", 4)
        assert modules.panel.max_cards() == 4
        mid = meeting(modules, segments=[seg(i * 1_000, f"line {i}") for i in range(20)],
                      notes=NOTES)
        data = modules.panel.project(modules.store.get_meeting(mid),
                                     modules.store.get_segments(mid), (), 
                                     modules.store.get_notes(mid))
        assert len(data["cards"]) == 4

    def test_the_header_is_the_last_thing_dropped(self, modules):
        # Every other row means less without it, and a panel whose first rows reshuffle as
        # the meeting grows is one nobody can glance at.
        mid = meeting(modules, segments=[seg(i * 1_000, f"line {i}") for i in range(50)],
                      notes=NOTES)
        data = modules.panel.project(modules.store.get_meeting(mid),
                                     modules.store.get_segments(mid), (),
                                     modules.store.get_notes(mid), limit=1)
        assert data["cards"][0]["title"] == "Q3 planning"
        assert "50 segments" in data["cards"][0]["body"]

    def test_the_recap_survives_a_meeting_full_of_decisions(self, modules):
        mid = meeting(
            modules,
            notes={"recap": "The one sentence that stands in for everything not shown.",
                   "decisions": [{"text": f"decision number {i}"} for i in range(40)]},
        )
        data = modules.panel.project(modules.store.get_meeting(mid), (), (),
                                     modules.store.get_notes(mid))
        bodies = [c["body"] for c in data["cards"]]
        assert "The one sentence that stands in for everything not shown." in bodies

    def test_a_long_body_is_cut_at_a_word(self, modules):
        # A panel row that wraps to six lines is a row nobody reads.
        mid = meeting(modules, notes={"recap": "revenue " * 200})
        data = modules.panel.project(modules.store.get_meeting(mid), (), (),
                                     modules.store.get_notes(mid))
        recap = [c for c in data["cards"] if c["title"] == "So far"][0]["body"]
        assert len(recap) <= modules.panel.MAX_BODY + 1
        assert recap.endswith("…")
        assert not recap.rstrip("…").endswith("reven")


# ── what a reader sees ──────────────────────────────────────────────────────


class TestTheProjection:
    def test_the_header_says_what_the_meeting_is(self, modules):
        mid = meeting(modules, segments=[seg(0, "hello")],
                      keyframes=[{"t_ms": 0, "url": "/f.jpg", "caption": "A slide."}])
        data = modules.panel.project(modules.store.get_meeting(mid),
                                     modules.store.get_segments(mid),
                                     modules.store.get_keyframes(mid))
        header = data["cards"][0]
        assert header["title"] == "Q3 planning"
        assert "teams" in header["body"]
        assert "1 segment" in header["body"]
        assert "1 slide" in header["body"]

    def test_a_live_meeting_is_badged_as_recording(self, modules):
        mid = meeting(modules, ended=None)
        live = modules.panel.project(modules.store.get_meeting(mid), live=True, elapsed_ms=90_000)
        ended = modules.panel.project(modules.store.get_meeting(mid))
        assert live["cards"][0]["badge"] == "recording"
        assert ended["cards"][0]["badge"] == "ended"
        assert "01:30" in live["cards"][0]["body"]

    def test_settled_items_are_left_out(self, modules):
        mid = meeting(modules, notes=NOTES)
        data = modules.panel.project(modules.store.get_meeting(mid), (), (),
                                     modules.store.get_notes(mid))
        bodies = " ".join(c["body"] for c in data["cards"])
        assert "Who signs off on the discount tier?" in bodies
        assert "Is October realistic?" not in bodies
        assert "Book the legal slot" not in bodies

    def test_an_action_carries_its_owner(self, modules):
        mid = meeting(modules, notes=NOTES)
        data = modules.panel.project(modules.store.get_meeting(mid), (), (),
                                     modules.store.get_notes(mid))
        assert any("Send the vendor the revised terms — Ana" == c["body"] for c in data["cards"])

    def test_the_slide_shown_is_the_last_captioned_one(self, modules):
        mid = meeting(modules, keyframes=[
            {"t_ms": 0, "url": "/a.jpg", "hash": "a", "caption": "Title slide."},
            {"t_ms": 60_000, "url": "/b.jpg", "hash": "b", "caption": "The chart."},
            {"t_ms": 90_000, "url": "/c.jpg", "hash": "c"},
        ])
        data = modules.panel.project(modules.store.get_meeting(mid), (),
                                     modules.store.get_keyframes(mid))
        on_screen = [c for c in data["cards"] if c["title"] == "On screen"]
        assert [c["body"] for c in on_screen] == ["The chart."]

    def test_a_meeting_with_nothing_in_it_is_still_a_legal_panel(self, modules):
        mid = meeting(modules)
        data = modules.panel.project(modules.store.get_meeting(mid))
        assert modules.panels.validate("cards", data) == []
        assert len(data["cards"]) == 1


# ── the message ─────────────────────────────────────────────────────────────


class TestDisplay:
    def test_a_meeting_that_is_not_there(self, modules):
        assert modules.panel.display("nope") is None

    def test_a_panel_the_channel_refuses_is_none_rather_than_a_crash(self, modules):
        # `panels.build` is what decides whether a panel is legal, and it is called rather
        # than reimplemented — so its refusal has to be survivable here. Squeezed with a real
        # limit rather than a nonsensical one: `build` floors max_kb at 1, so `max_kb=0` is
        # a 1 KB panel and a small meeting sails through it.
        mid = meeting(
            modules,
            notes={"recap": "The team held enterprise pricing. " * 10,
                   "decisions": [{"text": f"a decision worth writing out at length, number {i}"}
                                 for i in range(12)]},
        )
        assert modules.panel.display(mid) is not None
        assert modules.panel.display(mid, max_kb=1) is None

    def test_it_carries_the_meeting_id_so_a_click_can_open_the_card(self, modules):
        mid = meeting(modules)
        assert modules.panel.display(mid)["data"]["meeting_id"] == mid


# ── the avatar session ──────────────────────────────────────────────────────


class TestOverTheAvatarSession:
    def test_a_panel_request_draws_the_card(self, modules, monkeypatch, tmp_path):
        # One data source, two renderers: the same store rows the web card reads become a
        # `display` message the avatar client's existing panel renderer draws.
        import asyncio

        import app.meetingsense.avatar_bridge as bridge_mod
        import app.meetingsense.config as config_mod
        import app.meetingsense.session as session_mod

        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        monkeypatch.setenv("MEETINGSENSE_REMOTE", "true")
        session_mod._SESSIONS.clear()

        async def scenario():
            outbox = []
            bridge = bridge_mod.MeetingBridge(outbox, config=config_mod.load_config(),
                                              now=lambda: 1_700_000_000.0)
            await bridge.handle({"type": "meeting_start", "conversation_id": "c1",
                                 "title": "Q3 planning", "audio": {"channels": 1}})
            await bridge.handle({"type": "meeting_panel"})
            return outbox

        outbox = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())
        panels = [m for m in outbox if m.get("type") == "display"]
        assert len(panels) == 1
        assert panels[0]["kind"] == "cards"
        # A live meeting, badged as one.
        assert panels[0]["data"]["cards"][0]["badge"] == "recording"

    def test_a_panel_is_not_wrapped_as_a_meeting_frame(self, modules, monkeypatch):
        # `display` is the director's own message type and the client's renderer already
        # knows it. Wrapping it would need a second renderer for a card that has one.
        import asyncio

        import app.meetingsense.avatar_bridge as bridge_mod
        import app.meetingsense.config as config_mod
        import app.meetingsense.session as session_mod

        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        monkeypatch.setenv("MEETINGSENSE_REMOTE", "true")
        session_mod._SESSIONS.clear()

        async def scenario():
            outbox = []
            bridge = bridge_mod.MeetingBridge(outbox, config=config_mod.load_config(),
                                              now=lambda: 1.0)
            await bridge.handle({"type": "meeting_start", "conversation_id": "c1",
                                 "audio": {"channels": 1}})
            await bridge.handle({"type": "meeting_panel"})
            return outbox

        outbox = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())
        panel = [m for m in outbox if m.get("type") == "display"][0]
        assert "meeting" not in panel

    def test_an_undrawable_panel_is_dropped_rather_than_escalated(self, modules, monkeypatch):
        # The meeting is recording either way, and a card that could not be drawn is not a
        # reason to send an error frame into a live session — the client would show a failure
        # for something the user never asked for.
        import asyncio

        import app.meetingsense.avatar_bridge as bridge_mod
        import app.meetingsense.config as config_mod
        import app.meetingsense.panel as panel_mod
        import app.meetingsense.session as session_mod

        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        monkeypatch.setenv("MEETINGSENSE_REMOTE", "true")
        monkeypatch.setattr(panel_mod, "display", lambda *a, **kw: None)
        session_mod._SESSIONS.clear()

        async def scenario():
            outbox = []
            bridge = bridge_mod.MeetingBridge(outbox, config=config_mod.load_config(),
                                              now=lambda: 1.0)
            await bridge.handle({"type": "meeting_start", "conversation_id": "c1",
                                 "audio": {"channels": 1}})
            await bridge.handle({"type": "meeting_panel"})
            return outbox

        outbox = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())
        kinds = [m.get("type") for m in outbox]
        assert "display" not in kinds
        assert [m for m in outbox if m.get("meeting", {}).get("type") == "error"] == []

    def test_asking_for_a_panel_before_a_meeting_is_an_error_not_a_crash(self, modules, monkeypatch):
        import asyncio

        import app.meetingsense.avatar_bridge as bridge_mod
        import app.meetingsense.config as config_mod
        import app.meetingsense.session as session_mod

        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        monkeypatch.setenv("MEETINGSENSE_REMOTE", "true")
        session_mod._SESSIONS.clear()

        async def scenario():
            outbox = []
            bridge = bridge_mod.MeetingBridge(outbox, config=config_mod.load_config())
            await bridge.handle({"type": "meeting_panel"})
            return outbox

        outbox = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())
        assert outbox[0]["meeting"]["code"] == "not_live"
