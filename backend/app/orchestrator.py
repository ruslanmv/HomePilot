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
from .config import DEFAULT_PROVIDER, ProviderName, LLM_MODEL, LLM_BASE_URL, OLLAMA_MODEL, OLLAMA_BASE_URL

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
    # CRITICAL: Check if project_id is present - if so, route to project handler
    # This enables RAG (document chat) when a project is active
    if payload.get("project_id"):
        return "project"

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
    print(f"[_refine_prompt] Calling LLM to refine prompt...")
    print(f"[_refine_prompt] Provider: {provider}, Base URL: {provider_base_url}, Model: {provider_model}")

    messages = [
        {"role": "system", "content": PROMPT_REFINER_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]

    try:
        print(f"[_refine_prompt] Sending to llm_chat...")
        result = await llm_chat(
            messages,
            provider=provider,
            temperature=0.7,
            max_tokens=300,
            base_url=provider_base_url,
            model=provider_model,
        )
        print(f"[_refine_prompt] LLM response received")

        # Extract the response text
        response_text = (
            (result.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        ).strip()

        print(f"[_refine_prompt] Raw LLM response: '{response_text[:200]}...'")

        # Try to parse as JSON
        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            print(f"[_refine_prompt] Stripping markdown code blocks...")
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
            print(f"[_refine_prompt] After stripping: '{response_text[:200]}...'")

        print(f"[_refine_prompt] Parsing JSON...")
        refined = json.loads(response_text)
        print(f"[_refine_prompt] JSON parsed successfully")

        # Validate and set defaults
        result_dict = {
            "prompt": refined.get("prompt", user_prompt),
            "negative_prompt": refined.get("negative_prompt", "blurry, low quality, distorted"),
            "aspect_ratio": refined.get("aspect_ratio", "1:1"),
            "style": refined.get("style", "photorealistic"),
        }
        print(f"[_refine_prompt] Returning refined prompt: '{result_dict['prompt'][:100]}...'")
        return result_dict

    except Exception as e:
        # If refinement fails, return basic prompt
        print(f"[_refine_prompt] ERROR: {type(e).__name__}: {e}")
        import traceback
        print(f"[_refine_prompt] Traceback: {traceback.format_exc()}")
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
    img_batch_size: Optional[int] = None,
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

        try:
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
                    "image_path": image_url,  # Changed from image_url to image_path to match workflow
                    "motion": vid_motion if vid_motion is not None else "subtle cinematic camera drift",
                    "seconds": vid_seconds if vid_seconds is not None else 6,
                },
            )
            video_url = (res.get("videos") or [None])[0]
            text = "Here you go."
            media = {"video_url": video_url}
            add_message(cid, "assistant", text, media)
            return {"conversation_id": cid, "text": text, "media": media}
        except FileNotFoundError as e:
            error_str = str(e)
            if "svd.safetensors" in error_str.lower() or "model" in error_str.lower():
                text = "Video generation requires the SVD (Stable Video Diffusion) model which is not installed. This is a large (~10GB) specialized model for image-to-video. Currently, only image editing is available."
            else:
                text = f"Video generation error: {error_str}"
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}
        except Exception as e:
            error_str = str(e)
            # Check for SVD-specific errors
            if "svd.safetensors" in error_str or "CLIP_VISION" in error_str or "SVD_img2vid" in error_str:
                text = "Video generation requires the SVD (Stable Video Diffusion) model which is not installed. This feature is currently unavailable. Try using Edit mode instead to modify images."
            else:
                text = f"Video generation error: {error_str}"
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}

    # --- Edit ---
    if (m == "edit") or (image_url and EDIT_RE.search(text_in)):
        if not image_url:
            text = "To edit, upload an image first (or paste an image URL)."
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}

        res = run_workflow("edit", {
            "image_path": image_url,  # Changed from image_url to match workflow
            "prompt": text_in,  # Changed from instruction to match workflow
            "negative_prompt": "blurry, low quality, distorted"  # Added default negative prompt
        })
        images = res.get("images", []) or []
        text = "Done."
        media = {"images": images} if images else None
        add_message(cid, "assistant", text, media)
        return {"conversation_id": cid, "text": text, "media": media}

    # --- Imagine ---
    if (m == "imagine") or IMAGE_RE.search(text_in):
        # Debug: Log received parameters
        print(f"[IMAGE] === IMAGINE REQUEST ===")
        print(f"[IMAGE] Raw img_model parameter: '{img_model}' (type: {type(img_model).__name__})")
        print(f"[IMAGE] img_model is truthy: {bool(img_model)}")

        try:
            # Optional prompt refinement (enabled by default, can be disabled)
            if prompt_refinement:
                # Get provider for prompt refinement - use CHAT provider, NOT image provider
                # IMPORTANT: provider_model may be the IMAGE model (e.g., dreamshaper_8.safetensors)
                # which is NOT an LLM. We must use the proper chat model for refinement.
                prov: ProviderName = provider or DEFAULT_PROVIDER  # type: ignore

                # Determine the correct LLM model for refinement based on provider
                # DO NOT use provider_model as it may be an image model!
                if prov == "ollama":
                    refine_base_url = provider_base_url or OLLAMA_BASE_URL
                    # Use OLLAMA_MODEL if set, otherwise fallback to llama3:8b
                    # Note: Avoid auto-pick which might select deepseek-r1 (has thinking output)
                    refine_model = OLLAMA_MODEL if OLLAMA_MODEL else "llama3:8b"
                elif prov == "openai_compat":
                    refine_base_url = provider_base_url or LLM_BASE_URL
                    refine_model = LLM_MODEL if LLM_MODEL else None
                else:
                    # For other providers (openai, claude), use provider_base_url but NOT provider_model
                    # as provider_model may be the image model
                    refine_base_url = provider_base_url
                    refine_model = None  # Let the provider use its default

                print(f"[PROMPT_REFINE] === Starting prompt refinement ===")
                print(f"[PROMPT_REFINE] User prompt: '{text_in[:100]}...'")
                print(f"[PROMPT_REFINE] Provider: {prov}")
                print(f"[PROMPT_REFINE] Base URL: {refine_base_url}")
                print(f"[PROMPT_REFINE] Model: {refine_model}")
                print(f"[PROMPT_REFINE] (Note: img_model '{img_model}' is NOT used for refinement)")

                try:
                    # Refine the prompt using LLM (Grok-like behavior)
                    refined = await _refine_prompt(
                        text_in,
                        provider=prov,
                        provider_base_url=refine_base_url,
                        provider_model=refine_model,
                    )
                    print(f"[PROMPT_REFINE] SUCCESS! Refined prompt: '{refined.get('prompt', '')[:100]}...'")
                    print(f"[PROMPT_REFINE] Negative prompt: '{refined.get('negative_prompt', '')}'")
                    print(f"[PROMPT_REFINE] Style: {refined.get('style')}, Aspect: {refined.get('aspect_ratio')}")
                except Exception as e:
                    # Fallback to direct mode if refinement fails (e.g., Ollama unavailable)
                    print(f"[PROMPT_REFINE] FAILED: {e}")
                    print(f"[PROMPT_REFINE] Falling back to direct mode with original prompt")
                    refined = {
                        "prompt": text_in,
                        "negative_prompt": "",
                        "aspect_ratio": "1:1",
                        "style": "photorealistic",
                    }
            else:
                # Direct mode: use user prompt without refinement
                print(f"[PROMPT_REFINE] Direct mode (refinement disabled)")
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
            checkpoint_override = None

            if img_model:
                # Map model name to workflow filename
                # Supports both short names (sdxl) and full checkpoint filenames (sd_xl_base_1.0.safetensors)
                workflow_map = {
                    # Short names
                    "sdxl": "txt2img",
                    "flux-schnell": "txt2img-flux-schnell",
                    "flux-dev": "txt2img-flux-dev",
                    "pony-xl": "txt2img-pony-xl",
                    "sd15-uncensored": "txt2img-sd15-uncensored",
                    # SDXL checkpoints
                    "sd_xl_base_1.0.safetensors": "txt2img",
                    "ponyDiffusionV6XL.safetensors": "txt2img-pony-xl",
                    # SD1.5 checkpoints (use sd15-uncensored workflow which supports SD1.5 architecture)
                    "dreamshaper_8.safetensors": "txt2img-sd15-uncensored",
                    "realisticVisionV51.safetensors": "txt2img-sd15-uncensored",
                    "deliberate_v3.safetensors": "txt2img-sd15-uncensored",
                    "epicrealism_pureEvolution.safetensors": "txt2img-sd15-uncensored",
                    "sd15.safetensors": "txt2img-sd15-uncensored",
                    # Flux checkpoints
                    "flux1-schnell.safetensors": "txt2img-flux-schnell",
                    "flux1-dev.safetensors": "txt2img-flux-dev",
                }

                workflow_name = workflow_map.get(img_model, None)

                # Known SD1.5 models that need checkpoint override
                known_sd15_models = [
                    "dreamshaper_8.safetensors",
                    "realisticVisionV51.safetensors",
                    "deliberate_v3.safetensors",
                    "epicrealism_pureEvolution.safetensors",
                    "sd15.safetensors",
                ]

                # If model not in explicit map, try to detect architecture from filename
                if workflow_name is None:
                    model_lower = img_model.lower()

                    # Heuristics to detect model architecture from filename
                    # Flux models
                    if "flux" in model_lower:
                        if "schnell" in model_lower:
                            workflow_name = "txt2img-flux-schnell"
                        else:
                            workflow_name = "txt2img-flux-dev"
                        print(f"[IMAGE] Auto-detected Flux model: {img_model}")

                    # Pony models (usually XL-based)
                    elif "pony" in model_lower:
                        workflow_name = "txt2img-pony-xl"
                        print(f"[IMAGE] Auto-detected Pony model: {img_model}")

                    # SDXL models (look for XL indicators)
                    elif any(x in model_lower for x in ["sdxl", "_xl", "-xl", "xl_"]):
                        workflow_name = "txt2img"
                        print(f"[IMAGE] Auto-detected SDXL model: {img_model}")

                    # SD 1.5 models (common naming patterns from Civitai)
                    elif any(x in model_lower for x in [
                        "sd15", "sd_15", "sd1.5", "1.5",
                        "realistic", "dreamshaper", "deliberate", "epicrealism",
                        "anything", "abyssorangemix", "counterfeit", "chill",
                        "ghostmix", "majicmix", "meinaunreal", "protogen",
                        "revanimated", "unstable", "cyberrealistic", "absolute"
                    ]):
                        workflow_name = "txt2img-sd15-uncensored"
                        checkpoint_override = img_model
                        print(f"[IMAGE] Auto-detected SD1.5 model: {img_model}")

                    # Default to SDXL workflow for unknown models
                    else:
                        workflow_name = "txt2img"
                        print(f"[IMAGE] Unknown model architecture, defaulting to SDXL: {img_model}")

                # For known SD1.5 models or short name
                if img_model in known_sd15_models:
                    checkpoint_override = img_model
                elif img_model == "sd15-uncensored":
                    # Short name used, default to dreamshaper
                    checkpoint_override = "dreamshaper_8.safetensors"
                # For auto-detected SD1.5 models (already set above via heuristics)
                elif workflow_name == "txt2img-sd15-uncensored" and checkpoint_override is None:
                    checkpoint_override = img_model

                # Log model selection for debugging
                print(f"[IMAGE] Model requested: {img_model}")
                print(f"[IMAGE] Workflow selected: {workflow_name}")
                if checkpoint_override:
                    print(f"[IMAGE] Checkpoint to use: {checkpoint_override}")
            else:
                print("[IMAGE] No model specified, using default 'txt2img' workflow")

            # Add checkpoint to variables for SD1.5 workflow (uses {{ckpt_name}} template)
            if checkpoint_override:
                refined["ckpt_name"] = checkpoint_override

            # Debug: Log final workflow decision
            print(f"[IMAGE] === FINAL WORKFLOW DECISION ===")
            print(f"[IMAGE] Workflow to run: {workflow_name}")
            print(f"[IMAGE] Checkpoint override: {checkpoint_override}")
            print(f"[IMAGE] Variables being passed: ckpt_name={refined.get('ckpt_name', 'NOT SET')}")

            # Determine batch size (1, 2, or 4 images like Grok)
            batch_size = min(max(1, img_batch_size or 1), 4)
            print(f"[IMAGE] Batch size: {batch_size}")

            # Run the workflow with refined prompt and parameters
            # If batch_size > 1, run multiple times and aggregate results
            images = []
            for i in range(batch_size):
                # Vary the seed for each image in the batch (unless seed is explicitly set)
                batch_refined = refined.copy()
                if batch_size > 1 and (img_seed is None or img_seed == 0):
                    # Use a different seed for each image in the batch
                    import random
                    batch_refined["seed"] = random.randint(1, 2147483647)

                print(f"[IMAGE] Generating image {i + 1}/{batch_size}...")
                res = run_workflow(workflow_name, batch_refined)
                batch_images = res.get("images", []) or []
                images.extend(batch_images)

            print(f"[IMAGE] Total images generated: {len(images)}")

            # Short Grok-like caption
            text = "Here you go." if images else "Generated."
            media = {"images": images} if images else None
            add_message(cid, "assistant", text, media)
            return {"conversation_id": cid, "text": text, "media": media}

        except FileNotFoundError as e:
            # Distinguish between missing workflows and missing model files
            error_str = str(e)
            if "Workflow file not found" in error_str:
                text = "Image generation is not configured on this server. Please set up ComfyUI workflows."
            elif any(keyword in error_str.lower() for keyword in ["model", "checkpoint", "safetensors", "ckpt"]):
                text = "No models are downloaded yet. Please run 'make download-recommended' to download image generation models (~14GB)."
            else:
                text = f"Image generation error: Required file not found. {error_str}"
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
            img_batch_size=payload.get("imgBatchSize"),
            vid_seconds=payload.get("vidSeconds"),
            vid_fps=payload.get("vidFps"),
            vid_motion=payload.get("vidMotion"),
            vid_model=payload.get("vidModel"),
            nsfw_mode=payload.get("nsfwMode"),
            prompt_refinement=payload.get("promptRefinement", True),
        )
