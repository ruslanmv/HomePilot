"""Voice turn orchestration (MB2).

One place that both web and mobile reuse: given the running conversation, produce
the assistant's reply text and (when a TTS engine is available) its audio. The
LLM call reuses ``app.llm.chat`` — no new model wiring. The ``llm_fn`` seam keeps
this unit-testable without network.
"""

from __future__ import annotations

import base64
from typing import Any, Awaitable, Callable

from .providers import TTSProvider, get_tts_provider

# messages (OpenAI-style) -> assistant reply text
LlmFn = Callable[[list[dict[str, Any]]], Awaitable[str]]

DEFAULT_SYSTEM = (
    "You are HomePilot, a warm, concise voice assistant. Keep spoken replies short "
    "and natural — a sentence or two unless asked for more."
)


async def _default_llm_fn(messages: list[dict[str, Any]]) -> str:
    """Reuse the backend's existing multi-provider LLM client."""
    from app import config, llm

    result = await llm.chat(messages, provider=config.DEFAULT_PROVIDER, max_tokens=400)
    try:
        return (result["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return ""


class VoiceOrchestrator:
    """Stateful per-connection conversation: append turns, get spoken replies."""

    def __init__(
        self,
        *,
        llm_fn: LlmFn | None = None,
        tts: TTSProvider | None = None,
        system_prompt: str = DEFAULT_SYSTEM,
    ) -> None:
        self._llm_fn = llm_fn or _default_llm_fn
        self._tts = tts or get_tts_provider()
        self._messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    @property
    def tts_available(self) -> bool:
        return self._tts.name != "null"

    def set_system(self, prompt: str) -> None:
        """Switch persona / system prompt (MB4). Resets the conversation so the
        new companion starts clean."""
        self._messages = [{"role": "system", "content": prompt or DEFAULT_SYSTEM}]

    async def respond(self, user_text: str) -> dict[str, Any]:
        """Add a user turn, get the reply, synthesize audio if possible."""
        self._messages.append({"role": "user", "content": user_text})
        reply = await self._llm_fn(self._messages)
        self._messages.append({"role": "assistant", "content": reply})

        out: dict[str, Any] = {"type": "reply", "text": reply}
        if reply:
            audio = await self._tts.synth(reply)
            if audio:
                out["audio"] = {
                    "format": self._tts.audio_format,
                    "data_b64": base64.b64encode(audio).decode("ascii"),
                }
        return out
