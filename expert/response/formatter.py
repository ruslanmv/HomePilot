class Formatter:
    def format_tool_section(self, tool_results: list) -> str:
        if not tool_results:
            return ""
        lines = ["\nSources and tool outputs:"]
        for item in tool_results:
            status = "ok" if item.ok else "error"
            lines.append(f"- {item.tool_name}: {status}")
        return "\n".join(lines)
