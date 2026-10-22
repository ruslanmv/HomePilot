"""What the connected models can carry — the gate for Deep research and Heavy's escalation.

A deep-agent run (plan, tool calls over many rounds, long synthesis) needs a strong,
tool-calling model; a 3B local model loops and hallucinates calls. So the strength of the
models on the user's connection is measured, not assumed:

* Ollama: ``/api/tags`` says each model's parameter count.
* OpenAI-compatible gateways (OllaBridge and friends): ``/models`` lists ids; the names carry
  the hints — a size (``gemma4-31b``, ``gpt-oss-120b``) or a frontier family (``claude``,
  ``gemini``, ``gpt``, ``glm-5``, ``kimi``, ``deepseek-v4``).

Tiers: ``high`` (frontier family, or ≥ EXPERT_DEEP_MIN_PARAMS_B parameters), ``medium``
(7B and up), ``low``. Deep research is offered when the best model on the connection is
``high`` (``EXPERT_DEEP_RESEARCH=auto``); ``always`` / ``off`` override.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from .config import EXPERT_CAPABILITY_TTL_S, EXPERT_DEEP_MIN_PARAMS_B, EXPERT_DEEP_RESEARCH, EXPERT_LOCAL_MODEL
from . import providers
from . import state_store
from . import target as target_mod
from .target import ChatTarget

TIER_RANK = {"low": 0, "medium": 1, "high": 2}

# Frontier families: strong and tool-calling whatever the size suffix says.
_FRONTIER = re.compile(
    r"(claude|openai|gpt-?[45o]|gpt-oss|\bo[134]\b|gemini|grok|kimi|glm-?[45]|deepseek-?v[3-9]|"
    r"mistral-large|command-?a|llama-?4|qwen3?-?(?:235|max|coder-?480)|minimax|muse)",
    re.I,
)
# Families that call tools reliably once they are big enough.
_TOOL_FAMILIES = re.compile(
    r"(qwen2\.5|qwen3|llama-?3\.[1-9]|llama-?4|mistral|mixtral|gpt-oss|command|hermes|granite|"
    r"phi-?4|deepseek-?v[3-9]|glm|gemma-?[34]|kimi|claude|openai|gpt|gemini|grok|muse)",
    re.I,
)
# Reasoning distills that answer well but do not call tools (Ollama rejects the field).
_NO_TOOLS = re.compile(r"deepseek-r1", re.I)
_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.I)

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_S = 30.0


@dataclass
class ModelProfile:
    name: str
    params_b: Optional[float]
    tier: str
    tools_likely: bool
    reason: str

    @property
    def rank(self) -> int:
        return TIER_RANK.get(self.tier, 0)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["rank"] = self.rank
        return d


def params_from_name(name: str) -> Optional[float]:
    """``internal-qwen3-8-27b`` → 27, ``gpt-oss-120b`` → 120, ``deepseek-r1:latest`` → None."""
    hits = [float(m.group(1)) for m in _SIZE.finditer(name or "")]
    return max(hits) if hits else None


def profile(name: str, params_b: Optional[float] = None) -> ModelProfile:
    params = params_b if params_b is not None else params_from_name(name)
    frontier = bool(_FRONTIER.search(name or ""))
    no_tools = bool(_NO_TOOLS.search(name or ""))
    tools_likely = (frontier or bool(_TOOL_FAMILIES.search(name or ""))) and not no_tools
    if frontier and (params is None or params >= EXPERT_DEEP_MIN_PARAMS_B or not _SIZE.search(name or "")):
        return ModelProfile(name, params, "high", tools_likely, "frontier family")
    if params is not None and params >= EXPERT_DEEP_MIN_PARAMS_B:
        return ModelProfile(name, params, "high", tools_likely, f"{params:g}B parameters")
    if params is not None and params >= 7:
        return ModelProfile(name, params, "medium", tools_likely, f"{params:g}B parameters")
    if params is None:
        tier = "medium" if tools_likely else "low"
        return ModelProfile(name, None, tier, tools_likely, "size unknown")
    return ModelProfile(name, params, "low", tools_likely, f"{params:g}B parameters")


def best_of(profiles: List[ModelProfile]) -> Optional[ModelProfile]:
    if not profiles:
        return None
    return max(profiles, key=lambda p: (p.rank, 1 if p.tools_likely else 0, p.params_b or 0.0))


def deep_research_enabled(best: Optional[ModelProfile], verified: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``verified``: the probe's findings for ``best`` (see :func:`probe`); a model known to
    reject tools cannot research, whatever its size."""
    mode = EXPERT_DEEP_RESEARCH
    if mode == "always":
        return {"enabled": True, "reason": "EXPERT_DEEP_RESEARCH=always", "model": best.name if best else None}
    if mode == "off":
        return {"enabled": False, "reason": "Deep research is turned off (EXPERT_DEEP_RESEARCH=off).", "model": None}
    if best is None:
        return {"enabled": False, "reason": "No model answered on this connection.", "model": None}
    if best.tier == "high":
        if verified and verified.get("tools") == "no":
            # The harness runs the searches for a model that cannot call tools (deep.py).
            return {"enabled": True, "model": best.name,
                    "reason": f"{best.name} is a high-end model ({best.reason}); it cannot call tools, so HomePilot runs the searches for it."}
        return {"enabled": True, "reason": f"{best.name} is a high-end model ({best.reason}).", "model": best.name}
    return {
        "enabled": False,
        "reason": (
            f"Deep research needs a high-end model (a frontier family or ≥ {EXPERT_DEEP_MIN_PARAMS_B:g}B); "
            f"the strongest here is {best.name} ({best.reason})."
        ),
        "model": None,
    }


