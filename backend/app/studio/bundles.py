"""
Essay-video model bundles (essay-to-video pipeline).

THE ANALYSIS, encoded as data. Of every diffusion model HomePilot knows
(model_catalog_data.json + comfyui/workflows/ + orchestrator routing), these
are the ones that are compatible with essay-video creation - SFW, license
resolved, a real workflow file, and working name-based routing:

  images  SDXL             CreativeML Open RAIL++-M   fits 12GB native
          Flux.1 Schnell   Apache-2.0                 offloads on 12GB (4-step, still quick)
  video   SVD / SVD-XT     Stability Community        fits 12GB (25 frames)
          LTX-Video 2B     LTX community              fits 12GB native - the 12GB star
          Wan 2.2 TI2V-5B  Apache-2.0                 21.5GB pack -> weight offload on 12GB
          HunyuanVideo Q4  Tencent community (GGUF)   ~10GB pack -> offload on 12GB

Excluded and why: Mochi 1 (A100-class VRAM), CogVideoX (softer output; use
LTX instead on this hardware), Flux.1 Dev (non-commercial license + 12GB),
Pony-XL / uncensored SD1.5 (mature lane - the essay pipeline filters these
out by design, see model_manager.essay_pipeline_models()).

A bundle is an ordered list of EXISTING catalog ids (model_catalog_data.json
stays the single source of URLs) plus the ComfyUI addons they require, plus
generation presets tuned for the target GPU. Reinstalling a bundle re-runs
the same catalog installs - scripts/download.py skips files already on disk,
so it doubles as a repair command.

GPU target: RTX 4080 **Laptop** = 12GB GDDR6 (the desktop 4080 has 16GB -
the two are not the same card, and the presets below say which they mean).

ADDITIVE ONLY - reads the catalog, shells the existing installer, and shares
model_manager's job store; modifies none of them.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .model_manager import _JOBS, _JOBS_LOCK, resolve_license

ComponentRole = Literal["image", "video", "addon"]


class BundleComponent(BaseModel):
    catalog_id: str            # id in model_catalog_data.json (any section)
    role: ComponentRole
    picker_id: str = ""        # id in available_*_models() this enables
    size_gb: float = 0.0       # filled from the catalog at load time
    native_on_12gb: bool = True  # False -> runs via weight offloading (slower)
    note: str = ""


class QualityPreset(BaseModel):
    """Best-practice generation settings for one quality tier on the
    bundle's target GPU. The editor's advanced settings accept all of
    these directly (steps/cfg/resolution via /chat imgSteps etc.)."""
    image_model: str
    image_width: int
    image_height: int
    image_steps: int
    image_cfg: float
    video_model: str
    video_width: int
    video_height: int
    video_frames: int
    video_fps: int
    video_steps: int
    video_cfg: float
    scene_duration_hint_sec: int
    comfyui_flags: str = ""            # launch flags for this tier
    expected_speed: str = ""           # honest render-time expectation
    notes: str = ""


class EssayVideoBundle(BaseModel):
    id: str
    name: str
    description: str
    gpu_target: str
    disk_gb: float = 0.0               # computed from components
    components: List[BundleComponent]
    presets: Dict[str, QualityPreset]  # "high" | "ultra"
    vram_notes: str = ""


# ── Bundle definitions ───────────────────────────────────────────────────────

BUNDLES: Dict[str, EssayVideoBundle] = {
    "essay-video-core": EssayVideoBundle(
        id="essay-video-core",
        name="Essay Video - Core",
        description="The Phase-0 proof path: SDXL stills + SVD-XT motion. "
                    "Runs on any 8GB+ GPU; everything else builds on top.",
        gpu_target="any 8GB+ GPU",
        components=[
            BundleComponent(catalog_id="sd_xl_base_1.0.safetensors", role="image",
                            picker_id="sdxl"),
            BundleComponent(catalog_id="svd_xt.safetensors", role="video",
                            picker_id="svd", note="25-frame img2vid default"),
            BundleComponent(catalog_id="ComfyUI-VideoHelperSuite", role="addon"),
        ],
        presets={
            "high": QualityPreset(
                image_model="sdxl", image_width=1344, image_height=768,
                image_steps=28, image_cfg=6.5,
                video_model="svd", video_width=1024, video_height=576,
                video_frames=25, video_fps=8, video_steps=20, video_cfg=2.5,
                scene_duration_hint_sec=4,
                expected_speed="~30s/still, ~2min/clip on a 12GB laptop 4080",
                notes="Baseline quality; hero shots read better through the "
                      "4080 bundles."),
        },
        vram_notes="Fits 12GB (and 8GB with --lowvram) without offloading.",
    ),

    "essay-video-4080-high": EssayVideoBundle(
        id="essay-video-4080-high",
        name="Essay Video - RTX 4080 Laptop HIGH",
        description="The daily driver for a 12GB laptop 4080: SDXL stills + "
                    "LTX-Video 2B motion, everything native in VRAM, fast "
                    "iteration on full essays.",
        gpu_target="RTX 4080 Laptop (12GB)",
        components=[
            BundleComponent(catalog_id="sd_xl_base_1.0.safetensors", role="image",
                            picker_id="sdxl"),
            BundleComponent(catalog_id="svd_xt.safetensors", role="video",
                            picker_id="svd", note="fallback/compat img2vid"),
            BundleComponent(catalog_id="ltx-video-2b-v0.9.1.safetensors", role="video",
                            picker_id="ltx-video",
                            note="the 12GB sweet spot - fast drafts AND finals"),
            BundleComponent(catalog_id="ComfyUI-VideoHelperSuite", role="addon"),
            BundleComponent(catalog_id="ComfyUI-LTXVideo", role="addon"),
        ],
        presets={
            "high": QualityPreset(
                image_model="sdxl", image_width=1344, image_height=768,
                image_steps=30, image_cfg=6.5,
                video_model="ltx-video", video_width=768, video_height=512,
                video_frames=97, video_fps=24, video_steps=25, video_cfg=3.0,
                scene_duration_hint_sec=4,
                expected_speed="~35s/still, ~1min per 4s clip - fully native VRAM",
                notes="LTX at 24fps/97 frames = ~4s clips; matches the "
                      "pipeline's per-scene beat length."),
            "ultra": QualityPreset(
                image_model="sdxl", image_width=1536, image_height=864,
                image_steps=40, image_cfg=7.0,
                video_model="ltx-video", video_width=1024, video_height=576,
                video_frames=121, video_fps=24, video_steps=30, video_cfg=3.0,
                scene_duration_hint_sec=5,
                comfyui_flags="--preview-method none",
                expected_speed="~1min/still, ~3min per 5s clip on 12GB",
                notes="Highest quality this bundle reaches without weight "
                      "offloading; for Wan/Hunyuan hero shots install the "
                      "ULTRA bundle."),
        },
        vram_notes="Every model here runs natively in 12GB - no offloading, "
                   "no --lowvram needed.",
    ),

    "essay-video-4080-ultra": EssayVideoBundle(
        id="essay-video-4080-ultra",
        name="Essay Video - RTX 4080 Laptop ULTRA",
        description="Adds the hero-shot tier: Wan 2.2 TI2V-5B (best open "
                    "quality-per-compute, Apache-2.0) and HunyuanVideo GGUF "
                    "Q4 for occasional premium shots, plus Flux.1 Schnell "
                    "stills. On 12GB these offload weights to RAM - slower, "
                    "not smaller output. Native fit on a 16GB desktop 4080.",
        gpu_target="RTX 4080 Laptop (12GB, offloading) / RTX 4080 desktop (16GB, native)",
        components=[
            BundleComponent(catalog_id="sd_xl_base_1.0.safetensors", role="image",
                            picker_id="sdxl"),
            BundleComponent(catalog_id="flux1-schnell.safetensors", role="image",
                            picker_id="flux-schnell", native_on_12gb=False,
                            note="4-step stills; offloads on 12GB but stays quick"),
            BundleComponent(catalog_id="ltx-video-2b-v0.9.1.safetensors", role="video",
                            picker_id="ltx-video", note="draft passes before Wan finals"),
            BundleComponent(catalog_id="wan2.2_5b_fp16_pack", role="video",
                            picker_id="wan-2.2", native_on_12gb=False,
                            note="default hero-shot model; expect offloading on 12GB"),
            BundleComponent(catalog_id="hunyuanvideo_t2v_720p_gguf_q4_k_m_pack",
                            role="video", picker_id="hunyuan-video-1.5",
                            native_on_12gb=False,
                            note="occasional premium hero shot; Q4 GGUF + offload"),
            BundleComponent(catalog_id="ComfyUI-VideoHelperSuite", role="addon"),
            BundleComponent(catalog_id="ComfyUI-LTXVideo", role="addon"),
            BundleComponent(catalog_id="ComfyUI-GGUF", role="addon"),
        ],
        presets={
            "high": QualityPreset(
                image_model="flux-schnell", image_width=1344, image_height=768,
                image_steps=4, image_cfg=1.0,
                video_model="ltx-video", video_width=768, video_height=512,
                video_frames=97, video_fps=24, video_steps=25, video_cfg=3.0,
                scene_duration_hint_sec=4,
                expected_speed="stills ~45s (offload), clips ~1min - LTX for volume",
                notes="Flux Schnell wants cfg 1.0 and only 4 steps; don't "
                      "raise either. Use this tier for all non-hero scenes."),
            "ultra": QualityPreset(
                image_model="flux-schnell", image_width=1344, image_height=768,
                image_steps=4, image_cfg=1.0,
                video_model="wan-2.2", video_width=1280, video_height=704,
                video_frames=81, video_fps=24, video_steps=20, video_cfg=5.0,
                scene_duration_hint_sec=3,
                comfyui_flags="--lowvram --preview-method none",
                expected_speed="~10-15min per 3s hero clip on 12GB (offload); "
                               "~4min native on a 16GB desktop 4080",
                notes="Reserve Wan/Hunyuan for the diffusion hero/transition "
                      "scenes only (a minority after the renderer split) - "
                      "diagrams/quotes/CTAs never touch diffusion at all."),
        },
        vram_notes="12GB laptop: Wan 2.2 / Hunyuan / Flux run via ComfyUI "
                   "weight offloading (start ComfyUI with --lowvram for the "
                   "ultra preset). 16GB desktop 4080: native, no flags.",
    ),
}


# ── Catalog integration ──────────────────────────────────────────────────────

def _catalog() -> Dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "model_catalog_data.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _catalog_index() -> Dict[str, Dict[str, Any]]:
    """catalog_id -> entry, across every comfyui section."""
    comfy = _catalog().get("providers", {}).get("comfyui", {})
    out: Dict[str, Dict[str, Any]] = {}
    for section in comfy.values():
        for entry in section:
            if isinstance(entry, dict) and entry.get("id"):
                out[entry["id"]] = entry
    return out


def validate_bundle(bundle: EssayVideoBundle) -> List[str]:
    """Cross-check a bundle against the catalog and license allowlist.
    Returns a list of problems (empty = installable)."""
    problems: List[str] = []
    index = _catalog_index()
    declared_addons = {c.catalog_id for c in bundle.components if c.role == "addon"}

    for comp in bundle.components:
        entry = index.get(comp.catalog_id)
        if entry is None:
            problems.append(f"{comp.catalog_id}: not in model_catalog_data.json")
            continue
        if entry.get("nsfw"):
            problems.append(f"{comp.catalog_id}: nsfw entry - not allowed in essay bundles")
        for required in entry.get("requires_addons") or []:
            if required not in declared_addons:
                problems.append(f"{comp.catalog_id}: requires addon {required} "
                                "which the bundle does not include")
        if comp.role != "addon" and resolve_license(comp.catalog_id) is None \
                and resolve_license(comp.picker_id or "") is None:
            problems.append(f"{comp.catalog_id}: no resolved license row")
    return problems


def get_bundle(bundle_id: str) -> Optional[EssayVideoBundle]:
    bundle = BUNDLES.get(bundle_id)
    if bundle is None:
        return None
    # Fill sizes from the catalog so the API reports real disk cost
    index = _catalog_index()
    total = 0.0
    for comp in bundle.components:
        entry = index.get(comp.catalog_id) or {}
        comp.size_gb = float(entry.get("size_gb") or 0.0)
        total += comp.size_gb
    bundle.disk_gb = round(total, 1)
    return bundle


def list_bundles() -> List[EssayVideoBundle]:
    return [b for bid in BUNDLES if (b := get_bundle(bid))]


def bundle_install_status(bundle: EssayVideoBundle) -> Dict[str, Any]:
    """Which components are already on disk (via the existing scanner)."""
    from ..providers import scan_installed_models
    installed = set()
    for model_type in ("image", "video", "addons"):
        installed.update(scan_installed_models(model_type))
    per_component = {c.catalog_id: (c.catalog_id in installed)
                     for c in bundle.components}
    return {"components": per_component,
            "complete": all(per_component.values())}


# ── Installation (reinstall-safe: download.py skips files on disk) ──────────

def _download_script() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "download.py"


def install_plan(bundle: EssayVideoBundle) -> List[List[str]]:
    """The exact commands an install runs - addons first (models may need
    their custom nodes), then models, all through the existing installer."""
    script = str(_download_script())
    ordered = ([c for c in bundle.components if c.role == "addon"]
               + [c for c in bundle.components if c.role != "addon"])
    return [[sys.executable, script, "--model", c.catalog_id] for c in ordered]


def run_bundle_install(bundle_id: str, log) -> Dict[str, Any]:
    """Execute the plan synchronously (callers wrap in a job thread)."""
    bundle = get_bundle(bundle_id)
    if bundle is None:
        raise ValueError(f"Unknown bundle: {bundle_id}")
    problems = validate_bundle(bundle)
    if problems:
        raise PermissionError("Bundle failed validation: " + "; ".join(problems))

    results = []
    for cmd in install_plan(bundle):
        catalog_id = cmd[-1]
        log(f"installing {catalog_id} ...")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        ok = proc.returncode == 0
        results.append({"catalog_id": catalog_id, "ok": ok,
                        "tail": (proc.stdout or proc.stderr or "")[-400:]})
        log(f"{'done' if ok else 'FAILED'}: {catalog_id}")
        if not ok:
            raise RuntimeError(f"install failed for {catalog_id}: "
                               f"{(proc.stderr or proc.stdout or '')[-400:]}")

    return {"bundle": bundle_id, "installed": results,
            "status": bundle_install_status(bundle)}


def submit_bundle_install(bundle_id: str) -> Dict[str, Any]:
    """Background bundle install; poll via the shared manager job store
    (GET /studio/models/manager/jobs/{id})."""
    bundle = get_bundle(bundle_id)
    if bundle is None:
        raise ValueError(f"Unknown bundle: {bundle_id}")
    problems = validate_bundle(bundle)
    if problems:
        raise PermissionError("Bundle failed validation: " + "; ".join(problems))

    job_id = str(uuid.uuid4())
    job: Dict[str, Any] = {"id": job_id, "kind": "bundle", "status": "running",
                           "params": {"bundle_id": bundle_id}, "error": "",
                           "model": None, "log": [], "started_at": time.time()}
    with _JOBS_LOCK:
        _JOBS[job_id] = job

    def _log(line: str) -> None:
        with _JOBS_LOCK:
            job["log"] = (job["log"] + [line])[-50:]

    def _run() -> None:
        try:
            result = run_bundle_install(bundle_id, _log)
            with _JOBS_LOCK:
                job["status"] = "done"
                job["model"] = result
        except Exception as e:
            with _JOBS_LOCK:
                job["status"] = "error"
                job["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return {"id": job_id, "status": "running",
            "bundle": bundle_id, "disk_gb": bundle.disk_gb}
