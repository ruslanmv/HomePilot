#!/usr/bin/env python3
"""
Verify a Hugging Face Space after a deploy: it runs the commit just pushed, and a visitor who
types "hello" gets an answer — through the standard chat and through the chat's default path
(Expert, Fast).

deploy-hf.sh only pushes the bundle; Hugging Face builds the image afterwards. A build that
fails leaves the previous image serving, so a green push said nothing about production. This
waits for the build, then checks what a visitor would see. Exit 0 only when every check passes.

    HF_SPACE=ruslanmv/HomePilot EXPECTED_SHA=<commit> python3 verify_space.py

Environment:
    HF_SPACE        owner/name of the Space (default ruslanmv/HomePilot)
    HF_SPACE_URL    its app URL (default https://<owner>-<name>.hf.space)
    HF_TOKEN        optional; sent to the HF API and the Space (needed for a private Space)
    EXPECTED_SHA    the commit /version must report (default: git rev-parse HEAD)
    VERIFY_TIMEOUT  seconds to wait for build + model (default 2400)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

SPACE = os.environ.get("HF_SPACE", "ruslanmv/HomePilot")
TOKEN = os.environ.get("HF_TOKEN", "").strip()
TIMEOUT = int(os.environ.get("VERIFY_TIMEOUT", "2400"))
FAILED_STAGES = {"BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"}


def space_url() -> str:
    explicit = os.environ.get("HF_SPACE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    # Hugging Face's subdomain: lower case, "/" and anything not alphanumeric become "-".
    return "https://" + re.sub(r"[^a-z0-9]+", "-", SPACE.lower()).strip("-") + ".hf.space"


def expected_sha() -> str:
    sha = os.environ.get("EXPECTED_SHA", "").strip()
    if sha:
        return sha
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def request(url: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, str]:
    headers = {"User-Agent": "homepilot-deploy-verify"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}"


def as_json(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def runtime_stage() -> str:
    status, text = request(f"https://huggingface.co/api/spaces/{SPACE}/runtime")
    return str(as_json(text).get("stage") or "") if status == 200 else ""


def wait_for_build(base: str, sha: str, deadline: float) -> None:
    """Until /version reports ``sha``. A failed build or runtime stops the wait at once."""
    last = ""
    while time.time() < deadline:
        stage = runtime_stage()
        if stage in FAILED_STAGES:
            fail(f"the Space is in stage {stage}: Hugging Face could not build or start this "
                 f"commit; the previous image (if any) is still serving. See the Space's build logs.")
        status, text = request(f"{base}/version", timeout=15)
        running = as_json(text).get("sha", "") if status == 200 else ""
        note = f"stage={stage or '?'} /version={'HTTP %d' % status if status != 200 else running or '?'}"
        if note != last:
            print(f"   … {note}", flush=True)
            last = note
        if running and (running == sha or running.startswith(sha)):
            print(f"   ✓ serving {running}", flush=True)
            return
        time.sleep(20)
    fail(f"timed out after {TIMEOUT}s waiting for the Space to serve {sha} (last: {last})")


def wait_for_ready(base: str, deadline: float) -> None:
    """Until /health/ready: the chat model is pulled and listed."""
    last = ""
    while time.time() < deadline:
        status, text = request(f"{base}/health/ready", timeout=15)
        if status == 200:
            print(f"   ✓ ready: {as_json(text).get('chat', {}).get('model')}", flush=True)
            return
        reason = as_json(text).get("chat", {}).get("reason") or f"HTTP {status}"
        if reason != last:
            print(f"   … not ready: {reason}", flush=True)
            last = reason
        time.sleep(15)
    fail(f"timed out waiting for /health/ready (last: {last})")


def check_chat(base: str) -> None:
    status, text = request(f"{base}/chat", {"message": "hello"}, timeout=180)
    reply = as_json(text)
    answer = str(reply.get("text") or reply.get("content") or "").strip()
    if status != 200 or not answer or reply.get("error"):
        fail(f"POST /chat \"hello\" did not answer: HTTP {status}: {text[:300]}")
    print(f"   ✓ /chat: {answer[:80]!r}", flush=True)


def expert_answer(sse: str) -> tuple[str, str]:
    """(answer, error) from an Expert event stream."""
    event, answer, error = "", "", ""
    for line in sse.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            payload = line[5:].strip()
            if event == "done":
                answer = str(as_json(payload).get("content") or "").strip()
            elif event == "error":
                error = str(as_json(payload).get("error") or payload)
        elif not line.strip():
            event = ""
    return answer, error


def check_expert_fast(base: str) -> None:
    # What the composer sends for a new visitor's first message in Fast mode.
    body = {"query": "hello", "provider": "auto", "thinking_mode": "fast", "with_critique": False,
            "history": [], "session_id": "deploy-verify", "has_attachments": False,
            "feature_hints": {"budgetTier": "normal"}, "target": {"provider": "ollama"}}
    status, text = request(f"{base}/v1/expert/stream", body, timeout=180)
    answer, error = expert_answer(text) if status == 200 else ("", "")
    if status != 200 or error or not answer:
        fail(f"Fast \"hello\" (POST /v1/expert/stream) did not answer: HTTP {status}"
             + (f", error event: {error}" if error else f": {text[:300]}"))
    print(f"   ✓ Expert Fast: {answer[:80]!r}", flush=True)


def fail(message: str) -> None:
    print(f"✗ {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def main() -> None:
    base, sha = space_url(), expected_sha()
    deadline = time.time() + TIMEOUT
    print(f">> verifying {base} (Space {SPACE}) serves {sha}", flush=True)
    wait_for_build(base, sha, deadline)
    wait_for_ready(base, deadline)
    check_chat(base)
    check_expert_fast(base)
    print(">> Space verified", flush=True)


if __name__ == "__main__":
    main()
