class PolicyRouter:
    def should_run_pre_tool_safety(self, user_text: str) -> bool:
        risky = ["malware", "exploit", "steal", "credentials", "bypass"]
        return any(word in user_text.lower() for word in risky)

    def should_run_pre_output_safety(self, user_text: str) -> bool:
        sensitive = ["patch", "modify", "delete", "run code", "execute"]
        return any(word in user_text.lower() for word in sensitive)
