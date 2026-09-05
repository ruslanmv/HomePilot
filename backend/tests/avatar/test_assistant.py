"""B21 — the morning brief, and the absence of a second approval path.

The load-bearing tests here are the negative ones. Anyone can write a module that proposes
rather than acts; the question is whether the next person to touch it *can* make it act
without noticing. So this file reads the module's source for the machinery a bypass would
need, and asserts a proposal has no way to answer itself.
"""

from __future__ import annotations

import inspect
import re

import pytest

from app.avatar_director import assistant, safety
from app.avatar_director.panels import PROTOCOL_VERSION
from app.daypilot_bridge import bridge


def codeof(module) -> str:
    """Source with docstrings and comments removed.

    Every source-grep assertion in this repository has, at least once, matched the prose
    explaining why the thing it forbids is forbidden. Strip the prose first.
    """
    text = inspect.getsource(module)
    text = re.sub(r'"""[\s\S]*?"""', " ", text)
    text = re.sub(r"'''[\s\S]*?'''", " ", text)
    text = re.sub(r"(^|[^:])#.*$", r"\1", text, flags=re.MULTILINE)
    return text


AGENDA = [
    {"when": "09:00", "what": "Standup"},
    {"when": "11:30", "what": "Dentist"},
    {"when": "15:00", "what": "Design review with Ana"},
]


# ── the acceptance criterion, read literally ─────────────────────────────────


class TestGoodMorning:
    def test_it_produces_a_panel_a_spoken_summary_and_one_confirm(self):
        brief = assistant.good_morning(
            AGENDA,
            actions=[{"capability": "calendar.create", "summary": "Block an hour after the dentist"}],
        )
        assert brief.panel["type"] == "display"
        assert brief.panel["kind"] == "agenda"
        assert brief.speech.strip()
        assert brief.confirm_count == 1

    def test_the_panel_carries_every_item(self):
        brief = assistant.good_morning(AGENDA)
        assert len(brief.panel["data"]["items"]) == len(AGENDA)

    def test_the_frames_are_panel_then_gesture_then_speech(self):
        brief = assistant.good_morning(AGENDA)
        assert [f["type"] for f in brief.messages()] == ["display", "intent", "say"]

    def test_the_gesture_is_whitelisted(self):
        # `messages()` builds the intent through ProtocolHandler, which refuses an emote
        # outside EMOTE_WHITELIST — so this passing is the whitelist agreeing, not this
        # file asserting a string it also chose.
        from app.avatar_director.protocol import EMOTE_WHITELIST

        assert assistant.POINT_INTENT in EMOTE_WHITELIST

    def test_every_frame_carries_the_protocol_version(self):
        for frame in assistant.good_morning(AGENDA).messages():
            assert frame["v"] == PROTOCOL_VERSION

    def test_a_day_with_nothing_in_it_still_briefs(self):
        brief = assistant.good_morning([])
        assert brief.panel["data"]["items"] == []
        assert "nothing" in brief.speech.lower()
        assert brief.confirm_count == 0

    def test_no_action_means_no_confirmation(self):
        assert assistant.good_morning(AGENDA).confirm_count == 0


class TestExactlyOne:
    def test_a_second_valid_action_is_deferred_not_offered(self):
        brief = assistant.good_morning(
            AGENDA,
            actions=[
                {"capability": "calendar.create", "summary": "Block an hour"},
                {"capability": "email.send", "summary": "Tell Ana you may be late"},
                {"capability": "message.send", "summary": "Ping the team"},
            ],
        )
        assert brief.confirm_count == 1
        assert len(brief.deferred) == 2

    def test_deferred_proposals_are_not_in_the_directive_block(self):
        brief = assistant.good_morning(
            AGENDA,
            actions=[
                {"capability": "calendar.create", "summary": "Block an hour"},
                {"capability": "email.send", "summary": "Tell Ana"},
            ],
        )
        # Not offered means not sent. A deferred proposal arriving at the Approval Center
        # would be a confirmation the user was never shown the question for.
        assert len(brief.directives()) == 1
        assert brief.directives()[0]["capability"] == "calendar.create"

    def test_nothing_is_silently_dropped(self):
        actions = [{"capability": "calendar.create", "summary": f"thing {i}"} for i in range(5)]
        brief = assistant.good_morning(AGENDA, actions=actions)
        assert len(brief.proposals) + len(brief.deferred) == 5

    def test_the_limit_is_one_and_it_is_named(self):
        assert assistant.MAX_PROPOSALS_PER_BRIEF == 1


