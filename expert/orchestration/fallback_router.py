class FallbackRouter:
    def pick_fallback(self, failed_tool: str) -> str | None:
        if failed_tool == "hp.ws.search":
            return "hp.doc.query"
        if failed_tool == "hp.web.search":
            return None
        if failed_tool == "hp.code.run":
            return None
        return None
