class Repair:
    def fix(self, answer: str, issues: list[str]) -> str:
        if not issues:
            return answer
        suffix = "\n\nQuality notes:\n" + "\n".join(f"- {issue}" for issue in issues)
        return answer + suffix
