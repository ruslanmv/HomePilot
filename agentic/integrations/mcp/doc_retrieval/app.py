from __future__ import annotations

import uuid

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

_DOCS: dict[str, dict] = {}


def _content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def doc_index(args: dict) -> dict:
    text = str(args.get("text", "")).strip()
    title = str(args.get("title", "untitled")).strip()
    if not text:
        return _content("Missing required field: text", ok=False)
    doc_id = str(args.get("doc_id") or uuid.uuid4())
    _DOCS[doc_id] = {"doc_id": doc_id, "title": title, "text": text}
    return _content(f"Indexed document {doc_id}", ok=True, doc_id=doc_id)


async def doc_query(args: dict) -> dict:
    q = str(args.get("text", "")).strip().lower()
    top_k = max(1, min(int(args.get("top_k", 5) or 5), 25))
    if not q:
        return _content("Missing required field: text", ok=False)

    ranked = []
    for doc in _DOCS.values():
        hay = f"{doc['title']}\n{doc['text']}".lower()
        score = hay.count(q)
        if score > 0:
            ranked.append((score, doc))

    ranked.sort(key=lambda item: item[0], reverse=True)
    matches = [doc for _, doc in ranked[:top_k]]
    lines = [f"Found {len(matches)} documents for '{q}'."]
    for idx, doc in enumerate(matches, start=1):
        lines.append(f"{idx}. {doc['title']} ({doc['doc_id']})")

    return _content("\n".join(lines), ok=True, matches=matches)


async def doc_delete(args: dict) -> dict:
    doc_id = str(args.get("doc_id", "")).strip()
    if not doc_id:
        return _content("Missing required field: doc_id", ok=False)
    removed = _DOCS.pop(doc_id, None) is not None
    return _content(f"Deleted={removed} for {doc_id}", ok=True, deleted=removed)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef("hp.doc.index", "Index document chunks", {"type": "object", "properties": {"doc_id": {"type": "string"}, "title": {"type": "string"}, "text": {"type": "string"}}, "required": ["text"]}, doc_index),
        ToolDef("hp.doc.query", "Hybrid retrieval query", {"type": "object", "properties": {"text": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["text"]}, doc_query),
        ToolDef("hp.doc.delete", "Delete document", {"type": "object", "properties": {"doc_id": {"type": "string"}}, "required": ["doc_id"]}, doc_delete),
    ]


app = create_mcp_app(server_name="mcp-doc-retrieval", tools=register_tools())
