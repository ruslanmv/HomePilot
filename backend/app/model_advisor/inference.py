# Mirrored from FitLab src/fitlab/inference.py (ranking inference-1.0). Keep the two in step:
# FitLab publishes data/inference_registry.json with it; HomePilot ranks live Hub data with it.
"""Inference lane — which hosted models can HomePilot run right now, and which do people like most?

FITS / RUNS / PLUGS answer "will it run on *my* GPU". This lane answers the question for the
hosted side: models served by Hugging Face Inference Providers, which HomePilot's web edition
(and any HomePilot linked to a Hugging Face account) can run for chat, vision, images and video.

**Compatible** means: at least one provider serves the model *live* for the task HomePilot
calls (`inferenceProviderMapping` on the Hub), and the repo is a model rather than an adapter
(LoRA / PEFT) or a GGUF quantisation that the providers do not run as-is.

**Popularity** combines the Hub's own signals, each log-scaled to 0..1:

    popularity = 0.55·likes + 0.15·downloads + 0.20·trending + 0.10·recency

Likes lead because they are people's votes. Downloads corroborate use, trending captures what is
rising this week, and recency (half-life one year since the last update) keeps a model nobody
maintains from holding the top spot forever. Popular is not the same as best for a task, so the
published lists keep the raw counts beside every score and offer several orders:

    popular   the composite above (the default suggestion)
    likes     most liked first — "ranked by the people"
    trending  the Hub's trending score
    newest    most recently created
    rising    created in the last 120 days, by trending — newer models a likes order would bury

Pure functions only: no network. ``scripts/sync_inference.py`` fetches and publishes;
HomePilot mirrors this module to rank live Hub data the same way.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, Iterable, List, Optional

RANKING_VERSION = "inference-1.0"

#: HomePilot model type → (Hub pipeline tag, provider tasks HomePilot calls for it).
KINDS: Dict[str, Dict[str, Any]] = {
    "chat": {"pipeline_tag": "text-generation", "tasks": {"conversational", "text-generation"}},
    "vision": {"pipeline_tag": "image-text-to-text", "tasks": {"conversational", "image-text-to-text"}},
    "image": {"pipeline_tag": "text-to-image", "tasks": {"text-to-image"}},
    "video": {"pipeline_tag": "text-to-video", "tasks": {"text-to-video"}},
}
ORDERS = ("popular", "likes", "trending", "newest", "rising")

WEIGHTS = {"likes": 0.55, "downloads": 0.15, "trending": 0.20, "recency": 0.10}
LIKE_CAP = 20_000          # likes that saturate the likes term (log scale)
DOWNLOAD_DIGITS = 7        # 10M downloads in 30 days saturate
TREND_CAP = 300            # Hub trending scores above this saturate
RECENCY_HALF_LIFE_DAYS = 365
RISING_MAX_AGE_DAYS = 120

#: Org spellings that are the same publisher. Keys are lower-case.
_ORG_ALIASES = {"meta": "meta-llama", "facebook": "meta-llama", "meta-llama": "meta-llama"}
_ORG_LABELS = {
    "meta-llama": "Meta", "qwen": "Qwen", "mistralai": "Mistral AI", "google": "Google",
    "deepseek-ai": "DeepSeek", "openai": "OpenAI", "microsoft": "Microsoft",
    "black-forest-labs": "Black Forest Labs", "stabilityai": "Stability AI", "wan-ai": "Wan-AI",
    "zai-org": "Z.ai", "moonshotai": "Moonshot AI", "nvidia": "NVIDIA", "ibm-granite": "IBM Granite",
    "tencent": "Tencent", "bytedance": "ByteDance", "tongyi-mai": "Tongyi", "genmo": "Genmo",
}
_ADAPTER_LIBRARIES = {"peft", "gguf"}


def normalize_provider(repo_id: str) -> str:
    """The publisher of a repo, normalised: ``Meta-Llama/…`` and ``meta-llama/…`` are one."""
    org = (repo_id or "").split("/", 1)[0].strip().lower()
    return _ORG_ALIASES.get(org, org)


def provider_label(repo_id: str) -> str:
    org = normalize_provider(repo_id)
    return _ORG_LABELS.get(org) or (repo_id or "").split("/", 1)[0]


def live_providers(model: Dict[str, Any], kind: str) -> List[str]:
    """Inference providers serving this model live for the task HomePilot calls."""
    tasks = KINDS[kind]["tasks"]
    mapping = model.get("inferenceProviderMapping") or []
    if isinstance(mapping, dict):  # older Hub responses: {provider: {status, task}}
        mapping = [{"provider": k, **(v or {})} for k, v in mapping.items()]
    out = []
    for p in mapping:
        if isinstance(p, dict) and p.get("status") == "live" and p.get("task") in tasks and p.get("provider"):
            out.append(str(p["provider"]))
    return sorted(set(out))


def is_adapter(model: Dict[str, Any]) -> bool:
    tags = [str(t).lower() for t in (model.get("tags") or [])]
    if "lora" in tags or "gguf" in tags or any(t.startswith("base_model:adapter:") for t in tags):
        return True
    return str(model.get("library_name") or "").lower() in _ADAPTER_LIBRARIES


def compatible(model: Dict[str, Any], kind: str) -> bool:
    """HomePilot can run it: a live provider for the task, and a model rather than an adapter."""
    return bool(live_providers(model, kind)) and not is_adapter(model)


def _date(value: Any) -> Optional[_dt.datetime]:
    if not value:
        return None
    try:
        return _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(model: Dict[str, Any], now: _dt.datetime, field: str) -> Optional[float]:
    when = _date(model.get(field))
    return None if when is None else max(0.0, (now - when).total_seconds() / 86400)


def _log_norm(value: Any, cap: float) -> float:
    v = max(0.0, float(value or 0))
    return min(math.log10(1 + v) / math.log10(1 + cap), 1.0)


def signals(model: Dict[str, Any], now: _dt.datetime) -> Dict[str, float]:
    """Each popularity signal on 0..1."""
    updated = _age_days(model, now, "lastModified")
    if updated is None:
        updated = _age_days(model, now, "createdAt")
    return {
        "likes": _log_norm(model.get("likes"), LIKE_CAP),
        "downloads": min(math.log10(1 + max(0, int(model.get("downloads") or 0))) / DOWNLOAD_DIGITS, 1.0),
        "trending": _log_norm(model.get("trendingScore"), TREND_CAP),
        "recency": 0.5 ** ((updated if updated is not None else 3 * RECENCY_HALF_LIFE_DAYS) / RECENCY_HALF_LIFE_DAYS),
    }


def popularity(model: Dict[str, Any], now: _dt.datetime) -> float:
    s = signals(model, now)
    return round(sum(WEIGHTS[k] * s[k] for k in WEIGHTS), 4)


def entry(model: Dict[str, Any], kind: str, now: _dt.datetime) -> Dict[str, Any]:
    """One published row: the raw counts beside the score, so nobody has to trust a number blind."""
    repo = str(model.get("id") or model.get("modelId") or "")
    return {
        "id": repo,
        "provider": normalize_provider(repo),
        "provider_label": provider_label(repo),
        "likes": int(model.get("likes") or 0),
        "downloads": int(model.get("downloads") or 0),
        "trending_score": float(model.get("trendingScore") or 0),
        "created_at": model.get("createdAt"),
        "last_modified": model.get("lastModified"),
        "live_providers": live_providers(model, kind),
        "score": popularity(model, now),
    }


def _created_ts(row: Dict[str, Any]) -> float:
    when = _date(row.get("created_at"))
    return when.timestamp() if when else 0.0


_SORT = {
    "popular": lambda r: (-r["score"], -r["likes"], r["id"]),
    "likes": lambda r: (-r["likes"], -r["score"], r["id"]),
    "trending": lambda r: (-r["trending_score"], -r["score"], r["id"]),
    "newest": lambda r: (-_created_ts(r), r["id"]),
    "rising": lambda r: (-r["trending_score"], -r["score"], r["id"]),
}


def rank(models: Iterable[Dict[str, Any]], kind: str, order: str = "popular",
         now: Optional[_dt.datetime] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Compatible models for ``kind`` in ``order``, one row per repo (case-insensitive)."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
    if order not in ORDERS:
        raise ValueError(f"unknown order {order!r}; one of {', '.join(ORDERS)}")
    now = now or _dt.datetime.now(_dt.timezone.utc)
    seen: Dict[str, Dict[str, Any]] = {}
    for m in models:
        if not isinstance(m, dict) or not compatible(m, kind):
            continue
        row = entry(m, kind, now)
        key = row["id"].lower()
        if row["id"] and (key not in seen or row["likes"] > seen[key]["likes"]):
            seen[key] = row
    rows = list(seen.values())
    if order == "rising":
        cutoff = now.timestamp() - RISING_MAX_AGE_DAYS * 86400
        rows = [r for r in rows if _created_ts(r) >= cutoff]
    rows.sort(key=_SORT[order])
    return rows[:limit] if limit else rows


def diversity(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How concentrated a list is on a few publishers — to watch for popularity bias.
    ``top_publisher_share`` is 1.0 when one publisher holds every slot."""
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["provider"]] = counts.get(r["provider"], 0) + 1
    total = sum(counts.values())
    top = max(counts.values()) if counts else 0
    return {"publishers": len(counts), "rows": total,
            "top_publisher_share": round(top / total, 3) if total else 0.0}
