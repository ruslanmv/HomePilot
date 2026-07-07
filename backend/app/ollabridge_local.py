"""
OllaBridge Local — edition + provider-sidecar surface (additive, non-destructive).

Two concerns, one router:

* ``GET /v1/edition`` — tells the frontend whether this HomePilot is the hosted
  **web** consumer (the Hugging Face Space) or a **local** install that can act
  as a GPU *provider*. The UI uses this to show the right linking experience.

* ``/v1/ollabridge/local/*`` — status/control for the OllaBridge Local sidecar
  (the connector that dials the Cloud relay and exposes this PC's GPU/models).
  On the **web** edition there is no sidecar, so these report ``available:false``
  honestly. On the **local** edition, ``status`` probes the sidecar's
  localhost gateway; ``start``/``stop``/``pair`` are best-effort control hooks.

Design rules mirrored from the plan:
  installed ≠ paired ≠ shared. This surface only *reports/controls* the sidecar;
  it never auto-shares. Sharing scope defaults to owner-only and is decided in
  the Cloud/pairing flow, not here.
"""
from __future__ import annotations

from typing import Any, Dict

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from . import config as _cfg

router = APIRouter(tags=["ollabridge-local"])


def _edition() -> str:
    return (getattr(_cfg, "HOMEPILOT_EDITION", "local") or "local").strip().lower()


def _local_url() -> str:
    return (getattr(_cfg, "OLLABRIDGE_LOCAL_URL", "") or "").rstrip("/")


def _cloud_url() -> str:
    return (getattr(_cfg, "OLLABRIDGE_CLOUD_URL", "") or "").rstrip("/")


@router.get("/v1/edition")
def edition() -> Dict[str, Any]:
    """Which HomePilot edition is this — and can it act as a GPU provider?"""
    ed = _edition()
    return {
        "edition": ed,
        "is_web": ed == "web",
        "is_local": ed == "local",
        # Only a local install can expose its own GPU as a provider node.
        "can_provide_gpu": ed == "local",
        "cloud_url": _cloud_url(),
    }


async def _probe_sidecar() -> Dict[str, Any]:
    """Best-effort reachability probe of the OllaBridge Local sidecar.

    A running sidecar exposes an OpenAI-compatible gateway; we treat a 2xx from
    its models endpoint (or root) as "running". Never raises — returns a status
    dict. This is a *reachability* check only; pairing/sharing state is authoritative
    on the Cloud side.
    """
    base = _local_url()
    out: Dict[str, Any] = {"running": False, "models": 0, "local_url": base}
    if not base:
        return out
    for path in ("/v1/models", "/api/tags", "/"):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{base}{path}")
            if r.status_code < 500:
                out["running"] = r.status_code < 400
                try:
                    data = r.json()
                    n = data.get("data") if isinstance(data, dict) else None
                    if isinstance(n, list):
                        out["models"] = len(n)
                except Exception:
                    pass
                if out["running"]:
                    break
        except Exception:
            continue
    return out


@router.get("/v1/ollabridge/local/status")
async def local_status() -> Dict[str, Any]:
    """Report the OllaBridge Local sidecar state for this machine.

    Shape (stable) — matches the frontend contract:
      { edition, available, installed, running, paired, cloud_url,
        local_url, share_scope }
    """
    ed = _edition()
    if ed != "local":
        # The hosted web consumer has no provider sidecar — say so plainly so
        # the UI hides provider/pairing controls instead of showing a fake GPU.
        return {
            "edition": ed,
            "available": False,
            "installed": False,
            "running": False,
            "paired": False,
            "cloud_url": _cloud_url(),
            "local_url": None,
            "share_scope": "owner_only",
            "reason": "Provider mode is only available on HomePilot Local (installed on your PC).",
        }

    probe = await _probe_sidecar()
    running = bool(probe.get("running"))
    return {
        "edition": ed,
        "available": True,
        # We can only observe "running" locally; treat reachable ⇒ installed.
        "installed": running,
        "running": running,
        # Pairing is authoritative on the Cloud; the app learns it via the
        # Cloud /v1/devices list, so we don't assert it from here.
        "paired": None,
        "cloud_url": _cloud_url(),
        "local_url": probe.get("local_url"),
        "models": probe.get("models", 0),
        "share_scope": "owner_only",
    }


class _Empty(BaseModel):
    pass


def _control_not_available() -> Dict[str, Any]:
    return {
        "ok": False,
        "detail": "The OllaBridge Local sidecar is managed by the desktop app; "
                  "start/stop/pair are not available from this deployment.",
    }


@router.post("/v1/ollabridge/local/start")
async def local_start(_: _Empty = _Empty()) -> Dict[str, Any]:
    """Best-effort start hook. On the web edition (or when the sidecar is
    supervised by the desktop shell) this is a no-op that reports status —
    control lives in the desktop manager, not the backend process."""
    if _edition() != "local":
        return _control_not_available()
    probe = await _probe_sidecar()
    return {"ok": bool(probe.get("running")), "running": bool(probe.get("running")),
            "detail": "Sidecar lifecycle is managed by the HomePilot Local desktop shell."}


@router.post("/v1/ollabridge/local/stop")
async def local_stop(_: _Empty = _Empty()) -> Dict[str, Any]:
    if _edition() != "local":
        return _control_not_available()
    return {"ok": True, "detail": "Sidecar lifecycle is managed by the HomePilot Local desktop shell."}


@router.get("/v1/ollabridge/local/pair-url")
def local_pair_url() -> Dict[str, Any]:
    """Where to complete device-code pairing for this machine (Cloud page)."""
    cloud = _cloud_url()
    return {"pair_url": f"{cloud}/link" if cloud else "", "cloud_url": cloud}
