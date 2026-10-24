# expert/routes.py
# FastAPI router for the Expert module.
# Mount pattern identical to upscale.py / enhance.py — include in main.py with 2 lines.
#
# Endpoints:
#   GET  /v1/expert/info        → provider status + routing config
#   POST /v1/expert/chat        → single-turn or multi-turn, returns full response
#   POST /v1/expert/stream      → streaming SSE response
#   POST /v1/expert/route       → debug: returns which provider would be selected
#
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import (
    EXPERT_LOCAL_THRESHOLD, EXPERT_GROQ_THRESHOLD,
    EXPERT_LOCAL_MODEL, EXPERT_LOCAL_FAST_MODEL,
    GROQ_MODEL, GROK_MODEL, GEMINI_MODEL,
    EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE,
    EXPERT_HEAVY_ESCALATE, EXPERT_DEEP_TIME_BUDGET_S, EXPERT_TOOLS_ENABLED,
    available_expert_providers,
)
from .router import (
    build_messages,
    dispatch,
    dispatch_stream,
    extract_dispatch_meta,
    score_complexity,
    select_provider,
)
from .tool_loop import run_with_tools, stream_with_tools
from .policies import effort_for, is_trivial, resolve_thinking_mode
from .project_context import PROJECT_TOOL, project_system_prompt, project_tool
from . import tools as tools_mod
from .thinking import think, stream_think
from .heavy import heavy, stream_heavy
from .schemas import (
    CapabilitiesRequest,
    ExpertChatRequest,
    ExpertChatResponse,
    ExpertInfoResponse,
    ExpertStreamRequest,
    OllabridgeChatRequest,
    PersonaDraftRequest,
    PersonaDraftResponse,
    ProductionReadinessResponse,
    ReadinessCheckItem,
)
from . import capability
from . import compaction
from . import config as config_mod
from . import deep
from . import grounding
from . import target as target_mod
from .readiness import build_readiness_report
from .mcp_catalog import ESSENTIAL_MCP_SERVERS, TOOL_MAPPING, mcp_key_to_env, mcp_key_to_forge_tool_env
from .mcp_gateway import MCPGateway

logger = logging.getLogger("expert.routes")

router = APIRouter(prefix="/v1/expert", tags=["expert"])


def _compute_request_complexity(req: ExpertChatRequest) -> int:
    score = score_complexity(req.query)
    if req.has_attachments:
        score += 2
    if len(req.history) > 8:
        score += 1
    return min(score, 10)


