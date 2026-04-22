class AssistantPolicy:
    READ_ONLY_KEYWORDS = [
        "find", "search", "read", "analyze", "compare", "list", "explain"
    ]
    WRITE_KEYWORDS = [
        "replace", "patch", "modify", "delete", "write", "update", "rewrite"
    ]

    def classify_request(self, user_text: str) -> str:
        q = user_text.lower()
        if any(k in q for k in self.WRITE_KEYWORDS):
            return "write"
        if any(k in q for k in self.READ_ONLY_KEYWORDS):
            return "read"
        return "general"

    def should_prefer_tools(self, user_text: str) -> bool:
        q = user_text.lower()
        keywords = [
            "zip", "repo", "project", "file", "search", "latest", "current",
            "run code", "calculate", "internal docs", "knowledge base"
        ]
        return any(k in q for k in keywords)

    def can_answer_directly(self, user_text: str) -> bool:
        return not self.should_prefer_tools(user_text)
