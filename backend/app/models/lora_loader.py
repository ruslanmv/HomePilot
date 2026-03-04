"""
LoRA Loader — Scans the models/loras directory for installed .safetensors files.

Additive module (Golden Rule 1.0).
Does NOT modify any existing model loading or generation code.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Dict, List, Optional

from ..providers import get_comfy_models_path


# LoRA base → compatible checkpoint architectures (mirrors comfy.py COMPAT)
LORA_COMPAT: Dict[str, set] = {
    "sd1.5": {"sd15"},
    "sdxl": {"sdxl", "pony_xl", "noobai_xl", "noobai_xl_vpred"},
    "pony": {"pony_xl", "sdxl", "noobai_xl"},
    "flux": {"flux_schnell", "flux_dev"},
}

# Friendly labels for architecture display
ARCH_LABELS: Dict[str, str] = {
    "sd15": "SD1.5",
    "sdxl": "SDXL",
    "pony_xl": "Pony XL",
    "noobai_xl": "NoobAI XL",
    "noobai_xl_vpred": "NoobAI XL V-Pred",
    "flux_schnell": "Flux Schnell",
    "flux_dev": "Flux Dev",
}

# Friendly labels for LoRA base
LORA_BASE_LABELS: Dict[str, str] = {
    "sd1.5": "SD1.5",
    "sdxl": "SDXL",
    "pony": "Pony",
    "flux": "Flux",
}

# Minimum plausible LoRA file size (100 KB — anything smaller is corrupt/empty)
MIN_LORA_SIZE = 100 * 1024


def get_lora_dir() -> Path:
    """Return the path to the LoRA models directory."""
    return get_comfy_models_path() / "loras"


def _get_registry_lookup() -> Dict[str, "LoRAEntry"]:  # noqa: F821
    """Lazily build id→LoRAEntry map from the registry.

    Keys include both the entry ``id`` and the filename stem, so files
    that were manually renamed still match their registry metadata.
    """
    try:
        from .lora_registry import SFW_LORAS, NSFW_LORAS
        lookup: Dict[str, "LoRAEntry"] = {}
        for e in (*SFW_LORAS, *NSFW_LORAS):
            lookup[e.id] = e
            # Also index by filename stem for manual-download resilience
            stem = e.filename.rsplit(".", 1)[0] if "." in e.filename else e.filename
            if stem != e.id:
                lookup.setdefault(stem, e)
        return lookup
    except Exception:
        return {}


def _fmt_bytes(n: int) -> str:
    """Format byte count as human-readable string."""
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    elif n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def detect_lora_architecture(path: Path) -> Optional[str]:
    """Detect LoRA architecture by inspecting safetensors tensor key names.

    Reads only the JSON header (no tensor data loaded).

    Returns:
        "sd1.5", "sdxl", "flux", or None if unknown.
    """
    if path.suffix.lower() != ".safetensors":
        return None

    try:
        with open(path, "rb") as f:
            header_len_bytes = f.read(8)
            if len(header_len_bytes) < 8:
                return None
            header_len = struct.unpack("<Q", header_len_bytes)[0]
            if header_len > 100 * 1024 * 1024:
                return None
            header_bytes = f.read(header_len)
            if len(header_bytes) < header_len:
                return None
            header = json.loads(header_bytes)
    except Exception:
        return None

    keys = [k for k in header.keys() if k != "__metadata__"]
    if not keys:
        return None

    key_str = " ".join(keys)

    # Flux LoRAs have distinctive "lora_transformer_" or "transformer.single" keys
    if "lora_transformer_" in key_str or "transformer.single" in key_str:
        return "flux"

    # SDXL LoRAs reference transformer_blocks_1+ (multiple blocks per layer)
    # and have "input_blocks_4_1_transformer_blocks_1" or similar patterns.
    # Also SDXL has label_emb / time_embed keys in some LoRAs.
    # SD1.5 only has transformer_blocks_0 per spatial layer.
    has_tb1 = any("transformer_blocks_1" in k for k in keys)

    # Cross-attention dimension check: inspect a cross-attn tensor shape.
    # SD1.5 uses 768-dim context (CLIP ViT-L), SDXL uses 2048-dim.
    for k, meta in header.items():
        if k == "__metadata__":
            continue
        if "attn2" in k and "to_k" in k and "shape" in meta:
            shape = meta["shape"]
            if isinstance(shape, list) and len(shape) == 2:
                context_dim = shape[-1]
                if context_dim == 2048:
                    return "sdxl"
                elif context_dim == 768:
                    return "sd1.5"

    # Fallback: if transformer_blocks_1 keys exist, likely SDXL
    if has_tb1:
        return "sdxl"

    return None


def validate_safetensors_file(path: Path) -> Dict:
    """Validate a safetensors file by reading its header.

    Returns dict with:
      - healthy: True if file is valid, False if corrupt
      - error: error message if corrupt, "" if healthy
      - file_size: size in bytes
      - file_size_human: human-readable size

    Industry standard: safetensors files start with an 8-byte little-endian
    uint64 header length, followed by a JSON header of that length, followed
    by tensor data covering the rest of the file.
    """
    result: Dict = {
        "healthy": False,
        "error": "",
        "file_size": 0,
        "file_size_human": "",
    }

    try:
        file_size = path.stat().st_size
        result["file_size"] = file_size
        result["file_size_human"] = _fmt_bytes(file_size)
    except OSError as e:
        result["error"] = f"Cannot stat file: {e}"
        return result

    # Check 1: minimum size
    if file_size < MIN_LORA_SIZE:
        result["error"] = f"File too small ({result['file_size_human']}) — likely incomplete download"
        return result

    # Check 2: safetensors header structure
    if path.suffix.lower() == ".safetensors":
        # Fast path: use safetensors library if available (same check ComfyUI uses)
        try:
            import safetensors
            safetensors.safe_open(str(path), framework="pt", device="cpu").__enter__()
            # If we get here, safetensors_rust accepted the file
            result["healthy"] = True
            return result
        except ImportError:
            pass  # Fall back to manual header check below
        except Exception as e:
            result["error"] = f"safetensors validation failed: {e}"
            return result

        try:
            with open(path, "rb") as f:
                # Read 8-byte header length
                header_len_bytes = f.read(8)
                if len(header_len_bytes) < 8:
                    result["error"] = "File truncated — cannot read header length"
                    return result

                header_len = struct.unpack("<Q", header_len_bytes)[0]

                # Sanity: header should be < 100MB and < file size
                if header_len > 100 * 1024 * 1024 or header_len > file_size - 8:
                    result["error"] = "Invalid header length — file is corrupt or truncated"
                    return result

                # Read and parse JSON header
                header_bytes = f.read(header_len)
                if len(header_bytes) < header_len:
                    result["error"] = "Incomplete header — file truncated during download"
                    return result

                # Validate it's valid JSON
                header = json.loads(header_bytes)

                # Check 3: verify tensor data fully covers the file
                # Each tensor entry has "data_offsets": [begin, end]
                # The max end offset + 8 + header_len should equal file_size
                data_start = 8 + header_len
                max_end = 0
                has_tensors = False
                for key, meta in header.items():
                    if key == "__metadata__":
                        continue
                    offsets = meta.get("data_offsets")
                    if isinstance(offsets, (list, tuple)) and len(offsets) == 2:
                        has_tensors = True
                        if offsets[1] > max_end:
                            max_end = offsets[1]

                if has_tensors:
                    expected_size = data_start + max_end
                    if file_size != expected_size:
                        result["error"] = (
                            f"File size mismatch — expected {_fmt_bytes(expected_size)} "
                            f"but got {_fmt_bytes(file_size)}. "
                            f"Incomplete or corrupt download"
                        )
                        return result
                elif file_size < data_start:
                    result["error"] = "File size mismatch — incomplete download"
                    return result

        except json.JSONDecodeError:
            result["error"] = "Corrupt header — invalid JSON metadata"
            return result
        except Exception as e:
            result["error"] = f"Header read error: {e}"
            return result

    # For .pt/.ckpt files, basic size check only (no standard header format)
    result["healthy"] = True
    return result


def is_lora_compatible(lora_base: str, checkpoint_arch: str) -> Optional[bool]:
    """Check if a LoRA base is compatible with a checkpoint architecture.

    Returns:
        True  — compatible
        False — incompatible
        None  — unknown (no metadata)
    """
    if not lora_base or not checkpoint_arch:
        return None
    allowed = LORA_COMPAT.get(lora_base, set())
    if not allowed:
        return None
    return checkpoint_arch in allowed


def scan_installed_loras() -> List[Dict]:
    """Scan the loras directory and return a list of installed LoRA files.

    Each entry contains:
      - id: filename without extension
      - filename: full filename
      - path: absolute path
      - enabled: False (default state)
      - weight: 0.8 (default weight)
      - base: LoRA base architecture (e.g. "sd1.5", "sdxl") or "" if unknown
      - base_label: human-readable base label (e.g. "SD1.5") or "" if unknown
      - healthy: True if file is valid, False if corrupt
      - health_error: error description if corrupt, "" if healthy
      - file_size: size in bytes
      - file_size_human: human-readable size string
      - gated: True if LoRA is NSFW/gated (only show when spicy mode enabled)
    """
    lora_dir = get_lora_dir()
    if not lora_dir.exists():
        return []

    registry = _get_registry_lookup()

    results: List[Dict] = []
    for f in sorted(lora_dir.iterdir()):
        if f.suffix.lower() in (".safetensors", ".pt", ".ckpt"):
            lora_id = f.stem
            entry = registry.get(lora_id)
            base = entry.base if entry else ""
            gated = entry.gated if entry else False
            health = validate_safetensors_file(f)
            results.append({
                "id": lora_id,
                "filename": f.name,
                "path": str(f),
                "enabled": False,
                "weight": 0.8,
                "base": base,
                "base_label": LORA_BASE_LABELS.get(base, ""),
                "healthy": health["healthy"],
                "health_error": health["error"],
                "file_size": health["file_size"],
                "file_size_human": health["file_size_human"],
                "gated": gated,
            })

    return results
