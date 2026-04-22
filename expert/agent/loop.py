from typing import Awaitable, Callable, Optional
from expert.settings import settings
from expert.types import AgentEvent
from expert.agent.termination import TerminationPolicy
from expert.agent.self_check import SelfCheck
from expert.agent.repair import Repair
from expert.response.composer import ResponseComposer
from expert.workspace.workspace_binding import workspace_binding


EventCallback = Callable[[AgentEvent], Awaitable[None]]


class AgentLoop:
    def __init__(
        self,
        conversation_manager,
        tool_router,
        tool_executor,
        planner,
        model_client,
    ):
        self.conversation_manager = conversation_manager
        self.tool_router = tool_router
        self.tool_executor = tool_executor
        self.planner = planner
        self.model_client = model_client
        self.termination = TerminationPolicy()
        self.self_check = SelfCheck()
        self.repair = Repair()
        self.composer = ResponseComposer()

    async def run_turn(
        self,
        session_id: str,
        user_message: str,
        emit: Optional[EventCallback] = None,
    ) -> str:
        workspace_id = workspace_binding.get(session_id)
        context = self.conversation_manager.build_context(session_id, user_message)

        if emit:
            await emit(AgentEvent(type="status", data={"message": "Building tool plan"}))

        candidate_tools = self.tool_router.route(user_message, workspace_id=workspace_id)
        plan = self.planner.plan(user_message, candidate_tools, workspace_id=workspace_id)

        if emit:
            await emit(AgentEvent(
                type="plan",
                data={
                    "workspace_id": workspace_id,
                    "steps": [step.model_dump() for step in plan],
                },
            ))

        tool_results = []
        saw_finalize = False
        step_count = 0

        for step in plan:
            step_count += 1

            if step.kind == "confirm":
                state = self.conversation_manager.store.get_state(session_id)
                state.pending_confirmation = {
                    "step": step.model_dump(),
                    "message": step.confirmation_message,
                }
                self.conversation_manager.store.save_state(state)

                if emit:
                    await emit(AgentEvent(
                        type="confirmation_required",
                        data={
                            "message": step.confirmation_message,
                            "tool_name": step.tool_call.name if step.tool_call else None,
                        },
                    ))

                return (
                    "Confirmation required before I continue.\n\n"
                    f"{step.confirmation_message}"
                )

            if step.kind == "tool" and step.tool_call:
                result = await self.tool_executor.call(
                    step.tool_call.name,
                    step.tool_call.arguments,
                    emit=emit,
                )
                tool_results.append(result)
                self.conversation_manager.add_tool_message(
                    session_id,
                    step.tool_call.name,
                    result.model_dump(),
                )

            elif step.kind == "answer":
                if emit:
                    await emit(AgentEvent(type="status", data={"message": "Composing final answer"}))

            elif step.kind == "finalize":
                saw_finalize = True

            if self.termination.should_stop(step_count, settings.max_agent_steps, saw_finalize):
                break

        draft = await self.model_client.generate(
            context=context,
            user_message=user_message,
            tool_results=tool_results,
        )
        answer = self.composer.compose(draft, tool_results)
        issues = self.self_check.review(answer, tool_results)
        final_answer = self.repair.fix(answer, issues)

        if emit:
            await emit(AgentEvent(type="final_answer", data={"answer": final_answer}))
            await emit(AgentEvent(type="done", data={"session_id": session_id}))

        return final_answer

    async def continue_after_confirmation(
        self,
        session_id: str,
        confirmed: bool,
        emit: Optional[EventCallback] = None,
    ) -> str:
        state = self.conversation_manager.store.get_state(session_id)
        pending = state.pending_confirmation

        if not pending:
            return "No pending confirmation."

        if not confirmed:
            state.pending_confirmation = None
            self.conversation_manager.store.save_state(state)
            if emit:
                await emit(AgentEvent(type="done", data={"session_id": session_id}))
            return "Action cancelled."

        step = pending["step"]
        state.pending_confirmation = None
        self.conversation_manager.store.save_state(state)

        if emit:
            await emit(AgentEvent(type="status", data={"message": "Confirmation accepted. Executing action."}))

        tool_call = step.get("tool_call")
        if not tool_call:
            return "Invalid confirmation state."

        result = await self.tool_executor.call(
            tool_call["name"],
            tool_call["arguments"],
            emit=emit,
        )
        self.conversation_manager.add_tool_message(session_id, tool_call["name"], result.model_dump())

        answer = self.composer.compose(
            f"I completed the confirmed action using {tool_call['name']}.",
            [result],
        )
        issues = self.self_check.review(answer, [result])
        final_answer = self.repair.fix(answer, issues)

        if emit:
            await emit(AgentEvent(type="final_answer", data={"answer": final_answer}))
            await emit(AgentEvent(type="done", data={"session_id": session_id}))

        return final_answer
