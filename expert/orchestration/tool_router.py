from expert.orchestration.tool_policies import choose_tool_hints
from expert.policy.assistant_policy import AssistantPolicy
from expert.policy.tool_guardrails import ToolGuardrails


class ToolRouter:
    def __init__(self, registry: dict):
        self.registry = registry
        self.assistant_policy = AssistantPolicy()
        self.guardrails = ToolGuardrails()

    def route(self, user_text: str, workspace_id: str | None = None) -> list[str]:
        has_workspace = workspace_id is not None
        hints = choose_tool_hints(user_text, has_workspace)

        allowed = []
        for tool_name in hints:
            if tool_name in self.registry and self.guardrails.allow(tool_name, user_text):
                allowed.append(tool_name)

        return allowed