# ─────────────────────────────────────────────────────────────────────────────
# GET /v1/expert/info
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/info", response_model=ExpertInfoResponse, summary="Expert module status")
async def expert_info() -> ExpertInfoResponse:
    """Return which providers are configured and the current routing thresholds."""
    providers = available_expert_providers()
    return ExpertInfoResponse(
        available_providers=providers,
        default_provider="auto",
        local_threshold=EXPERT_LOCAL_THRESHOLD,
        groq_threshold=EXPERT_GROQ_THRESHOLD,
        local_model=EXPERT_LOCAL_MODEL,
        local_fast_model=EXPERT_LOCAL_FAST_MODEL,
        groq_model=GROQ_MODEL,
        grok_model=GROK_MODEL,
        gemini_model=GEMINI_MODEL,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/expert/chat  (non-streaming, full response)
# ─────────────────────────────────────────────────────────────────────────────

def _provider_for(req: ExpertChatRequest, chosen) -> str:
    """The provider to start from. With the user's own chat model chosen (``target``), 'auto'
    means that model — a complex question is not a reason to send it to a cloud provider the
    user did not pick."""
    if chosen is not None and req.provider == "auto":
        return "local"
    return select_provider(req.query, preferred=req.provider)


def _model_label(chosen, requested: Optional[str]) -> Optional[str]:
    """The model a response reports: the chosen target's, else the one the request named."""
    if chosen is not None and chosen.model:
        return chosen.model
    return requested or None


async def _escalate_for_heavy(chosen, req: ExpertChatRequest, mode: str, provider: str):
    """Heavy runs on the strongest model of the user's own connection when that is a clear
    step up (capability.py) — the same Ollama or gateway, never a provider they did not pick.
    Returns ``(target to run with, escalated model name or None)``."""
    if mode != "heavy" or not EXPERT_HEAVY_ESCALATE or provider != "local":
        return chosen, None
    if isinstance(req.feature_hints, dict) and req.feature_hints.get("escalate") is False:
        return chosen, None
    try:
        caps = await capability.assess(chosen, req.model)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Heavy escalation skipped: %s", exc)
        return chosen, None
    best, selected = caps.get("best"), caps.get("selected") or {}
    if not best or not capability.stronger(best, selected):
        return chosen, None
    if chosen is None:
        return target_mod.ChatTarget(provider="ollama", base_url="", model=best["name"]), best["name"]
    return (
        target_mod.ChatTarget(provider=chosen.provider, base_url=chosen.base_url, model=best["name"], api_key=chosen.api_key),
        best["name"],
    )


def _project(req: ExpertChatRequest) -> Optional[Dict[str, Any]]:
    return req.project.model_dump() if req.project is not None else None


def _request_tools(req: ExpertChatRequest) -> tools_mod.RequestTools:
    """The shared tools plus this request's own: the project's documents, when there are any
    and the backend's retrieval is reachable (project_context.py)."""
    local = [t for t in (project_tool(_project(req)),) if t is not None]
    return tools_mod.RequestTools(tools_mod.registry(), local)


def _forced_tools(req: ExpertChatRequest, registry: Optional[tools_mod.RequestTools] = None):
    """What runs before the model is asked anything: the project's documents when the chat is
    inside a project with documents, and a web search when the chat's "Search the web" switch
    is on (feature_hints.webSearch = "force") — in every mode."""
    forced: list = []
    project = _project(req)
    if project and int(project.get("document_count") or 0) > 0 and (registry is None or registry.spec(PROJECT_TOOL)):
        forced.append((PROJECT_TOOL, {"query": req.query}))
    hints = req.feature_hints if isinstance(req.feature_hints, dict) else {}
    if str(hints.get("webSearch") or "").lower() in ("force", "on", "true", "1"):
        forced.append(("hp_web_search", {"query": req.query}))
    return forced or None


def _effort_notice(effort) -> Optional[str]:
    return None


def _escalation_notice(escalated: str, chosen, req: ExpertChatRequest) -> str:
    was = _model_label(chosen, req.model) or EXPERT_LOCAL_MODEL
    return f"Heavy used {escalated}, the strongest model on this connection, instead of {was}."


@router.post("/chat", response_model=ExpertChatResponse, summary="Expert chat (sync)")
async def expert_chat(req: ExpertChatRequest) -> ExpertChatResponse:
    """
    Send a message to the Expert and get a complete response.

    thinking_mode controls the pipeline:
      'fast'  → single LLM call (default for simple queries)
      'think' → analyze → plan → solve  (3 chained LLM calls)
      'heavy' → research → reason → synthesize → validate  (4-agent pipeline)
      'auto'  → complexity score decides which pipeline to use

    ``target`` (the user's chosen chat model) is in force for every step of the pipeline.
    """
    chosen = target_mod.from_request(req.target)
    # Today's date (and any web sources HomePilot found) reach every step's system prompt.
    with target_mod.using(chosen), grounding.using(req.client_timezone, req.context):
        return await _expert_chat(req, chosen)


async def _expert_chat(req: ExpertChatRequest, chosen) -> ExpertChatResponse:
    complexity = _compute_request_complexity(req)
    provider = _provider_for(req, chosen)
    started = time.perf_counter()
    include_raw = os.getenv("EXPERT_DEBUG", "").lower() in ("1", "true", "yes")

    resolution = resolve_thinking_mode(req.thinking_mode, complexity)
    mode = resolution.mode_used
    strategy = resolution.strategy
    route_notices: list[str] = []
    if req.thinking_mode == "auto":
        route_notices.append(f"Auto selected '{mode}' strategy for complexity score {complexity}.")
    budget_tier = str(req.feature_hints.get("budgetTier", "")).lower() if req.feature_hints else ""
    if budget_tier == "low" and mode == "heavy":
        route_notices.append("Budget tier is low; downgraded heavy mode to think.")
        mode = "think"
        strategy = "expert-thinking"

    # The request's tools (the project's documents among them), what runs first, and the
    # effort this message earns inside the mode (policies.effort_for).
    registry = _request_tools(req)
    forced = _forced_tools(req, registry)
    effort = effort_for(mode, complexity, trivial=is_trivial(req.query), forced_tools=bool(forced))
    temperature = req.temperature if req.temperature is not None else effort.temperature
    max_tokens = req.max_tokens if req.max_tokens is not None else effort.max_tokens
    system_prompt = project_system_prompt(req.system_prompt, _project(req))
    direct = effort.level == "direct"
    if direct and mode != "fast":
        strategy = "direct"

    # Compaction: the turns the window keeps go verbatim; the older ones ride as a note.
    window, note, compaction_notice = await compaction.prepare(
        [m.model_dump() for m in req.history], session_id=req.session_id, provider=provider, model=req.model,
    )
    if compaction_notice:
        route_notices.append(compaction_notice)
    run_target, escalated = (chosen, None) if direct else await _escalate_for_heavy(chosen, req, mode, provider)
    if escalated:
        route_notices.append(_escalation_notice(escalated, chosen, req))

    trace_id = (req.session_id or "expert")[:8]
    history_chars = sum(len(m.content or "") for m in req.history)
    print(
        f"[EXPERT CHAT {trace_id}] start requested_mode={req.thinking_mode!r} "
        f"resolved_mode={mode!r} strategy={strategy!r} provider={provider!r} "
        f"model={req.model!r} target={chosen!r} complexity={complexity} history={len(req.history)} "
        f"history_chars={history_chars} query_chars={len(req.query or '')} "
        f"max_tokens={max_tokens} temperature={temperature} tools={int(bool(EXPERT_TOOLS_ENABLED))}"
    )

    try:
        # ── heavy pipeline ────────────────────────────────────────────────────
        if mode == "heavy" and not direct:
            with target_mod.using(run_target), compaction.using(note):
                result = await heavy(
                    req.query, provider,
                    history=window, system_prompt=system_prompt, forced_tools=forced,
                    research=effort.research, registry=registry, tool_rounds=effort.tool_rounds,
                    model=req.model, temperature=temperature, max_tokens=max_tokens,
                )
            print(
                f"[EXPERT CHAT {trace_id}] done mode=heavy provider={result.get('provider', provider)!r} "
                f"elapsed_ms={int((time.perf_counter() - started) * 1000)} "
                f"answer_len={len(result.get('final_answer') or '')} fallback={bool(result.get('fallback_applied', False))} "
                f"verdict={result.get('verdict')!r} escalated={escalated!r}"
            )
            return ExpertChatResponse(
                content=result["final_answer"],
                provider_used=result.get("provider", provider),
                model_used=_model_label(run_target, req.model),
                complexity_score=complexity,
                thinking_mode_used="heavy",
                steps=result.get("agents"),
                strategy_used=strategy,
                fallback_applied=bool(result.get("fallback_applied", False)),
                notices=[*route_notices, *list(result.get("notices", []))],
                latency_ms=int((time.perf_counter() - started) * 1000),
                tool_trace=list(result.get("tool_trace", [])),
                sources=list(result.get("sources", [])),
                verdict=result.get("verdict"),
                verdict_detail=result.get("verdict_detail"),
                model_escalated=escalated,
                effort=effort.as_dict(),
            )

        # ── think pipeline ────────────────────────────────────────────────────
        if mode == "think" and not direct:
            with compaction.using(note):
                result = await think(
                    req.query, provider,
                    history=window, system_prompt=system_prompt, forced_tools=forced,
                    plan=effort.plan, analyze=effort.analyze, registry=registry, tool_rounds=effort.tool_rounds,
                    model=req.model, temperature=temperature, max_tokens=max_tokens,
                    with_critique=req.with_critique,
                )
            print(
                f"[EXPERT CHAT {trace_id}] done mode=think provider={result.get('provider', provider)!r} "
                f"elapsed_ms={int((time.perf_counter() - started) * 1000)} "
                f"answer_len={len(result.get('final_answer') or '')} fallback={bool(result.get('fallback_applied', False))}"
            )
            return ExpertChatResponse(
                content=result["final_answer"],
                provider_used=result.get("provider", provider),
                model_used=result.get("model") or _model_label(chosen, req.model),
                complexity_score=complexity,
                thinking_mode_used="think",
                steps=result.get("steps"),
                strategy_used=strategy,
                fallback_applied=bool(result.get("fallback_applied", False)),
                notices=[*route_notices, *list(result.get("notices", []))],
                latency_ms=int((time.perf_counter() - started) * 1000),
                tool_trace=list(result.get("tool_trace", [])),
                sources=list(result.get("sources", [])),
                effort=effort.as_dict(),
            )

        # ── one generation with the per-turn tool loop: Fast, and a trivial message in any mode ──
        with compaction.using(note):
            messages = build_messages(req.query, history=window, system_prompt=system_prompt)
            result = await run_with_tools(
                messages, provider, model=req.model, temperature=temperature, max_tokens=max_tokens,
                call=dispatch, forced=forced, registry=registry, max_rounds=effort.tool_rounds,
            )
        content = result.get("content") or ""
        notices = [*route_notices, *list(result.get("notices", []))]

        print(
            f"[EXPERT CHAT {trace_id}] done mode={mode} effort={effort.level} provider={provider!r} "
            f"model={_model_label(chosen, req.model)!r} elapsed_ms={int((time.perf_counter() - started) * 1000)} "
            f"answer_len={len(content or '')} tools={len(result.get('tool_trace', []))} "
            f"fallback={bool(result.get('fallback_applied', False))}"
        )
        return ExpertChatResponse(
            content=content,
            provider_used=(chosen.label if chosen is not None else provider),
            model_used=_model_label(chosen, req.model),
            complexity_score=complexity,
            thinking_mode_used=mode,
            strategy_used=strategy,
            fallback_applied=bool(result.get("fallback_applied", False)),
            notices=notices,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tool_trace=list(result.get("tool_trace", [])),
            sources=list(result.get("sources", [])),
            effort=effort.as_dict(),
        )

    except Exception as exc:
        print(
            f"[EXPERT CHAT {trace_id}] error mode={mode!r} provider={provider!r} "
            f"model={req.model!r} tools={int(bool(EXPERT_TOOLS_ENABLED))} "
            f"error={type(exc).__name__}: {exc}"
        )
        logger.error("Expert chat failed (mode=%s): %s", mode, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Expert pipeline error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/expert/stream  (Server-Sent Events streaming)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/stream", summary="Expert chat (streaming SSE)")
async def expert_stream(req: ExpertStreamRequest) -> StreamingResponse:
    """
    Stream Expert response via SSE. Routes through fast/think/heavy pipeline.

    Event types:
      event: meta      → {provider, complexity, thinking_mode}
      event: step      → {step, label, provider}   (think/heavy only)
      event: step_end  → {step}
      data: <token>    → plain text token
      data: [DONE]     → end of stream
      event: error     → {error: str}
    """
    complexity = _compute_request_complexity(req)
    chosen = target_mod.from_request(req.target)
    provider = _provider_for(req, chosen)

    resolution = resolve_thinking_mode(req.thinking_mode, complexity)
    mode = resolution.mode_used
    stream_notices: list[str] = []
    if req.thinking_mode == "auto":
        stream_notices.append(f"Auto selected '{mode}' strategy for complexity score {complexity}.")
    budget_tier = str(req.feature_hints.get("budgetTier", "")).lower() if req.feature_hints else ""
    if budget_tier == "low" and mode == "heavy":
        stream_notices.append("Budget tier is low; downgraded heavy mode to think.")
        mode = "think"
        resolution = resolve_thinking_mode(mode, complexity)

    # The request's tools, what runs first, and the effort this message earns (as in _expert_chat).
    registry = _request_tools(req)
    forced = _forced_tools(req, registry)
    effort = effort_for(mode, complexity, trivial=is_trivial(req.query), forced_tools=bool(forced))
    temperature = req.temperature if req.temperature is not None else effort.temperature
    max_tokens = req.max_tokens if req.max_tokens is not None else effort.max_tokens
    system_prompt = project_system_prompt(req.system_prompt, _project(req))
    direct = effort.level == "direct"
    strategy = "direct" if direct and mode != "fast" else resolution.strategy

    # Compaction runs inside the stream (below): the reader sees "Compacting the conversation…"
    # while the summary is written, and the summary is written by the chat's own model (the
    # target context is set around the stream, not around this function).
    history_dump = [m.model_dump() for m in req.history]
    compacting_turns = compaction.needs_summary(history_dump, req.session_id)
    run_target, escalated = (chosen, None) if direct else await _escalate_for_heavy(chosen, req, mode, provider)
    if escalated:
        stream_notices.append(_escalation_notice(escalated, chosen, req))
    started = time.perf_counter()
    project = _project(req)

    def sse(name: str, payload: Dict[str, Any]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def tok(text: str) -> str:
        return f"data: {text.replace(chr(10), chr(92) + 'n')}\n\n"

    async def event_generator():
        summary: Dict[str, Any] = {"tool_trace": [], "sources": [], "verdict": None, "notices": list(stream_notices)}
        final_answer = ""

        def relay(event: Dict[str, Any]) -> str:
            """A pipeline event → its SSE frame ('' for events the client has no use for)."""
            kind = event["type"]
            if kind == "step_start":
                return sse("step", {
                    "step": event["step"], "label": event.get("label", ""),
                    "provider": event.get("provider", provider), "role": event.get("role", "work"),
                })
            if kind == "step_end":
                return sse("step_end", {"step": event["step"]})
            if kind == "token":
                return tok(event["content"])
            if kind in ("tool_start", "tool_end"):
                payload = {k: v for k, v in event.items() if k != "type"}
                payload["phase"] = "start" if kind == "tool_start" else "end"
                if kind == "tool_end":
                    summary["tool_trace"].append(
                        {k: event.get(k) for k in ("id", "name", "label", "ok", "summary", "elapsed_ms", "step")}
                    )
                return sse("tool", payload)
            if kind == "sources":
                summary["sources"] = event["sources"]
                return sse("sources", {"sources": event["sources"], "step": event.get("step")})
            if kind == "reset":
                return sse("reset", {"step": event.get("step")})
            if kind == "wait":
                return sse("wait", {k: v for k, v in event.items() if k != "type"})
            if kind == "notice":
                if event["text"] not in summary["notices"]:
                    summary["notices"].append(event["text"])
                return sse("notice", {"text": event["text"]})
            if kind == "verdict":
                summary["verdict"] = event["verdict"]
                summary["verdict_detail"] = {"verdict": event["verdict"], "note": event.get("note", ""), **(event.get("detail") or {})}
                return sse("verdict", {"verdict": event["verdict"], "note": event.get("note", ""), "detail": event.get("detail") or {}})
            return ""

        if compacting_turns:
            yield sse("compacting", {
                "turns": compacting_turns,
                "text": f"Compacting the conversation: summarizing {compacting_turns} earlier "
                        f"message{'' if compacting_turns == 1 else 's'}…",
            })
        window, note, compaction_notice = await compaction.prepare(
            history_dump, session_id=req.session_id, provider=provider, model=req.model,
        )
        if compaction_notice:
            stream_notices.append(compaction_notice)
            summary["notices"].append(compaction_notice)
        yield sse("meta", {
            "provider": provider, "complexity": complexity, "thinking_mode": mode,
            "strategy": strategy, "notices": list(stream_notices),
            "model": _model_label(run_target, req.model), "escalated": escalated,
            "compacted": bool(note), "effort": effort.as_dict(),
            "project": {"id": project["id"], "name": project.get("name")} if project else None,
        })
        try:
            with compaction.using(note):
                if mode == "heavy" and not direct:
                    with target_mod.using(run_target):
                        async for event in stream_heavy(
                            req.query, provider, history=window, system_prompt=system_prompt,
                            forced_tools=forced, research=effort.research, registry=registry,
                            tool_rounds=effort.tool_rounds,
                            model=req.model, temperature=temperature, max_tokens=max_tokens,
                        ):
                            if event["type"] == "final":
                                final_answer = event.get("content") or ""
                                continue
                            frame = relay(event)
                            if frame:
                                yield frame
                elif mode == "think" and not direct:
                    async for event in stream_think(
                        req.query, provider, history=window, system_prompt=system_prompt,
                        forced_tools=forced, plan=effort.plan, analyze=effort.analyze, registry=registry, tool_rounds=effort.tool_rounds,
                        model=req.model, temperature=temperature, max_tokens=max_tokens,
                        with_critique=req.with_critique,
                    ):
                        if event["type"] == "final":
                            final_answer = event.get("content") or ""
                            continue
                        frame = relay(event)
                        if frame:
                            yield frame
                else:
                    # One generation with the tool loop: Fast, and a trivial message in any mode.
                    messages = build_messages(req.query, history=window, system_prompt=system_prompt)
                    async for event in stream_with_tools(
                        messages, provider, model=req.model, temperature=temperature, max_tokens=max_tokens,
                        forced=forced, registry=registry, max_rounds=effort.tool_rounds,
                    ):
                        if event["type"] == "done":
                            final_answer = event.get("content") or ""
                            summary["tool_trace"] = list(event.get("tool_trace", []))
                            summary["sources"] = list(event.get("sources", []))
                            continue
                        frame = relay(event)
                        if frame:
                            yield frame
            if mode in ("heavy", "think") and not direct and final_answer:
                # The reply, sent whole: the step tokens above were the work, not the answer.
                yield "event: final_answer\ndata: start\n\n"
                yield tok(final_answer)
            yield sse("done", {
                "content": final_answer, "thinking_mode": mode, "strategy": strategy, "effort": effort.as_dict(),
                "latency_ms": int((time.perf_counter() - started) * 1000), **summary,
            })
        except Exception as exc:
            logger.error(
                "Expert stream error (mode=%s provider=%s model=%s tools=%s session=%s): %s",
                mode, provider, req.model, int(bool(EXPERT_TOOLS_ENABLED)),
                (req.session_id or "")[:8], exc, exc_info=True,
            )
            yield sse("error", {"error": str(exc)})
        yield "data: [DONE]\n\n"

    async def with_target():
        # Set inside the generator: the response body is iterated after this function has
        # returned, so a context set around the return would already be gone.
        with target_mod.using(chosen), grounding.using(req.client_timezone, req.context):
            async for item in event_generator():
                yield item

    return StreamingResponse(
        with_heartbeat(with_target()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def with_heartbeat(source: AsyncIterator[str], every: Optional[float] = None) -> AsyncIterator[str]:
    """``source``'s frames, plus a ``: keep-alive`` comment whenever it is silent for ``every``
    seconds (a long model call before the first token, a slow tool). Proxies and browsers
    then never take a working stream for a dead one. The source runs as its own task, so a
    timeout never cancels it mid-await; when the reader goes away, that task is cancelled
    with the response, which closes the model request behind it."""
    every = config_mod.EXPERT_SSE_HEARTBEAT_S if every is None else every
    if not every or every <= 0:
        async for item in source:
            yield item
        return
    queue: "asyncio.Queue[Any]" = asyncio.Queue()
    finished = object()

    async def pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised on the reader's side
            await queue.put(exc)
            return
        await queue.put(finished)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=every)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is finished:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - the pump's own cancellation
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Capabilities + Deep research
# ─────────────────────────────────────────────────────────────────────────────

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@router.get("/usage", summary="Usage meter: each model endpoint's queue, pacing and learned rate limit")
async def expert_usage() -> dict:
    """Per OpenAI-compatible endpoint this process has called: requests in flight and in line,
    the gap between starts and any cooldown, the learned cap (requests per window before the
    provider rate-limits), and the rolling window's requests, successes and rate limits."""
    from .providers import endpoint_usage
    from .config import EXPERT_PROVIDER_MAX_INFLIGHT, EXPERT_PROVIDER_WAIT_S, EXPERT_PROVIDER_BACKGROUND_WAIT_S
    return {
        "endpoints": endpoint_usage(),
        "policy": {
            "max_in_flight": EXPERT_PROVIDER_MAX_INFLIGHT,
            "interactive_wait_s": EXPERT_PROVIDER_WAIT_S,
            "background_wait_s": EXPERT_PROVIDER_BACKGROUND_WAIT_S,
        },
    }


@router.post("/capabilities", summary="What the connected models can carry (the Deep research gate)")
async def expert_capabilities(req: CapabilitiesRequest) -> dict:
    """The selected model's tier, the strongest model on the same connection, and whether
    Deep research is offered (capability.py). POST, so a gateway key never rides in a URL."""
    chosen = target_mod.from_request(req.target)
    return await capability.assess(chosen, req.model, run_probe=req.probe)


@router.post("/deep", summary="Start a Deep research run (background job)")
async def deep_start(req: ExpertChatRequest) -> dict:
    """Plan → sub-agents with tools → cited report, as a background job (deep.py). Refused
    (403) when the connection has no high-end model, unless EXPERT_DEEP_RESEARCH=always."""
    chosen = target_mod.from_request(req.target)
    provider = _provider_for(req, chosen)
    caps = await capability.assess(chosen, req.model)
    gate = caps["deep_research"]
    if not gate["enabled"]:
        raise HTTPException(status_code=403, detail=gate["reason"])
    notices: list = []
    # The model chosen in the chat runs the research too (no silent swap to another model).
    run_target, model = chosen, req.model
    window, note, compaction_notice = await compaction.prepare(
        [m.model_dump() for m in req.history], session_id=req.session_id, provider=provider, model=model,
    )
    if compaction_notice:
        notices.append(compaction_notice)
    registry = _request_tools(req)
    job = deep.start(
        req.query, provider=provider, model=_model_label(run_target, model), history=window, chosen=run_target,
        timezone=req.client_timezone, context=req.context, note=note, notices=notices,
        registry=registry, operator_prompt=project_system_prompt(req.system_prompt, _project(req)),
        session_id=req.session_id,
    )
    return {"job_id": job.id, "status": job.status, "model": job.model, "notices": notices,
            "time_budget_s": EXPERT_DEEP_TIME_BUDGET_S}


@router.get("/deep/{job_id}", summary="Deep research job snapshot")
async def deep_status(job_id: str) -> dict:
    job = deep.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown Deep research job")
    return job.snapshot()


@router.get("/deep/{job_id}/events", summary="Deep research progress (SSE; replays from `after`, or from the start)")
async def deep_events(job_id: str, request: Request, after: int = 0) -> StreamingResponse:
    """Every frame carries ``id: <seq>``. A client that reconnects sends ``Last-Event-ID`` (or
    ``?after=``) and gets only what it missed — no duplicate steps, no duplicate text."""
    job = deep.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown Deep research job")
    header = request.headers.get("last-event-id")
    if header and header.isdigit():
        after = max(after, int(header))

    async def gen():
        queue = job.subscribe(after=after)
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if job.finished_state:
                        break
                    yield ": keep-alive\n\n"
                    continue
                yield f"id: {ev.get('seq', 0)}\nevent: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev["type"] in ("done", "error", "cancelled"):
                    break
        finally:
            job.unsubscribe(queue)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.delete("/deep/{job_id}", summary="Cancel a Deep research job")
async def deep_cancel(job_id: str) -> dict:
    job = deep.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown Deep research job")
    job.cancel()
    return {"job_id": job_id, "status": job.status}


# ─────────────────────────────────────────────────────────────────────────────
# POST /v1/expert/route  (debug helper — shows routing decision)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/route", summary="Debug: show provider routing decision")
async def expert_route(query: str, preferred: str = "auto") -> dict:
    """
    Returns the provider that would be selected for a given query.
    Useful for debugging and tuning routing thresholds.
    """
    complexity = score_complexity(query)
    provider = select_provider(query, preferred=preferred)  # type: ignore[arg-type]
    return {
        "query_preview": query[:100],
        "complexity_score": complexity,
        "selected_provider": provider,
        "available_providers": available_expert_providers(),
        "thresholds": {
            "local": f"complexity ≤ {EXPERT_LOCAL_THRESHOLD}",
            "groq": f"complexity ≤ {EXPERT_GROQ_THRESHOLD}",
            "cloud": f"complexity > {EXPERT_GROQ_THRESHOLD}",
        },
    }


@router.post("/ollabridge/chat/completions", summary="OllaBridge-compatible Expert chat")
async def ollabridge_chat(req: OllabridgeChatRequest) -> dict:
    """
    OpenAI-compatible adapter endpoint so HomePilot can expose Expert through
    OllaBridge cloud persona workflows.
    """
    if req.stream:
        raise HTTPException(status_code=400, detail="stream=true is not supported on this adapter endpoint yet.")

    if not req.messages:
        raise HTTPException(status_code=422, detail="messages cannot be empty.")

    user_query = ""
    history = []
    for msg in req.messages:
        d = msg.model_dump()
        if d["role"] == "user":
            user_query = d["content"]
        else:
            history.append(d)

    if not user_query:
        raise HTTPException(status_code=422, detail="At least one user message is required.")

    expert_req = ExpertChatRequest(
        query=user_query,
        provider=req.provider,
        thinking_mode=req.thinking_mode,
        history=history,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    expert_resp = await expert_chat(expert_req)

    return {
        "id": "expert-ollabridge-chat",
        "object": "chat.completion",
        "provider": expert_resp.provider_used,
        "model": expert_resp.model_used or req.model or "expert-auto",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": expert_resp.content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@router.post("/persona/draft", response_model=PersonaDraftResponse, summary="Create persona draft from Expert")
async def expert_persona_draft(req: PersonaDraftRequest) -> PersonaDraftResponse:
    """
    Generate a persona draft that can be used by HomePilot persona creation
    flows (including OllaBridge cloud personas).
    """
    constraints = "\\n".join(f"- {c}" for c in req.constraints) if req.constraints else "- Keep safety-first behavior."
    prompt = (
        "Create a high-quality HomePilot persona draft as JSON fields:\\n"
        "name, description, system_prompt, first_message, suggested_tools (array), "
        "memory_policy (object with keys recall, retention_days, pii_redaction).\\n\\n"
        f"Mission: {req.mission}\\n"
        f"Domain: {req.domain}\\n"
        f"Tone: {req.tone}\\n"
        f"Constraints:\\n{constraints}\\n"
    )

    expert_req = ExpertChatRequest(
        query=prompt,
        provider=req.provider,
        thinking_mode=req.thinking_mode,
        model=req.model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )
    resp = await expert_chat(expert_req)

    content = resp.content.strip()
    default_name = f"{req.domain.title()} Research Persona"
    default_desc = f"Persona for {req.mission[:120]}"
    return PersonaDraftResponse(
        name=default_name,
        description=default_desc,
        system_prompt=content,
        first_message=f"Hello, I am your {default_name}. I can help with: {req.mission}.",
        suggested_tools=["retrieval", "web_search", "model_compare"],
        memory_policy={"recall": True, "retention_days": 30, "pii_redaction": True},
        provider_used=resp.provider_used,
        thinking_mode_used=resp.thinking_mode_used,
    )


@router.get("/readiness", response_model=ProductionReadinessResponse, summary="Expert production readiness report")
async def expert_readiness() -> ProductionReadinessResponse:
    """
    Returns a lightweight production-readiness report based on Expert feature
    flags and required runtime configuration.
    """
    report = build_readiness_report()
    return ProductionReadinessResponse(
        ready=report.ready,
        stage=report.stage,  # type: ignore[arg-type]
        checks=[ReadinessCheckItem(name=c.name, passed=c.passed, detail=c.detail) for c in report.checks],
    )


@router.get("/mcp/plan", summary="Expert MCP rollout plan and configuration status")
async def expert_mcp_plan() -> dict:
    gateway = MCPGateway()
    status_by_key = {item.key: item for item in gateway.status()}
    servers = []

    for spec in ESSENTIAL_MCP_SERVERS:
        status = status_by_key.get(spec.key)
        servers.append(
            {
                "key": spec.key,
                "priority": spec.priority,
                "purpose": spec.purpose,
                "required_apis": spec.required_apis,
                "configured": status.configured if status else False,
                "endpoint": status.endpoint if status else "",
                "forge_tool_id": status.forge_tool_id if status else "",
                "env_key": mcp_key_to_env(spec.key),
                "forge_tool_env_key": mcp_key_to_forge_tool_env(spec.key),
            }
        )

    return {
        "orchestrator": gateway.orchestrator,
        "context_forge_url": gateway.forge_base_url,
        "tool_mapping": TOOL_MAPPING,
        "servers": servers,
        "minimal_production_set": [
            "mcp-web-search",
            "mcp-doc-retrieval",
            "mcp-memory-store",
            "mcp-safety-policy",
            "mcp-observability",
        ],
    }
