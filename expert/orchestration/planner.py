import uuid
from expert.types import PlannedStep, ToolCall
from expert.policy.confirmation_rules import ConfirmationRules
from expert.policy.assistant_policy import AssistantPolicy
from expert.orchestration.policy_router import PolicyRouter


class Planner:
    def __init__(self):
        self.confirmation_rules = ConfirmationRules()
        self.assistant_policy = AssistantPolicy()
        self.policy_router = PolicyRouter()

    def _id(self) -> str:
        return str(uuid.uuid4())

    def plan(
        self,
        user_text: str,
        candidate_tools: list[str],
        workspace_id: str | None = None,
    ) -> list[PlannedStep]:
        request_type = self.assistant_policy.classify_request(user_text)
        steps: list[PlannedStep] = []

        if self.policy_router.should_run_pre_tool_safety(user_text):
            steps.append(
                PlannedStep(
                    id=self._id(),
                    kind="tool",
                    reasoning="Run safety check before executing risky workflow.",
                    tool_call=ToolCall(
                        name="hp.safety.check_output",
                        arguments={"text": user_text, "profile": "default"},
                    ),
                    tags=["safety", "preflight"],
                )
            )

        if not candidate_tools:
            steps.append(
                PlannedStep(
                    id=self._id(),
                    kind="answer",
                    reasoning="No tool appears necessary; answer directly.",
                    tags=["direct-answer"],
                )
            )
            steps.append(
                PlannedStep(
                    id=self._id(),
                    kind="finalize",
                    reasoning="Finalize the answer.",
                    tags=["final"],
                )
            )
            return steps

        for tool_name in candidate_tools:
            args = self._default_args(tool_name, user_text, workspace_id)

            requires_confirmation = self.confirmation_rules.requires_confirmation(tool_name, user_text)
            if requires_confirmation and request_type == "write":
                steps.append(
                    PlannedStep(
                        id=self._id(),
                        kind="confirm",
                        reasoning=f"{tool_name} may modify state; require confirmation.",
                        requires_confirmation=True,
                        confirmation_message=self.confirmation_rules.build_confirmation_message(tool_name),
                        tool_call=ToolCall(name=tool_name, arguments=args),
                        tags=["confirmation", "write"],
                    )
                )
            else:
                steps.append(
                    PlannedStep(
                        id=self._id(),
                        kind="tool",
                        reasoning=f"Use {tool_name} because it matches the request.",
                        tool_call=ToolCall(name=tool_name, arguments=args),
                        tags=["tool"],
                    )
                )

        if any(t in candidate_tools for t in ["hp.web.search", "hp.doc.query", "hp.ws.search"]):
            steps.append(
                PlannedStep(
                    id=self._id(),
                    kind="tool",
                    reasoning="Verify supporting citations for evidence-backed response.",
                    tool_call=ToolCall(
                        name="hp.citation.verify",
                        arguments={"response_text": user_text},
                    ),
                    tags=["citation"],
                )
            )

        if self.policy_router.should_run_pre_output_safety(user_text):
            steps.append(
                PlannedStep(
                    id=self._id(),
                    kind="tool",
                    reasoning="Run safety check before emitting final answer.",
                    tool_call=ToolCall(
                        name="hp.safety.check_output",
                        arguments={"text": user_text, "profile": "default"},
                    ),
                    tags=["safety", "pre-output"],
                )
            )

        steps.append(
            PlannedStep(
                id=self._id(),
                kind="answer",
                reasoning="Compose the final answer from the gathered evidence.",
                tags=["answer"],
            )
        )
        steps.append(
            PlannedStep(
                id=self._id(),
                kind="finalize",
                reasoning="Finalize the answer and stop.",
                tags=["final"],
            )
        )
        return steps

    def _default_args(self, tool_name: str, user_text: str, workspace_id: str | None) -> dict:
        if tool_name == "hp.web.search":
            return {"query": user_text, "top_k": 5, "recency_days": 30}
        if tool_name == "hp.doc.query":
            return {"text": user_text, "top_k": 5, "filters": {}}
        if tool_name == "hp.ws.search":
            return {"workspace_id": workspace_id, "query": user_text, "top_k": 20}
        if tool_name == "hp.ws.read_range":
            return {"workspace_id": workspace_id, "path": "", "start_line": 1, "end_line": 80}
        if tool_name == "hp.ws.replace_range":
            return {
                "workspace_id": workspace_id,
                "path": "",
                "start_line": 1,
                "end_line": 1,
                "replacement": "",
            }
        if tool_name == "hp.code.run":
            return {
                "language": "python",
                "code": "print('replace with planned code')",
                "timeout_s": 5,
                "memory_mb": 256,
            }
        if tool_name == "hp.citation.verify":
            return {"response_text": user_text}
        return {"query": user_text}
