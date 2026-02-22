# backend/app/agent_chat.py
"""
Topology 3: Agent-Controlled tool use — core loop.

Additive module. Does NOT modify any existing endpoints or behavior.
The agent asks the main LLM to output strict JSON (final answer or tool call),
executes tools when requested, injects results, and loops until a final answer.

Tools available in v1:
  - vision.analyze  → uses existing multimodal.analyze_image(...)
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
DEFAULT_MAX_TOOL_CALLS = 2
DEFAULT_HISTORY_LIMIT = 24

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


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


def _build_agent_system_prompt() -> str:
    """
    System prompt instructing the LLM to use a minimal JSON protocol.
    This avoids requiring full function-calling support and is easy to ship.
    """
    return (
        "You are an agent that can optionally call tools.\n"
        "\n"
        "You MUST reply with STRICT JSON ONLY (no markdown, no extra text).\n"
        "\n"
        "Allowed response shapes:\n"
        "1) Final answer:\n"
        '{ "type": "final", "text": "..." }\n'
        "\n"
        "2) Tool call (one at a time):\n"
        '{ "type": "tool_call", "tool": "vision.analyze", "args": { "image_url": "...", "question": "...", "mode": "both" } }\n'
        "\n"
        "Tool catalog:\n"
        "- vision.analyze(image_url, question, mode): analyzes an image and returns useful text.\n"
        "  mode is one of: caption | ocr | both\n"
        "\n"
        "Rules:\n"
        "- Only call a tool if it is necessary to answer correctly.\n"
        "- If no image_url is available, return a final answer asking the user to upload an image.\n"
        "- Keep tool calls minimal.\n"
    )


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

    # Pull recent history for context (role/content only)
    history_pairs: List[Tuple[str, str]] = []
    try:
        history_pairs = get_recent(cid, limit=history_limit)
    except Exception:
        history_pairs = []

    # Convert to chat messages for LLM
    messages: List[Dict[str, Any]] = [{"role": "system", "content": _build_agent_system_prompt()}]

    # Include history (excluding current user message if it was just stored, but that's ok either way)
    for role, content in history_pairs[-history_limit:]:
        if role in ("system", "user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # Ensure current user prompt is last
    if text_in:
        messages.append({"role": "user", "content": text_in})

    tool_calls_used = 0
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
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used}}

        step_type = (parsed.get("type") or "").strip().lower()

        if step_type == "final":
            final_text = (parsed.get("text") or "").strip()
            if not final_text:
                final_text = "No answer provided."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used}}

        if step_type != "tool_call":
            # Unknown response type → safe fallback
            final_text = (parsed.get("text") or "").strip() or raw_text or "I couldn't complete the request."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used}}

        # TOOL_CALL
        if tool_calls_used >= max_tool_calls:
            final_text = "I reached the maximum number of tool calls for this request. Please refine your question."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used}}

        tool = (parsed.get("tool") or "").strip()
        args = parsed.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        if tool != "vision.analyze":
            final_text = f"Requested tool '{tool}' is not available."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used}}

        # Resolve image_url (tool may omit it; use last seen)
        image_url = (args.get("image_url") or "").strip() or (last_image_url or "")
        question = (args.get("question") or "").strip() or text_in
        mode = (args.get("mode") or "both").strip().lower()
        if mode not in ("caption", "ocr", "both"):
            mode = "both"

        if not image_url:
            final_text = "I don't have an image to analyze. Please upload an image first."
            add_message(cid, "assistant", final_text, media=None, project_id=project_id)
            return {"conversation_id": cid, "text": final_text, "media": None, "agent": {"tool_calls_used": tool_calls_used}}

        # Execute the vision tool
        tool_calls_used += 1
        analysis_text, full = await _run_vision_analyze(
            image_url=image_url,
            question=question,
            mode=mode,
            provider=vision_provider,
            base_url=vision_base_url,
            model=vision_model,
            nsfw_mode=nsfw_mode,
        )

        # Persist tool artifact in history (consistent with existing multimodal)
        add_message(
            cid,
            "assistant",
            f"[Image Analysis]\n{analysis_text}",
            media={"images": [image_url]},
            project_id=project_id,
        )

        # Inject tool result for the next reasoning step
        tool_ctx = _format_tool_context("vision.analyze", analysis_text, meta={"image_url": image_url, "mode": mode})
        messages.append({"role": "system", "content": tool_ctx})

        # Continue loop for final response
