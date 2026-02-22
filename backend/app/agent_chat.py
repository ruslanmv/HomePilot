# backend/app/agent_chat.py
"""
Topology 3: Agent-Controlled tool use — core loop.

Additive module. Does NOT modify any existing endpoints or behavior.
The agent asks the main LLM to output strict JSON (final answer or tool call),
executes tools when requested, injects results, and loops until a final answer.

Tools available in v2:
  - vision.analyze   → uses existing multimodal.analyze_image(...)
  - knowledge.search → queries project RAG knowledge base (ChromaDB)
  - memory.recall    → retrieves long-term persona memory (Memory V2)
  - web.search       → performs web search with summarization
  - image.index      → indexes image into knowledge base via vision analysis (T4)
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .llm import chat as llm_chat
from .multimodal import analyze_image
from .storage import add_message, get_messages, get_recent
from .config import UPLOAD_DIR

# --- Safety limits (production-friendly defaults) ---
DEFAULT_MAX_TOOL_CALLS = 4
DEFAULT_HISTORY_LIMIT = 24

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

# --- Tool registry ---
# Maps tool_name -> (description_for_catalog, handler_coroutine_factory)
# Handlers are registered at module level; dispatch uses this dict.
TOOL_REGISTRY: Dict[str, str] = {}


def _register_tool(name: str, description: str) -> None:
    """Register a tool name + catalog description (handler lives as _run_<name>)."""
    TOOL_REGISTRY[name] = description


# Register all tools (catalog descriptions only — handlers are async functions below)
_register_tool(
    "vision.analyze",
    "vision.analyze(image_url, question, mode): analyzes an image and returns useful text.\n"
    "  mode is one of: caption | ocr | both",
)
_register_tool(
    "knowledge.search",
    "knowledge.search(query, n_results): searches the project's knowledge base for relevant documents.\n"
    "  query: text to search for. n_results: number of results (default 3, max 5).",
)
_register_tool(
    "memory.recall",
    "memory.recall(query): recalls long-term memories about the user (preferences, facts, boundaries).\n"
    "  query: topic or keyword to search memories for.",
)
_register_tool(
    "web.search",
    "web.search(query, max_results): searches the web for current information.\n"
    "  query: search query. max_results: number of results (default 3, max 5).",
)
_register_tool(
    "image.index",
    "image.index(image_url): indexes an image into the project knowledge base for future search.\n"
    "  Extracts visual description + text via vision analysis and stores it.\n"
    "  Use this when a user uploads an image and wants it searchable later.",
)
_register_tool(
    "memory.store",
    "memory.store(key, value, importance): stores a fact or preference about the user.\n"
    "  key: short label (e.g. 'favorite_color'). value: the fact. importance: 0.0-1.0 (default 0.5).\n"
    "  Use this when you learn something important the user would want remembered long-term.",
)


@dataclass
class AgentStepResult:
    type: str  # "final" | "tool_call"
    text: str = ""
    tool: str = ""
    args: Dict[str, Any] = field(default_factory=dict)


def _extract_json_obj(s: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extract the first JSON object from a model response.
    Returns None if parsing fails.
    """
    if not s:
        return None
    s = s.strip()
    # If the whole string is JSON, try directly first
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Fallback: find a JSON object substring
    m = _JSON_OBJ_RE.search(s)
    if not m:
        return None
    candidate = m.group(0)
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def _build_tool_catalog() -> str:
    """Build the tool catalog section of the system prompt from the registry."""
    lines = ["Tool catalog:"]
    for name, desc in TOOL_REGISTRY.items():
        lines.append(f"- {desc}")
    return "\n".join(lines)


