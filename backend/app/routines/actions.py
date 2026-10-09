"""Safe, read-only action preparation for HomePilot routines.

Actions gather current information and build the **task the assistant performs**. The
response is still generated through HomePilot's existing assistant/project/persona chat
pipelines, so routine output inherits the same identity and context as a normal
conversation.

── A routine is something HomePilot does, not something the user said ──────────────────

Each action returns an ``instruction``: an imperative task, addressed to the assistant.
It is deliberately *not* phrased as the user speaking.

That distinction used to be lost at the last step. These functions returned a first-person
line — ``"Prepare my morning news briefing for today."`` — and the executor handed it to the
chat pipeline as the user's message, so every routine opened its conversation with a
sentence the user never typed, over their name. Nothing downstream could tell it from a real
request: not the reader, not search, not memory, not a later summary of that thread.

So the phrasing here is imperative ("Prepare today's news briefing…") and
:mod:`..routines.service` stores it as a ``system`` turn. The model reads the same words
either way; only the attribution changes, and the attribution is the part that was wrong.
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


async def _invoke_named_tool(
    client: ContextForgeClient,
    name: str,
    args: Dict[str, Any],
    *,
    timeout: float,
) -> Any:
    """Invoke a Forge tool by stable name, resolving generated IDs if needed."""
    result = await client.invoke_tool(name, args, timeout=timeout)
    if not (isinstance(result, dict) and result.get("error")):
        return result

    try:
        tools = await client.list_tools(timeout=5.0)
    except Exception:
        tools = []
    for tool in tools:
        if str(tool.get("name") or "") != name:
            continue
        tool_id = str(tool.get("id") or tool.get("tool_id") or name)
        if tool_id == name:
            break
        resolved = await client.invoke_tool(tool_id, args, timeout=timeout)
        if not (isinstance(resolved, dict) and resolved.get("error")):
            return resolved
    return result


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
    news_query: str = "",
) -> Dict[str, Any]:
    client = _forge_client()

    if prefer_news and news_query:
        news_search = await _invoke_named_tool(
            client,
            "news.search",
            {"query": news_query, "limit": max_items},
            timeout=20.0,
        )
        if not (isinstance(news_search, dict) and news_search.get("error")):
            text = _tool_payload(news_search)
            return {
                "provider": "hp-news",
                "raw": text,
                "sources": _source_urls(text),
            }

    if prefer_news:
        news_result = await _invoke_named_tool(
            client,
            "news.top",
            {"limit": max_items},
            timeout=20.0,
        )
        if not (isinstance(news_result, dict) and news_result.get("error")):
            text = _tool_payload(news_result)
            return {
                "provider": "hp-news",
                "raw": text,
                "sources": _source_urls(text),
            }

    web_result = await _invoke_named_tool(
        client,
        "hp.web.search",
        {
            "query": query,
            "limit": max_items,
            "top_k": max_items,
            "recency_days": 1,
        },
        timeout=25.0,
    )
    if not (isinstance(web_result, dict) and web_result.get("error")):
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
            news_query=f"{location} latest news today" if location else "",
        )
        extra_context = (
            "A scheduled Morning News routine has come due. Nobody has just spoken to you: "
            "you are acting on your own, so do not open by answering a question. "
            "Prepare today's news briefing from the CURRENT INFORMATION below. "
            "Do not invent facts that are not present. Deduplicate repeated stories, "
            "prioritize fresh and important items, and sound natural rather than reading "
            "a list of search results. If local information is present, lead with it. "
            f"The user's timezone is {timezone_name}. Include at most {max_items} stories.\n\n"
            f"CURRENT INFORMATION ({current['provider']}):\n{current['raw'][:16000]}"
        )
        return {
            "instruction": (
                "Prepare today's news briefing for the user from the current information "
                "supplied above."
            ),
            "extra_context": extra_context,
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
        extra_context = (
            f"The scheduled '{workflow.display_name}' routine has come due. Nobody has just "
            "spoken to you: you are acting on your own, so do not open by answering a "
            "question or thanking the user for asking. "
            "Follow these existing Secretary workflow hints:\n"
            f"{step_hints}\n\n"
            "Use the current information below only where relevant. Keep the briefing concise, "
            "warm, and useful. Do not claim access to calendar/email data unless it is actually "
            "present in the supplied context or project/persona memory.\n\n"
            f"CURRENT INFORMATION ({current['provider']}):\n{current['raw'][:12000]}"
        )
        return {
            "instruction": "Deliver the user's daily briefing.",
            "extra_context": extra_context,
            "sources": current["sources"],
            "provider": current["provider"],
        }

    if action_type == "reminder":
        message = str(params.get("message") or "").strip()
        if not message:
            raise RoutineActionError("Reminder routine has no message.")
        return {
            "instruction": f"Remind the user: {message}",
            "extra_context": (
                "A scheduled reminder has come due. Deliver it to the user briefly and "
                "naturally, in your own voice. Do not invent extra tasks, and do not reply "
                "as though the user had just asked you something — nobody spoke to you."
            ),
            "sources": [],
            "provider": "local",
        }

    if action_type == "assistant_prompt":
        prompt = str(params.get("prompt") or "").strip()
        if not prompt:
            raise RoutineActionError("Assistant prompt routine has no prompt.")
        return {
            "instruction": prompt,
            "extra_context": (
                "A scheduled HomePilot routine has come due, and the task above is what it "
                "asks you to do. Carry it out now in the selected assistant/persona/project "
                "context and present the result to the user. Nobody has just spoken to you, "
                "so do not open by answering a question or thanking them for asking."
            ),
            "sources": [],
            "provider": "local",
        }

    raise RoutineActionError(f"Unsupported routine action: {action_type or 'unknown'}")
