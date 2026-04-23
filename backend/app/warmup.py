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
model. We submit a lightweight txt2img workflow at boot using
the same model settings (size/steps/cfg) as normal runtime
requests so warmup validates the real configured path.

``make start`` launches the backend and ComfyUI in parallel, so
the backend reaches its startup event well before ComfyUI's
slow custom-node imports finish (especially on WSL2 /mnt/c).
To avoid a spurious "connection refused" warning, the warmup
waits on a small GET /system_stats probe loop before submitting
— only running the weights-load once ComfyUI is actually
answering HTTP. Generous budget (default 600 s) so a laptop
with InstantID + LTX-Video custom nodes still gets warmed.

This is best-effort and never blocks startup:

* ComfyUI never comes up     → warn after the wait budget
* Model file missing         → warn, keep going
* Render takes longer than 90s → warn, keep going
* Any other exception         → caught + logged

If any of those happen, user requests still work exactly as
before — they just eat the cold-load cost the normal way.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional


log = logging.getLogger(__name__)


_DEFAULT_WARMUP_TIMEOUT_S = 90.0

# Generous readiness budget because WSL2 /mnt/c + heavy custom
# nodes (InstantID, LTX-Video, Impact-Pack) routinely need 60-120s
# just to import. Still bounded so a forever-broken ComfyUI
# doesn't pin an asyncio task until shutdown.
_COMFY_READY_MAX_WAIT_S = 600.0
_COMFY_READY_POLL_INTERVAL_S = 3.0


def _resolve_warmup_checkpoint(model: str) -> str:
    """Resolve the warmup checkpoint to a concrete installed filename.

    Settings may provide either:
      - a real checkpoint filename (``*.safetensors`` / ``*.ckpt``), or
      - a shorthand token (e.g. ``sdxl``) from legacy defaults.

    ComfyUI's ``CheckpointLoaderSimple`` requires a concrete filename
    present on disk. This resolver keeps warmup aligned with current
    settings while avoiding invalid shorthand checkpoint values.
    """
    raw = (model or "").strip()
    if not raw:
        return raw

    # Already a concrete file-like model id → use as-is.
    lower = raw.lower()
    if lower.endswith(".safetensors") or lower.endswith(".ckpt"):
        return raw

    try:
        from .providers import scan_installed_models
        from .model_config import detect_architecture_from_filename

        installed = scan_installed_models("image") or []
        if not installed:
            return raw

        # If token already matches an installed id, keep it.
        if raw in installed:
            return raw

        # Otherwise match by architecture (sd15/sdxl/flux/pony/noobai).
        wanted_arch = detect_architecture_from_filename(raw)
        for candidate in installed:
            if detect_architecture_from_filename(candidate) == wanted_arch:
                log.info(
                    "warmup: mapped image model '%s' -> '%s' (arch=%s)",
                    raw, candidate, wanted_arch,
                )
                return candidate

        # Final fallback: first installed model, still concrete + valid.
        fallback = installed[0]
        log.info(
            "warmup: using fallback installed model '%s' for unresolved setting '%s'",
            fallback, raw,
        )
        return fallback
    except Exception:
        return raw


def warmup_enabled() -> bool:
    """Opt-out via env. Default on so fresh installs get the
    "just works" experience. Set ``INTERACTIVE_WARMUP_IMAGE=false``
    (or equivalent) to skip on boot — useful in CI."""
    raw = os.getenv("INTERACTIVE_WARMUP_IMAGE", "").strip().lower()
    if raw in {"0", "false", "no", "off", "n"}:
        return False
    return True