def _build_agent_system_prompt(
    *,
    memory_context: str = "",
    knowledge_hint: str = "",
    user_context: str = "",
    session_context: str = "",
) -> str:
    """
    System prompt instructing the LLM to use a minimal JSON protocol.
    This avoids requiring full function-calling support and is easy to ship.

    Accepts optional context blocks that are injected into the prompt
    when available (additive, never destructive).
    """
    parts = [
        "You are an agent that can optionally call tools.\n",
        "You MUST reply with STRICT JSON ONLY (no markdown, no extra text).\n",
        "Allowed response shapes:\n"
        "1) Final answer:\n"
        '{ "type": "final", "text": "..." }\n',
        "2) Tool call (one at a time):\n"
        '{ "type": "tool_call", "tool": "<tool_name>", "args": { ... } }\n',
        _build_tool_catalog(),
        "\nRules:\n"
        "- Only call a tool if it is necessary to answer correctly.\n"
        "- If no image_url is available for vision.analyze, return a final answer asking the user to upload an image.\n"
        "- Use knowledge.search when the user asks about project documents or uploaded files.\n"
        "- Use memory.recall when you need to remember user preferences, facts, or boundaries.\n"
        "- Use memory.store when you learn an important fact about the user that should be remembered.\n"
        "- Use web.search when the user asks about current events or needs up-to-date information.\n"
        "- Keep tool calls minimal.\n",
    ]

    # Inject user context (profile, preferences, boundaries)
    if user_context:
        parts.append(f"\n--- USER CONTEXT ---\n{user_context}\n--- END USER CONTEXT ---\n")

    # Inject session continuity context
    if session_context:
        parts.append(f"\n{session_context}\n")

    # Inject memory context (from Memory V2) if available
    if memory_context:
        parts.append(f"\n--- PERSONA MEMORY ---\n{memory_context}\n--- END MEMORY ---\n")

    # Inject knowledge hint if available
    if knowledge_hint:
        parts.append(f"\n{knowledge_hint}\n")

    return "\n".join(parts)


def _find_last_image_url(conversation_id: str) -> Optional[str]:
    """
    Looks for the most recent message with media.images and returns its first image URL.
    Uses storage.get_messages which includes media.
    """
    try:
        msgs = get_messages(conversation_id, limit=200)
    except Exception:
        return None

    for m in reversed(msgs):
        media = m.get("media") or {}
        images = media.get("images") or []
        if images and isinstance(images, list):
            url = images[0]
            if isinstance(url, str) and url.strip():
                return url.strip()
    return None


def _format_tool_context(tool_name: str, tool_output: str, meta: Optional[Dict[str, Any]] = None) -> str:
    """
    Injected into the agent context after tool execution.
    """
    lines = [
        "TOOL_RESULT",
        f"tool={tool_name}",
        "output:",
        tool_output.strip() if tool_output else "(empty)",
    ]
    if meta:
        try:
            lines.append("meta:")
            lines.append(json.dumps(meta, ensure_ascii=False))
        except Exception:
            pass
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool handlers — each returns (output_text, meta_dict)
# ---------------------------------------------------------------------------

async def _run_vision_analyze(
    *,
    image_url: str,
    question: Optional[str],
    mode: str,
    provider: str,
    base_url: Optional[str],
    model: Optional[str],
    nsfw_mode: bool,
) -> Tuple[str, Dict[str, Any]]:
    """
    Execute the vision tool using existing multimodal module.
    Returns (analysis_text, full_result_json).
    """
    upload_path = Path(UPLOAD_DIR)
    res = await analyze_image(
        image_url=image_url,
        upload_path=upload_path,
        provider=provider,
        base_url=base_url,
        model=model,
        user_prompt=question,
        nsfw_mode=nsfw_mode,
        mode=mode or "both",
    )
    analysis = (res.get("analysis_text") or "").strip()
    if not analysis:
        analysis = "No analysis available."
    return analysis, res


