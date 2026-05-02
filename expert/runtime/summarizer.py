from typing import List
from expert.types import Message


class Summarizer:
    def summarize(self, messages: List[Message]) -> str:
        if not messages:
            return ""
        last = messages[-6:]
        joined = " | ".join(f"{m.role}: {m.content[:80]}" for m in last)
        return f"Recent conversation summary: {joined[:800]}"
