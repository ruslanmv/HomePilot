"""
ComfyUI model warmup.

The first image-generation request of a session pays a 30–60 s
cold-start cost while ComfyUI loads the configured checkpoint
from disk into VRAM. On any client with a fixed request-timeout
(browser default, reverse-proxy, gateway) that cold load can
trip a "timed out" error even though the backend eventually
completes successfully.

Best-practice mitigation (used by AWS Bedrock async jobs,
Replicate, OpenAI's image APIs) is to warm the model at server
startup so the first real user request hits an already-loaded
model. We submit a tiny 1-step 64×64 workflow to ComfyUI at boot
— just enough to force the weight-loader path without burning
noticeable GPU time.

This is best-effort and never blocks startup:

* ComfyUI not reachable       → warn, keep going
* Model file missing          → warn, keep going
* Render takes longer than 90s → warn, keep going
* Warmup raises anything else → catch + log

If any of those happen, user requests still work exactly as
before — they just eat the cold-load cost the normal way.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional


log = logging.getLogger(__name__)


_DEFAULT_WARMUP_TIMEOUT_S = 90.0


def warmup_enabled() -> bool:
    """Opt-out via env. Default on so fresh installs get the
    "just works" experience. Set ``INTERACTIVE_WARMUP_IMAGE=false``
    (or equivalent) to skip on boot — useful in CI."""
    raw = os.getenv("INTERACTIVE_WARMUP_IMAGE", "").strip().lower()
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    return True


async def warm_image_model_on_startup() -> None:
    """Submit a tiny txt2img prompt to ComfyUI so the checkpoint
    is resident before the first user request.

    Runs in the background; never blocks server startup.
    Failures are logged at WARNING and swallowed — the user's
    first real request will still succeed, it just won't have
    the warm advantage.
    """
    if not warmup_enabled():
        return

    # Resolve the live image model the same way every other
    # runtime path does, so whatever is in Settings → Providers
    # (or IMAGE_MODEL env) is the one we warm.
    try:
        from .interactive.media_router import resolve_current_image_model
        model = resolve_current_image_model()
    except Exception as exc:  # noqa: BLE001
        log.warning("warmup: couldn't resolve IMAGE_MODEL — skipping (%s)", exc)
        return

    if not model:
        log.info("warmup: IMAGE_MODEL not set — skipping")
        return

    # Architecture dispatch matches Imagine + the new Interactive
    # render_adapter, so we're always testing the same workflow
    # file the first real request will use.
    try:
        from .model_config import detect_architecture_from_filename
        arch = detect_architecture_from_filename(model)
    except Exception:
        arch = "sd15"
    workflow = {
        "sd15": "txt2img-sd15-uncensored",
        "sdxl": "txt2img",
        "flux_schnell": "txt2img-flux-schnell",
        "flux_dev": "txt2img-flux-dev",
        "pony_xl": "txt2img-pony-xl",
        "noobai_xl": "txt2img",
        "noobai_xl_vpred": "txt2img",
    }.get(arch, "txt2img-sd15-uncensored")

    variables: Dict[str, Any] = {
        "prompt": "warmup",
        "positive_prompt": "warmup",
        "negative_prompt": "",
        "aspect_ratio": "1:1",
        "style": "photorealistic",
        "width": 64,
        "height": 64,
        "steps": 1,
        "cfg": 1.0,
        "ckpt_name": model,
        "seed": 1,
    }
    log.info(
        "warmup: preloading image model model=%s workflow=%s",
        model, workflow,
    )
    loop = asyncio.get_event_loop()

    def _go() -> Optional[Dict[str, Any]]:
        try:
            from .comfy import run_workflow  # late import
            return run_workflow(workflow, variables) or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("warmup: render_workflow failed — skipping (%s)", exc)
            return None

    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _go),
            timeout=_DEFAULT_WARMUP_TIMEOUT_S,
        )
        log.info("warmup: image model loaded — first user request will be fast")
    except asyncio.TimeoutError:
        log.warning(
            "warmup: exceeded %.0fs — continuing without warm model",
            _DEFAULT_WARMUP_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("warmup: unexpected error — skipping (%s)", exc)


__all__ = ["warm_image_model_on_startup", "warmup_enabled"]