async def _run_knowledge_search(
    *,
    query: str,
    project_id: Optional[str],
    n_results: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    """
    Search the project knowledge base (ChromaDB RAG).
    Wraps existing vectordb.query_project_knowledge().
    Returns (formatted_results_text, meta).
    """
    if not project_id:
        return "No project context available. Knowledge search requires a project.", {"error": "no_project"}

    try:
        from .vectordb import query_project_knowledge, get_project_document_count, CHROMADB_AVAILABLE
    except ImportError:
        return "Knowledge base is not available (ChromaDB not installed).", {"error": "chromadb_missing"}

    if not CHROMADB_AVAILABLE:
        return "Knowledge base is not available (ChromaDB not installed).", {"error": "chromadb_missing"}

    n_results = max(1, min(n_results, 5))

    try:
        doc_count = get_project_document_count(project_id)
        if doc_count == 0:
            return "No documents in this project's knowledge base. Upload files to enable knowledge search.", {
                "doc_count": 0,
            }

        results = query_project_knowledge(project_id, query, n_results=n_results)
        if not results:
            return f"No relevant results found for: {query}", {"doc_count": doc_count, "results_found": 0}

        lines = [f"Found {len(results)} relevant document chunks (out of {doc_count} total):"]
        for i, doc in enumerate(results, 1):
            source = doc.get("metadata", {}).get("source", "Unknown")
            content = doc.get("content", "")
            similarity = doc.get("similarity", 0.0)
            lines.append(f"\n[{i}] Source: {source} (relevance: {similarity:.2f})")
            lines.append(content[:500])

        return "\n".join(lines), {"doc_count": doc_count, "results_found": len(results)}

    except Exception as e:
        return f"Error searching knowledge base: {e}", {"error": str(e)}


async def _run_memory_recall(
    *,
    query: str,
    project_id: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """
    Recall long-term memories from Memory V2.
    Wraps existing memory_v2.MemoryV2Engine.build_context().
    Returns (memory_context_text, meta).
    """
    if not project_id:
        return "No project context available. Memory recall requires a project.", {"error": "no_project"}

    try:
        from .memory_v2 import get_memory_v2, ensure_v2_columns
    except ImportError:
        return "Memory V2 module is not available.", {"error": "memory_v2_missing"}

    try:
        ensure_v2_columns()
        engine = get_memory_v2()
        context = engine.build_context(project_id, query)
        if not context or not context.strip():
            return "No memories stored yet for this project.", {"memories_found": 0}

        return context, {"memories_found": context.count("  - ")}

    except Exception as e:
        return f"Error recalling memories: {e}", {"error": str(e)}


async def _run_web_search(
    *,
    query: str,
    max_results: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    """
    Perform web search using existing search module.
    Wraps existing search.web_search() + search.summarize_results().
    Returns (summary_text, meta).
    """
    try:
        from .search import web_search, summarize_results
    except ImportError:
        return "Web search module is not available.", {"error": "search_missing"}

    max_results = max(1, min(max_results, 5))

    try:
        results = await web_search(query, max_results=max_results)
        if not results:
            return f"No web results found for: {query}", {"results_found": 0}

        # Build compact output for agent context
        lines = [f"Web search results for: {query}"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            url = r.get("url", "")
            lines.append(f"\n[{i}] {title}")
            lines.append(f"    {snippet}")
            if url:
                lines.append(f"    URL: {url}")

        return "\n".join(lines), {"results_found": len(results)}

    except Exception as e:
        return f"Error performing web search: {e}", {"error": str(e)}


async def _run_image_index(
    *,
    image_url: str,
    project_id: Optional[str],
    provider: str,
    base_url: Optional[str],
    model: Optional[str],
    nsfw_mode: bool,
) -> Tuple[str, Dict[str, Any]]:
    """
    Index an image into the project knowledge base via vision analysis.
    Wraps vectordb_images.index_image_from_url().
    Returns (result_text, meta).
    """
    if not project_id:
        return "No project context available. Image indexing requires a project.", {"error": "no_project"}

    if not image_url:
        return "No image URL provided for indexing.", {"error": "no_image"}

    try:
        from .vectordb_images import index_image_from_url
    except ImportError:
        return "Image indexing module is not available.", {"error": "module_missing"}

    try:
        result = await index_image_from_url(
            project_id=project_id,
            image_url=image_url,
            provider=provider,
            base_url=base_url,
            model=model,
            nsfw_mode=nsfw_mode,
        )

        if result.get("ok"):
            chunks = result.get("chunks_added", 0)
            preview = result.get("analysis_preview", "")
            return (
                f"Image indexed successfully. {chunks} chunks added to knowledge base.\n"
                f"Content preview: {preview}"
            ), result
        else:
            return f"Image indexing failed: {result.get('error', 'unknown')}", result

    except Exception as e:
        return f"Error indexing image: {e}", {"error": str(e)}


async def _run_memory_store(
    *,
    key: str,
    value: str,
    importance: float,
    project_id: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """
    Store a fact/preference into Memory V2 as a semantic memory.
    Wraps memory_v2._upsert_memory().
    Returns (result_text, meta).
    """
    if not project_id:
        return "No project context available. Memory store requires a project.", {"error": "no_project"}

    if not key or not value:
        return "Both key and value are required to store a memory.", {"error": "missing_args"}

    try:
        from .memory_v2 import get_memory_v2, ensure_v2_columns, _upsert_memory
    except ImportError:
        return "Memory V2 module is not available.", {"error": "memory_v2_missing"}

    try:
        ensure_v2_columns()
        importance = max(0.0, min(1.0, importance))

        _upsert_memory(
            project_id=project_id,
            category="agent_learned",
            key=key.strip()[:100],
            value=value.strip()[:600],
            mem_type="S",
            source_type="inferred",
            confidence=0.8,
            strength=0.6,
            importance=importance,
        )

        return (
            f"Stored memory: '{key}' = '{value[:80]}{'...' if len(value) > 80 else ''}' (importance: {importance:.1f})"
        ), {"key": key, "importance": importance}

    except Exception as e:
        return f"Error storing memory: {e}", {"error": str(e)}


# ---------------------------------------------------------------------------
# Memory V2 context builder (injected into system prompt)
# ---------------------------------------------------------------------------

def _get_memory_context(project_id: Optional[str], query: str) -> str:
    """
    Build Memory V2 context for system prompt injection.
    Returns empty string if Memory V2 is unavailable or no memories exist.
    Non-blocking: failures return empty string.
    """
    if not project_id:
        return ""
    try:
        from .memory_v2 import get_memory_v2, ensure_v2_columns
        ensure_v2_columns()
        engine = get_memory_v2()
        ctx = engine.build_context(project_id, query)
        return (ctx or "").strip()
    except Exception:
        return ""


def _get_knowledge_hint(project_id: Optional[str]) -> str:
    """
    Build a short hint about available knowledge base docs.
    Helps the agent decide whether to call knowledge.search.
    """
    if not project_id:
        return ""
    try:
        from .vectordb import get_project_document_count, CHROMADB_AVAILABLE
        if not CHROMADB_AVAILABLE:
            return ""
        count = get_project_document_count(project_id)
        if count > 0:
            return f"[This project has {count} document chunks in its knowledge base. Use knowledge.search to find relevant information.]"
    except Exception:
        pass
    return ""


def _get_user_context(project_id: Optional[str], user_id: Optional[str] = None) -> str:
    """
    Build user context (profile + preferences) for agent system prompt.
    Uses per-user SQLite profile when user_id is available (Bearer auth),
    falls back to legacy profile.json for single-user/API-key mode.
    Returns empty string if unavailable.
    """
    if not project_id:
        return ""
    try:
        from .user_context import build_user_context_for_ai

        profile: dict = {}
        memory: dict = {}

        if user_id:
            # Per-user: read from SQLite user_profiles / user_memory_items tables
            try:
                from .user_profile_store import _get_user_profile, _get_db_path
                import sqlite3, json
                profile = _get_user_profile(user_id)
                # Read per-user memory items
                path = _get_db_path()
                con = sqlite3.connect(path)
                con.row_factory = sqlite3.Row
                cur = con.cursor()
                cur.execute(
                    "SELECT * FROM user_memory_items WHERE user_id = ? ORDER BY pinned DESC, importance DESC",
                    (user_id,),
                )
                rows = cur.fetchall()
                con.close()
                memory = {"items": [dict(r) for r in rows]}
            except Exception:
                # Table may not exist yet; fall through to legacy
                pass

        if not profile:
            # Legacy: read global profile.json / user_memory.json
            from .profile import read_profile
            from .user_memory import _read as read_memory
            profile = read_profile()
            memory = read_memory()

        if not profile.get("personalization_enabled", True):
            return ""
        ctx = build_user_context_for_ai(profile, memory, nsfw_mode=False)
        return (ctx or "").strip()
    except Exception:
        return ""


def _get_session_context(project_id: Optional[str]) -> str:
    """
    Build session awareness context for the agent.
    Shows active session info and last session summary.
    Returns empty string if no session data available.
    """
    if not project_id:
        return ""
    try:
        from .sessions import list_sessions, resolve_session
        active = resolve_session(project_id)
        if not active:
            return ""
        lines = []
        title = active.get("title", "Untitled")
        msg_count = active.get("message_count", 0)
        lines.append(f"[Active session: \"{title}\" ({msg_count} messages)]")

        # Include last ended session summary if available
        sessions = list_sessions(project_id, limit=3)
        for s in sessions:
            if s.get("ended_at") and s.get("summary"):
                lines.append(f"[Previous session summary: {s['summary'][:200]}]")
                break

        return "\n".join(lines)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Tool dispatch — generalized for N tools
# ---------------------------------------------------------------------------

async def _dispatch_tool(
    tool: str,
    args: Dict[str, Any],
    *,
    # Context passed through for tools that need it
    conversation_id: str,
    project_id: Optional[str],
    user_text: str,
    last_image_url: Optional[str],
    vision_provider: str,
    vision_base_url: Optional[str],
    vision_model: Optional[str],
    nsfw_mode: bool,
) -> Tuple[str, Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Dispatch a tool call to the appropriate handler.
    Returns (output_text, meta_dict, media_dict_or_none).
    """
    if tool == "vision.analyze":
        # Resolve image_url (tool may omit it; use last seen)
        image_url = (args.get("image_url") or "").strip() or (last_image_url or "")
        question = (args.get("question") or "").strip() or user_text
        mode = (args.get("mode") or "both").strip().lower()
        if mode not in ("caption", "ocr", "both"):
            mode = "both"

        if not image_url:
            return (
                "I don't have an image to analyze. Please upload an image first.",
                {"error": "no_image"},
                None,
            )

        try:
            text, full = await _run_vision_analyze(
                image_url=image_url,
                question=question,
                mode=mode,
                provider=vision_provider,
                base_url=vision_base_url,
                model=vision_model,
                nsfw_mode=nsfw_mode,
            )
        except FileNotFoundError:
            return (
                "Could not load the image — the file may no longer exist. Please upload it again.",
                {"error": "image_load_failed", "image_url": image_url},
                None,
            )
        return text, {"image_url": image_url, "mode": mode}, {"images": [image_url]}

    elif tool == "knowledge.search":
        query = (args.get("query") or "").strip() or user_text
        n_results = int(args.get("n_results", 3))
        text, meta = await _run_knowledge_search(
            query=query,
            project_id=project_id,
            n_results=n_results,
        )
        return text, meta, None

    elif tool == "memory.recall":
        query = (args.get("query") or "").strip() or user_text
        text, meta = await _run_memory_recall(
            query=query,
            project_id=project_id,
        )
        return text, meta, None

    elif tool == "web.search":
        query = (args.get("query") or "").strip() or user_text
        max_results = int(args.get("max_results", 3))
        text, meta = await _run_web_search(
            query=query,
            max_results=max_results,
        )
        return text, meta, None

    elif tool == "image.index":
        image_url = (args.get("image_url") or "").strip() or (last_image_url or "")
        if not image_url:
            return (
                "No image URL provided. Please specify an image to index.",
                {"error": "no_image"},
                None,
            )
        text, meta = await _run_image_index(
            image_url=image_url,
            project_id=project_id,
            provider=vision_provider,
            base_url=vision_base_url,
            model=vision_model,
            nsfw_mode=nsfw_mode,
        )
        return text, meta, {"images": [image_url]}

    elif tool == "memory.store":
        key = (args.get("key") or "").strip()
        value = (args.get("value") or "").strip()
        importance = float(args.get("importance", 0.5))
        text, meta = await _run_memory_store(
            key=key,
            value=value,
            importance=importance,
            project_id=project_id,
        )
        return text, meta, None

    else:
        return f"Requested tool '{tool}' is not available.", {"error": "unknown_tool"}, None


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def agent_chat(
    *,
    user_text: str,
    conversation_id: Optional[str],
    project_id: Optional[str],
    # main LLM settings
    llm_provider: str,
    llm_base_url: Optional[str],
    llm_model: Optional[str],
    temperature: float,
    max_tokens: int,
    # multimodal settings (vision tool)
    vision_provider: str,
    vision_base_url: Optional[str],
    vision_model: Optional[str],
    nsfw_mode: bool,
    # agent controls
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    # per-user isolation
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Topology 3: Agent-Controlled tool use.
    Additive-only. Does not change /chat.
    """

    cid = conversation_id or str(uuid.uuid4())
    text_in = (user_text or "").strip()

    # Persist the user message (same as existing behavior)
    if text_in:
        add_message(cid, "user", text_in, media=None, project_id=project_id)

    # Ingest user text into Memory V2 (additive, non-blocking)
    if text_in and project_id:
        try:
            from .memory_v2 import get_memory_v2, ensure_v2_columns
            ensure_v2_columns()
            get_memory_v2().ingest_user_text(project_id, text_in, user_id=user_id)
        except Exception:
            pass  # Non-fatal: Memory V2 is optional

    # Pull recent history for context (role/content only)
    history_pairs: List[Tuple[str, str]] = []
    try:
        history_pairs = get_recent(cid, limit=history_limit)
    except Exception:
        history_pairs = []

    # Build enriched system prompt with all context layers
    memory_ctx = _get_memory_context(project_id, text_in)
    knowledge_hint = _get_knowledge_hint(project_id)
    user_ctx = _get_user_context(project_id, user_id=user_id)
    session_ctx = _get_session_context(project_id)

    # Convert to chat messages for LLM
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _build_agent_system_prompt(
            memory_context=memory_ctx,
            knowledge_hint=knowledge_hint,
            user_context=user_ctx,
            session_context=session_ctx,
        )}
    ]

    # Include history (excluding current user message if it was just stored, but that's ok either way)
    for role, content in history_pairs[-history_limit:]:
        if role in ("system", "user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Ensure current user prompt is last
    if text_in:
        messages.append({"role": "user", "content": text_in})

    tool_calls_used = 0
    tools_invoked: List[str] = []
    last_image_url = _find_last_image_url(cid)  # used as fallback if tool call lacks image_url

    # --- Agent loop (simple, safe) ---
    while True:
        # Ask LLM for either FINAL or TOOL_CALL
        llm_res = await llm_chat(
            messages,
            provider=llm_provider,
            base_url=llm_base_url,
            model=llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # Normalize output text
        raw_text = ""
        if isinstance(llm_res, dict):
            # Most providers return OpenAI-like choices; llm.py returns provider-style dict.
            raw_text = (llm_res.get("text") or llm_res.get("content") or "").strip()
            if not raw_text and "choices" in llm_res:
                try:
                    raw_text = llm_res["choices"][0]["message"]["content"].strip()
                except Exception:
                    pass

        parsed = _extract_json_obj(raw_text)
        if not parsed:
            # Fallback: treat as final text to avoid agent deadlock
            final_text = raw_text or "I couldn't parse the agent response. Please try again."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used, "tools_invoked": tools_invoked}}

        step_type = (parsed.get("type") or "").strip().lower()

        if step_type == "final":
            final_text = (parsed.get("text") or "").strip()
            if not final_text:
                final_text = "No answer provided."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used, "tools_invoked": tools_invoked}}

        if step_type != "tool_call":
            # Unknown response type → safe fallback
            final_text = (parsed.get("text") or "").strip() or raw_text or "I couldn't complete the request."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used, "tools_invoked": tools_invoked}}

        # TOOL_CALL
        if tool_calls_used >= max_tool_calls:
            final_text = "I reached the maximum number of tool calls for this request. Please refine your question."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used, "tools_invoked": tools_invoked}}

        tool = (parsed.get("tool") or "").strip()
        args = parsed.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        # Validate tool exists in registry
        if tool not in TOOL_REGISTRY:
            final_text = f"Requested tool '{tool}' is not available. Available tools: {', '.join(TOOL_REGISTRY.keys())}"
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used, "tools_invoked": tools_invoked}}

        # Dispatch tool
        tool_calls_used += 1
        tools_invoked.append(tool)

        output_text, meta, media = await _dispatch_tool(
            tool,
            args,
            conversation_id=cid,
            project_id=project_id,
            user_text=text_in,
            last_image_url=last_image_url,
            vision_provider=vision_provider,
            vision_base_url=vision_base_url,
            vision_model=vision_model,
            nsfw_mode=nsfw_mode,
        )

        # Check if dispatch returned an error that should terminate
        if meta.get("error") in ("no_image", "unknown_tool"):
            add_message(cid, "assistant", output_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": output_text, "media": None, "agent": {"tool_calls_used": tool_calls_used, "tools_invoked": tools_invoked}}

        # Persist tool artifact in history
        tool_label = {
            "vision.analyze": "Image Analysis",
            "knowledge.search": "Knowledge Search",
            "memory.recall": "Memory Recall",
            "web.search": "Web Search",
            "image.index": "Image Indexed",
            "memory.store": "Memory Stored",
        }.get(tool, tool)

        add_message(
            cid,
            "assistant",
            f"[{tool_label}]\n{output_text}",
            media=media,
            project_id=project_id,
        )

        # Inject tool result for the next reasoning step
        tool_ctx = _format_tool_context(tool, output_text, meta=meta)
        messages.append({"role": "system", "content": tool_ctx})

        # Continue loop for final response
