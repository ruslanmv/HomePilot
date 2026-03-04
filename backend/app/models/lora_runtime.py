"""
LoRA Runtime — Builds LoRA prompt tags for injection into the generation pipeline.

Additive module (Golden Rule 1.0).
Does NOT modify existing generation code; it provides helpers that can be
called optionally by the edit/generation layer.
"""

from __future__ import annotations

from typing import Dict, List

# Maximum LoRAs that can be stacked (VRAM guard for <12 GB GPUs)
MAX_LORA_STACK = 4


def build_lora_prompt(loras: List[Dict]) -> str:
    """Build a ComfyUI-compatible LoRA prompt fragment.

    Each enabled LoRA produces: ``<lora:model_id:weight>``

    Args:
        loras: list of dicts with ``id``, ``enabled`` (bool), ``weight`` (float).

    Returns:
        Space-separated LoRA tags string, or empty string if none are enabled.

    Raises:
        ValueError: if more than MAX_LORA_STACK LoRAs are enabled.
    """
    active = [lr for lr in loras if lr.get("enabled")]

    if len(active) > MAX_LORA_STACK:
        raise ValueError(
            f"Too many LoRAs enabled ({len(active)}). "
            f"Maximum is {MAX_LORA_STACK} for <12 GB VRAM safety."
        )

    tags = [
        f"<lora:{lr['id']}:{lr.get('weight', 0.8):.2f}>"
        for lr in active
    ]
    return " ".join(tags)