# ── the one door ─────────────────────────────────────────────────────────────


class TestGate:
    def test_every_daypilot_capability_is_confirm(self):
        for capability in bridge.CAPABILITIES:
            assert assistant.gate(capability) == assistant.CONFIRM

    def test_avatar_tools_keep_the_grades_safety_gave_them(self):
        for tool, level in safety.TOOL_SAFETY.items():
            assert assistant.gate(tool) == level

    def test_an_unknown_capability_is_refused_not_defaulted(self):
        # Grading an unknown name "confirm to be safe" would let a typo become a real-world
        # action that the user then approves, believing they read it.
        with pytest.raises(assistant.AssistantError) as caught:
            assistant.gate("calendar.creat")
        assert caught.value.code == "capability_unknown"

    def test_an_empty_capability_is_refused(self):
        with pytest.raises(assistant.AssistantError) as caught:
            assistant.gate("")
        assert caught.value.code == "capability_missing"

    def test_the_capability_list_is_read_from_the_bridge_not_copied(self):
        assert assistant.capabilities() is bridge.CAPABILITIES

    def test_an_autonomous_tool_cannot_become_a_proposal(self):
        assert safety.level_for("play_animation") == "autonomous"
        with pytest.raises(assistant.AssistantError) as caught:
            assistant.propose("play_animation", "wave at you")
        assert caught.value.code == "not_a_proposal"

    def test_a_read_only_tool_cannot_become_a_proposal_either(self):
        with pytest.raises(assistant.AssistantError) as caught:
            assistant.propose("search_animations", "look something up")
        assert caught.value.code == "not_a_proposal"

    def test_a_proposal_needs_words_the_user_can_read(self):
        with pytest.raises(assistant.AssistantError) as caught:
            assistant.propose("calendar.create", "   ")
        assert caught.value.code == "summary_missing"

    def test_a_bad_candidate_costs_the_brief_nothing(self):
        brief = assistant.good_morning(
            AGENDA,
            actions=[
                {"capability": "not.a.thing", "summary": "do something"},
                {"capability": "calendar.create", "summary": "Block an hour"},
            ],
        )
        assert brief.confirm_count == 1
        assert brief.proposals[0].capability == "calendar.create"


# ── no tool runs outside the safety layer ────────────────────────────────────


class TestNoSecondApprovalPath:
    #: What a module would need in order to act on its own. If any of it appears here, the
    #: second door has been built.
    FORBIDDEN = [
        "httpx",
        "requests",
        "urllib",
        "aiohttp",
        "subprocess",
        "os.system",
        "socket",
        "smtplib",
        "googleapiclient",
        "msgraph",
    ]

    def test_the_module_cannot_reach_the_network(self):
        source = codeof(assistant)
        for token in self.FORBIDDEN:
            assert token not in source, f"assistant.py mentions {token!r} — it has a way to act"

    def test_the_stripper_is_not_vacuous(self):
        # If codeof() returned an empty string the test above would pass for free.
        source = codeof(assistant)
        assert "def compose(" in source
        assert "MAX_PROPOSALS_PER_BRIEF = 1" in source

    def test_a_proposal_has_no_way_to_answer_itself(self):
        proposal = assistant.propose("calendar.create", "Block an hour")
        for verb in ("run", "execute", "call", "send", "apply", "confirm", "approve"):
            assert not hasattr(proposal, verb), f"Proposal.{verb} exists — that is the second door"

    def test_a_proposal_is_frozen(self):
        proposal = assistant.propose("calendar.create", "Block an hour")
        with pytest.raises(Exception):
            proposal.capability = "email.send"

    def test_the_only_rendering_of_a_proposal_is_a_bridge_directive(self):
        proposal = assistant.propose("calendar.create", "Block an hour", {"at": "12:30"})
        directive = proposal.as_directive()
        assert directive["type"] == "daypilot.action.propose"
        assert directive["type"] in bridge.ALLOWED_DIRECTIVES

    def test_the_directive_survives_the_bridge_validating_it_again(self):
        # Two independent validations of the same untrusted output is the contract. If this
        # module ever emitted something the bridge drops, the proposal would vanish between
        # the persona and the Approval Center and the user would simply never be asked.
        brief = assistant.good_morning(
            AGENDA, actions=[{"capability": "calendar.create", "summary": "Block an hour", "arguments": {"at": "12:30"}}]
        )
        clean = bridge._sanitize_directive(brief.directives()[0])
        assert clean is not None
        assert clean["capability"] == "calendar.create"
        assert clean["arguments"] == {"at": "12:30"}

    def test_compose_takes_no_executor(self):
        # The structural half of the guarantee: there is nowhere to inject one.
        params = set(inspect.signature(assistant.compose).parameters)
        for name in ("client", "executor", "session", "http", "tools", "run"):
            assert name not in params

    def test_the_brief_holds_data_and_nothing_callable(self):
        brief = assistant.good_morning(AGENDA, actions=[{"capability": "email.send", "summary": "Tell Ana"}])
        for proposal in brief.proposals + brief.deferred:
            callables = [n for n in dir(proposal) if not n.startswith("_") and callable(getattr(proposal, n))]
            assert callables == ["as_directive"], callables


