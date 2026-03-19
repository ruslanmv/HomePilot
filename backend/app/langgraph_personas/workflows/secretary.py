"""
Secretary Workflow Definitions — named multi-step graphs for Scarlett.

AAA pattern: "Quest/Mission System" — predefined sequences of actions
that the secretary persona can execute when triggered by specific intents.

These workflows are referenced in cognitive_profile.json as:
  "workflow_graphs": ["secretary_daily_briefing", "secretary_email_triage", "secretary_meeting_prep"]
"""
from __future__ import annotations

from typing import Any, Dict, List


# ── Workflow step definitions ────────────────────────────────────────

class WorkflowStep:
    """A single step in a named workflow."""

    def __init__(
        self,
        name: str,
        tool: str = "",
        tool_args: Dict[str, Any] = None,
        prompt_hint: str = "",
        requires_previous: bool = False,
    ) -> None:
        self.name = name
        self.tool = tool
        self.tool_args = tool_args or {}
        self.prompt_hint = prompt_hint
        self.requires_previous = requires_previous

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "tool": self.tool,
            "tool_args": self.tool_args,
            "prompt_hint": self.prompt_hint,
            "requires_previous": self.requires_previous,
        }


class WorkflowDefinition:
    """A named multi-step workflow."""

    def __init__(
        self,
        workflow_id: str,
        display_name: str,
        description: str,
        steps: List[WorkflowStep],
        trigger_phrases: List[str] = None,
    ) -> None:
        self.workflow_id = workflow_id
        self.display_name = display_name
        self.description = description
        self.steps = steps
        self.trigger_phrases = trigger_phrases or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "display_name": self.display_name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "trigger_phrases": self.trigger_phrases,
        }


# ── Secretary workflows ──────────────────────────────────────────────

SECRETARY_DAILY_BRIEFING = WorkflowDefinition(
    workflow_id="secretary_daily_briefing",
    display_name="Daily Briefing",
    description="Compile and present the user's daily overview: schedule, priorities, reminders.",
    trigger_phrases=["daily briefing", "what's on today", "morning summary", "brief me"],
    steps=[
        WorkflowStep(
            name="recall_user_context",
            tool="memory.recall",
            tool_args={"query": "schedule preferences routines reminders"},
            prompt_hint="Recall the user's known schedule preferences and routines.",
        ),
        WorkflowStep(
            name="check_profile",
            tool="user.profile.get",
            prompt_hint="Get the latest user profile for timezone and preferences.",
        ),
        WorkflowStep(
            name="search_recent_context",
            tool="web.search",
            tool_args={"query": "today's date weather news headlines", "max_results": 3},
            prompt_hint="Get today's date, weather, and top headlines for context.",
            requires_previous=True,
        ),
        WorkflowStep(
            name="synthesize_briefing",
            prompt_hint=(
                "Compile everything into a concise daily briefing. "
                "Include: greeting, date/time, weather, key reminders, "
                "and any open tasks. Keep it warm and professional."
            ),
            requires_previous=True,
        ),
    ],
)

SECRETARY_EMAIL_TRIAGE = WorkflowDefinition(
    workflow_id="secretary_email_triage",
    display_name="Email Triage",
    description="Help the user sort and prioritize incoming communications.",
    trigger_phrases=["check emails", "email triage", "sort my inbox", "any messages"],
    steps=[
        WorkflowStep(
            name="recall_email_context",
            tool="memory.recall",
            tool_args={"query": "email contacts priorities communication preferences"},
            prompt_hint="Recall email-related preferences and important contacts.",
        ),
        WorkflowStep(
            name="check_integrations",
            tool="user.integrations.list",
            prompt_hint="Check which communication integrations are configured.",
        ),
        WorkflowStep(
            name="prioritize_and_respond",
            prompt_hint=(
                "Based on available context, help the user understand their "
                "communication priorities. If no email integration is configured, "
                "explain what would be needed and offer to help set it up."
            ),
            requires_previous=True,
        ),
    ],
)

SECRETARY_MEETING_PREP = WorkflowDefinition(
    workflow_id="secretary_meeting_prep",
    display_name="Meeting Preparation",
    description="Prepare materials and context for an upcoming meeting.",
    trigger_phrases=["prepare for meeting", "meeting prep", "get ready for the call"],
    steps=[
        WorkflowStep(
            name="recall_meeting_context",
            tool="memory.recall",
            tool_args={"query": "meetings attendees topics preparation notes"},
            prompt_hint="Recall any known meeting context, attendees, and topics.",
        ),
        WorkflowStep(
            name="research_topics",
            tool="web.search",
            tool_args={"query": "", "max_results": 3},
            prompt_hint="Search for relevant background on meeting topics.",
            requires_previous=True,
        ),
        WorkflowStep(
            name="compile_prep",
            prompt_hint=(
                "Compile a meeting preparation brief: key talking points, "
                "attendee context, relevant research, and suggested questions. "
                "Format it clearly and concisely."
            ),
            requires_previous=True,
        ),
    ],
)


# ── Registry ─────────────────────────────────────────────────────────

SECRETARY_WORKFLOWS: Dict[str, WorkflowDefinition] = {
    "secretary_daily_briefing": SECRETARY_DAILY_BRIEFING,
    "secretary_email_triage": SECRETARY_EMAIL_TRIAGE,
    "secretary_meeting_prep": SECRETARY_MEETING_PREP,
}


def get_secretary_workflow(workflow_id: str) -> WorkflowDefinition | None:
    return SECRETARY_WORKFLOWS.get(workflow_id)


def match_secretary_workflow(utterance: str) -> WorkflowDefinition | None:
    """Match an utterance to a secretary workflow by trigger phrases."""
    text = utterance.lower().strip()
    for wf in SECRETARY_WORKFLOWS.values():
        for phrase in wf.trigger_phrases:
            if phrase in text:
                return wf
    return None
