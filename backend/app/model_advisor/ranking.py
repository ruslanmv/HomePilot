"""
Rank FitLab's models for this machine.

Chat and vision use FitLab's FITS arithmetic (fitlab/estimate.py) at Q4_K_M and an 8K
context, and its ranking v1.1 (scripts/sync_hf.py), evaluated for the detected GPU instead
of FitLab's two reference cards:

    score = 0.30·fit + 0.30·capability + 0.25·momentum + 0.10·speed + 0.05·plugs

Image and video use the media registry's own published weights and per-model components;
only the fit verdict is computed here, from the detected VRAM.

Only models HomePilot can install are suggested: an Ollama tag for chat/vision, a HomePilot
catalogue id for image/video.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set

# fitlab/estimate.py
BPW = {"Q4_K_M": 4.85, "Q8_0": 8.5}
WEIGHTS_OVERHEAD = 1.03
KV_BYTES = 2
RUNTIME_GB = 0.9
TIGHT, OFFLOAD = 0.92, 1.6
EFFICIENCY = 0.62
QUANT, CONTEXT = "Q4_K_M", 8192

# fitlab/scripts/sync_hf.py, ranking_version 1.1
LLM_WEIGHTS = {"fit": 0.30, "capability": 0.30, "momentum": 0.25, "speed": 0.10, "plugs": 0.05}
FIT_SCORE = {"fits": 1.0, "tight": 0.7, "offload": 0.3, "no": 0.0}

MIN_USABLE_TPS = 5.0

KINDS = ("chat", "vision", "image", "video")
_MEDIA_TASKS = {"image": {"text-to-image"}, "video": {"text-to-video", "image-to-video"}}
_LLM_CATEGORY = {"chat": "text-generation", "vision": "image-text-to-text"}


def fit_llm(model: dict, vram_gb: float, bw: Optional[float], quant: str = QUANT, ctx: int = CONTEXT) -> dict:
    a = model.get("arch") or {}
    bpw = BPW[quant]
    w = model["params_b"] * bpw / 8 * WEIGHTS_OVERHEAD
    kv = 2 * a.get("n_layers", 0) * a.get("n_kv_heads", 0) * a.get("head_dim", 0) * ctx * KV_BYTES / 1e9
    est = w + kv + RUNTIME_GB
    if vram_gb <= 0:
        verdict = "no"
    elif est <= vram_gb * TIGHT:
        verdict = "fits"
    elif est <= vram_gb:
        verdict = "tight"
    elif est <= vram_gb * OFFLOAD:
        verdict = "offload"
    else:
        verdict = "no"
    tps = None
    if bw:
        active = model.get("active_params_b") or model["params_b"]
        tps = round(bw * 1e9 / (active * 1e9 * bpw / 8 + kv * 1e9 / ctx * 64) * EFFICIENCY, 1)
    return {"est_gb": round(est, 1), "verdict": verdict, "est_tps": tps}


def verdict_media(vram_gb: float, need: dict, offload_fraction: float = 0.7) -> str:
    if vram_gb >= need["recommended"]:
        return "fits"
    if vram_gb >= need["min"]:
        return "tight"
    if vram_gb >= need["min"] * offload_fraction:
        return "offload"
    return "no"


def _momentum(downloads: int) -> float:
    return min(math.log10(1 + max(0, downloads or 0)) / 7, 1.0)


def _fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _installed(tag: str, installed: Set[str]) -> bool:
    if not tag:
        return False
    if tag in installed:
        return True
    if ":" not in tag:
        return f"{tag}:latest" in installed
    return tag.endswith(":latest") and tag[: -len(":latest")] in installed


_VERDICT_WORDS = {
    "fits": "Fits in {mem:g} GB",
    "tight": "Fits tightly in {mem:g} GB",
    "offload": "Runs with part offloaded to RAM (slower)",
}


def rank_llm(doc: dict, kind: str, hw: Dict[str, Any], memory_gb: float, installed: Set[str],
             limit: int) -> List[Dict[str, Any]]:
    bw = hw.get("bandwidth_gbs")
    profile = hw.get("profile_id")
    measured_all = doc.get("benchmarks_latest") or {}
    compat = doc.get("compat") or {}
    plugs = (sum(1 for r in compat.values() if isinstance(r, dict) and r.get("ok")) / len(compat)) if compat else 0.5
    calib = (doc.get("calibration") or {}).get("estimate_over_measured")
    out = []
    for mid, m in (doc.get("models") or {}).items():
        if m.get("category") != _LLM_CATEGORY[kind] or m.get("status") == "stale":
            continue
        caps = m.get("capabilities") or []
        if not m.get("ollama_tag") or not m.get("arch") or not m.get("params_b") or "embeddings" in caps:
            continue
        f = fit_llm(m, memory_gb, bw)
        if f["verdict"] == "no":
            continue
        measured = measured_all.get(f"{mid}|{profile}") if profile else None
        if measured and measured.get("gen_tps"):
            speed, tps, tps_kind = min(measured["gen_tps"] / 60, 1.0), round(measured["gen_tps"], 1), "measured"
        elif f["est_tps"]:
            speed = min(f["est_tps"] / 60, 1.0) * 0.5
            # FitLab's own calibration: the bandwidth model runs optimistic; report it divided out.
            tps = round(f["est_tps"] / calib, 1) if calib and calib > 1 else f["est_tps"]
            tps_kind = "estimated"
        else:
            speed, tps, tps_kind = 0.0, None, None
        downloads = int((m.get("hf_stats") or {}).get("downloads_30d") or 0)
        capability = min(math.log10(1 + m["params_b"]) / 1.35, 1.0)
        score = (LLM_WEIGHTS["fit"] * FIT_SCORE[f["verdict"]] + LLM_WEIGHTS["capability"] * capability
                 + LLM_WEIGHTS["momentum"] * _momentum(downloads) + LLM_WEIGHTS["speed"] * speed
                 + LLM_WEIGHTS["plugs"] * plugs)
        where = " of RAM" if hw.get("kind") == "cpu" else ""
        reasons = [_VERDICT_WORDS[f["verdict"]].format(mem=memory_gb) + where + f" — needs about {f['est_gb']:g} GB"]
        if tps:
            reasons.append(f"About {tps:g} tokens/s ({tps_kind})")
        if tps is not None and tps < MIN_USABLE_TPS:
            # Below reading speed a chat feels broken; a faster model that fits ranks first.
            score *= 0.6
            reasons.append("Slow on this machine")
        if downloads:
            reasons.append(f"{_fmt_count(downloads)} downloads in the last 30 days")
        out.append({
            "id": mid,
            "name": (m.get("hf_id") or mid).split("/")[-1],
            "kind": kind,
            "hf_id": m.get("hf_id"),
            "license": m.get("license"),
            "params_b": m.get("params_b"),
            "capabilities": caps,
            "verdict": f["verdict"],
            "memory_needed_gb": f["est_gb"],
            "tokens_per_s": tps,
            "tokens_per_s_kind": tps_kind,
            "score": round(score, 4),
            "reasons": reasons,
            "install": {"provider": "ollama", "model_type": "chat" if kind == "chat" else "multimodal",
                        "model_id": m["ollama_tag"]},
            "installed": _installed(m["ollama_tag"], installed),
        })
    out.sort(key=lambda s: (-s["score"], s["id"]))
    return out[:limit]


def rank_media(doc: dict, kind: str, vram_gb: float, installed: Set[str], limit: int) -> List[Dict[str, Any]]:
    scoring = doc.get("scoring") or {}
    weights, fit_score = scoring.get("weights") or {}, scoring.get("fit_score") or FIT_SCORE
    out = []
    for mid, m in (doc.get("models") or {}).items():
        hp = m.get("homepilot")
        if m.get("task") not in _MEDIA_TASKS[kind] or not hp or not m.get("vram_gb"):
            continue
        v = verdict_media(vram_gb, m["vram_gb"])
        if v == "no":
            continue
        c = m.get("components") or {}
        score = weights.get("fit", 0) * fit_score.get(v, 0) + sum(
            weights.get(k, 0) * float(c.get(k, 0)) for k in ("capability", "momentum", "speed"))
        need = m["vram_gb"]
        downloads = int((m.get("hf_stats") or {}).get("downloads_30d") or 0)
        reasons = {
            "fits": [f"Fits in {vram_gb:g} GB — recommended {need['recommended']:g} GB"],
            "tight": [f"Runs in {vram_gb:g} GB (minimum {need['min']:g} GB, recommended {need['recommended']:g} GB)"],
            "offload": [f"Runs in low-VRAM mode only (minimum {need['min']:g} GB) — slow"],
        }[v]
        if downloads:
            reasons.append(f"{_fmt_count(downloads)} downloads in the last 30 days")
        out.append({
            "id": mid,
            "name": m.get("name") or mid,
            "kind": kind,
            "hf_id": m.get("hf_id"),
            "license": m.get("license"),
            "params_b": m.get("params_b"),
            "task": m.get("task"),
            "verdict": v,
            "memory_needed_gb": need["recommended"] if v == "fits" else need["min"],
            "vram_gb": need,
            "download_gb": m.get("download_gb"),
            "score": round(score, 4),
            "reasons": reasons,
            "install": {"provider": hp["provider"], "model_type": hp["model_type"], "model_id": hp["model_id"]},
            "installed": hp["model_id"] in installed,
        })
    out.sort(key=lambda s: (-s["score"], s["id"]))
    return out[:limit]
