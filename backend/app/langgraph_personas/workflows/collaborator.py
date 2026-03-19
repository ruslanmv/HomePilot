"""
Collaborator Workflow Definitions — named multi-step graphs for Nova.

AAA pattern: "Quest/Mission System" — predefined research and planning
workflows that the collaborator persona can execute.
"""
from __future__ import annotations

from typing import Any, Dict

from .secretary import WorkflowStep, WorkflowDefinition


# ── Collaborator workflows ───────────────────────────────────────────

COLLABORATOR_RESEARCH = WorkflowDefinition(
    workflow_id="collaborator_research",
    display_name="Research Task",
    description="Conduct multi-step research on a topic and synthesize findings.",
    trigger_phrases=["research this", "look into", "investigate", "find out about"],
    steps=[
        WorkflowStep(
            name="recall_existing_knowledge",
            tool="memory.recall",
            tool_args={"query": ""},
            prompt_hint="Recall any existing knowledge about the research topic.",
        ),
        WorkflowStep(
            name="web_research_1",
            tool="web.search",
            tool_args={"query": "", "max_results": 5},
            prompt_hint="Search for primary sources and recent information.",
            requires_previous=True,
        ),
        WorkflowStep(
            name="web_research_2",
            tool="web.search",
            tool_args={"query": "", "max_results": 3},
            prompt_hint="Search for alternative perspectives and deeper details.",
            requires_previous=True,
        ),
        WorkflowStep(
            name="synthesize_findings",
            prompt_hint=(
                "Synthesize all research into a clear, structured summary. "
                "Include key findings, source quality assessment, and "
                "recommended next steps."
            ),
            requires_previous=True,
        ),
    ],
)

COLLABORATOR_PLANNING = WorkflowDefinition(
    workflow_id="collaborator_planning",
    display_name="Project Planning",
    description="Help plan a project or task with structured breakdown.",
    trigger_phrases=["help me plan", "project plan", "let's plan", "break this down"],
    steps=[
        WorkflowStep(
            name="understand_scope",
            tool="memory.recall",
            tool_args={"query": "projects goals preferences work style"},
            prompt_hint="Recall relevant project context and user work preferences.",
        ),
        WorkflowStep(
            name="research_best_practices",
            tool="web.search",
            tool_args={"query": "", "max_results": 3},
            prompt_hint="Research best practices for the type of project.",
            requires_previous=True,
        ),
        WorkflowStep(
            name="create_plan",
            prompt_hint=(
                "Create a structured project plan with: "
                "1. Clear objectives, "
                "2. Task breakdown with priorities, "
                "3. Dependencies and blockers, "
                "4. Suggested timeline. "
                "Keep it actionable and realistic."
            ),
            requires_previous=True,
        ),
    ],
)

COLLABORATOR_KNOWLEDGE_INDEX = WorkflowDefinition(
    workflow_id="collaborator_knowledge_index",
    display_name="Knowledge Indexing",
    description="Index and organize information into the knowledge base.",
    trigger_phrases=["save this", "index this", "remember this research", "store these findings"],
    steps=[
        WorkflowStep(
            name="analyze_content",
            prompt_hint="Analyze the content to extract key facts, categories, and relationships.",
        ),
        WorkflowStep(
            name="store_knowledge",
            tool="memory.store",
            tool_args={"key": "", "value": "", "importance": 0.7},
            prompt_hint="Store the most important extracted facts as memories.",
            requires_previous=True,
        ),
    ],
)


# ── Registry ─────────────────────────────────────────────────────────

COLLABORATOR_WORKFLOWS: Dict[str, WorkflowDefinition] = {
    "collaborator_research": COLLABORATOR_RESEARCH,
    "collaborator_planning": COLLABORATOR_PLANNING,
    "collaborator_knowledge_index": COLLABORATOR_KNOWLEDGE_INDEX,
}


def get_collaborator_workflow(workflow_id: str) -> WorkflowDefinition | None:
    return COLLABORATOR_WORKFLOWS.get(workflow_id)


def match_collaborator_workflow(utterance: str) -> WorkflowDefinition | None:
    """Match an utterance to a collaborator workflow by trigger phrases."""
    text = utterance.lower().strip()
    for wf in COLLABORATOR_WORKFLOWS.values():
        for phrase in wf.trigger_phrases:
            if phrase in text:
                return wf
    return None
