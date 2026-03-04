"""
LoRA Loader — Scans the models/loras directory for installed .safetensors files.

Additive module (Golden Rule 1.0).
Does NOT modify any existing model loading or generation code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from ..providers import get_comfy_models_path


def get_lora_dir() -> Path:
    """Return the path to the LoRA models directory."""
    return get_comfy_models_path() / "loras"


def scan_installed_loras() -> List[Dict]:
    """Scan the loras directory and return a list of installed LoRA files.

    Each entry contains:
      - id: filename without extension
      - filename: full filename
      - path: absolute path
      - enabled: False (default state)
      - weight: 0.8 (default weight)
    """
    lora_dir = get_lora_dir()
    if not lora_dir.exists():
        return []

    results: List[Dict] = []
    for f in sorted(lora_dir.iterdir()):
        if f.suffix.lower() in (".safetensors", ".pt", ".ckpt"):
            results.append({
                "id": f.stem,
                "filename": f.name,
                "path": str(f),
                "enabled": False,
                "weight": 0.8,
            })

    return results
