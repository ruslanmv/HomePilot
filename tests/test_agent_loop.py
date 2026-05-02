import pytest
from expert.runtime.session_store import session_store
from expert.runtime.conversation_manager import ConversationManager
from expert.orchestration.tool_registry import build_registry
from expert.orchestration.tool_router import ToolRouter
from expert.orchestration.executor import ToolExecutor
from expert.orchestration.planner import Planner
from expert.models.client import ModelClient
from expert.agent.loop import AgentLoop


@pytest.mark.asyncio
async def test_agent_direct_answer():
    conv = ConversationManager(session_store)
    router = ToolRouter(build_registry())
    executor = ToolExecutor(build_registry())
    planner = Planner()
    model = ModelClient()
    agent = AgentLoop(conv, router, executor, planner, model)

    answer = await agent.run_turn("t1", "hello world")
    assert "direct answer" in answer.lower() or "using model" in answer.lower()
