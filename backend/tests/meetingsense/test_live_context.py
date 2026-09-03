"""What a persona knows about the meeting happening right now (batch MS18, wave W6).

Together mode is one block of text prepended to a system prompt, and everything hard about it
is what that block may **not** contain.

**The transcript is not it.** HomePilot's chat path passes `get_recent(cid, limit=6)` and drops
everything older — a limit this batch does not touch. A three-hour meeting is perhaps 30,000
words, and a block that grows with the meeting turns every question in the second hour into a
truncated prompt, which produces an answer confidently wrong about the part that got cut. So:
D9 tiers 1 and 2 only, and a hard 900 tokens.

**The trim order is D9's priority, again.** Verbatim first, then the notes list, and the recap
never. A model with the recap and no verbatim can still say what the meeting has been about; one
with the verbatim and no recap knows the last thirty seconds of a three-hour call and nothing.

**Off is byte-identical.** With no live meeting, or the flag down, or MeetingSense absent, the
prompt is character-for-character what it was before this batch — asserted rather than assumed,
because a context provider that quietly changes every prompt changes every persona in the
product.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_TOGETHER"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.config as config
        import app.meetingsense.live_context as live_context
        import app.meetingsense.session as session
        import app.meetingsense.store as store
        import app.personalities.prompt_builder as prompt_builder

        self.config = config
        self.live_context = live_context
        self.session = session
        self.store = store
        self.prompt_builder = prompt_builder


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


@pytest.fixture()
def together(monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    monkeypatch.setenv("MEETINGSENSE_TOGETHER", "true")


RECAP = ("The team reviewed enterprise pricing and agreed to hold at forty a seat, then moved "
         "to the vendor contract, which needs legal sign-off before October.")

NOTES = {
    "recap": RECAP,
    "decisions": [{"text": "Hold pricing at forty a seat", "t0": 600_000}],
    "actions": [{"text": "Send the vendor the revised terms", "owner": "Ana", "t0": 900_000},
                {"text": "Book the legal slot", "done": True}],
    "questions": [{"text": "Who signs off on the discount tier?", "resolved": False},
                  {"text": "Is October realistic?", "resolved": True}],
}


def seg(t0, text, speaker="them"):
    return {"t0_ms": t0, "t1_ms": t0 + 3_000, "text": text, "speaker": speaker}


def meeting(mods, mid="m1", *, conversation="conv-1", title="Q3 planning",
            segments=(), keyframes=(), notes=None):
    mods.store.create_meeting(conversation_id=conversation, meeting_id=mid, title=title,
                              started_at=1_700_000_000.0)
    if segments:
        mods.store.add_segments(mid, segments)
    for frame in keyframes:
        mods.store.add_keyframe(mid, **frame)
    if notes is not None:
        mods.store.save_notes(mid, notes)
    return mid


class FakeSession:
    """A live session, without a socket. `for_conversation` reads exactly these three."""

    def __init__(self, meeting_id, conversation_id, elapsed_ms, state):
        self.meeting_id = meeting_id
        self.conversation_id = conversation_id
        self.elapsed_ms = elapsed_ms
        self.state = state


def go_live(mods, meeting_id, conversation_id="conv-1", elapsed_ms=3_600_000):
    session = FakeSession(meeting_id, conversation_id, elapsed_ms, mods.session.MeetingState.LIVE)
    mods.session._SESSIONS[meeting_id] = session
    return session


# ── off is byte-identical ───────────────────────────────────────────────────


@pytest.fixture()
def agent(modules):
    """A real personality, so the byte-identical claim is about a real prompt."""
    from app.personalities import registry

    return registry.get_or_default("companion")


class TestOffIsInvisible:
    def test_no_conversation_id_is_the_prompt_the_product_had(self, modules, agent):
        # Every existing caller omits the argument. This is the assertion that says so.
        base = modules.prompt_builder.build_system_prompt(agent)
        with_none = modules.prompt_builder.build_system_prompt(agent, conversation_id=None)
        assert base == with_none
        assert modules.live_context.BLOCK_HEADER not in base

    def test_a_live_meeting_with_the_flag_down_changes_nothing(self, modules, agent, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")  # master on, `together` still off
        mid = meeting(modules, segments=[seg(0, "we should hold pricing at forty a seat")],
                      notes=NOTES)
        go_live(modules, mid)
        base = modules.prompt_builder.build_system_prompt(agent)
        live = modules.prompt_builder.build_system_prompt(agent, conversation_id="conv-1")
        assert live == base

    def test_a_conversation_with_no_live_meeting_changes_nothing(self, modules, agent, together):
        # The meeting exists in the store but nothing is recording it — a meeting that ended
        # is history, and history reaches a persona through retrieval, not through the prompt.
        meeting(modules, segments=[seg(0, "we should hold pricing")], notes=NOTES)
        base = modules.prompt_builder.build_system_prompt(agent)
        assert modules.prompt_builder.build_system_prompt(agent, conversation_id="conv-1") == base

    def test_no_conversation_id_does_not_even_reach_meetingsense(self, modules, agent, together,
                                                                   monkeypatch):
        # The guard in the prompt builder is not a duplicate of the one in `for_conversation`:
        # it is what keeps the common case — every caller that has no conversation id — from
        # importing MeetingSense and loading its config on every single prompt.
        called = []
        monkeypatch.setattr(modules.live_context, "for_conversation",
                            lambda cid, **kw: called.append(cid) or "")
        modules.prompt_builder.build_system_prompt(agent)
        modules.prompt_builder.build_system_prompt(agent, conversation_id=None)
        modules.prompt_builder.build_system_prompt(agent, conversation_id="")
        assert called == []

    def test_meetingsense_raising_never_costs_a_chat(self, modules, agent, together, monkeypatch):
        # A persona that cannot answer because a meeting was being recorded would be a worse
        # bug than no meeting context at all.

        def angry(conversation_id, **kwargs):
            raise RuntimeError("the meeting store is on fire")

        monkeypatch.setattr(modules.live_context, "for_conversation", angry)
        base = modules.prompt_builder.build_system_prompt(agent)
        assert modules.prompt_builder.build_system_prompt(agent, conversation_id="conv-1") == base

    def test_a_live_meeting_with_nothing_said_yet_says_nothing(self, modules, together):
        # A meeting ten seconds old has nothing to report, and a block saying so costs tokens
        # to tell a persona nothing.
        mid = meeting(modules)
        go_live(modules, mid, elapsed_ms=10_000)
        assert modules.live_context.for_conversation("conv-1") == ""


# ── on ──────────────────────────────────────────────────────────────────────


class TestTheBlock:
    @pytest.fixture()
    def live(self, modules, together):
        mid = meeting(
            modules,
            segments=[seg(3_540_000, "so the number she quoted was four hundred and twelve"),
                      seg(3_560_000, "right, four twelve", speaker="me")],
            keyframes=[{"t_ms": 3_400_000, "url": "/files/a.jpg", "hash": "a",
                        "caption": "Enterprise pricing, per seat."}],
            notes=NOTES,
        )
        go_live(modules, mid, elapsed_ms=3_600_000)
        return mid

    def test_the_block_is_there_and_named(self, modules, live):
        block = modules.live_context.for_conversation("conv-1")
        assert block.startswith(modules.live_context.BLOCK_HEADER)

    def test_it_carries_the_four_tiers(self, modules, live):
        block = modules.live_context.for_conversation("conv-1")
        assert "hold at forty a seat" in block                      # recap
        assert "Hold pricing at forty a seat" in block              # decisions
        assert "Who signs off on the discount tier?" in block       # open questions
        assert "Enterprise pricing, per seat." in block             # the slide on screen
        assert "four hundred and twelve" in block                   # verbatim

    def test_it_leaves_out_what_is_already_settled(self, modules, live):
        # An "open questions" list that includes answered ones is a list the reader re-checks.
        block = modules.live_context.for_conversation("conv-1")
        assert "Is October realistic?" not in block
        assert "Book the legal slot" not in block

    def test_it_tells_the_persona_what_it_cannot_see(self, modules, live):
        # Without this a model asked "what did she say?" answers about the last thing in *its*
        # window, which is the chat, not the meeting — and cites a timestamp it invented.
        block = modules.live_context.for_conversation("conv-1")
        assert "cannot see the rest of the transcript" in block
        assert "Cite a timestamp only if it appears below" in block

    def test_it_is_prepended_to_the_prompt_not_appended(self, modules, agent, live):
        # It is what the user is asking about, and a model reading a long system prompt
        # weights the opening.
        prompt = modules.prompt_builder.build_system_prompt(agent, conversation_id="conv-1")
        assert prompt.startswith(modules.live_context.BLOCK_HEADER)
        assert agent.system_prompt in prompt


class TestCurrentSlide:
    def test_the_last_captioned_slide_is_the_one_on_screen(self, modules):
        frames = [{"t_ms": 0, "caption": "Title slide."}, {"t_ms": 60_000, "caption": "The chart."}]
        assert "The chart." in modules.live_context.current_slide(frames)

    def test_an_uncaptioned_newer_slide_falls_back_rather_than_going_blank(self, modules):
        # The vision model has not answered about it yet. The slide before it is more use than
        # saying nothing about what is on screen.
        frames = [{"t_ms": 0, "caption": "The chart."}, {"t_ms": 60_000, "caption": None}]
        assert "The chart." in modules.live_context.current_slide(frames)

    def test_no_captions_at_all(self, modules):
        assert modules.live_context.current_slide([]) == ""
        assert modules.live_context.current_slide([{"t_ms": 0, "caption": "  "}]) == ""


# ── the budget ──────────────────────────────────────────────────────────────


class TestBudget:
    def three_hours(self, mods):
        """A meeting big enough that an unbounded block would truncate the prompt."""
        rows = [seg(i * 4_000, f"a routine point number {i} about the quarter and the plan")
                for i in range(2700)]
        rows[100] = seg(400_000, "the thing said in the first hour that must not reach the prompt")
        return meeting(mods, segments=rows, notes=NOTES,
                       keyframes=[{"t_ms": 10_000, "url": "/f.jpg", "hash": "h",
                                   "caption": "A slide from the first minutes."}])

    def test_a_three_hour_meeting_stays_inside_the_budget(self, modules, together):
        import app.meetingsense.ask as ask

        mid = self.three_hours(modules)
        go_live(modules, mid, elapsed_ms=10_800_000)
        block = modules.live_context.for_conversation("conv-1")
        assert block
        # Against **900**, D9's number, not against the module's own constant: an assertion
        # written `<= live_context.TOKEN_BUDGET` passes for any budget the module cares to
        # set, including one raised out of the way, which is the failure it exists to catch.
        assert ask.estimate_tokens(block) <= 900
        assert modules.live_context.TOKEN_BUDGET == 900

    def test_and_still_contains_the_recap(self, modules, together):
        # The acceptance criterion, and the reason the trim order is written down: a model with
        # the verbatim and no recap knows the last thirty seconds of a three-hour call.
        mid = self.three_hours(modules)
        go_live(modules, mid, elapsed_ms=10_800_000)
        block = modules.live_context.for_conversation("conv-1")
        assert "hold at forty a seat" in block

    def test_the_transcript_body_never_reaches_the_prompt(self, modules, together):
        # D9, and the reason `limit=6` in main.py is not touched: everything older than the
        # verbatim window reaches a persona through retrieval, cited, when it is asked for.
        mid = self.three_hours(modules)
        go_live(modules, mid, elapsed_ms=10_800_000)
        block = modules.live_context.for_conversation("conv-1")
        assert "must not reach the prompt" not in block
        assert block.count("a routine point number") < 30


class TestTrimOrder:
    def rows(self, count, at=0):
        return [seg(at + i * 1_000, f"line number {i} " + "padding " * 20) for i in range(count)]

    def test_verbatim_is_trimmed_before_the_notes(self, modules):
        block = modules.live_context.assemble(
            recap=RECAP, notes=NOTES, verbatim_rows=self.rows(40), budget=260
        )
        assert "Hold pricing at forty a seat" in block
        assert "line number 0 " not in block

    def test_the_oldest_verbatim_goes_first(self, modules):
        # The newest is likeliest to be what a question asked mid-meeting is about; trimming
        # from the end would strip the context nearest the ask.
        block = modules.live_context.assemble(recap="", notes={}, verbatim_rows=self.rows(20),
                                              budget=150)
        assert "line number 19 " in block
        assert "line number 0 " not in block

    def test_the_notes_are_trimmed_before_the_recap(self, modules):
        import app.meetingsense.ask as ask

        # Five decisions, under MAX_ITEMS, so the *trim* is what removes them rather than the
        # display cap — with twenty the cap does the work and the test passes with the trim
        # loop deleted.
        block = modules.live_context.assemble(
            recap=RECAP,
            notes={"decisions": [{"text": f"decision number {i} " + "padding " * 10}
                                 for i in range(5)]},
            # 130 sits between the block's floor with the recap alone (123) and its size with
            # the decisions in (254), so the trim has to happen and the recap has to survive
            # it. A budget below the floor would pass whatever the trim loop did.
            budget=130,
        )
        assert "hold at forty a seat" in block
        assert ask.estimate_tokens(block) <= 130
        assert "decision number 4" not in block

    def test_the_recap_survives_a_budget_that_leaves_room_for_nothing_else(self, modules):
        block = modules.live_context.assemble(
            recap=RECAP, notes=NOTES, slide="00:00:10 A slide.",
            verbatim_rows=self.rows(40), budget=1,
        )
        assert "hold at forty a seat" in block

    def test_a_block_that_fits_is_not_trimmed_at_all(self, modules):
        block = modules.live_context.assemble(recap=RECAP, notes=NOTES,
                                              verbatim_rows=self.rows(2), budget=900)
        assert "line number 0 " in block
        assert "Who signs off on the discount tier?" in block


class TestTheChatPathIsWired:
    def test_the_orchestrator_passes_the_conversation_to_the_prompt_builder(self, modules):
        """The one-line seam, checked at the source.

        Everything else in this file exercises `build_system_prompt` directly, which leaves
        the actual wiring — the chat path handing it a conversation id — untested. Booting the
        orchestrator to prove one keyword argument would need a model, a store and a socket;
        reading the call is the right weight for the claim, and it fails if somebody
        "simplifies" the argument away.
        """
        import inspect
        import app.orchestrator as orchestrator

        source = inspect.getsource(orchestrator.orchestrate)
        call = source[source.index("build_system_prompt("):]
        call = call[: call.index(")") + 1]
        assert "conversation_id=cid" in call, call


class TestEnabled:
    def test_the_master_flag_alone_is_not_enough(self, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        assert modules.live_context.enabled(modules.config.load_config()) is False

    def test_together_alone_is_not_enough_either(self, modules, monkeypatch):
        # No sub-flag is implied by the master, and none implies it.
        monkeypatch.setenv("MEETINGSENSE_TOGETHER", "true")
        assert modules.live_context.enabled(modules.config.load_config()) is False

    def test_both(self, modules, together):
        assert modules.live_context.enabled(modules.config.load_config()) is True