def _connection_key(target: Optional[ChatTarget]) -> str:
    if target is None:
        return "ollama|"
    return f"{target.provider}|{target.base_url}"


async def list_profiles(target: Optional[ChatTarget]) -> List[ModelProfile]:
    """Every model on the connection ``target`` names (the default Ollama when None)."""
    if target is None or target.is_ollama:
        rows = await providers.ollama_models_detail(target.base_url if target and target.base_url else None)
        return [profile(r["name"], r.get("params_b")) for r in rows if r.get("name")]
    names = await providers.openai_compat_models(target.base_url, target.api_key)
    return [profile(n) for n in names]


# ── Probes: measured facts, cached in the state store ────────────────────────

PING_TOOL = [{
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Reports that tool calling works. Call it with the given word.",
        "parameters": {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]},
    },
}]


def probe_key(target: Optional[ChatTarget], model: Optional[str]) -> str:
    from .tool_loop import capability_key  # the loop's learned facts use the same key
    return capability_key(target, "local", model)


def verified_for(target: Optional[ChatTarget], model: Optional[str]) -> Optional[Dict[str, Any]]:
    """The probe's findings for this connection and model, when they are on record. A fact the
    tool loop learned by itself (a refusal, a successful call) counts as well."""
    key = probe_key(target, model)
    found = state_store.kv_get(f"probe:{key}")
    if found:
        return found
    learned = state_store.kv_get(f"tools:{key}")
    if learned is not None and isinstance(learned.get("ok"), bool):
        return {"tools": "yes" if learned["ok"] else "no", "json": "unknown", "source": learned.get("source", "observed"),
                "probed_at": learned.get("at")}
    return None


