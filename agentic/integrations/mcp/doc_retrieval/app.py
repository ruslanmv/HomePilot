from __future__ import annotations

from typing import Any, Dict

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app


_STORE: Dict[str, Dict[str, Any]] = {}


def _as_content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def retrieval_index(args: dict) -> dict:
    document_id = str(args.get("document_id", "")).strip()
    text = str(args.get("text", "")).strip()
    metadata = args.get("metadata") or {}
    if not document_id or not text:
        return _as_content("Missing required fields: document_id, text", ok=False)
    _STORE[document_id] = {"text": text, "metadata": metadata}
    return _as_content(f"Indexed {document_id}", ok=True, document_id=document_id)


async def retrieval_query(args: dict) -> dict:
    query = str(args.get("text", "")).strip()
    top_k = max(1, min(int(args.get("top_k", 5) or 5), 20))
    if not query:
        return _as_content("Missing required field: text", ok=False)

    items = []
    for doc_id, payload in _STORE.items():
        body = str(payload.get("text", ""))
        score = 1.0 if query.lower() in body.lower() else 0.5
        items.append(
            {
                "document_id": doc_id,
                "text": body[:500],
                "metadata": payload.get("metadata", {}),
                "score": score,
            }
        )

    items.sort(key=lambda x: x["score"], reverse=True)
    results = items[:top_k]
    return _as_content(f"Retrieved {len(results)} results for '{query}'", ok=True, results=results)


async def retrieval_delete(args: dict) -> dict:
    document_id = str(args.get("document_id", "")).strip()
    if not document_id:
        return _as_content("Missing required field: document_id", ok=False)
    existed = document_id in _STORE
    _STORE.pop(document_id, None)
    return _as_content(f"Deleted {document_id}" if existed else f"Not found: {document_id}", ok=existed, document_id=document_id)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="hp.doc.index",
            description="Index a document into retrieval memory",
            input_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "text": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["document_id", "text"],
            },
            handler=retrieval_index,
        ),
        ToolDef(
            name="hp.doc.query",
            description="Retrieve relevant docs by text query",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5},
                    "filters": {"type": "object"},
                },
                "required": ["text"],
            },
            handler=retrieval_query,
        ),
        ToolDef(
            name="hp.doc.delete",
            description="Delete indexed document by id",
            input_schema={
                "type": "object",
                "properties": {"document_id": {"type": "string"}},
                "required": ["document_id"],
            },
            handler=retrieval_delete,
        ),
    ]


app = create_mcp_app(server_name="mcp-doc-retrieval", tools=register_tools())
