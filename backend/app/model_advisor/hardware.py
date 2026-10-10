"""
The machine HomePilot runs on, as FitLab needs it: usable memory and its bandwidth.

  NVIDIA        nvidia-smi (HomePilot's own reader) → VRAM; bandwidth from FitLab's GPU
                catalogue, matched by name and memory size the way ``fitlab detect`` does
  Apple Silicon unified memory × 0.7 (what Metal can use), bandwidth by chip
  CPU only      no GPU: chat/vision are sized against half the system RAM at DDR speed;
                image and video generation are not suggested

A caller may override the memory (``vram_gb``) to plan for another machine.
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

DATA_DIR = Path(__file__).parent / "data"

# Datacenter cards FitLab's GeForce catalogue does not list (fitlab/hardware.py).
_BW = [("h100", 3350), ("a100", 1555), ("l40", 864), ("rtx 6000", 960), ("a10", 600),
       ("v100", 900), ("p100", 732), ("l4", 300), ("t4", 320)]
_APPLE_BW = [("m4 max", 546), ("m4 pro", 273), ("m4", 120), ("m3 max", 400), ("m3 pro", 150), ("m3", 100),
             ("m2 max", 400), ("m2 pro", 200), ("m2", 100), ("m1 max", 400), ("m1 pro", 200), ("m1", 68)]
CPU_BANDWIDTH_GBS = 50


def _lookup(name: str, table, default=None):
    low = (name or "").lower()
    for key, val in table:
        if key in low:
            return val
    return default


def _catalog() -> list:
    try:
        return json.loads((DATA_DIR / "fitlab_gpus.json").read_text(encoding="utf-8"))["gpus"]
    except Exception:
        return []


def normalize_name(name: str) -> str:
    """Same normalisation as fitlab.gpu_catalog: drop vendor words and sizes, keep Ti/SUPER/laptop."""
    name = re.sub(r"\b(?:nvidia|geforce)\b", "", name, flags=re.I)
    name = re.sub(r"(?<=\d)(?=ti\b)", " ", name, flags=re.I)
    name = re.sub(r"\b(?:gpu|\d+(?:\.\d+)?\s*g(?:b)?)\b", "", name, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def resolve_gpu(name: str, vram_gb: Optional[float]) -> Optional[dict]:
    """The catalogue profile for a detected card, or None when it is ambiguous or unknown."""
    target = normalize_name(name)
    if not target:
        return None
    candidates = [g for g in _catalog() if target in {
        normalize_name(g.get("model", g["name"])), normalize_name(g["name"]),
        *(normalize_name(a) for a in g.get("aliases", []))}]
    if vram_gb is not None:
        candidates = [g for g in candidates if abs(g["vram_gb"] - vram_gb) < 0.6]
    return candidates[0] if len(candidates) == 1 else None


def _nvidia() -> Optional[Dict[str, Any]]:
    try:
        from ..system_resources import _get_gpu_info
        gpu = _get_gpu_info()
    except Exception:
        return None
    if not gpu.get("available") or not gpu.get("vram_total_mb"):
        return None
    name = str(gpu.get("name") or "NVIDIA GPU")
    vram = round(float(gpu["vram_total_mb"]) / 1024, 1)
    profile = resolve_gpu(name, vram)
    bw = profile["bandwidth_gbs"] if profile and profile.get("bandwidth_gbs") else _lookup(name, _BW)
    return {"kind": "nvidia", "name": name, "vram_gb": vram, "bandwidth_gbs": bw,
            "profile_id": profile["id"] if profile else None,
            "note": "" if bw else "Unlisted GPU — speed estimates are unavailable; fit is still exact."}


def _total_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1e9
    except Exception:
        return 0.0


def _apple() -> Optional[Dict[str, Any]]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None
    try:
        chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                              text=True, timeout=2).stdout.strip() or "Apple Silicon"
    except Exception:
        chip = "Apple Silicon"
    total = _total_ram_gb() or 16.0
    return {"kind": "apple", "name": chip, "vram_gb": round(total * 0.7, 1),
            "bandwidth_gbs": _lookup(chip, _APPLE_BW, 120), "profile_id": "apple-m-16",
            "note": f"Unified memory {total:.0f} GB → about {total * 0.7:.0f} GB usable by Metal."}


def detect() -> Dict[str, Any]:
    hw = _nvidia() or _apple()
    if hw:
        return {**hw, "detected": True}
    ram = _total_ram_gb()
    return {"kind": "cpu", "name": platform.processor() or platform.machine() or "CPU",
            "vram_gb": 0.0, "ram_gb": round(ram, 1), "bandwidth_gbs": CPU_BANDWIDTH_GBS,
            "profile_id": "cpu-only", "detected": True,
            "note": "No GPU found — chat models are sized for system RAM; image and video need a GPU."}


def with_override(hw: Dict[str, Any], vram_gb: Optional[float]) -> Dict[str, Any]:
    """Plan for another amount of GPU memory (a GPU of that size, typical bandwidth)."""
    if vram_gb is None:
        return hw
    vram_gb = max(0.0, min(float(vram_gb), 256.0))
    if vram_gb == 0:
        return {**hw, "kind": "cpu", "name": "CPU only (planned)", "vram_gb": 0.0,
                "bandwidth_gbs": CPU_BANDWIDTH_GBS, "profile_id": "cpu-only", "detected": False,
                "note": "Planning for a machine without a GPU."}
    # Typical bandwidth for a card of that size, from the catalogue's desktop cards.
    sized = [g for g in _catalog() if g.get("form_factor") == "desktop" and g.get("bandwidth_gbs")
             and abs(g["vram_gb"] - vram_gb) < 0.6]
    bw = sorted(g["bandwidth_gbs"] for g in sized)[len(sized) // 2] if sized else None
    return {**hw, "kind": "planned", "name": f"{vram_gb:g} GB GPU (planned)", "vram_gb": vram_gb,
            "bandwidth_gbs": bw, "profile_id": None, "detected": False,
            "note": "Planning for a different GPU — typical bandwidth for this memory size."}


def chat_memory_gb(hw: Dict[str, Any]) -> float:
    """Memory a chat model may use: VRAM, or half the system RAM on a CPU-only machine."""
    if hw.get("vram_gb"):
        return float(hw["vram_gb"])
    return round(float(hw.get("ram_gb") or _total_ram_gb()) * 0.5, 1)
