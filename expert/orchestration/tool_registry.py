from dataclasses import dataclass
from expert.settings import settings


@dataclass
class ToolMeta:
    name: str
    server_url: str
    description: str


def build_registry() -> dict[str, ToolMeta]:
    return {
        "hp.web.search": ToolMeta(
            name="hp.web.search",
            server_url=settings.mcp_web_search_url,
            description="Search the web for current information.",
        ),
        "hp.doc.query": ToolMeta(
            name="hp.doc.query",
            server_url=settings.mcp_doc_retrieval_url,
            description="Query internal document retrieval.",
        ),
        "hp.ws.search": ToolMeta(
            name="hp.ws.search",
            server_url=settings.mcp_archive_workspace_url,
            description="Search files in uploaded workspace/archive.",
        ),
        "hp.ws.read_range": ToolMeta(
            name="hp.ws.read_range",
            server_url=settings.mcp_archive_workspace_url,
            description="Read a small line range from a file.",
        ),
        "hp.code.run": ToolMeta(
            name="hp.code.run",
            server_url=settings.mcp_code_sandbox_url,
            description="Run safe sandboxed code.",
        ),
        "hp.citation.verify": ToolMeta(
            name="hp.citation.verify",
            server_url=settings.mcp_citation_url,
            description="Verify citations against claims.",
        ),
        "hp.memory.append": ToolMeta(
            name="hp.memory.append",
            server_url=settings.mcp_memory_url,
            description="Store durable memory.",
        ),
        "hp.safety.check_output": ToolMeta(
            name="hp.safety.check_output",
            server_url=settings.mcp_safety_url,
            description="Check outgoing answer safety.",
        ),
    }
