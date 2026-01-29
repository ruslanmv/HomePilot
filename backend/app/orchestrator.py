# homepilot/backend/app/orchestrator.py
from __future__ import annotations

import json
import random
import re
import uuid
from typing import Any, Dict, Optional, Literal

from .comfy import run_workflow
from .llm import chat as llm_chat
from .prompts import BASE_SYSTEM, FUN_SYSTEM
from .storage import add_message, get_recent
from .config import DEFAULT_PROVIDER, ProviderName, LLM_MODEL, LLM_BASE_URL, OLLAMA_MODEL, OLLAMA_BASE_URL
from .defaults import DEFAULT_NEGATIVE_PROMPT, enhance_negative_prompt
from .model_config import get_model_settings, get_architecture, MODEL_ARCHITECTURES

# Import specialized handlers
from .search import run_search
from .projects import run_project_chat
from .edit_flags import parse_edit_flags, build_edit_workflow_vars, determine_workflow

IMAGE_RE = re.compile(r"\b(imagine|generate|create|draw|make)\b.*\b(image|picture|photo|art)\b", re.I)
EDIT_RE = re.compile(r"\b(edit|inpaint|replace|remove|change)\b", re.I)
ANIM_RE = re.compile(r"\b(animate|make (a )?video|image\s*to\s*video)\b", re.I)
URL_RE = re.compile(r"(https?://\S+)")


