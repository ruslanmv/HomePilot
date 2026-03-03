"""
LoRA Model Registry — Additive module (Golden Rule 1.0).

Provides a curated catalog of LoRA models for Stable Diffusion workflows.
LoRAs are lightweight adapter weights that modify checkpoint behavior without
replacing the base model.  They are ideal for <12 GB VRAM GPUs.

Design:
- SFW LoRAs are always returned.
- NSFW / gated LoRAs are only returned when ``spicy_enabled=True``.
- No auto-download.  The registry only describes what is available.
- Does NOT modify any existing model loader or generation pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LoRAEntry:
    """Describes a single LoRA model in the registry."""

    id: str
    name: str
    base: str  # "sd1.5", "sdxl", "flux", "pony"
    source: str  # "civitai", "huggingface"
    model_url: str  # Page URL (for user browsing)
    download_url: str  # Direct safetensors download
    filename: str  # Expected filename inside models/loras/
    description: str = ""
    size_mb: int = 0
    trigger_words: List[str] = field(default_factory=list)
    gated: bool = False  # True → only visible when spicy mode is on
    recommended: bool = False
    recommended_nsfw: bool = False


# =============================================================================
# SFW LoRA CATALOG — always visible
# =============================================================================

SFW_LORAS: List[LoRAEntry] = [
    # --- SD 1.5 utility LoRAs ---
    LoRAEntry(
        id="add_detail",
        name="Add Detail (Detail Tweaker)",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/58390/detail-tweaker-lora-lora",
        download_url="https://civitai.com/api/download/models/62833?type=Model&format=SafeTensor",
        filename="add_detail.safetensors",
        description="Adds or removes fine detail. Use weight 0.5-1.0 for more detail, negative for softer look.",
        size_mb=144,
        trigger_words=[],
        recommended=True,
    ),
    LoRAEntry(
        id="epi_noiseoffset_v2",
        name="epiCRealism Noise Offset v2",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/13941/epicrealism-noise-offset",
        download_url="https://civitai.com/api/download/models/16576?type=Model&format=SafeTensor",
        filename="epi_noiseoffset_v2.safetensors",
        description="Improves contrast and lighting for photorealistic outputs. Works great with realistic checkpoints.",
        size_mb=36,
        trigger_words=[],
    ),
    LoRAEntry(
        id="film_grain_style",
        name="Film Grain Style",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/55653/film-grain-style",
        download_url="https://civitai.com/api/download/models/60149?type=Model&format=SafeTensor",
        filename="film_grain_style.safetensors",
        description="Adds analog film grain texture for cinematic look.",
        size_mb=144,
        trigger_words=["film grain style"],
    ),
    # --- SD 1.5 character LoRAs ---
    LoRAEntry(
        id="kasumigaoka_utaha_v2",
        name="Kasumigaoka Utaha (Saekano) v2",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/26869/kasumigaoka-utaha-saekano",
        download_url="https://civitai.com/api/download/models/350534?type=Model&format=SafeTensor",
        filename="kasumigaoka_utaha_v2.safetensors",
        description="Anime character LoRA for Kasumigaoka Utaha from Saekano. Multiple outfits supported. Weight ~0.7.",
        size_mb=36,
        trigger_words=["aautaha", "long hair", "black hair", "hairband"],
    ),
    # --- SDXL utility LoRAs ---
    LoRAEntry(
        id="more_details_xl",
        name="Add More Details (SDXL)",
        base="sdxl",
        source="civitai",
        model_url="https://civitai.com/models/82098/add-more-details-detail-enhancer-tweaker-lora",
        download_url="https://civitai.com/api/download/models/87153?type=Model&format=SafeTensor",
        filename="more_details_xl.safetensors",
        description="SDXL version of the Detail Tweaker. Enhances texture and sharpness.",
        size_mb=269,
        trigger_words=[],
        recommended=True,
    ),
    LoRAEntry(
        id="lcm_lora_sdxl",
        name="LCM LoRA SDXL",
        base="sdxl",
        source="huggingface",
        model_url="https://huggingface.co/latent-consistency/lcm-lora-sdxl",
        download_url="https://huggingface.co/latent-consistency/lcm-lora-sdxl/resolve/main/pytorch_lora_weights.safetensors",
        filename="lcm_lora_sdxl.safetensors",
        description="Accelerates SDXL to 4-8 steps. Use with LCM sampler for fast generation.",
        size_mb=393,
        trigger_words=[],
    ),
]


# =============================================================================
# NSFW / GATED LoRA CATALOG — only visible when spicy mode enabled
# =============================================================================

NSFW_LORAS: List[LoRAEntry] = [
    # =========================================================================
    # SD 1.5 — NSFW LoRAs
    # =========================================================================
    LoRAEntry(
        id="undressing_clothes_over_head",
        name="Undressing - Clothes Over Head",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/1166008/undressing-clothes-over-head",
        download_url="https://civitai.com/api/download/models/1311797?type=Model&format=SafeTensor",
        filename="undressing_clothes_over_head.safetensors",
        description="Clothes-over-head pose LoRA for SD1.5 checkpoints.",
        size_mb=144,
        trigger_words=["undressing", "clothes over head"],
        gated=True,
        recommended_nsfw=True,
    ),
    LoRAEntry(
        id="undressed_clothes",
        name="Undressed Clothes",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/1541259/undressed-clothes",
        download_url="https://civitai.com/api/download/models/1743884?type=Model&format=SafeTensor",
        filename="undressed_clothes.safetensors",
        description="Outfit removal LoRA for SD1.5.",
        size_mb=144,
        trigger_words=["undressed"],
        gated=True,
        recommended_nsfw=True,
    ),
    LoRAEntry(
        id="hanfu_partially_undressed",
        name="Simple Hanfu (Partially Undressed)",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/765172/a-simple-hanfupartially-undressed",
        download_url="https://civitai.com/api/download/models/855843?type=Model&format=SafeTensor",
        filename="hanfu_partially_undressed.safetensors",
        description="Partially undressed hanfu outfit LoRA.",
        size_mb=144,
        trigger_words=["hanfu", "partially undressed"],
        gated=True,
    ),
    LoRAEntry(
        id="real_upskirt_v1",
        name="Real Upskirt - Photorealistic Panties",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/199026/real-upskirt-photorealistic-panties-sfw",
        download_url="https://civitai.com/api/download/models/223922?type=Model&format=SafeTensor",
        filename="real_upskirt_v1.safetensors",
        description="Photorealistic upskirt LoRA for SD1.5. Use with realistic checkpoints.",
        size_mb=144,
        trigger_words=["upskirt", "u_p_s", "panties"],
        gated=True,
        recommended_nsfw=True,
    ),
    LoRAEntry(
        id="real_upskirt_v2",
        name="Real Upskirt 2 - Photorealistic Panties",
        base="sd1.5",
        source="civitai",
        model_url="https://civitai.com/models/202285/real-upskirt-2-photorealistic-panties-sfw",
        download_url="https://civitai.com/api/download/models/227727?type=Model&format=SafeTensor",
        filename="real_upskirt_v2.safetensors",
        description="Enhanced v2 photorealistic upskirt LoRA for SD1.5.",
        size_mb=144,
        trigger_words=["upskirt", "panties"],
        gated=True,
    ),
    # =========================================================================
    # Pony — NSFW LoRAs
    # =========================================================================
    LoRAEntry(
        id="high_waisted_panties_pony",
        name="High-Waisted Panties (Pony)",
        base="pony",
        source="civitai",
        model_url="https://civitai.com/models/556220/high-waisted-panties-pony",
        download_url="https://civitai.com/api/download/models/619046?type=Model&format=SafeTensor",
        filename="high_waisted_panties_pony.safetensors",
        description="High-waisted panties pose LoRA for Pony Diffusion checkpoints.",
        size_mb=144,
        trigger_words=["Highwaistedpanties"],
        gated=True,
        recommended_nsfw=True,
    ),
    # =========================================================================
    # SDXL — NSFW LoRAs
    # =========================================================================
    LoRAEntry(
        id="lift_skirt_exhibitionism_xl",
        name="Lift Skirt Exhibitionism (SDXL)",
        base="sdxl",
        source="civitai",
        model_url="https://civitai.com/models/552204/lift-skirt-exhibitionism",
        download_url="https://civitai.com/api/download/models/614495?type=Model&format=SafeTensor",
        filename="lift_skirt_exhibitionism_xl.safetensors",
        description="Skirt-lifting and exhibitionism pose LoRA for SDXL/Pony checkpoints.",
        size_mb=144,
        trigger_words=["LIFT UP SKIRT", "FROM BELOW", "CURTSEY"],
        gated=True,
    ),
    # =========================================================================
    # Flux — NSFW LoRAs
    # =========================================================================
    LoRAEntry(
        id="voye_spy_v3_flux",
        name="Voye-Spy V3 Beta - Angles View Helper (Flux)",
        base="flux",
        source="civitai",
        model_url="https://civitai.com/models/1424203/voye-spy-v3-beta-angles-view-helper",
        download_url="https://civitai.com/api/download/models/1609896?type=Model&format=SafeTensor",
        filename="voye_spy_v3_flux.safetensors",
        description="Camera angle helper LoRA for Flux.1 D. Supports upskirt, downblouse, low-angle, and spy angles.",
        size_mb=144,
        trigger_words=["upskirt", "innersit", "downblouse", "asspy", "showspy"],
        gated=True,
        recommended_nsfw=True,
    ),
]


# =============================================================================
# PUBLIC API
# =============================================================================

def get_lora_registry(spicy_enabled: bool = False) -> List[Dict]:
    """Return the LoRA catalog as a list of dicts (JSON-friendly).

    Args:
        spicy_enabled: When True, include gated/NSFW entries.
    """
    entries: List[LoRAEntry] = list(SFW_LORAS)
    if spicy_enabled:
        entries.extend(NSFW_LORAS)

    return [_entry_to_dict(e) for e in entries]


def get_lora_by_id(lora_id: str) -> Optional[LoRAEntry]:
    """Look up a single LoRA entry by ID across both SFW and NSFW catalogs."""
    for e in SFW_LORAS:
        if e.id == lora_id:
            return e
    for e in NSFW_LORAS:
        if e.id == lora_id:
            return e
    return None


def get_default_sfw_lora() -> Optional[LoRAEntry]:
    """Return the single recommended SFW LoRA (for ``make download-lora``)."""
    for e in SFW_LORAS:
        if e.recommended:
            return e
    return SFW_LORAS[0] if SFW_LORAS else None


def _entry_to_dict(e: LoRAEntry) -> Dict:
    return {
        "id": e.id,
        "name": e.name,
        "base": e.base,
        "source": e.source,
        "model_url": e.model_url,
        "download_url": e.download_url,
        "filename": e.filename,
        "description": e.description,
        "size_mb": e.size_mb,
        "trigger_words": e.trigger_words,
        "gated": e.gated,
        "recommended": e.recommended,
        "recommended_nsfw": e.recommended_nsfw,
    }
