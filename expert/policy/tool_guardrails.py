class ToolGuardrails:
    WRITE_TOOLS = {
        "hp.ws.replace_range",
        "hp.ws.patch",
    }

    EXECUTION_TOOLS = {
        "hp.code.run",
    }

    def allow(self, tool_name: str, user_text: str) -> bool:
        q = user_text.lower()

        if tool_name in self.EXECUTION_TOOLS:
            return any(k in q for k in ["run", "execute", "test", "calculate", "python"])

        if tool_name in self.WRITE_TOOLS:
            return any(k in q for k in ["replace", "patch", "modify", "update", "rewrite"])

        return True
