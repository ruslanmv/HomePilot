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
from .config import DEFAULT_PROVIDER, ProviderName

# Import specialized handlers
from .search import run_search
from .projects import run_project_chat

IMAGE_RE = re.compile(r"\b(imagine|generate|create|draw|make)\b.*\b(image|picture|photo|art)\b", re.I)
EDIT_RE = re.compile(r"\b(edit|inpaint|replace|remove|change)\b", re.I)
ANIM_RE = re.compile(r"\b(animate|make (a )?video|image\s*to\s*video)\b", re.I)
URL_RE = re.compile(r"(https?://\S+)")


def route_request(mode: str, payload: Dict[str, Any]) -> str:
    """
    Mode-centric routing: determines which handler to use

    Modes:
    - chat: Regular conversation (orchestrate)
    - voice: Voice conversation (orchestrate with voice context)
    - search: Web search + summarization (run_search)
    - project: Project-scoped chat (run_project_chat)
    - imagine: Image generation (orchestrate)
    - edit: Image editing (orchestrate)
    - animate: Video generation (orchestrate)

    Returns: handler name
    """
    normalized = (mode or "").strip().lower()

    if normalized == "search":
        return "search"
    elif normalized == "project":
        return "project"
    else:
        # chat, voice, imagine, edit, animate all use orchestrate
        return "orchestrate"


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
    provider_base_url: Optional[str] = None,
    provider_model: Optional[str] = None,
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
            base_url=provider_base_url,
            model=provider_model,
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
    provider_base_url: Optional[str] = None,
    provider_model: Optional[str] = None,
    text_temperature: Optional[float] = None,
    text_max_tokens: Optional[int] = None,
    img_width: Optional[int] = None,
    img_height: Optional[int] = None,
    img_steps: Optional[int] = None,
    img_cfg: Optional[float] = None,
    img_seed: Optional[int] = None,
    img_model: Optional[str] = None,
    vid_seconds: Optional[int] = None,
    vid_fps: Optional[int] = None,
    vid_motion: Optional[str] = None,
    vid_model: Optional[str] = None,
    nsfw_mode: Optional[bool] = None,
    prompt_refinement: Optional[bool] = True,
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

        # Determine which video workflow to use based on selected model
        video_workflow_name = "img2vid"
        if vid_model:
            # Map model name to workflow filename
            video_workflow_map = {
                "svd": "img2vid",
                "wan-2.2": "img2vid-wan",
                "seedream": "img2vid-seedream",
            }
            video_workflow_name = video_workflow_map.get(vid_model, "img2vid")

        res = run_workflow(
            video_workflow_name,
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
            # Optional prompt refinement (enabled by default, can be disabled)
            if prompt_refinement:
                # Get provider for prompt refinement
                prov: ProviderName = provider or DEFAULT_PROVIDER  # type: ignore

                try:
                    # Refine the prompt using LLM (Grok-like behavior)
                    refined = await _refine_prompt(
                        text_in,
                        provider=prov,
                        provider_base_url=provider_base_url,
                        provider_model=provider_model,
                    )
                except Exception as e:
                    # Fallback to direct mode if refinement fails (e.g., Ollama unavailable)
                    print(f"Prompt refinement failed, using direct mode: {e}")
                    refined = {
                        "prompt": text_in,
                        "negative_prompt": "",
                        "aspect_ratio": "1:1",
                        "style": "photorealistic",
                    }
            else:
                # Direct mode: use user prompt without refinement
                refined = {
                    "prompt": text_in,
                    "negative_prompt": "",
                    "aspect_ratio": "1:1",
                    "style": "photorealistic",
                }

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

            # Determine which workflow to use based on selected model
            workflow_name = "txt2img"
            if img_model:
                # Map model name to workflow filename
                workflow_map = {
                    "sdxl": "txt2img",
                    "flux-schnell": "txt2img-flux-schnell",
                    "flux-dev": "txt2img-flux-dev",
                    "pony-xl": "txt2img-pony-xl",
                    "sd15-uncensored": "txt2img-sd15-uncensored",
                }
                workflow_name = workflow_map.get(img_model, "txt2img")

            # Run the workflow with refined prompt and parameters
            res = run_workflow(workflow_name, refined)
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
            base_url=provider_base_url,
            model=provider_model,
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


async def handle_request(mode: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unified entry point for all requests.
    Routes to specialized handlers based on mode.

    Args:
        mode: The mode (chat, search, project, imagine, edit, animate, voice)
        payload: Request payload with all parameters

    Returns:
        Unified response dict with at minimum: conversation_id, text, media
    """
    handler = route_request(mode or "chat", payload)

    if handler == "search":
        # Search mode: web search + summarization
        result = await run_search(payload)
        # Normalize to standard response format
        return {
            "conversation_id": payload.get("conversation_id", str(uuid.uuid4())),
            "text": result.get("summary", ""),
            "media": {
                "type": "search",
                "query": result.get("query", ""),
                "results": result.get("results", [])
            } if result.get("results") else None
        }

    elif handler == "project":
        # Project mode: project-scoped chat
        result = await run_project_chat(payload)
        return {
            "conversation_id": result.get("conversation_id", ""),
            "text": result.get("text", ""),
            "media": result.get("media")
        }

    else:
        # Default: orchestrate (chat, voice, imagine, edit, animate)
        prov = payload.get("provider") or DEFAULT_PROVIDER
        # Backwards-compatible mapping from legacy fields
        base_url = payload.get("provider_base_url")
        model = payload.get("provider_model")
        if not base_url:
            if prov == "ollama":
                base_url = payload.get("ollama_base_url")
            elif prov == "openai_compat":
                base_url = payload.get("llm_base_url")
        if not model:
            if prov == "ollama":
                model = payload.get("ollama_model")
            elif prov == "openai_compat":
                model = payload.get("llm_model")
        return await orchestrate(
            user_text=payload.get("message", ""),
            conversation_id=payload.get("conversation_id"),
            fun_mode=payload.get("fun_mode", False),
            mode=mode,
            provider=prov,
            provider_base_url=base_url,
            provider_model=model,
            text_temperature=payload.get("textTemperature"),
            text_max_tokens=payload.get("textMaxTokens"),
            img_width=payload.get("imgWidth"),
            img_height=payload.get("imgHeight"),
            img_steps=payload.get("imgSteps"),
            img_cfg=payload.get("imgCfg"),
            img_seed=payload.get("imgSeed"),
            img_model=payload.get("imgModel"),
            vid_seconds=payload.get("vidSeconds"),
            vid_fps=payload.get("vidFps"),
            vid_motion=payload.get("vidMotion"),
            vid_model=payload.get("vidModel"),
            nsfw_mode=payload.get("nsfwMode"),
            prompt_refinement=payload.get("promptRefinement", True),
        )
