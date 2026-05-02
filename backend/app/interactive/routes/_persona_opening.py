"""
Opening-turn generator for Persona Live Play.

Fires once, at session start, when the wizard stamped
``interaction_type=persona_live_play`` and linked a persona project.
Renders ``personaplay.opening_turn`` off the persona's profile,
calls the configured LLM, and persists the reply as the first
``assistant`` turn so the overlay has a greeting to show before
the viewer types anything.

Everything is best-effort: any failure (LLM off, missing prompt,
malformed JSON) returns ``None`` and the session proceeds normally
— losing the greeting must never block the Play button.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional

from .. import repo
from ..playback.persona_profile import load_persona_prompt_vars
from ..playback.playback_config import load_playback_config
from ..prompts import default_library


log = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def maybe_generate_opening_turn(exp: Any, sess: Any) -> Optional[Dict[str, Any]]:
    """Try to produce the opening bubble for a Persona Live Play
    session. Returns ``{"reply_text", "scene_prompt", "character_turn_id"}``
    on success; ``None`` when the session isn't persona mode, when
    the LLM is disabled, or when any part of rendering / calling /
    parsing fails.

    Synchronous entry point that spins an asyncio loop locally so
    the caller (a sync FastAPI handler) doesn't have to manage one.
    """
    pid, label = _persona_fields(exp)
    if not (pid or label):
        return None

    vars_ = load_persona_prompt_vars(
        pid,
        persona_label=label,
        persona_emotion="neutral",
        affinity_score=0.0,
        synopsis="",
        viewer_message="",
        intent_hint="",
        duration_sec=5,
    )
    if not vars_:
        return None

    # Trim the vars the opening prompt actually declares so the
    # library doesn't complain about extras being passed (it won't
    # — _SafeDict ignores unknowns — but keep it clean). The six
    # shared fields needed for the opener:
    opening_vars = {
        k: vars_[k] for k in (
            "persona_name", "persona_role", "persona_objective",
            "persona_traits", "persona_tone", "persona_style",
            "persona_backstory", "persona_outfit", "persona_emotion",
            "allow_explicit", "duration_sec",
        )
    }

    cfg = load_playback_config()
    if not cfg.llm_enabled:
        return None

    try:
        rendered = default_library().render(
            "personaplay.opening_turn", **opening_vars,
        )
        policy = default_library().policy("personaplay.opening_turn")
    except Exception as exc:  # noqa: BLE001
        log.warning("persona opening prompt render failed: %s", str(exc)[:200])
        return None

    payload = _run_llm_sync(rendered.to_messages(), policy, cfg)
    if not payload:
        return None

    reply = _trim(payload.get("reply_text"), 400)
    scene_prompt = _trim(payload.get("scene_prompt"), 400)
    if not reply:
        return None

    # Persist the opening bubble as the first assistant turn so the
    # existing /chat synopsis + turn-log contracts include it.
    try:
        char_turn_id = repo.append_turn(sess.id, "assistant", reply)
        repo.append_event(
            sess.id, "persona_opening",
            payload={"reply_text": reply[:200], "scene_prompt": scene_prompt[:200]},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("persona opening persist failed: %s", str(exc)[:200])
        return None

    return {
        "reply_text": reply,
        "scene_prompt": scene_prompt,
        "character_turn_id": char_turn_id,
    }


def _persona_fields(exp: Any) -> tuple[str, str]:
    ap = getattr(exp, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return "", ""
    if str(ap.get("interaction_type") or "").strip() != "persona_live_play":
        return "", ""
    return (
        str(ap.get("persona_project_id") or "").strip(),
        str(ap.get("persona_label") or "").strip(),
    )


def _run_llm_sync(
    messages: list, policy: Any, cfg: Any,
) -> Optional[Dict[str, Any]]:
    """Call chat_ollama with a private loop so we can fire from a
    sync FastAPI handler without requiring it to be async. Returns
    the parsed JSON dict or ``None`` on any failure.
    """
    # ``asyncio.run(coro)`` raises immediately when a loop is already
    # running in this thread. If we were to inline ``_go()`` into
    # asyncio.run(...) first, Python would create a coroutine object
    # that never gets awaited, triggering:
    #   RuntimeWarning: coroutine ... was never awaited
    # Guard first, then construct/run the coroutine only in the
    # loop-free sync path.
    try:
        asyncio.get_running_loop()
        log.debug("persona opening skipped — event loop already running")
        return None
    except RuntimeError:
        # No running loop in this thread (normal sync FastAPI path).
        pass

    # Local import keeps this module cheap to import from tests
    # that don't exercise the LLM path.
    from ...llm import chat_ollama

    async def _go() -> Optional[Dict[str, Any]]:
        try:
            response = await asyncio.wait_for(
                chat_ollama(
                    messages,
                    temperature=cfg.llm_temperature,
                    max_tokens=cfg.llm_max_tokens,
                    response_format="json",
                ),
                timeout=max(5.0, float(getattr(policy, "timeout_s", 25.0))),
            )
        except asyncio.TimeoutError:
            log.warning("persona opening LLM timeout")
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("persona opening LLM error: %s", str(exc)[:200])
            return None

        content = _content_of(response)
        if not content:
            return None
        match = _JSON_BLOCK.search(content)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    return asyncio.run(_go())


def _content_of(response: Dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else ""
    return content.strip() if isinstance(content, str) else ""


def _trim(value: Any, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


__all__ = ["maybe_generate_opening_turn"]
