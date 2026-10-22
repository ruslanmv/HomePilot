"""A project's context for Expert: its instructions in the system prompt, its documents as a
tool.

When Expert runs inside HomePilot (the usual case: the package is mounted as ``app.expert``),
the project's documents are searched through the backend's own retrieval — the same
``query_project_knowledge`` the standard chat uses — so Expert in a project sees what the
standard chat sees. As a standalone service that retrieval is out of reach, and the tool is
simply not offered; the instructions still apply.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from .config import EXPERT_SYSTEM_PROMPT
from .tools import LocalTool, ToolOutcome, ToolSpec

logger = logging.getLogger("expert.project")

PROJECT_TOOL = "project_search"
PROJECT_TOOL_NATIVE = "hp.project.search"


def project_system_prompt(base: Optional[str], project: Optional[Dict[str, Any]]) -> Optional[str]:
    """The system prompt with the project folded in; ``base`` (or the Expert default) alone
    when there is no project."""
    if not project or not (project.get("name") or project.get("instructions")):
        return base
    name = str(project.get("name") or "this project").strip()
    lines = [base or EXPERT_SYSTEM_PROMPT, "", f"You are working inside the project “{name}”."]
    instructions = str(project.get("instructions") or "").strip()
    if instructions:
        lines += ["Project instructions:", instructions]
    if int(project.get("document_count") or 0) > 0:
        lines.append(
            f"The project has documents; the {PROJECT_TOOL} tool searches them. Prefer what they say over "
            "general knowledge and name the document you used."
        )
    return "\n".join(lines)


def _retrieval() -> Optional[Callable[..., List[Dict[str, Any]]]]:
    """The backend's project retrieval, when this Expert runs inside HomePilot."""
    try:
        from ..vectordb import query_project_knowledge  # type: ignore[import-not-found]
        return query_project_knowledge
    except Exception:  # noqa: BLE001  — standalone Expert, or RAG disabled
        return None


def render_passages(docs: List[Dict[str, Any]]) -> str:
    """Retrieved chunks grouped per document, numbered, the way the standard chat renders them."""
    grouped: Dict[str, List[str]] = {}
    for doc in docs or []:
        if not isinstance(doc, dict):
            continue
        source = str((doc.get("metadata") or {}).get("source") or "Unknown")
        grouped.setdefault(source, []).append(str(doc.get("content") or ""))
    if not grouped:
        return "No matching passages in the project's documents."
    parts = []
    for i, (source, chunks) in enumerate(grouped.items(), 1):
        parts.append(f"[Document {i}: {source}]\n" + "\n...\n".join(c.strip() for c in chunks if c.strip()))
    return "\n\n".join(parts)


def project_tool(project: Optional[Dict[str, Any]], retrieval: Optional[Callable[..., Any]] = None) -> Optional[LocalTool]:
    """The ``project_search`` tool for ``project``, or None when the project has no documents or
    retrieval is not reachable from this process."""
    if not project or not project.get("id") or int(project.get("document_count") or 0) <= 0:
        return None
    search = retrieval or _retrieval()
    if search is None:
        return None
    project_id = str(project["id"])
    name = str(project.get("name") or "the project")

    async def handler(arguments: Dict[str, Any]) -> ToolOutcome:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolOutcome(name=PROJECT_TOOL, ok=False, error="query is required")
        limit = max(1, min(int(arguments.get("limit") or 5), 10))
        docs = await asyncio.to_thread(search, project_id, query, limit)
        docs = list(docs or [])
        sources = {str((d.get("metadata") or {}).get("source") or "Unknown") for d in docs if isinstance(d, dict)}
        text = render_passages(docs)
        return ToolOutcome(
            name=PROJECT_TOOL, ok=True, text=text,
            data={"project_id": project_id, "passages": len(docs), "documents": sorted(sources)},
        )

    spec = ToolSpec(
        name=PROJECT_TOOL,
        native=PROJECT_TOOL_NATIVE,
        description=f"Search the documents of the project “{name}” for passages relevant to a query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for in the project's documents"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
        server="local",
    )
    return LocalTool(spec=spec, handler=handler)
