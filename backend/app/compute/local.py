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
        if "provider" in extra:
            kwargs["provider"] = extra["provider"]
        if "temperature" in extra:
            kwargs["temperature"] = extra["temperature"]
        if "max_tokens" in extra:
            kwargs["max_tokens"] = extra["max_tokens"]
        return await llm.chat(messages, **kwargs)

    async def available(self) -> bool:
        try:
            from app.config import COMFY_BASE_URL
            from app.services.comfyui.client import comfyui_healthy
            return bool(comfyui_healthy(COMFY_BASE_URL))
        except Exception:
            return False

    def describe(self) -> dict[str, Any]:
        from app.config import COMFY_BASE_URL
        return {"provider": "local", "comfyui_url": COMFY_BASE_URL}
