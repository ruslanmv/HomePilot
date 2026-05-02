class SelfCheck:
    def review(self, answer: str, tool_results: list) -> list[str]:
        issues: list[str] = []

        if len(answer.strip()) < 30:
            issues.append("Answer is too short.")

        if tool_results and "Citations:" not in answer:
            issues.append("Grounded answer is missing citation section.")

        for r in tool_results:
            if not r.ok:
                issues.append(f"Tool failed: {r.tool_name}")

        return issues
