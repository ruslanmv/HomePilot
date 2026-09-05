"""What a persona knows about the screen being shared (batch MS29, wave W11).

The bug: the user pressed 👁 Share screen, the vision model captioned the frame correctly, and
the chat answered *"No, I can't see your screen."* Nothing was broken — the caption went to
ScreenSense's own panel and the chat model was never told, so from where it sat that answer was
true. It was also a flat **capability claim**, which is the kind of wrong that stops the user
trying again.

Two properties carry these tests. **Presence is not content**: knowing a screen is shared leaks
nothing about what is on it, and on its own fixes the bug. And **content expires**: a caption
from four minutes ago describes a screen that is gone, and repeating it confidently is worse
than saying nothing.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def screen(monkeypatch):
    import app.meetingsense.screen_context as module

    module._reset_for_tests()
    monkeypatch.setenv("MEETINGSENSE_SCREEN", "true")
    return module


T0 = 1_760_000_000.0


class TestPresence:
    def test_sharing_is_announced(self, screen):
        assert screen.begin("c1", mode="browser", now=T0) is True
        block = screen.build("c1", now=T0 + 5)
        assert screen.BLOCK_HEADER in block
        assert "sharing their screen" in block

    def test_it_never_lets_a_persona_deny_it(self, screen):
        # The sentence the whole batch exists for.
        screen.begin("c1", now=T0)
        assert "Never tell them you cannot see their screen" in screen.build("c1", now=T0)

    def test_nobody_sharing_is_nothing_at_all(self, screen):
        # Byte-identical: the prompt is what it was before this file existed.
        assert screen.build("c1", now=T0) == ""
        assert screen.for_conversation("c1") == ""
        assert screen.for_conversation("") == ""

    def test_the_desktop_and_a_picked_window_read_differently(self, screen):
        # "Your desktop" and "a window you picked" are different amounts of exposure, and the
        # persona should not describe one as the other.
        screen.begin("c1", mode="desktop", now=T0)
        assert "their desktop" in screen.build("c1", now=T0)
        screen.end("c1")
        screen.begin("c1", mode="browser", now=T0)
        assert "window or tab they picked" in screen.build("c1", now=T0)

    def test_it_says_how_long(self, screen):
        screen.begin("c1", now=T0)
        assert "just now" in screen.build("c1", now=T0 + 10)
        assert "5 minutes ago" in screen.build("c1", now=T0 + 300)

    def test_a_renewal_keeps_the_original_start(self, screen):
        # The pings that keep a share alive must not make it look like it just began.
        screen.begin("c1", now=T0)
        screen.begin("c1", now=T0 + 240)
        assert "4 minutes ago" in screen.build("c1", now=T0 + 240)

    def test_stopping_removes_everything(self, screen):
        # A hard delete, like MS27's prep material: "stop sharing" that leaves the last thing
        # seen in a prompt has not stopped anything.
        screen.begin("c1", now=T0)
        screen.observe("c1", "a spreadsheet of salaries", now=T0)
        assert screen.end("c1") is True
        assert screen.build("c1", now=T0) == ""
        assert screen.active("c1", now=T0) is None

    def test_stopping_what_was_never_started(self, screen):
        assert screen.end("c1") is False

    def test_a_share_that_was_never_stopped_expires(self, screen):
        # A tab that closed mid-share sends no "stopped". Believing it forever is how a persona
        # insists it can see a screen that was put away an hour ago.
        screen.begin("c1", now=T0)
        assert screen.build("c1", now=T0 + screen.PRESENCE_TTL_S - 1) != ""
        assert screen.build("c1", now=T0 + screen.PRESENCE_TTL_S + 1) == ""

    def test_shares_are_per_conversation(self, screen):
        screen.begin("c1", now=T0)
        assert screen.build("c2", now=T0) == ""

    def test_an_unnamed_conversation_shares_nothing(self, screen):
        assert screen.begin("", now=T0) is False
        assert screen.begin("   ", now=T0) is False


class TestTheLastLook:
    def test_a_recent_caption_is_carried(self, screen):
        screen.begin("c1", now=T0)
        screen.observe("c1", "a Python traceback about a missing module", now=T0)
        assert "missing module" in screen.build("c1", now=T0 + 10)

    def test_a_stale_caption_is_held_back(self, screen):
        # The important one. A caption describes a screen that may be long gone, and describing
        # it confidently is worse than saying nothing — so the presence line stands alone and
        # the persona is told to look again.
        screen.begin("c1", now=T0)
        screen.observe("c1", "a Python traceback", now=T0)
        stale = screen.build("c1", now=T0 + screen.CAPTION_TTL_S + 1)
        assert "traceback" not in stale
        assert "ask for a fresh look" in stale
        # …and the persona still knows a screen is being shared.
        assert "sharing their screen" in stale

    def test_a_caption_is_capped(self, screen):
        # A vision model asked an open question will write a paragraph. The prompt is not the
        # place to discover that.
        screen.begin("c1", now=T0)
        screen.observe("c1", "x" * 5_000, now=T0)
        assert len(screen.active("c1", now=T0)["caption"]) == screen.MAX_CAPTION_CHARS

    def test_the_newest_look_wins(self, screen):
        screen.begin("c1", now=T0)
        screen.observe("c1", "the first screen", now=T0)
        screen.observe("c1", "the second screen", now=T0 + 5)
        block = screen.build("c1", now=T0 + 6)
        assert "second" in block and "first" not in block

    def test_a_caption_with_no_share_is_dropped(self, screen):
        # A late answer about a screen that is already put away.
        assert screen.observe("c1", "something", now=T0) is False
        assert screen.build("c1", now=T0) == ""

    def test_an_empty_caption_is_not_a_look(self, screen):
        screen.begin("c1", now=T0)
        assert screen.observe("c1", "   ", now=T0) is False

    def test_looking_keeps_the_share_alive(self, screen):
        # Captions are pings too: somebody actively asking about their screen is somebody
        # actively sharing it.
        screen.begin("c1", now=T0)
        screen.observe("c1", "still here", now=T0 + screen.PRESENCE_TTL_S - 1)
        assert screen.build("c1", now=T0 + screen.PRESENCE_TTL_S + 1) != ""


class TestTheOperatorSwitch:
    def test_it_is_on_by_default(self, monkeypatch):
        # The one flag in this feature that defaults on, because the block exists only while
        # the user is actively sharing — a deliberate act with an OS indicator on it.
        import app.meetingsense.screen_context as module

        monkeypatch.delenv("MEETINGSENSE_SCREEN", raising=False)
        assert module.enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "FALSE", "Off"])
    def test_an_operator_can_turn_it_off(self, monkeypatch, value):
        import app.meetingsense.screen_context as module

        module._reset_for_tests()
        monkeypatch.setenv("MEETINGSENSE_SCREEN", value)
        # Real time, not the frozen T0: `for_conversation` reads the clock, so a share stamped
        # in the past expires on its own and the test would pass without the switch working.
        module.begin("c1")
        assert module.enabled() is False
        assert module.for_conversation("c1") == ""
        # …and the same share is visible the moment the switch is back on, which is what says
        # the empty answer above came from the switch and not from an expired share.
        monkeypatch.setenv("MEETINGSENSE_SCREEN", "true")
        assert module.BLOCK_HEADER in module.for_conversation("c1")

    def test_a_raising_provider_is_silence_not_a_crash(self, screen, monkeypatch):
        # A chat that failed because somebody was sharing their screen would be a far worse bug
        # than no screen context at all. MS18's rule on this seam, kept.
        monkeypatch.setattr(screen, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert screen.for_conversation("c1") == ""


class TestThePromptSeam:
    def test_the_block_reaches_the_system_prompt(self, screen):
        from app.personalities.prompt_builder import _live_screen_context

        # Real time, not the frozen T0 the rest of this file uses: `for_conversation` reads the
        # clock, so a share stamped eleven months ago is correctly expired before it is asked
        # about. That is the presence TTL working, and it is easy to mistake for a broken seam.
        screen.begin("c1")
        assert screen.BLOCK_HEADER in _live_screen_context("c1")

    def test_the_block_lands_in_the_assembled_system_prompt(self, screen):
        # Not just that the provider returns a block — that the prompt actually carries it. A
        # provider wired to nothing would pass every other test in this class.
        from app.personalities.prompt_builder import build_system_prompt
        from app.personalities.types import PersonalityAgent

        screen.begin("c1")
        agent = PersonalityAgent(id="p1", label="P", system_prompt="You are P.")
        prompt = build_system_prompt(agent, conversation_id="c1")
        assert screen.BLOCK_HEADER in prompt
        # And gone again when nobody is sharing, byte-for-byte.
        screen.end("c1")
        assert build_system_prompt(agent, conversation_id="c1") == \
            build_system_prompt(agent, conversation_id=None)

    def test_and_is_absent_when_nobody_is_sharing(self, screen):
        from app.personalities.prompt_builder import _live_screen_context

        assert _live_screen_context("c1") == ""
        assert _live_screen_context(None) == ""

    def test_the_hook_never_raises(self, monkeypatch):
        # Guarded like MS18's, so this module keeps working on an install where MeetingSense
        # is absent entirely.
        import app.personalities.prompt_builder as builder
        import app.meetingsense.screen_context as module

        monkeypatch.setattr(module, "for_conversation",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gone")))
        assert builder._live_screen_context("c1") == ""


class TestTheWire:
    @pytest.fixture()
    def client(self, screen):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import app.meetingsense.routes as routes

        app = FastAPI()
        app.include_router(routes.router)
        return TestClient(app)

    def test_start_stop_and_seen(self, client, screen):
        assert client.post("/v1/meetingsense/screen/c1",
                           json={"action": "start", "mode": "browser"}).json()["sharing"] is True
        assert client.post("/v1/meetingsense/screen/c1",
                           json={"action": "seen", "caption": "a traceback"}).json()["ok"] is True
        assert "traceback" in screen.build("c1")
        assert client.post("/v1/meetingsense/screen/c1",
                           json={"action": "stop"}).json()["sharing"] is False

    def test_an_unknown_action_is_refused(self, client):
        assert client.post("/v1/meetingsense/screen/c1", json={"action": "peek"}).status_code == 400
        assert client.post("/v1/meetingsense/screen/c1", json={}).status_code == 400

    def test_it_works_with_the_recorder_switched_off(self, client, screen, monkeypatch):
        # ScreenSense stands alone: it works on an install that never enables the meeting
        # recorder, and this seam has to work there too.
        monkeypatch.delenv("MEETINGSENSE_ENABLED", raising=False)
        assert client.post("/v1/meetingsense/screen/c1",
                           json={"action": "start"}).json()["sharing"] is True
