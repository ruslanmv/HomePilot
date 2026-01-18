# homepilot/backend/app/orchestrator.py
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, Optional, Literal

from .comfy import run_workflow
from .llm import chat as llm_chat
from .prompts import BASE_SYSTEM, FUN_SYSTEM
from .storage import add_message, get_recent
from .config import DEFAULT_PROVIDER

ProviderName = Literal["openai_compat", "ollama"]

IMAGE_RE = re.compile(r"\b(imagine|generate|create|draw|make)\b.*\b(image|picture|photo|art)\b", re.I)
EDIT_RE = re.compile(r"\b(edit|inpaint|replace|remove|change)\b", re.I)
ANIM_RE = re.compile(r"\b(animate|make (a )?video|image\s*to\s*video)\b", re.I)
URL_RE = re.compile(r"(https?://\S+)")

# Prompt refiner system message (Grok-like behavior)
PROMPT_REFINER_SYSTEM = """You are an expert at refining user prompts into detailed, visual image generation prompts.

Given a user's casual request, output a JSON object with these fields:
- "prompt": (string) A detailed, visual, specific prompt optimized for FLUX/SDXL. Include subject, style, lighting, composition, mood. Be vivid and specific.
- "negative_prompt": (string, optional) Things to avoid in the generation (e.g., "blurry, low quality, distorted").
- "aspect_ratio": (string) One of: "1:1", "16:9", "9:16", "4:3", "3:4". Default to "1:1" if unclear.
- "style": (string) One of: "photorealistic", "illustration", "cinematic", "artistic", "anime". Default to "photorealistic".

Keep your response as a single JSON object, no markdown, no explanations."""


def _norm_mode(mode: Optional[str]) -> str:
    return (mode or "").strip().lower()


