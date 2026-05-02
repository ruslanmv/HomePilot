class CitationInserter:
    def insert(self, text: str, tool_results: list) -> str:
        supporting = [r.tool_name for r in tool_results if r.ok]
        if not supporting:
            return text
        return text + "\n\nCitations: " + ", ".join(supporting)
