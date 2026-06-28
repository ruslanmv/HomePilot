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
from dataclasses import dataclass, field
from typing import Any


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
    async def available(self) -> bool:
        """Can this provider serve a request right now?"""
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

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name}
