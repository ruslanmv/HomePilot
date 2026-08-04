"""
LocalComputeProvider (Wave A — Batch 6 / HP-1).

Today's behaviour, behind the ComputeProvider interface: image/video generation
go through the existing ``comfy.run_workflow``; chat goes through the existing
``llm.chat``. Nothing here is new generation logic — it's a thin, behaviour-
preserving wrapper so that selecting ``local`` mode (the default) is identical
to the pre-Batch-6 app.

``run_workflow`` is exposed verbatim so existing routes can later be rewired to
call the provider with zero behavioural change.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import ComputeProvider, GeneratedMedia

# model id → ComfyUI workflow name (HomePilot's bundled workflows). Falls back
# to the generic "txt2img" workflow, which always ships.
_IMAGE_WORKFLOWS = {
    "sdxl": "txt2img",
    "flux-schnell": "txt2img-flux-schnell",
    "flux-dev": "txt2img-flux-dev",
    "pony-xl": "txt2img-pony-xl",
}

# Which local runtime a given modality needs. Chat/multimodal run on Ollama
# (the LLM), image/video/edit run on ComfyUI. This is why local health has to be
# per-modality: a healthy Ollama must not be reported "unavailable" just because
# ComfyUI happens to be down (and vice versa).
_COMFY_MODALITIES = {"image", "video", "edit"}
_OLLAMA_MODALITIES = {"chat", "multimodal"}


async def _ollama_healthy() -> bool:
    """Async probe of the local Ollama runtime (``GET /api/tags``)."""
    try:
        import httpx

        from app.config import OLLAMA_BASE_URL
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def _comfy_healthy() -> bool:
    try:
        from app.config import COMFY_BASE_URL
        from app.services.comfyui.client import comfyui_healthy
        return bool(comfyui_healthy(COMFY_BASE_URL))
    except Exception:
        return False


class LocalComputeProvider(ComputeProvider):
    name = "local"

    async def run_workflow(self, name: str, variables: dict[str, Any]) -> dict:
        """Verbatim passthrough to the existing sync ComfyUI runner (off-thread)."""
        from app import comfy
        return await asyncio.to_thread(comfy.run_workflow, name, variables)

    async def generate_image(
        self, *, prompt, model=None, negative_prompt="",
        width=None, height=None, steps=None, seed=None, workflow=None, **extra,
    ) -> GeneratedMedia:
        wf = workflow or _IMAGE_WORKFLOWS.get((model or "").lower(), "txt2img")
        variables: dict[str, Any] = {"prompt": prompt, "negative_prompt": negative_prompt}
        for k, v in (("width", width), ("height", height), ("steps", steps), ("seed", seed)):
            if v is not None:
                variables[k] = v
        variables.update(extra)
        result = await self.run_workflow(wf, variables)
        return GeneratedMedia(
            images=result.get("images", []),
            videos=result.get("videos", []),
            meta={"provider": "local", "workflow": wf, "prompt_id": result.get("prompt_id")},
        )

    async def edit_image(self, *, prompt, image, model=None, workflow="edit", **extra) -> GeneratedMedia:
        variables = {"prompt": prompt, "image": image, **extra}
        result = await self.run_workflow(workflow, variables)
        return GeneratedMedia(
            images=result.get("images", []),
            videos=result.get("videos", []),
            meta={"provider": "local", "workflow": workflow},
        )

    async def generate_video(self, *, prompt=None, image=None, model=None, workflow="img2vid", **extra) -> GeneratedMedia:
        variables: dict[str, Any] = {**extra}
        if prompt is not None:
            variables["prompt"] = prompt
        if image is not None:
            variables["image"] = image
        result = await self.run_workflow(workflow, variables)
        return GeneratedMedia(
            images=result.get("images", []),
            videos=result.get("videos", []),
            meta={"provider": "local", "workflow": workflow},
        )

    async def chat(self, *, model, messages, **extra) -> dict:
        from app import llm
        kwargs: dict[str, Any] = {"model": model}
        for key in ("provider", "temperature", "max_tokens", "base_url"):
            if extra.get(key) is not None:
                kwargs[key] = extra[key]
        return await llm.chat(messages, **kwargs)

    async def chat_stream(self, *, model, messages, **extra):
        from app import llm
        kwargs: dict[str, Any] = {"model": model}
        for key in ("provider", "temperature", "max_tokens", "base_url"):
            if extra.get(key) is not None:
                kwargs[key] = extra[key]
        async for delta in llm.stream_chat(messages, **kwargs):
            yield delta

    async def available(self, modality: str | None = None) -> bool:
        # Per-modality health: chat asks Ollama, image/video/edit ask ComfyUI.
        # ``None`` means "any local runtime is up".
        if modality in _OLLAMA_MODALITIES:
            return await _ollama_healthy()
        if modality in _COMFY_MODALITIES:
            return _comfy_healthy()
        # Unknown / unspecified modality: available if either runtime is up.
        # Check ComfyUI first (cheap, synchronous) so a healthy image runtime
        # short-circuits before we touch the network for Ollama.
        return _comfy_healthy() or await _ollama_healthy()

    def describe(self) -> dict[str, Any]:
        from app.config import COMFY_BASE_URL
        return {"provider": "local", "comfyui_url": COMFY_BASE_URL}