def _map_ref_strength_to_denoise(ref_strength: Optional[float]) -> float:
    """
    Map user-friendly reference strength (0..1) to ComfyUI denoise value.

    UI uses 0..1:
      0.0 => very similar to reference
      1.0 => more creative (less reference influence)

    Comfy img2img uses denoise ~ 0.15..0.85
      Lower denoise = more similar to input
      Higher denoise = more variation
    """
    if ref_strength is None:
        return 0.35  # Default: balanced similarity
    try:
        s = float(ref_strength)
    except (TypeError, ValueError):
        return 0.35
    # Clamp to 0..1
    s = max(0.0, min(1.0, s))
    # Map to denoise range 0.15..0.85
    return 0.15 + (0.70 * s)


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


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Robustly extract JSON from LLM response text.
    Handles: markdown code blocks, partial JSON, truncated responses.
    """
    if not text:
        return None

    # Strip markdown code blocks if present
    if "```" in text:
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)
        if json_lines:
            text = "\n".join(json_lines).strip()

    # Try direct JSON parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find and extract JSON object {...}
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # Try to fix common JSON issues (truncated strings, missing quotes)
    # Extract the prompt field even if JSON is malformed
    import re
    prompt_match = re.search(r'"prompt"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text)
    if prompt_match:
        prompt_value = prompt_match.group(1)
        # Unescape common escapes
        prompt_value = prompt_value.replace('\\"', '"').replace('\\n', '\n')
        return {"prompt": prompt_value}

    return None


async def _refine_prompt(
    user_prompt: str,
    provider: ProviderName,
    provider_base_url: Optional[str] = None,
    provider_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Use LLM to refine user's casual prompt into a detailed image generation prompt.
    Returns dict with: prompt, negative_prompt, aspect_ratio, style

    IMPORTANT: On any failure, returns the ORIGINAL user_prompt to preserve user intent.
    """
    print(f"[_refine_prompt] Calling LLM to refine prompt...")
    print(f"[_refine_prompt] Original user prompt: '{user_prompt[:100]}...'")
    print(f"[_refine_prompt] Provider: {provider}, Base URL: {provider_base_url}, Model: {provider_model}")

    # Default fallback - always preserves user's original prompt
    # Uses centralized DEFAULT_NEGATIVE_PROMPT from defaults.py
    fallback_result = {
        "prompt": user_prompt,
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
        "aspect_ratio": "1:1",
        "style": "photorealistic",
    }

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
            max_tokens=500,  # Increased from 300 to avoid truncation
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

        if not response_text:
            print(f"[_refine_prompt] WARNING: Empty LLM response, using original prompt")
            return fallback_result

        print(f"[_refine_prompt] Raw LLM response: '{response_text[:300]}...'")

        # Try to parse JSON robustly
        print(f"[_refine_prompt] Parsing JSON...")
        refined = _extract_json_from_text(response_text)

        if refined and refined.get("prompt"):
            refined_prompt = refined.get("prompt", "").strip()
            if refined_prompt:
                # CRITICAL: Always enhance the negative prompt to include anti-duplicate terms
                # The LLM often returns weak negatives like "avoid blurry" - we need to fix that
                llm_negative = refined.get("negative_prompt", "")
                enhanced_negative = enhance_negative_prompt(llm_negative)

                result_dict = {
                    "prompt": refined_prompt,
                    "negative_prompt": enhanced_negative,
                    "aspect_ratio": refined.get("aspect_ratio", "1:1"),
                    "style": refined.get("style", "photorealistic"),
                }
                print(f"[_refine_prompt] SUCCESS: Refined prompt: '{result_dict['prompt'][:100]}...'")
                print(f"[_refine_prompt] LLM negative: '{llm_negative}' -> Enhanced: '{enhanced_negative[:80]}...'")
                return result_dict

        # JSON parsing failed or prompt field empty
        print(f"[_refine_prompt] WARNING: JSON parsing failed or empty prompt, using original")
        return fallback_result

    except Exception as e:
        # If refinement fails, return original user prompt (never lose user's intent)
        print(f"[_refine_prompt] ERROR: {type(e).__name__}: {e}")
        import traceback
        print(f"[_refine_prompt] Traceback: {traceback.format_exc()}")
        print(f"[_refine_prompt] FALLBACK: Using original user prompt")
        return fallback_result


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
    img_aspect_ratio: Optional[str] = None,  # Accept aspect ratio from frontend
    img_steps: Optional[int] = None,
    img_cfg: Optional[float] = None,
    img_seed: Optional[int] = None,
    img_model: Optional[str] = None,
    img_batch_size: Optional[int] = None,
    img_preset: Optional[str] = None,  # Accept preset from frontend ("low", "med", "high", "custom")
    vid_seconds: Optional[int] = None,
    vid_fps: Optional[int] = None,
    vid_motion: Optional[str] = None,
    vid_model: Optional[str] = None,
    vid_steps: Optional[int] = None,
    vid_cfg: Optional[float] = None,
    vid_denoise: Optional[float] = None,
    vid_seed: Optional[int] = None,
    nsfw_mode: Optional[bool] = None,
    prompt_refinement: Optional[bool] = True,
    img_reference: Optional[str] = None,  # Reference image URL for img2img
    img_ref_strength: Optional[float] = None,  # Reference strength 0..1 (0=similar, 1=creative)
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
            detected_model_type = None

            if vid_model:
                # Map model filename or short name to workflow
                # Support both full filenames and short names
                vid_model_lower = vid_model.lower()

                # Detect model type from filename
                if "ltx" in vid_model_lower or "ltx-video" in vid_model_lower:
                    detected_model_type = "ltx"
                    video_workflow_name = "img2vid-ltx"
                elif "svd" in vid_model_lower:
                    detected_model_type = "svd"
                    video_workflow_name = "img2vid"
                elif "wan" in vid_model_lower:
                    detected_model_type = "wan"
                    video_workflow_name = "img2vid-wan"
                elif "mochi" in vid_model_lower:
                    detected_model_type = "mochi"
                    video_workflow_name = "img2vid-mochi"
                elif "hunyuan" in vid_model_lower:
                    detected_model_type = "hunyuan"
                    video_workflow_name = "img2vid-hunyuan"
                elif "cogvideo" in vid_model_lower:
                    detected_model_type = "cogvideo"
                    video_workflow_name = "img2vid-cogvideo"
                else:
                    # Legacy short name mapping
                    video_workflow_map = {
                        "svd": "img2vid",
                        "wan-2.2": "img2vid-wan",
                        "seedream": "img2vid-seedream",
                    }
                    video_workflow_name = video_workflow_map.get(vid_model, "img2vid")

            # Calculate frames from seconds - use model-specific fps
            # LTX-Video works best with 24 fps, others default to 8 fps
            if detected_model_type == "ltx":
                fps = 24
            else:
                fps = 8
            seconds = vid_seconds if vid_seconds is not None else 4
            frames = seconds * fps

            # LTX-Video requires frames >= 9 (minimum for the node)
            if detected_model_type == "ltx" and frames < 9:
                frames = 9

            # Build workflow variables with defaults for advanced parameters
            workflow_vars = {
                "image_path": image_url,
                "prompt": text_in.replace("animate", "").strip() or "smooth natural motion",
                "motion": vid_motion if vid_motion is not None else "medium",
                "seconds": seconds,
                "frames": frames,
                "fps": fps,
                "seed": vid_seed if vid_seed is not None else random.randint(0, 2**32 - 1),
                # Advanced parameters with sensible defaults
                "steps": vid_steps if vid_steps is not None else 40,
                "cfg": vid_cfg if vid_cfg is not None else 3.5,
                "denoise": vid_denoise if vid_denoise is not None else 0.85,
            }

            res = run_workflow(video_workflow_name, workflow_vars)
            video_url = (res.get("videos") or [None])[0]
            images = res.get("images") or []

            # If no video, check for animated images (WEBP/GIF from SaveAnimatedWEBP)
            if not video_url and images:
                # Animated WEBP/GIF files should be treated as videos
                # URL format: http://.../view?filename=xxx.webp&subfolder=&type=output
                for img in images:
                    img_lower = img.lower()
                    if '.webp' in img_lower or '.gif' in img_lower:
                        video_url = img
                        break

            if video_url:
                text = "Here's your animated video!"
                media = {
                    "video_url": video_url,
                    "seed": workflow_vars["seed"],
                    "model": vid_model,
                }
                add_message(cid, "assistant", text, media)
                return {"conversation_id": cid, "text": text, "media": media}
            elif images:
                # Fall back to showing frames if no animated output
                text = f"Generated {len(images)} frames."
                media = {"images": images}
                add_message(cid, "assistant", text, media)
                return {"conversation_id": cid, "text": text, "media": media}
            else:
                raise RuntimeError("No video or images returned from workflow")
        except FileNotFoundError as e:
            error_str = str(e)
            # Provide helpful messages based on detected model type
            if detected_model_type == "ltx":
                text = (
                    "LTX-Video workflow not found. LTX-Video requires the ComfyUI-LTXVideo custom nodes. "
                    "Install them via ComfyUI Manager or from: https://github.com/Lightricks/ComfyUI-LTXVideo\n\n"
                    "After installing, restart ComfyUI and try again."
                )
            elif "svd.safetensors" in error_str.lower() or "model" in error_str.lower():
                text = "Video generation requires a video model. Install one from Settings > Models > Video tab."
            else:
                text = f"Video workflow error: {error_str}"
            add_message(cid, "assistant", text)
            return {"conversation_id": cid, "text": text, "media": None}
        except Exception as e:
            error_str = str(e)
            # Check for model-specific errors
            if "ltx" in error_str.lower() and ("not found" in error_str.lower() or "class_type" in error_str.lower()):
                text = (
                    "LTX-Video generation failed. This model requires ComfyUI-LTXVideo custom nodes.\n\n"
                    "Install via ComfyUI Manager or from: https://github.com/Lightricks/ComfyUI-LTXVideo\n"
                    "Then restart ComfyUI and try again."
                )
            elif "svd.safetensors" in error_str or "CLIP_VISION" in error_str or "SVD_img2vid" in error_str:
                text = (
                    "SVD (Stable Video Diffusion) model is not installed. "
                    "Either install SVD from Settings > Models > Video, or select a different video model like LTX-Video."
                )
            elif "ckpt_name" in error_str and "not in" in error_str:
                # Model not found in ComfyUI's checkpoint list
                text = (
                    f"Video model not found in ComfyUI. The selected model may not be installed correctly.\n\n"
                    f"Please verify the model file exists in your ComfyUI models folder and restart ComfyUI."
                )
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

        # Parse edit flags from user instruction (e.g., --steps 30 --cfg 6.5)
        clean_prompt, flags = parse_edit_flags(text_in)

        # Build workflow variables using parsed flags
        workflow_vars = build_edit_workflow_vars(
            image_url=image_url,
            prompt=clean_prompt,
            flags=flags,
            negative_prompt=DEFAULT_NEGATIVE_PROMPT,
        )

        # Determine which workflow to use based on flags
        workflow_name = determine_workflow(flags, clean_prompt)

        print(f"[EDIT] === EDIT REQUEST ===")
        print(f"[EDIT] Original instruction: '{text_in[:100]}...'")
        print(f"[EDIT] Cleaned prompt: '{clean_prompt[:100]}...'")
        print(f"[EDIT] Workflow: {workflow_name}")
        print(f"[EDIT] Mode: {flags.mode}, Steps: {flags.steps}, CFG: {flags.cfg}, Denoise: {flags.denoise}")

        try:
            res = run_workflow(workflow_name, workflow_vars)
            images = res.get("images", []) or []
            text = "Done."
            media = {
                "images": images,
                "edit_settings": flags.to_dict(),  # Include settings used in response
            } if images else None
            add_message(cid, "assistant", text, media)
            return {"conversation_id": cid, "text": text, "media": media}
        except FileNotFoundError as e:
            # Fallback to default edit workflow if specialized workflow not found
            print(f"[EDIT] Workflow '{workflow_name}' not found, falling back to 'edit'")
            res = run_workflow("edit", {
                "image_path": image_url,
                "prompt": clean_prompt,
                "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
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
                    # _refine_prompt handles all logging internally and always preserves user intent on failure
                    refined = await _refine_prompt(
                        text_in,
                        provider=prov,
                        provider_base_url=refine_base_url,
                        provider_model=refine_model,
                    )
                    # Log final result (whether refined or fallback)
                    print(f"[PROMPT_REFINE] Final prompt: '{refined.get('prompt', '')[:100]}...'")
                    print(f"[PROMPT_REFINE] Negative: '{refined.get('negative_prompt', '')}', Style: {refined.get('style')}, Aspect: {refined.get('aspect_ratio')}")
                except Exception as e:
                    # Fallback to direct mode if refinement fails (e.g., Ollama unavailable)
                    print(f"[PROMPT_REFINE] EXCEPTION: {e}")
                    print(f"[PROMPT_REFINE] Using original prompt directly")
                    refined = {
                        "prompt": text_in,
                        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,  # Use centralized default
                        "aspect_ratio": "1:1",
                        "style": "photorealistic",
                    }
            else:
                # Direct mode: use user prompt without refinement
                print(f"[PROMPT_REFINE] Direct mode (refinement disabled)")
                refined = {
                    "prompt": text_in,
                    "negative_prompt": DEFAULT_NEGATIVE_PROMPT,  # Use centralized default
                    "aspect_ratio": "1:1",
                    "style": "photorealistic",
                }

            # =================================================================
            # DYNAMIC PRESET SYSTEM - Prevents "two heads" issue
            # =================================================================
            # The root cause of duplicate subjects is SD1.5 models generating
            # at SDXL resolutions (1024x1024). We use get_model_settings() to
            # automatically select the correct dimensions based on model architecture.

            # Determine model to use (default to dreamshaper for SD1.5)
            model_filename = img_model or "dreamshaper_8.safetensors"

            # Handle short names -> full filenames
            short_name_map = {
                "sdxl": "sd_xl_base_1.0.safetensors",
                "flux-schnell": "flux1-schnell.safetensors",
                "flux-dev": "flux1-dev.safetensors",
                "pony-xl": "ponyDiffusionV6XL.safetensors",
                "sd15-uncensored": "dreamshaper_8.safetensors",
            }
            if model_filename in short_name_map:
                model_filename = short_name_map[model_filename]

            # Get aspect ratio: prefer explicit from frontend, then LLM refinement, then default
            # This allows the UI aspect ratio picker to override LLM suggestions
            aspect_ratio = img_aspect_ratio or refined.get("aspect_ratio", "1:1")
            # IMPORTANT: Write back to refined so ComfyUI receives correct aspect_ratio
            refined["aspect_ratio"] = aspect_ratio
            print(f"[IMAGE] Aspect ratio source: {'frontend' if img_aspect_ratio else 'LLM refinement'}")

            # Get architecture-specific settings (width, height, steps, cfg)
            # This is the KEY fix - SD1.5 models get max 768px, SDXL/Flux get 1024px+
            # Use preset from frontend if provided, otherwise default to "med"
            preset_to_use = img_preset or "med"
            model_settings = get_model_settings(model_filename, aspect_ratio, preset=preset_to_use)
            architecture = model_settings["architecture"]

            print(f"[IMAGE] === DYNAMIC PRESET SYSTEM ===")
            print(f"[IMAGE] Model: {model_filename}")
            print(f"[IMAGE] Architecture: {architecture}")
            print(f"[IMAGE] Preset: {preset_to_use}")
            print(f"[IMAGE] Aspect ratio: {aspect_ratio}")
            print(f"[IMAGE] Safe dimensions: {model_settings['width']}x{model_settings['height']}")
            print(f"[IMAGE] Recommended steps: {model_settings['steps']}, CFG: {model_settings['cfg']}")

            # Apply architecture-specific settings based on preset
            # When preset is "low", "med", or "high", use the computed values (ignore stale frontend values)
            # When preset is "custom", use frontend values if provided
            is_custom_preset = preset_to_use == "custom"

            if img_width is None:
                refined["width"] = model_settings["width"]
            else:
                refined["width"] = img_width
                print(f"[IMAGE] User override width: {img_width}")

            if img_height is None:
                refined["height"] = model_settings["height"]
            else:
                refined["height"] = img_height
                print(f"[IMAGE] User override height: {img_height}")

            # Steps and CFG: use preset values unless in custom mode
            if is_custom_preset and img_steps is not None:
                refined["steps"] = img_steps
                print(f"[IMAGE] Custom steps: {img_steps}")
            else:
                refined["steps"] = model_settings["steps"]
                if img_steps is not None and img_steps != model_settings["steps"]:
                    print(f"[IMAGE] Ignoring frontend steps ({img_steps}), using preset {preset_to_use}: {model_settings['steps']}")

            if is_custom_preset and img_cfg is not None:
                refined["cfg"] = img_cfg
                print(f"[IMAGE] Custom CFG: {img_cfg}")
            else:
                refined["cfg"] = model_settings["cfg"]
                if img_cfg is not None and img_cfg != model_settings["cfg"]:
                    print(f"[IMAGE] Ignoring frontend CFG ({img_cfg}), using preset {preset_to_use}: {model_settings['cfg']}")

            if img_seed is not None:
                refined["seed"] = img_seed

            # =================================================================
            # WORKFLOW SELECTION based on architecture
            # =================================================================
            workflow_map = {
                "sd15": "txt2img-sd15-uncensored",
                "sdxl": "txt2img",
                "flux_schnell": "txt2img-flux-schnell",
                "flux_dev": "txt2img-flux-dev",
            }
            workflow_name = workflow_map.get(architecture, "txt2img")

            # Special case: Pony models use SDXL architecture but have their own workflow
            if "pony" in model_filename.lower():
                workflow_name = "txt2img-pony-xl"

            # Set checkpoint override for SD1.5 models (workflow uses {{ckpt_name}} template)
            checkpoint_override = None
            if architecture == "sd15":
                checkpoint_override = model_filename
                refined["ckpt_name"] = checkpoint_override

            print(f"[IMAGE] Workflow selected: {workflow_name}")
            if checkpoint_override:
                print(f"[IMAGE] Checkpoint: {checkpoint_override}")

            # =================================================================
            # REFERENCE IMAGE ROUTING (img2img similar generation)
            # =================================================================
            # If a reference image is provided, switch to edit workflow (img2img)
            # This allows generating similar images based on a reference
            if img_reference:
                print(f"[IMAGE] === REFERENCE IMAGE MODE ===")
                print(f"[IMAGE] Reference URL: {img_reference}")
                print(f"[IMAGE] Reference strength: {img_ref_strength}")

                # Override to use edit workflow (which is img2img)
                workflow_name = "edit"

                # Set up img2img variables
                refined["image_path"] = img_reference
                refined["denoise"] = _map_ref_strength_to_denoise(img_ref_strength)

                # Set default sampler/scheduler for img2img
                refined.setdefault("sampler_name", "euler")
                refined.setdefault("scheduler", "normal")
                refined.setdefault("filename_prefix", "homepilot_ref")

                print(f"[IMAGE] Mapped denoise: {refined['denoise']:.2f}")
                print(f"[IMAGE] Using edit workflow for img2img reference generation")

            # Debug: Log final workflow decision
            print(f"[IMAGE] === FINAL WORKFLOW DECISION ===")
            print(f"[IMAGE] Workflow to run: {workflow_name}")
            print(f"[IMAGE] Checkpoint override: {checkpoint_override}")
            print(f"[IMAGE] Dimensions: {refined.get('width', 'NOT SET')}x{refined.get('height', 'NOT SET')}")
            print(f"[IMAGE] Variables being passed: ckpt_name={refined.get('ckpt_name', 'NOT SET')}")
            if img_reference:
                print(f"[IMAGE] Reference mode: image_path={refined.get('image_path')}, denoise={refined.get('denoise')}")

            # Determine batch size (1, 2, or 4 images like Grok)
            batch_size = min(max(1, img_batch_size or 1), 4)
            print(f"[IMAGE] Batch size: {batch_size}")

            # Run the workflow with refined prompt and parameters
            # If batch_size > 1, run multiple times and aggregate results
            images = []
            seeds_used = []  # Track seeds for each generated image
            for i in range(batch_size):
                batch_refined = refined.copy()

                # IMPORTANT: Always use a random seed unless user explicitly set one
                # This prevents ComfyUI from caching/skipping identical prompts
                # ComfyUI detects duplicate prompt graphs and skips execution,
                # causing "Prompt executed in 0.00 seconds" with no output
                if img_seed is None or img_seed == 0 or img_seed == -1:
                    batch_refined["seed"] = random.randint(1, 2147483647)
                    print(f"[IMAGE] Using random seed: {batch_refined['seed']}")
                else:
                    batch_refined["seed"] = img_seed

                # Track the seed used for this image
                seeds_used.append(batch_refined["seed"])

                print(f"[IMAGE] Generating image {i + 1}/{batch_size}...")
                res = run_workflow(workflow_name, batch_refined)
                batch_images = res.get("images", []) or []
                images.extend(batch_images)

                # Small delay between batch requests to let ComfyUI settle
                if i < batch_size - 1 and batch_size > 1:
                    import time
                    time.sleep(0.5)

            print(f"[IMAGE] Total images generated: {len(images)}")

            # Short Grok-like caption
            text = "Here you go." if images else "Generated."
            # Include the final refined prompt in the response so frontend can store it
            # This is the actual prompt used for image generation
            # Also include generation parameters for reproducibility
            media = {
                "images": images,
                "final_prompt": refined.get("prompt", text_in),  # The actual prompt sent to ComfyUI
                "seed": seeds_used[0] if seeds_used else None,  # Primary seed (for single image)
                "seeds": seeds_used,  # All seeds (for batch)
                "width": refined.get("width"),
                "height": refined.get("height"),
                "steps": refined.get("steps"),
                "cfg": refined.get("cfg"),
                "model": model_filename,
            } if images else None
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
            img_aspect_ratio=payload.get("imgAspectRatio"),  # NEW: Pass aspect ratio
            img_steps=payload.get("imgSteps"),
            img_cfg=payload.get("imgCfg"),
            img_seed=payload.get("imgSeed"),
            img_model=payload.get("imgModel"),
            img_batch_size=payload.get("imgBatchSize"),
            img_preset=payload.get("imgPreset"),  # Pass preset for architecture-aware settings
            vid_seconds=payload.get("vidSeconds"),
            vid_fps=payload.get("vidFps"),
            vid_motion=payload.get("vidMotion"),
            vid_model=payload.get("vidModel"),
            vid_steps=payload.get("vidSteps"),
            vid_cfg=payload.get("vidCfg"),
            vid_denoise=payload.get("vidDenoise"),
            vid_seed=payload.get("vidSeed"),
            nsfw_mode=payload.get("nsfwMode"),
            prompt_refinement=payload.get("promptRefinement", True),
            img_reference=payload.get("imgReference"),
            img_ref_strength=payload.get("imgRefStrength"),
        )