async def probe(target: Optional[ChatTarget], model: Optional[str], *, force: bool = False) -> Dict[str, Any]:
    """Two short requests, once per model: does it return a structured tool call, and does it
    follow a tiny JSON instruction. Findings are kept for EXPERT_CAPABILITY_TTL_S."""
    from .router import dispatch
    from .providers import ToolsUnsupported
    from .tool_loop import remember_tools

    key = probe_key(target, model)
    if not force:
        cached = state_store.kv_get(f"probe:{key}")
        if cached:
            return cached
    result: Dict[str, Any] = {"tools": "unclear", "json": "no", "source": "probe", "probed_at": time.time(), "errors": []}
    with target_mod.using(target):
        try:
            raw = await dispatch(
                [{"role": "system", "content": "You have one tool, ping. When asked, call it; do not answer in prose."},
                 {"role": "user", "content": "Call ping with the word \"pong\"."}],
                "local", model=model, temperature=0.0, max_tokens=64, tools=PING_TOOL,
            )
            calls = (((raw.get("choices") or [{}])[0] or {}).get("message") or {}).get("tool_calls") or []
            result["tools"] = "yes" if calls else "unclear"
        except ToolsUnsupported as exc:
            result["tools"] = "no"
            result["errors"].append(str(exc)[:200])
        except Exception as exc:  # noqa: BLE001
            result["tools"] = "error"
            result["errors"].append(f"{type(exc).__name__}: {exc}"[:200])
        try:
            raw = await dispatch(
                [{"role": "user", "content": 'Reply with exactly this JSON and nothing else: {"ok": true}'}],
                "local", model=model, temperature=0.0, max_tokens=32,
            )
            text = str((((raw.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or "")
            m = re.search(r"\{.*\}", text, flags=re.S)
            result["json"] = "yes" if m and json.loads(m.group(0)).get("ok") is True else "no"
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"{type(exc).__name__}: {exc}"[:200])
    if result["tools"] in ("yes", "no"):
        remember_tools(key, result["tools"] == "yes", source="probe")
    if result["tools"] != "error":
        state_store.kv_set(f"probe:{key}", result, ttl_s=EXPERT_CAPABILITY_TTL_S)
    return result


async def assess(target: Optional[ChatTarget], selected_model: Optional[str] = None, *, run_probe: bool = False) -> Dict[str, Any]:
    """The selected model's profile, the best one on the connection, and the Deep research gate.
    ``run_probe`` measures the selected model's tool calling once (cached) instead of guessing."""
    key = _connection_key(target)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and now - cached["ts"] < _CACHE_TTL_S:
        profiles: List[ModelProfile] = cached["profiles"]
    else:
        profiles = await list_profiles(target)
        _CACHE[key] = {"ts": now, "profiles": profiles}

    selected_name = selected_model or (target.model if target else "") or EXPERT_LOCAL_MODEL
    by_name = {p.name: p for p in profiles}
    selected = by_name.get(selected_name)
    if selected is None:
        stem = selected_name.split(":")[0]
        selected = next((p for p in profiles if p.name.split(":")[0] == stem), None) or profile(selected_name)
    best = best_of(profiles) or selected

    verified = verified_for(target, selected.name)
    if run_probe and verified is None:
        try:
            verified = await probe(target, selected.name)
        except Exception:  # noqa: BLE001
            verified = None
    if verified and verified.get("tools") in ("yes", "no"):
        selected = ModelProfile(selected.name, selected.params_b, selected.tier, verified["tools"] == "yes", selected.reason)
    # The gate judges the model the user chose: it is the model for every mode, Deep research
    # included. ``best`` stays in the answer as information.
    gate = deep_research_enabled(selected, verified)
    return {
        "connection": "ollama" if (target is None or target.is_ollama) else (target.provider or "openai_compat"),
        "selected": selected.as_dict(),
        "best": best.as_dict() if best else None,
        "tier": selected.tier,
        "verified": verified,
        "models": [p.as_dict() for p in sorted(profiles, key=lambda p: (-p.rank, -(p.params_b or 0)))][:40],
        "deep_research": gate,
    }


def stronger(best: Optional[Dict[str, Any]], selected: Dict[str, Any]) -> bool:
    """Whether ``best`` is a meaningful step up from ``selected`` (Heavy's escalation, Deep
    research's model choice): a higher tier, or — below the high tier — the same tier with at
    least twice the known parameters. A high-end model the user picked is never swapped for
    another high-end one."""
    if not best or best.get("name") == selected.get("name"):
        return False
    best_rank, sel_rank = best.get("rank", 0), selected.get("rank", 0)
    if best_rank > sel_rank:
        return True
    if best_rank < sel_rank or sel_rank >= TIER_RANK["high"]:
        return False
    bp, sp = best.get("params_b"), selected.get("params_b")
    return bool(bp and sp and bp >= 2 * sp)


def reset_cache() -> None:
    _CACHE.clear()