# ── she points at the panel rather than narrating into space ─────────────────


class TestSpeechDefersToThePanel:
    def test_a_long_day_is_not_read_out(self):
        agenda = [{"when": f"{h:02d}:00", "what": f"Meeting {h}"} for h in range(9, 21)]
        brief = assistant.good_morning(agenda)
        spoken = sum(1 for item in agenda if item["what"] in brief.speech)
        assert spoken <= assistant.SPOKEN_ITEM_LIMIT
        assert len(brief.panel["data"]["items"]) == len(agenda)

    def test_it_says_how_many_are_on_the_screen(self):
        agenda = [{"when": f"{h:02d}:00", "what": f"Meeting {h}"} for h in range(9, 15)]
        assert "on the screen" in assistant.good_morning(agenda).speech

    def test_the_summary_stays_inside_its_budget(self):
        agenda = [{"when": "09:00", "what": "A" * 400}, {"when": "10:00", "what": "B" * 400}]
        speech = assistant.summarise([{"key": i["when"], "value": i["what"]} for i in agenda])
        assert len(speech) <= assistant.SPEECH_CHAR_BUDGET

    def test_the_proposal_is_asked_as_a_question(self):
        brief = assistant.good_morning(AGENDA, actions=[{"capability": "calendar.create", "summary": "Block an hour"}])
        assert brief.speech.rstrip().endswith("?")


# ── untrusted input ──────────────────────────────────────────────────────────


class TestAgendaIsUntrusted:
    def test_one_malformed_entry_does_not_cost_the_morning(self):
        brief = assistant.good_morning([AGENDA[0], None, 42, {"when": "x"}, AGENDA[1]])
        assert len(brief.panel["data"]["items"]) == 2

    def test_a_bare_string_is_an_item(self):
        brief = assistant.good_morning(["Call the plumber"])
        assert brief.panel["data"]["items"] == [{"key": "", "value": "Call the plumber"}]

    def test_alternative_field_names_are_read(self):
        brief = assistant.good_morning([{"start": "09:00", "title": "Standup"}])
        assert brief.panel["data"]["items"] == [{"key": "09:00", "value": "Standup"}]

    def test_a_day_longer_than_the_panel_is_trimmed_to_the_panel_and_says_so(self):
        # The panel refuses more rows than it can draw; this is the caller that knows what
        # to do about it. The count is spoken, so nothing is quietly missing.
        agenda = [{"when": "09:00", "what": f"Thing {i}"} for i in range(40)]
        brief = assistant.good_morning(agenda)
        assert len(brief.panel["data"]["items"]) == 24
        assert brief.panel["data"]["footer"] == "16 more not shown"

    def test_an_oversized_panel_is_refused_rather_than_trimmed(self):
        from app.avatar_director.panels import PanelError

        agenda = [{"when": "09:00", "what": "x" * 4000} for _ in range(24)]
        with pytest.raises(PanelError) as caught:
            assistant.good_morning(agenda, max_kb=8)
        assert caught.value.code == "panel_too_large"
