def choose_tool_hints(user_text: str, has_workspace: bool) -> list[str]:
    q = user_text.lower()
    hints: list[str] = []

    if any(k in q for k in ["latest", "current", "today", "news"]):
        hints.append("hp.web.search")

    if any(k in q for k in ["internal docs", "knowledge base", "design doc", "retrieval"]):
        hints.append("hp.doc.query")

    workspace_intent = any(k in q for k in ["zip", "repo", "project", "file", "search", "class", "function", "symbol"])
    if (has_workspace or workspace_intent) and workspace_intent:
        hints.append("hp.ws.search")

    if has_workspace and any(k in q for k in ["read lines", "read range", "show lines", "open file"]):
        hints.append("hp.ws.read_range")

    if has_workspace and any(k in q for k in ["replace", "patch", "modify", "rewrite", "update file"]):
        hints.append("hp.ws.replace_range")

    if any(k in q for k in ["calculate", "run code", "execute", "python", "test snippet"]):
        hints.append("hp.code.run")

    if any(k in q for k in ["citation", "verify source", "verify citations"]):
        hints.append("hp.citation.verify")

    return hints
