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

import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import (
    EXPERT_LOCAL_THRESHOLD, EXPERT_GROQ_THRESHOLD,
    EXPERT_LOCAL_MODEL, EXPERT_LOCAL_FAST_MODEL,
    GROQ_MODEL, GROK_MODEL, GEMINI_MODEL,
    EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE,
    available_expert_providers,
)
from .router import (
    build_messages,
    dispatch,
    dispatch_stream,
    score_complexity,
    select_provider,
)
from .thinking import think, stream_think
from .heavy import heavy, stream_heavy
from .schemas import (
    ExpertChatRequest,
    ExpertChatResponse,
    ExpertInfoResponse,
    ExpertStreamRequest,
)

logger = logging.getLogger("expert.routes")

router = APIRouter(prefix="/v1/expert", tags=["expert"])


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

@router.post("/chat", response_model=ExpertChatResponse, summary="Expert chat (sync)")
async def expert_chat(req: ExpertChatRequest) -> ExpertChatResponse:
    """
    Send a message to the Expert and get a complete response.

    thinking_mode controls the pipeline:
      'fast'  → single LLM call (default for simple queries)
      'think' → analyze → plan → solve  (3 chained LLM calls)
      'heavy' → research → reason → synthesize → validate  (4-agent pipeline)
      'auto'  → complexity score decides which pipeline to use
    """
    complexity = score_complexity(req.query)
    provider = select_provider(req.query, preferred=req.provider)

    temperature = req.temperature if req.temperature is not None else EXPERT_TEMPERATURE
    max_tokens = req.max_tokens if req.max_tokens is not None else EXPERT_MAX_TOKENS
    include_raw = os.getenv("EXPERT_DEBUG", "").lower() in ("1", "true", "yes")

    # Resolve auto mode → concrete pipeline
    mode = req.thinking_mode
    if mode == "auto":
        if complexity >= 8:
            mode = "heavy"
        elif complexity >= 5:
            mode = "think"
        else:
            mode = "fast"

    try:
        # ── heavy pipeline ────────────────────────────────────────────────────
        if mode == "heavy":
            result = await heavy(
                req.query, provider,
                history=[m.model_dump() for m in req.history],
                model=req.model, temperature=temperature, max_tokens=max_tokens,
            )
            return ExpertChatResponse(
                content=result["final_answer"],
                provider_used=result.get("provider", provider),
                model_used=req.model,
                complexity_score=complexity,
                thinking_mode_used="heavy",
                steps=result.get("agents"),
            )

        # ── think pipeline ────────────────────────────────────────────────────
        if mode == "think":
            result = await think(
                req.query, provider,
                history=[m.model_dump() for m in req.history],
                model=req.model, temperature=temperature, max_tokens=max_tokens,
                with_critique=req.with_critique,
            )
            return ExpertChatResponse(
                content=result["final_answer"],
                provider_used=result.get("provider", provider),
                model_used=result.get("model"),
                complexity_score=complexity,
                thinking_mode_used="think",
                steps=result.get("steps"),
            )

        # ── fast pipeline (single call) ───────────────────────────────────────
        messages = build_messages(
            req.query,
            history=[m.model_dump() for m in req.history],
            system_prompt=req.system_prompt,
        )
        raw = await dispatch(
            messages, provider,
            model=req.model, temperature=temperature, max_tokens=max_tokens,
        )
        try:
            content = raw["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            content = ""

        return ExpertChatResponse(
            content=content,
            provider_used=raw.get("provider", provider),
            model_used=raw.get("model"),
            complexity_score=complexity,
            thinking_mode_used="fast",
            provider_raw=raw if include_raw else None,
        )

    except Exception as exc:
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
    complexity = score_complexity(req.query)
    provider = select_provider(req.query, preferred=req.provider)
    temperature = req.temperature if req.temperature is not None else EXPERT_TEMPERATURE
    max_tokens = req.max_tokens if req.max_tokens is not None else EXPERT_MAX_TOKENS

    mode = req.thinking_mode
    if mode == "auto":
        if complexity >= 8:
            mode = "heavy"
        elif complexity >= 5:
            mode = "think"
        else:
            mode = "fast"

    async def event_generator():
        meta = json.dumps({"provider": provider, "complexity": complexity, "thinking_mode": mode})
        yield f"event: meta\ndata: {meta}\n\n"
        try:
            if mode == "heavy":
                _synthesis_chunks: list = []
                _active_step_h = ""
                async for event in stream_heavy(
                    req.query, provider,
                    history=[m.model_dump() for m in req.history],
                    model=req.model, temperature=temperature, max_tokens=max_tokens,
                ):
                    if event["type"] == "step_start":
                        _active_step_h = event["step"]
                        d = json.dumps({"step": event["step"], "label": event.get("label",""), "provider": event.get("provider", provider)})
                        yield f"event: step\ndata: {d}\n\n"
                    elif event["type"] == "token":
                        if _active_step_h == "synthesis":
                            _synthesis_chunks.append(event["content"])
                        safe = event["content"].replace("\n", "\\n")
                        yield f"data: {safe}\n\n"
                    elif event["type"] == "step_end":
                        yield f"event: step_end\ndata: {json.dumps({'step': event['step']})}\n\n"
                # Emit final answer as plain tokens so turn.content gets populated
                final_answer = "".join(_synthesis_chunks)
                if final_answer:
                    yield f"event: final_answer\ndata: start\n\n"
                    for ch in final_answer:
                        yield f"data: {ch.replace(chr(10), chr(92)+'n')}\n\n"
            elif mode == "think":
                _solve_chunks: list = []
                _active_step_t = ""
                async for event in stream_think(
                    req.query, provider,
                    history=[m.model_dump() for m in req.history],
                    model=req.model, temperature=temperature, max_tokens=max_tokens,
                    with_critique=req.with_critique,
                ):
                    if event["type"] == "step_start":
                        _active_step_t = event["step"]
                        d = json.dumps({"step": event["step"], "label": event.get("label","")})
                        yield f"event: step\ndata: {d}\n\n"
                    elif event["type"] == "token":
                        if _active_step_t == "solve":
                            _solve_chunks.append(event["content"])
                        safe = event["content"].replace("\n", "\\n")
                        yield f"data: {safe}\n\n"
                    elif event["type"] == "step_end":
                        yield f"event: step_end\ndata: {json.dumps({'step': event['step']})}\n\n"
                # Emit final answer so turn.content gets populated
                final_answer = "".join(_solve_chunks)
                if final_answer:
                    yield f"event: final_answer\ndata: start\n\n"
                    for ch in final_answer:
                        yield f"data: {ch.replace(chr(10), chr(92)+'n')}\n\n"
            else:
                messages = build_messages(
                    req.query,
                    history=[m.model_dump() for m in req.history],
                    system_prompt=req.system_prompt,
                )
                async for chunk in dispatch_stream(
                    messages, provider,
                    model=req.model, temperature=temperature, max_tokens=max_tokens,
                ):
                    safe = chunk.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"
        except Exception as exc:
            logger.error("Expert stream error (mode=%s): %s", mode, exc, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


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