async def _wait_for_comfy_ready(
    base_url: str,
    *,
    max_wait_s: Optional[float] = None,
    interval_s: Optional[float] = None,
) -> bool:
    """Poll ComfyUI's ``/system_stats`` endpoint until it answers
    200 OK or ``max_wait_s`` elapses.

    ``max_wait_s`` / ``interval_s`` default to the module-level
    ``_COMFY_READY_MAX_WAIT_S`` / ``_COMFY_READY_POLL_INTERVAL_S``
    read at CALL time (not import time) so tests that shrink
    those constants via ``monkeypatch.setattr`` take effect.

    Uses httpx (already a backend dep) with a short per-request
    timeout so a hung ComfyUI doesn't consume the entire wait
    budget on one probe. Returns True when reachable, False on
    overall timeout or unexpected error.
    """
    if max_wait_s is None:
        max_wait_s = _COMFY_READY_MAX_WAIT_S
    if interval_s is None:
        interval_s = _COMFY_READY_POLL_INTERVAL_S

    try:
        import httpx
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("warmup: httpx unavailable — skipping readiness wait (%s)", exc)
        return False

    url = f"{base_url.rstrip('/')}/system_stats"
    deadline = time.monotonic() + max_wait_s
    attempts = 0

    while time.monotonic() < deadline:
        attempts += 1
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    elapsed = max_wait_s - (deadline - time.monotonic())
                    log.info(
                        "warmup: ComfyUI reachable after %.1fs (%d probe%s) — starting warmup",
                        elapsed, attempts, "s" if attempts != 1 else "",
                    )
                    return True
        except Exception:  # noqa: BLE001 — expected during boot
            pass
        # Low-noise log every 10 attempts (~30s default) so operators
        # watching the console can tell what we're waiting on.
        if attempts % 10 == 0:
            log.info(
                "warmup: still waiting for ComfyUI at %s (%d probes)",
                base_url, attempts,
            )
        await asyncio.sleep(interval_s)

    log.warning(
        "warmup: ComfyUI didn't become reachable within %.0fs — skipping warmup",
        max_wait_s,
    )
    return False


async def warm_image_model_on_startup() -> None:
    """Submit a tiny txt2img prompt to ComfyUI so the checkpoint
    is resident before the first user request.

    Runs in the background; never blocks server startup.
    Waits for ComfyUI to be reachable first — ``make start``
    brings the backend up seconds before ComfyUI finishes its
    custom-node imports, and submitting before that lands on a
    "connection refused" stacktrace in the logs.

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
        from .interactive.media_router import (
            resolve_current_comfy_base_url,
            resolve_current_image_model,
        )
        model = resolve_current_image_model()
        comfy_base_url = resolve_current_comfy_base_url()
    except Exception as exc:  # noqa: BLE001
        log.warning("warmup: couldn't resolve IMAGE_MODEL / Comfy URL — skipping (%s)", exc)
        return

    if not model:
        log.info("warmup: IMAGE_MODEL not set — skipping")
        return

    model = _resolve_warmup_checkpoint(model)

    # Step 1: wait for ComfyUI to actually be listening before
    # we try to submit. Addresses the "Connection refused" noise
    # on parallel startup (make start fires backend + ComfyUI at
    # the same time; ComfyUI takes longer to boot).
    ready = await _wait_for_comfy_ready(comfy_base_url)
    if not ready:
        return

    # Step 1.5: if ComfyUI already has recent job history, skip warmup.
    # Typical during uvicorn --reload: ComfyUI stays alive across backend
    # restarts, the checkpoint is still resident in VRAM, and re-running
    # a 30-step SDXL pass on every file-save wastes ~10s of GPU. First-
    # ever startup has empty history, so we still warm up then.
    # Non-fatal: any probe failure falls through to the real warmup.
    try:
        import httpx  # already imported above; cheap re-import
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            r = await client.get(f"{comfy_base_url.rstrip('/')}/history?max_items=1")
            if r.status_code == 200:
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if isinstance(body, dict) and body:
                    log.info("warmup: ComfyUI already warm (history non-empty) — skipping")
                    return
    except Exception:  # noqa: BLE001
        pass

    # Step 2: architecture dispatch matches Imagine + Interactive's
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

    # Use the same dimension/steps/CFG defaults as the real image
    # pipeline so warmup matches runtime settings (model-specific
    # safe sizes) instead of forcing 64x64/1-step.
    width, height, steps, cfg_scale = 512, 512, 25, 7.0
    try:
        from .model_config import get_model_settings
        settings = get_model_settings(model, "1:1", "med")
        width = int(settings.get("width", width))
        height = int(settings.get("height", height))
        steps = int(settings.get("steps", steps))
        cfg_scale = float(settings.get("cfg", cfg_scale))
    except Exception:
        pass

    variables: Dict[str, Any] = {
        "prompt": "warmup",
        "positive_prompt": "warmup",
        "negative_prompt": "",
        "aspect_ratio": "1:1",
        "style": "photorealistic",
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg_scale,
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


__all__ = [
    "warm_image_model_on_startup",
    "warmup_enabled",
    "_wait_for_comfy_ready",
]