async def _refine_prompt(
    user_prompt: str,
    provider: ProviderName,
    ollama_base_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Use LLM to refine user's casual prompt into a detailed image generation prompt.
    Returns dict with: prompt, negative_prompt, aspect_ratio, style
    """
    messages = [
        {"role": "system", "content": PROMPT_REFINER_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = await llm_chat(
            messages,
            provider=provider,
            temperature=0.7,
            max_tokens=300,
            base_url=ollama_base_url if provider == "ollama" else None,
            model=ollama_model if provider == "ollama" else None,
        )

        # Extract the response text
        response_text = (
            (result.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        ).strip()

        # Try to parse as JSON
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            # Extract JSON from code block
            lines = response_text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or (not line.strip().startswith("```")):
                    json_lines.append(line)
            response_text = "\n".join(json_lines).strip()

        refined = json.loads(response_text)

        # Validate and set defaults
        return {
            "prompt": refined.get("prompt", user_prompt),
            "negative_prompt": refined.get("negative_prompt", "blurry, low quality, distorted"),
            "aspect_ratio": refined.get("aspect_ratio", "1:1"),
            "style": refined.get("style", "photorealistic"),
        }

    except Exception as e:
        # If refinement fails, return basic prompt
        return {
            "prompt": user_prompt,
            "negative_prompt": "blurry, low quality, distorted",
            "aspect_ratio": "1:1",
            "style": "photorealistic",
        }


async def orchestrate(
    user_text: str,
    conversation_id: Optional[str] = None,
    fun_mode: bool = False,
    mode: Optional[str] = None,
    provider: Optional[ProviderName] = None,
    ollama_base_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
    text_temperature: Optional[float] = None,
    text_max_tokens: Optional[int] = None,
    img_width: Optional[int] = None,
    img_height: Optional[int] = None,
    img_steps: Optional[int] = None,
    img_cfg: Optional[float] = None,
    img_seed: Optional[int] = None,
    vid_seconds: Optional[int] = None,
    vid_fps: Optional[int] = None,
    vid_motion: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main router:
      - chat -> LLM (provider selectable)
      - imagine -> txt2img workflow
      - edit/animate (with URL) -> edit/img2vid workflow

    Returns stable schema:
      {"conversation_id": str, "text": str, "media": dict | None}
    """
    cid = conversation_id or str(uuid.uuid4())
    text_in = (user_text or "").strip()

    # Persist user message
    add_message(cid, "user", text_in)

    # Detect URL (for edit/animate)
    url_match = URL_RE.search(text_in)
    image_url = url_match.group(1) if url_match else ""

    m = _norm_mode(mode)

    # --- Animate ---
    if (m == "animate") or (image_url and ANIM_RE.search(text_in)):
        if not image_url:
            text = "To animate, upload an image first (or paste an image URL)."
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}

        res = run_workflow(
            "img2vid",
            {
                "image_url": image_url,
                "motion": vid_motion if vid_motion is not None else "subtle cinematic camera drift",
                "seconds": vid_seconds if vid_seconds is not None else 6,
            },
        )
        video_url = (res.get("videos") or [None])[0]
        text = "Here you go."
        add_message(cid, "assistant", text)
        return {"conversation_id": cid, "text": text, "media": {"video_url": video_url}}

    # --- Edit ---
    if (m == "edit") or (image_url and EDIT_RE.search(text_in)):
        if not image_url:
            text = "To edit, upload an image first (or paste an image URL)."
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}

        res = run_workflow("edit", {"image_url": image_url, "instruction": text_in})
        images = res.get("images", []) or []
        text = "Done."
        add_message(cid, "assistant", text)
        return {"conversation_id": cid, "text": text, "media": {"images": images}}

    # --- Imagine ---
    if (m == "imagine") or IMAGE_RE.search(text_in):
        try:
            # Get provider for prompt refinement
            prov: ProviderName = provider or DEFAULT_PROVIDER  # type: ignore

            # Refine the prompt using LLM (Grok-like behavior)
            refined = await _refine_prompt(
                text_in,
                provider=prov,
                ollama_base_url=ollama_base_url if prov == "ollama" else None,
                ollama_model=ollama_model if prov == "ollama" else None,
            )

            # Merge custom image parameters if provided
            if img_width is not None:
                refined["width"] = img_width
            if img_height is not None:
                refined["height"] = img_height
            if img_steps is not None:
                refined["steps"] = img_steps
            if img_cfg is not None:
                refined["cfg"] = img_cfg
            if img_seed is not None:
                refined["seed"] = img_seed

            # Run the workflow with refined prompt and parameters
            res = run_workflow("txt2img", refined)
            images = res.get("images", []) or []

            # Short Grok-like caption
            text = "Here you go." if images else "Generated."
            add_message(cid, "assistant", text)
            media = {"images": images} if images else None
            return {"conversation_id": cid, "text": text, "media": media}

        except FileNotFoundError as e:
            # In CI/tests, workflows may not be mounted. Return a stable text-only response.
            text = "Image generation is not configured on this server. Please set up ComfyUI workflows."
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}
        except Exception as e:
            text = f"Image generation error: {str(e)}"
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}

    # --- Normal chat ---
    history = get_recent(cid, limit=24)
    system = BASE_SYSTEM + ("\n" + FUN_SYSTEM if fun_mode else "")

    messages = [{"role": "system", "content": system}]
    for role, content in history:
        messages.append({"role": role, "content": content})

    prov: ProviderName = provider or DEFAULT_PROVIDER  # type: ignore

    try:
        out = await llm_chat(
            messages,
            provider=prov,
            temperature=text_temperature if text_temperature is not None else (0.9 if fun_mode else 0.7),
            max_tokens=text_max_tokens if text_max_tokens is not None else 900,
            base_url=ollama_base_url if prov == "ollama" else None,
            model=ollama_model if prov == "ollama" else None,
        )
    except Exception as e:
        # Don't crash the API; return a stable response
        err = f"LLM error ({prov}): {str(e)}"
        add_message(cid, "assistant", err)
        return {"conversation_id": cid, "text": err, "media": None}

    # Robust parsing
    text = (
        (out.get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
        or "…"
    )

    add_message(cid, "assistant", text)
    return {"conversation_id": cid, "text": text, "media": None}
