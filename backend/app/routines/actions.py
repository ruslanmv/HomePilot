"""Safe, read-only action preparation for HomePilot routines.

Actions gather current information and build a prompt. The actual response is
still generated through HomePilot's existing assistant/project/persona chat
pipelines so routine output inherits the same identity and context as a normal
conversation.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from ..agentic.client import ContextForgeClient
from ..langgraph_personas.workflows.secretary import SECRETARY_DAILY_BRIEFING


class RoutineActionError(RuntimeError):
    pass


def _forge_client() -> ContextForgeClient:
    return ContextForgeClient(
        base_url=os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444"),
        token=os.getenv("CONTEXT_FORGE_TOKEN", ""),
        auth_user=os.getenv("CONTEXT_FORGE_AUTH_USER", "admin"),
        auth_pass=os.getenv("CONTEXT_FORGE_AUTH_PASS", "changeme"),
    )


def _tool_payload(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception:
        return str(result)


def _source_urls(text: str, limit: int = 12) -> List[Dict[str, str]]:
    urls: List[Dict[str, str]] = []
    seen: set[str] = set()
    for url in re.findall(r"https?://[^\s\]\[)>,\"']+", text or ""):
        cleaned = url.rstrip(".,;:")
        if cleaned in seen:
            continue
        seen.add(cleaned)
        urls.append({"name": cleaned.split("/")[2], "url": cleaned})
        if len(urls) >= limit:
            break
    return urls


async def _invoke_current_information(
    *,
    query: str,
    max_items: int,
    prefer_news: bool = False,
) -> Dict[str, Any]:
    client = _forge_client()

    if prefer_news:
        news_result = await client.invoke_tool(
            "news.top",
            {"limit": max_items},
            timeout=20.0,
        )
        if not news_result.get("error"):
            text = _tool_payload(news_result)
            return {
                "provider": "hp-news",
                "raw": text,
                "sources": _source_urls(text),
            }

    web_result = await client.invoke_tool(
        "hp.web.search",
        {
            "query": query,
            "limit": max_items,
            "top_k": max_items,
            "recency_days": 1,
        },
        timeout=25.0,
    )
    if not web_result.get("error"):
        text = _tool_payload(web_result)
        return {
            "provider": "hp.web.search",
            "raw": text,
            "sources": _source_urls(text),
        }

    raise RoutineActionError(
        "Current-information tools are unavailable. Start hp-news or the HomePilot web-search MCP server."
    )


async def prepare_action(routine: Dict[str, Any]) -> Dict[str, Any]:
    action = routine.get("action") or {}
    action_type = str(action.get("type") or "")
    params = action.get("parameters") or {}
    timezone_name = str(routine.get("timezone") or "UTC")

    if action_type == "news_digest":
        max_items = max(1, min(int(params.get("max_items") or 6), 12))
        scope = params.get("scope") or ["local", "national", "world"]
        if not isinstance(scope, list):
            scope = [str(scope)]
        location = str(params.get("location") or "").strip()
        query_bits = ["today's most important news"]
        if location:
            query_bits.append(f"for {location}")
        if scope:
            query_bits.append("covering " + ", ".join(str(item) for item in scope))
        current = await _invoke_current_information(
            query=" ".join(query_bits),
            max_items=max_items,
            prefer_news=True,
        )
        prompt = (
            "Prepare today's news briefing from the CURRENT INFORMATION below. "
            "Do not invent facts that are not present. Deduplicate repeated stories, "
            "prioritize fresh and important items, and sound natural rather than reading "
            "a list of search results. If local information is present, lead with it. "
            f"The user's timezone is {timezone_name}. Include at most {max_items} stories.\n\n"
            f"CURRENT INFORMATION ({current['provider']}):\n{current['raw'][:16000]}"
        )
        return {
            "prompt": prompt,
            "sources": current["sources"],
            "provider": current["provider"],
        }

    if action_type == "daily_briefing":
        workflow = SECRETARY_DAILY_BRIEFING
        current = await _invoke_current_information(
            query="today weather news headlines",
            max_items=5,
            prefer_news=False,
        )
        step_hints = "\n".join(
            f"- {step.prompt_hint}" for step in workflow.steps if step.prompt_hint
        )
        prompt = (
            f"Run the '{workflow.display_name}' routine. Follow these existing Secretary workflow hints:\n"
            f"{step_hints}\n\n"
            "Use the current information below only where relevant. Keep the briefing concise, "
            "warm, and useful. Do not claim access to calendar/email data unless it is actually "
            "present in the supplied context or project/persona memory.\n\n"
            f"CURRENT INFORMATION ({current['provider']}):\n{current['raw'][:12000]}"
        )
        return {
            "prompt": prompt,
            "sources": current["sources"],
            "provider": current["provider"],
        }

    if action_type == "reminder":
        message = str(params.get("message") or "").strip()
        if not message:
            raise RoutineActionError("Reminder routine has no message.")
        return {
            "prompt": (
                "Deliver this reminder to the user now. Keep it short and natural. "
                f"Reminder: {message}"
            ),
            "sources": [],
            "provider": "local",
        }

    if action_type == "assistant_prompt":
        prompt = str(params.get("prompt") or "").strip()
        if not prompt:
            raise RoutineActionError("Assistant prompt routine has no prompt.")
        return {"prompt": prompt, "sources": [], "provider": "local"}

    raise RoutineActionError(f"Unsupported routine action: {action_type or 'unknown'}")
