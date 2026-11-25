"""
Match model filenames in a workflow to the ones *this* ComfyUI lists.

ComfyUI names a model in a subfolder by its path relative to the model folder, with the
operating system's separator: ``InstantID/diffusion_pytorch_model.safetensors`` on Linux,
``InstantID\\diffusion_pytorch_model.safetensors`` on Windows. HomePilot's workflow files use
``/``, so a Windows-native ComfyUI (docs/design/COMFYUI_RUNTIME.md) rejected them with
"Value not in list". Before a workflow is submitted, each input value that contains a path
separator is compared with that input's allowed values; if only the other-separator spelling
is listed, that spelling is used. Everything else is left as it is.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

_TTL_S = 300.0
_FAILURE_TTL_S = 30.0
# (base_url, node_class) -> (fetched_at, {input_name: [allowed values]})
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, List[str]]]] = {}


def _options_from_info(info: Dict[str, Any]) -> Dict[str, List[str]]:
    """{input_name: [allowed string values]} for the node's combo inputs."""
    out: Dict[str, List[str]] = {}
    inputs = (info or {}).get("input") or {}
    for section in ("required", "optional"):
        for name, spec in (inputs.get(section) or {}).items():
            if not isinstance(spec, (list, tuple)) or not spec:
                continue
            first = spec[0]
            if isinstance(first, list):  # classic: [["a", "b"], {...}]
                values = first
            elif first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):  # newer: ["COMBO", {"options": [...]}]
                values = spec[1].get("options") or []
            else:
                continue
            out[name] = [v for v in values if isinstance(v, str)]
    return out


def node_input_options(base_url: str, node_class: str, timeout: float = 10.0) -> Dict[str, List[str]]:
    """Allowed values of a node's combo inputs, from ``/object_info/<node_class>`` (cached)."""
    key = (base_url.rstrip("/"), node_class)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < (_TTL_S if hit[1] else _FAILURE_TTL_S):
        return hit[1]
    options: Dict[str, List[str]] = {}
    try:
        r = httpx.get(f"{key[0]}/object_info/{quote(node_class)}", timeout=httpx.Timeout(timeout, connect=2.0))
        if r.status_code == 200:
            options = _options_from_info((r.json() or {}).get(node_class) or {})
    except Exception:
        options = {}
    _cache[key] = (now, options)
    return options


def _other_separator(value: str) -> Optional[str]:
    if "/" in value:
        return value.replace("/", "\\")
    if "\\" in value:
        return value.replace("\\", "/")
    return None


def align_model_paths(graph: Dict[str, Any], base_url: str) -> int:
    """Rewrite in place any input whose value names a file the target ComfyUI lists only with
    the other path separator. Returns how many values were changed."""
    changed = 0
    for node in (graph or {}).values():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        inputs = node.get("inputs")
        if not cls or not isinstance(inputs, dict):
            continue
        candidates = {
            k: v for k, v in inputs.items()
            if isinstance(v, str) and ("/" in v or "\\" in v) and "://" not in v
        }
        if not candidates:
            continue
        options = node_input_options(base_url, cls)
        for name, value in candidates.items():
            allowed = options.get(name)
            if not allowed or value in allowed:
                continue
            alt = _other_separator(value)
            if alt and alt in allowed:
                inputs[name] = alt
                changed += 1
    return changed


def clear_cache() -> None:
    _cache.clear()
