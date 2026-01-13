from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from .config import COMFY_BASE_URL, COMFY_POLL_INTERVAL_S, COMFY_POLL_MAX_S

WORKFLOWS_DIR = Path(os.getenv("COMFY_WORKFLOWS_DIR", "/workflows"))


def _deep_replace(obj: Any, mapping: Dict[str, Any]) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_replace(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_replace(x, mapping) for x in obj]
    if isinstance(obj, str):
        out = obj
        for k, v in mapping.items():
            out = out.replace(f"{{{{{k}}}}}", str(v))
        return out
    return obj


def _load_workflow(name: str) -> Dict[str, Any]:
    p = WORKFLOWS_DIR / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(
            f"Workflow file not found: {p}. "
            f"Mount workflows into {WORKFLOWS_DIR} (docker volume) or set COMFY_WORKFLOWS_DIR."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def _post_prompt(client: httpx.Client, prompt: Dict[str, Any]) -> str:
    url = f"{COMFY_BASE_URL.rstrip('/')}/prompt"
    r = client.post(url, json={"prompt": prompt})
    r.raise_for_status()
    data = r.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id. Response: {data}")
    return str(prompt_id)


def _get_history(client: httpx.Client, prompt_id: str) -> Dict[str, Any]:
    url = f"{COMFY_BASE_URL.rstrip('/')}/history/{prompt_id}"
    r = client.get(url)
    r.raise_for_status()
    return r.json()


def _view_url(filename: str, subfolder: str = "", filetype: str = "output") -> str:
    base = COMFY_BASE_URL.rstrip("/")
    return f"{base}/view?filename={filename}&subfolder={subfolder}&type={filetype}"


def _extract_media(history: Dict[str, Any], prompt_id: str) -> Tuple[List[str], List[str]]:
    images: List[str] = []
    videos: List[str] = []

    entry = history.get(prompt_id)
    if not isinstance(entry, dict):
        return images, videos

    outputs = entry.get("outputs") or {}
    if not isinstance(outputs, dict):
        return images, videos

    for _node_id, node_out in outputs.items():
        if not isinstance(node_out, dict):
            continue

        for img in (node_out.get("images") or []):
            if not isinstance(img, dict):
                continue
            fn = img.get("filename")
            if fn:
                images.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(img.get("subfolder", "")),
                        filetype=str(img.get("type", "output")),
                    )
                )

        for vid in (node_out.get("gifs") or []):
            if not isinstance(vid, dict):
                continue
            fn = vid.get("filename")
            if fn:
                videos.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(vid.get("subfolder", "")),
                        filetype=str(vid.get("type", "output")),
                    )
                )

        for vid in (node_out.get("videos") or []):
            if not isinstance(vid, dict):
                continue
            fn = vid.get("filename")
            if fn:
                videos.append(
                    _view_url(
                        filename=str(fn),
                        subfolder=str(vid.get("subfolder", "")),
                        filetype=str(vid.get("type", "output")),
                    )
                )

    return images, videos


def run_workflow(name: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    workflow = _load_workflow(name)
    prompt_graph = _deep_replace(workflow, variables)

    timeout = httpx.Timeout(60.0, connect=60.0)
    with httpx.Client(timeout=timeout) as client:
        prompt_id = _post_prompt(client, prompt_graph)

        started = time.time()
        while True:
            history = _get_history(client, prompt_id)

            entry = history.get(prompt_id)
            if isinstance(entry, dict) and entry.get("outputs"):
                images, videos = _extract_media(history, prompt_id)
                return {"images": images, "videos": videos, "prompt_id": prompt_id}

            if (time.time() - started) > float(COMFY_POLL_MAX_S):
                raise TimeoutError(
                    f"ComfyUI workflow '{name}' timed out after {COMFY_POLL_MAX_S}s (prompt_id={prompt_id})"
                )

            time.sleep(float(COMFY_POLL_INTERVAL_S))
