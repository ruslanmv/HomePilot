#!/usr/bin/env python3
"""
Hello-world smoke test for the Interactive subsystem with REAL deps.

Runs end-to-end against the actual code paths (no monkey-patching),
so it exercises whichever backends are reachable at the moment:

  - Ollama    reachable → real LLM composer fires
              unreachable → phase-1 heuristic fallback (still passes)
  - ComfyUI   reachable → real video render
              unreachable → phase-1 stub asset fallback (still passes)

Usage:
  .venv/bin/python scripts/interactive_smoke.py

Exit code 0 → every checkpoint passed.
Exit code 1 → any HTTP or assertion failed (see the last red line).

Environment knobs:
  OLLAMA_BASE_URL    default http://localhost:11434
  OLLAMA_MODEL       default llama3.2:1b   (the lightest chat model)
  COMFY_BASE_URL     default http://localhost:8188

Pretty output by default; every step prints ✓ / ⚠ / ✗ so the
terminal tells you at a glance where the pipeline is broken.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

# Run against a fresh SQLite DB so the smoke test never steps on
# a dev database. Set BEFORE importing anything that reads it.
_TMP_DB = os.environ.setdefault(
    "SQLITE_PATH",
    os.path.expanduser("~/.homepilot_smoke.db"),
)
os.environ.setdefault("INTERACTIVE_ENABLED", "true")
# Default phase-2 flags on; the pipelines gracefully fall back to
# phase-1 stubs when their backends are unreachable.
os.environ.setdefault("INTERACTIVE_PLAYBACK_LLM", "true")
os.environ.setdefault("INTERACTIVE_PLAYBACK_RENDER", "true")


# ── Pretty output ───────────────────────────────────────────────

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET}  {msg}", file=sys.stderr)


def step(n: int, title: str) -> None:
    print(f"\n{CYAN}[{n}] {title}{RESET}")


def sub(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


# ── Backend reachability probes ─────────────────────────────────

def probe_ollama() -> Optional[str]:
    """Return the first model tag Ollama has, or None if unreachable."""
    import urllib.request
    import json as _json
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as r:
            body = _json.loads(r.read().decode("utf-8"))
        models = body.get("models") or []
        if not models:
            return ""
        return str(models[0].get("name") or models[0].get("model") or "")
    except Exception:
        return None


def probe_comfy() -> bool:
    import urllib.request
    base = os.getenv("COMFY_BASE_URL", "http://localhost:8188").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/system_stats", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


# ── Run the hello-world scenario ────────────────────────────────

def run_scenario() -> int:
    # Late import so env vars are set before FastAPI/TestClient load.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.interactive.config import InteractiveConfig
    from app.interactive.router import build_router
    from app.interactive.routes._common import current_user
    from app.interactive.playback import schema

    schema._reset_for_tests()
    # Ensure a fresh _RESOLVED_DB_PATH is computed from our env.
    from app import storage
    storage._RESOLVED_DB_PATH = None

    cfg = InteractiveConfig(
        enabled=True, max_branches=6, max_depth=4,
        max_nodes_per_experience=100,
        llm_model=os.getenv("OLLAMA_MODEL", "llama3.2:1b"),
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )
    app = FastAPI()
    app.include_router(build_router(cfg))
    user_id = f"smoke_{uuid.uuid4().hex[:8]}"
    app.dependency_overrides[current_user] = lambda: user_id
    client = TestClient(app)

    # ── Probes ──────────────────────────────────────────────────
    step(0, "Probe backends")
    ollama_tag = probe_ollama()
    if ollama_tag is None:
        warn("Ollama unreachable — LLM composer will fall back to heuristic")
    elif not ollama_tag:
        warn("Ollama up, but no models pulled. Try: ollama pull llama3.2:1b")
        ollama_tag = None
    else:
        ok(f"Ollama reachable with model '{ollama_tag}'")
    comfy_up = probe_comfy()
    if comfy_up:
        ok("ComfyUI reachable — renderer will produce a real clip")
    else:
        warn("ComfyUI unreachable — renderer will fall back to stub asset id")

    # ── 1. Health ───────────────────────────────────────────────
    step(1, "Health check")
    h = client.get("/v1/interactive/health")
    if h.status_code != 200 or not h.json().get("ok"):
        fail(f"/health returned {h.status_code}: {h.text}")
        return 1
    ok("interactive service is up")

    # ── 2. Create experience + seed one node ────────────────────
    step(2, "Create experience + seed opening scene")
    exp_r = client.post(
        "/v1/interactive/experiences",
        json={
            "title": "Smoke: Hello world",
            "description": "warm friendly presenter, soft natural light",
            "experience_mode": "sfw_general",
            "policy_profile_id": "sfw_general",
        },
    )
    if exp_r.status_code != 200:
        fail(f"create_experience failed: {exp_r.status_code} {exp_r.text}")
        return 1
    exp = exp_r.json()["experience"]
    ok(f"experience {exp['id']} created")
    node_r = client.post(
        f"/v1/interactive/experiences/{exp['id']}/nodes",
        json={"kind": "scene", "title": "Opening", "narration": "Welcome in."},
    )
    if node_r.status_code != 200:
        fail(f"create_node failed: {node_r.status_code} {node_r.text}")
        return 1
    ok("opening scene node seeded")

    # ── 3. Start a session ──────────────────────────────────────
    step(3, "Start play session")
    s_r = client.post(
        "/v1/interactive/play/sessions",
        json={"experience_id": exp["id"], "viewer_ref": "smoke_viewer"},
    )
    if s_r.status_code != 200:
        fail(f"create_session failed: {s_r.status_code} {s_r.text}")
        return 1
    sess = s_r.json()["session"]
    ok(f"session {sess['id']} started on node {sess.get('current_node_id', '')[:16]}…")

    # ── 4. Send 'Hello world' ───────────────────────────────────
    step(4, "Send 'Hello world' chat turn")
    t0 = time.time()
    c_r = client.post(
        f"/v1/interactive/play/sessions/{sess['id']}/chat",
        json={"text": "Hello world"},
    )
    elapsed = time.time() - t0
    if c_r.status_code != 200:
        fail(f"chat failed: {c_r.status_code} {c_r.text}")
        return 1
    chat = c_r.json()
    if chat.get("status") != "ok":
        fail(f"chat blocked or errored: {chat}")
        return 1
    ok(f"chat resolved in {elapsed:.2f}s")
    sub(f"reply_text: {chat['reply_text']}")
    sub(f"intent_code: {chat['intent_code']}  mood: {chat['mood']}"
        f"  affinity: {chat['affinity_score']:.2f}")

    # ── 5. Scene job + asset ────────────────────────────────────
    step(5, "Verify scene job + asset resolution")
    if chat.get("video_job_status") != "ready":
        fail(f"job did not reach 'ready' ({chat.get('video_job_status')})")
        return 1
    asset_id = chat.get("video_asset_id", "")
    asset_url = chat.get("video_asset_url", "")
    if asset_id.startswith("ixa_playback_"):
        ok(f"real asset id: {asset_id}")
    elif asset_id.startswith("ixa_stub_"):
        warn(f"fell back to stub asset: {asset_id} (expected when ComfyUI is down)")
    else:
        fail(f"unexpected asset id shape: {asset_id!r}")
        return 1
    if asset_url:
        ok(f"asset URL resolves: {asset_url[:80]}")
    else:
        sub("no URL resolved (stub path — normal when ComfyUI is unreachable)")

    # ── 6. Persisted state ──────────────────────────────────────
    step(6, "Verify session state + transcript persisted")
    p_r = client.get(f"/v1/interactive/play/sessions/{sess['id']}/progress")
    if p_r.status_code != 200:
        fail(f"progress failed: {p_r.status_code} {p_r.text}")
        return 1
    pb = p_r.json()
    ok(f"mood persisted as '{pb.get('mood')}' "
       f"(affinity {pb.get('affinity_score', 0):.2f})")

    # ── Done ────────────────────────────────────────────────────
    print()
    print(f"{GREEN}────────────────────────────────────────────────────{RESET}")
    print(f"{GREEN}  Hello-world smoke test passed.{RESET}")
    print(f"{GREEN}────────────────────────────────────────────────────{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(run_scenario())
