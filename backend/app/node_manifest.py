"""
HomePilot Node Manifest — Phase 1 of the OllaBridge Cloud Mirror.

A localhost-only description of this HomePilot installation that OllaBridge
Local reads and republishes (owner-scoped) to OllaBridge Cloud, so the cloud
UI can mirror local resources without copying model weights or databases.

Design: docs/design/ollabridge-cloud-mirror/README.md

Strictly ADDITIVE and feature-flagged (OLLABRIDGE_NODE_MANIFEST_ENABLED,
default off). It only READS existing sources - available_*_models(),
capabilities._check_torch_gpu(), projects.list_all_projects(), the persona
shared_api flag - and never modifies them. Nothing here touches the legacy
/v1 provider plane.

Two invariants the tests lock down:
  1. Localhost only. The manifest can expose more than the public catalog
     (all owner-mirrored personas, GPU details), so it must never be
     reachable from off-box. Remote callers get 403.
  2. No secrets. Only ids, display names, types, status, and the two
     permission flags (mirror_to_owner / publish_provider_api). API keys,
     MCP tokens, DB creds and device keys are never included.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["node-manifest"])

MANIFEST_SCHEMA = "homepilot.node.manifest/v1"

# Monotonic revision derived from content hash: the revision only advances
# when the manifest content actually changes, so the cloud can delta-sync
# and detect continuity loss. Persisted best-effort across restarts.
_REVISION_STATE: Dict[str, Any] = {"hash": "", "revision": 0}


def _flag_enabled() -> bool:
    return os.getenv("OLLABRIDGE_NODE_MANIFEST_ENABLED", "false").strip().lower() in (
        "1", "true", "yes")


def _revision_store_path() -> str:
    base = os.getenv("NODE_MANIFEST_STATE_PATH", "").strip()
    if base:
        return base
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "node_manifest_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _load_revision_state() -> None:
    try:
        with open(_revision_store_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "revision" in data:
            _REVISION_STATE.update({"hash": data.get("hash", ""),
                                    "revision": int(data.get("revision", 0))})
    except Exception:
        pass


def _save_revision_state() -> None:
    try:
        with open(_revision_store_path(), "w", encoding="utf-8") as fh:
            json.dump(_REVISION_STATE, fh)
    except Exception:
        pass


# ── Data collectors (all read-only, all failure-tolerant) ────────────────────

def _node_id() -> str:
    explicit = os.getenv("HOMEPILOT_NODE_ID", "").strip()
    if explicit:
        return explicit
    try:
        host = socket.gethostname() or "homepilot-node"
    except Exception:
        host = "homepilot-node"
    # Stable, non-identifying slug
    return "node_" + hashlib.sha256(host.encode("utf-8")).hexdigest()[:12]


def _node_name() -> str:
    return os.getenv("HOMEPILOT_NODE_NAME", "").strip() or _safe_hostname()


def _safe_hostname() -> str:
    try:
        return socket.gethostname() or "HomePilot Node"
    except Exception:
        return "HomePilot Node"


def _versions() -> Dict[str, str]:
    hp = os.getenv("HOMEPILOT_VERSION", "").strip()
    if not hp:
        try:
            from .config import HOMEPILOT_VERSION as _v  # type: ignore
            hp = str(_v)
        except Exception:
            hp = "unknown"
    return {"homepilot": hp,
            "ollabridge": os.getenv("OLLABRIDGE_VERSION", "").strip() or "unknown"}


def _hardware() -> Dict[str, Any]:
    hw: Dict[str, Any] = {"platform": platform.system().lower()}

    # GPU via the existing capability probe; details via torch when present.
    try:
        from .capabilities import _check_torch_gpu
        ok, note = _check_torch_gpu()
        hw["gpu_available"] = bool(ok and not note)
    except Exception:
        hw["gpu_available"] = False
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            hw["gpu_name"] = torch.cuda.get_device_name(0)
            hw["vram_total_mb"] = int(props.total_memory / (1024 * 1024))
            free, total = torch.cuda.mem_get_info()
            hw["vram_free_mb"] = int(free / (1024 * 1024))
    except Exception:
        pass

    # RAM (best effort, no hard dependency on psutil)
    try:
        import psutil
        vm = psutil.virtual_memory()
        hw["ram_total_mb"] = int(vm.total / (1024 * 1024))
    except Exception:
        pass

    try:
        usage = shutil.disk_usage(os.getcwd())
        hw["disk_free_mb"] = int(usage.free / (1024 * 1024))
    except Exception:
        pass
    return hw


def _services() -> Dict[str, Dict[str, str]]:
    """Service health without importing heavy runtimes at manifest time."""
    services: Dict[str, Dict[str, str]] = {"homepilot": {"status": "ready"}}

    def _http_ready(url: str, timeout: float = 1.5) -> bool:
        try:
            import httpx
            r = httpx.get(url, timeout=timeout)
            return r.status_code < 500
        except Exception:
            return False

    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    services["ollama"] = {
        "status": "ready" if _http_ready(f"{ollama_url}/api/tags") else "offline"}

    try:
        from .config import COMFY_BASE_URL
        comfy_ok = _http_ready(f"{COMFY_BASE_URL.rstrip('/')}/system_stats")
    except Exception:
        comfy_ok = False
    services["comfyui"] = {"status": "ready" if comfy_ok else "offline"}

    for name, flag in (("voice", "VOICE_BACKEND_ENABLED"),
                       ("avatar", "AVATAR_ENABLED"),
                       ("mcp", "AGENTIC_ENABLED")):
        on = os.getenv(flag, "true" if name == "mcp" else "false").strip().lower() in (
            "1", "true", "yes")
        services[name] = {"status": "ready" if on else "disabled"}
    return services


def _capabilities(services: Dict[str, Dict[str, str]]) -> List[str]:
    caps = ["chat.completions", "chat.stream", "personas.chat", "projects.read"]
    if services.get("ollama", {}).get("status") == "ready":
        caps.append("embeddings.create")
    if services.get("comfyui", {}).get("status") == "ready":
        caps += ["images.generate", "images.edit", "videos.generate"]
    if services.get("voice", {}).get("status") == "ready":
        caps += ["voice.transcribe", "voice.synthesize"]
    if services.get("avatar", {}).get("status") == "ready":
        caps.append("avatar.render")
    if services.get("mcp", {}).get("status") == "ready":
        caps.append("mcp.invoke")
    return caps


def _chat_models() -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        import httpx
        r = httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                mid = m.get("name")
                if mid:
                    models.append({"id": mid, "display_name": mid,
                                   "runtime": "ollama", "status": "installed"})
    except Exception:
        pass
    return models


def _personas() -> List[Dict[str, Any]]:
    """All persona projects, each carrying BOTH permission flags. mirror_to_owner
    is always true (owner sees their own); publish_provider_api mirrors the
    existing shared_api.enabled flag - the legacy catalog's gate, unchanged."""
    out: List[Dict[str, Any]] = []
    try:
        from . import projects as projects_mod
        from .openai_compat_endpoint import _build_external_id
    except Exception:
        return out
    try:
        all_projects = projects_mod.list_all_projects()
    except Exception:
        return out

    for proj in all_projects:
        if proj.get("project_type") != "persona":
            continue
        shared = proj.get("shared_api") or {}
        published = bool(shared.get("enabled"))
        pid = proj.get("id", "")
        label = ""
        pa = proj.get("persona_agent")
        if isinstance(pa, dict):
            label = (pa.get("label") or "").strip()
        display = label or (proj.get("name") or "Persona").strip()
        out.append({
            "id": pid,
            "provider_id": _build_external_id(proj) if published else None,
            "display_name": display,
            "mirror_to_owner": True,
            "publish_provider_api": published,
        })
    return out


