"""
ComputeProvider abstraction (Wave A — Batch 6 / HP-1).

Stops HomePilot from assuming ComfyUI / the LLM are always local. Two
implementations:

  * ``LocalComputeProvider``        — today's behaviour, wrapping the existing
                                       ``comfy.run_workflow`` and ``llm.chat``.
  * ``OllaBridgeCloudComputeProvider`` — routes generation to a paired GPU
                                       through OllaBridge Cloud's job API.

The default compute mode is ``local`` (config.HOMEPILOT_COMPUTE_MODE), so
introducing this seam changes no existing behaviour — every persona, gallery,
avatar, and Imagine/Animate path keeps working exactly as before until a user
opts into cloud or auto mode.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


async def iter_openai_sse(resp: Any) -> AsyncIterator[str]:
    """Parse an OpenAI-style ``/v1/chat/completions`` SSE stream, yielding the
    ``choices[0].delta.content`` text deltas. Tolerates keep-alive blanks and
    the terminal ``data: [DONE]``. ``resp`` is a streaming httpx response."""
    async for line in resp.aiter_lines():
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = (choices[0].get("delta") or {}).get("content")
        if delta:
            yield delta


@dataclass
class GeneratedMedia:
    """Normalised result of a generation call across providers."""
    images: list[str] = field(default_factory=list)   # served URLs
    videos: list[str] = field(default_factory=list)    # served URLs
    meta: dict[str, Any] = field(default_factory=dict)  # provider/job detail


class ComputeProvider(abc.ABC):
    """Interface every compute backend implements."""

    name: str = "base"

    @abc.abstractmethod
    async def generate_image(
        self,
        *,
        prompt: str,
        model: str | None = None,
        negative_prompt: str = "",
        width: int | None = None,
        height: int | None = None,
        steps: int | None = None,
        seed: int | None = None,
        **extra: Any,
    ) -> GeneratedMedia:
        ...

    @abc.abstractmethod
    async def available(self, modality: str | None = None) -> bool:
        """Can this provider serve a request right now?

        ``modality`` (``"chat"``/``"multimodal"``/``"image"``/``"video"``/
        ``"edit"``) lets a provider answer for the specific runtime a request
        needs — e.g. a healthy Ollama should report *available for chat* even
        when the ComfyUI image runtime is down. ``None`` means "any runtime".
        """
        ...

    # The following have sensible defaults so a provider only overrides what it
    # supports; callers can feature-detect via ``available()`` / ``describe()``.

    async def edit_image(
        self, *, prompt: str, image: str, model: str | None = None, **extra: Any
    ) -> GeneratedMedia:
        raise NotImplementedError(f"{self.name} does not support image editing")

    async def generate_video(
        self,
        *,
        prompt: str | None = None,
        image: str | None = None,
        model: str | None = None,
        **extra: Any,
    ) -> GeneratedMedia:
        raise NotImplementedError(f"{self.name} does not support video generation")

    async def chat(self, *, model: str, messages: list[dict], **extra: Any) -> dict:
        raise NotImplementedError(f"{self.name} does not support chat")

    async def chat_stream(
        self, *, model: str, messages: list[dict], **extra: Any
    ) -> AsyncIterator[str]:
        """Yield assistant text deltas. Default: adapt the non-streaming ``chat``
        into a single chunk, so every provider streams *something* uniformly."""
        result = await self.chat(model=model, messages=messages, **extra)
        text = ((result.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "")
        if text:
            yield text

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name}
