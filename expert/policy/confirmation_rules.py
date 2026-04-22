class ConfirmationRules:
    WRITE_ACTIONS = [
        "replace", "patch", "modify", "delete", "write", "rewrite", "update"
    ]

    def requires_confirmation(self, tool_name: str, user_text: str) -> bool:
        q = user_text.lower()

        if tool_name in {"hp.ws.replace_range", "hp.ws.patch"}:
            return True

        return any(action in q for action in self.WRITE_ACTIONS)

    def build_confirmation_message(self, tool_name: str) -> str:
        if tool_name == "hp.ws.replace_range":
            return "This will modify a file range in the workspace. Confirm to continue."
        if tool_name == "hp.ws.patch":
            return "This will apply a patch to the workspace. Confirm to continue."
        return f"This action will execute {tool_name}. Confirm to continue."
