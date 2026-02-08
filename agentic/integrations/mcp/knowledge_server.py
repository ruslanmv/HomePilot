from __future__ import annotations

from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app


def _text(content: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": content}]}


async def hp_search_workspace(query: str, scope: str = "all", limit: int = 10) -> Dict[str, Any]:
    # Reference-only: returns deterministic dummy results.
    results = []
    for i in range(min(limit, 5)):
        results.append(
            {
                "title": f"Result {i+1} for '{query}'",
                "snippet": f"This is a placeholder snippet from scope '{scope}'.",
                "source_type": "doc",
                "source_id": f"doc-{i+1}",
                "confidence": 0.65,
            }
        )
    return {"results": results}


async def hp_get_document(doc_id: str, include_text: bool = True) -> Dict[str, Any]:
    return {
        "doc_id": doc_id,
        "title": f"Document {doc_id}",
        "text": "Placeholder document text." if include_text else None,
        "mime_type": "text/plain",
    }


async def hp_answer_with_sources(question: str, context_ids: List[str] | None = None, max_sources: int = 6) -> Dict[str, Any]:
    context_ids = context_ids or []
    sources = context_ids[: max_sources] or ["doc-1", "doc-2"]
    return {
        "answer": f"Placeholder grounded answer to: {question}",
        "sources": [{"source_id": s, "quote": "Placeholder quote."} for s in sources],
    }


async def hp_summarize_project(project_id: str, style: str = "brief") -> Dict[str, Any]:
    return _text(f"[{style}] Placeholder summary for project '{project_id}'.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.search_workspace",
        description="Search across projects, docs, and notes.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "scope": {"type": "string", "enum": ["project", "docs", "all"], "default": "all"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
        handler=lambda args: hp_search_workspace(**args),
    ),
    ToolDef(
        name="hp.get_document",
        description="Fetch a document by id.",
        input_schema={
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "include_text": {"type": "boolean", "default": True},
            },
            "required": ["doc_id"],
        },
        handler=lambda args: hp_get_document(**args),
    ),
    ToolDef(
        name="hp.answer_with_sources",
        description="Answer a question using sources and return citations.",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "context_ids": {"type": "array", "items": {"type": "string"}},
                "max_sources": {"type": "integer", "default": 6, "minimum": 1, "maximum": 12},
            },
            "required": ["question"],
        },
        handler=lambda args: hp_answer_with_sources(**args),
    ),
    ToolDef(
        name="hp.summarize_project",
        description="Summarize project state.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "style": {"type": "string", "enum": ["brief", "detailed"], "default": "brief"},
            },
            "required": ["project_id"],
        },
        handler=lambda args: hp_summarize_project(**args),
    ),
]


app = create_mcp_app(server_name="homepilot-knowledge", tools=TOOLS)
