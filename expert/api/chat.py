from fastapi import APIRouter
from pydantic import BaseModel
from expert.runtime.session_store import session_store
from expert.runtime.conversation_manager import ConversationManager
from expert.orchestration.tool_registry import build_registry
from expert.orchestration.tool_router import ToolRouter
from expert.orchestration.executor import ToolExecutor
from expert.orchestration.planner import Planner
from expert.models.client import ModelClient
from expert.agent.loop import AgentLoop
from expert.api.streaming import get_session_emitter
from expert.workspace.workspace_binding import workspace_binding

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    workspace_id: str | None = None


class ConfirmationRequest(BaseModel):
    session_id: str
    confirmed: bool


@router.post("/chat")
async def chat(req: ChatRequest):
    if req.workspace_id:
        workspace_binding.bind(req.session_id, req.workspace_id)

    conv = ConversationManager(session_store)
    conv.add_user_message(req.session_id, req.message)

    registry = build_registry()
    router_ = ToolRouter(registry)
    executor = ToolExecutor(registry)
    planner = Planner()
    model = ModelClient()
    agent = AgentLoop(
        conversation_manager=conv,
        tool_router=router_,
        tool_executor=executor,
        planner=planner,
        model_client=model,
    )

    emit = get_session_emitter(req.session_id)
    answer = await agent.run_turn(req.session_id, req.message, emit=emit)
    conv.add_assistant_message(req.session_id, answer)
    return {"session_id": req.session_id, "answer": answer}


@router.post("/chat/confirm")
async def chat_confirm(req: ConfirmationRequest):
    conv = ConversationManager(session_store)
    registry = build_registry()
    router_ = ToolRouter(registry)
    executor = ToolExecutor(registry)
    planner = Planner()
    model = ModelClient()

    agent = AgentLoop(
        conversation_manager=conv,
        tool_router=router_,
        tool_executor=executor,
        planner=planner,
        model_client=model,
    )

    emit = get_session_emitter(req.session_id)
    answer = await agent.continue_after_confirmation(req.session_id, req.confirmed, emit=emit)
    conv.add_assistant_message(req.session_id, answer)
    return {"session_id": req.session_id, "answer": answer}