def _image_models() -> List[Dict[str, Any]]:
    try:
        from .providers import available_image_models
        return [{"id": m, "runtime": "comfyui", "status": "installed",
                 "type": "image", "operations": ["images.generate"]}
                for m in available_image_models()]
    except Exception:
        return []


def _video_models() -> List[Dict[str, Any]]:
    try:
        from .providers import available_video_models
        return [{"id": m, "runtime": "comfyui", "status": "installed",
                 "type": "video", "operations": ["videos.generate"]}
                for m in available_video_models()]
    except Exception:
        return []


# ── Manifest assembly + revisioning ──────────────────────────────────────────

def build_manifest() -> Dict[str, Any]:
    """Assemble the full manifest from live sources and stamp a revision.

    The revision advances only when the content (everything except the
    volatile timestamp/revision fields) changes, so repeated polls of an
    idle node keep the same revision - cheap delta sync for the cloud.
    """
    services = _services()
    manifest: Dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "node_id": _node_id(),
        "node_name": _node_name(),
        **_versions_block(),
        "hardware": _hardware(),
        "services": services,
        "capabilities": _capabilities(services),
        "resources": {
            "chat_models": _chat_models(),
            "personas": _personas(),
            "image_models": _image_models(),
            "video_models": _video_models(),
            "workflows": _workflows(),
        },
    }

    content_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    if not _REVISION_STATE["revision"]:
        _load_revision_state()
    if content_hash != _REVISION_STATE["hash"]:
        _REVISION_STATE["hash"] = content_hash
        _REVISION_STATE["revision"] = int(_REVISION_STATE["revision"]) + 1
        _save_revision_state()

    manifest["manifest_revision"] = _REVISION_STATE["revision"]
    manifest["manifest_hash"] = f"sha256:{content_hash}"
    manifest["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return manifest


def _versions_block() -> Dict[str, str]:
    v = _versions()
    return {"homepilot_version": v["homepilot"], "ollabridge_version": v["ollabridge"]}


def _workflows() -> List[Dict[str, Any]]:
    try:
        from pathlib import Path
        wf_dir = Path(__file__).resolve().parents[2] / "comfyui" / "workflows"
        out = []
        for f in sorted(wf_dir.glob("*.json")):
            out.append({"id": f.stem, "type": "video" if "vid" in f.stem else "image",
                        "display_name": f.stem.replace("-", " ").replace("_", " ").title()})
        return out
    except Exception:
        return []


# ── Endpoints (localhost only, feature-flagged) ──────────────────────────────

def _is_localhost(request: Request) -> bool:
    client = request.client.host if request.client else ""
    if client in ("127.0.0.1", "::1", "localhost"):
        return True
    # Trust an explicit allowlist for the sidecar on a private Docker network.
    allow = os.getenv("NODE_MANIFEST_ALLOW_HOSTS", "").strip()
    if allow and client in {h.strip() for h in allow.split(",") if h.strip()}:
        return True
    return False


def _guard(request: Request) -> Optional[JSONResponse]:
    if not _flag_enabled():
        return JSONResponse(status_code=404, content={"error": "node_manifest_disabled"})
    if not _is_localhost(request):
        return JSONResponse(status_code=403,
                            content={"error": "node_manifest_local_only",
                                     "message": "The node manifest is served to "
                                                "localhost / the local sidecar only."})
    return None


@router.get("/v1/node/manifest")
def get_node_manifest(request: Request):
    """Full node manifest. Localhost-only; OllaBridge Local reads this and
    republishes an owner-scoped copy to the cloud."""
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    return build_manifest()


@router.get("/v1/node/manifest/revision")
def get_node_manifest_revision(request: Request):
    """Cheap {revision, hash} for delta polling - build the manifest, return
    only its revision stamp."""
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    m = build_manifest()
    return {"node_id": m["node_id"], "manifest_revision": m["manifest_revision"],
            "manifest_hash": m["manifest_hash"], "generated_at": m["generated_at"]}
