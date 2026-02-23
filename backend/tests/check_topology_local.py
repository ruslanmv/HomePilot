#!/usr/bin/env python3
# backend/tests/check_topology_local.py
"""
Local Topology Integration Checks — requires running Ollama + backend.

This script validates that all 4 topologies actually work end-to-end
against a real local environment. NOT for CI — requires:
  - Ollama running at OLLAMA_BASE_URL (default http://localhost:11434)
  - Backend running at BACKEND_URL (default http://localhost:8000)
  - At least one LLM model pulled in Ollama
  - A vision model (moondream) for T3/T4 tests

Usage:
  python tests/check_topology_local.py
  python tests/check_topology_local.py --topology t1
  python tests/check_topology_local.py --topology t3 --backend http://localhost:8000

Exit codes: 0 = all pass, 1 = failures
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

results = []


def _req(method, url, body=None, timeout=30):
    """Simple HTTP request helper (no external deps)."""
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=timeout)
    return resp.status, json.loads(resp.read().decode())


def _check(name, passed, detail=""):
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append((name, passed))


# ===================================================================
# T1: Basic Chat
# ===================================================================

def check_t1():
    print(f"\n{'='*50}")
    print("T1: Basic Chat")
    print(f"{'='*50}")

    # Health
    try:
        code, data = _req("GET", f"{BACKEND_URL}/health")
        _check("Health endpoint", code == 200 and data.get("ok"), f"v{data.get('version', '?')}")
    except Exception as e:
        _check("Health endpoint", False, str(e))
        return  # Can't continue without backend

    # Chat
    try:
        code, data = _req("POST", f"{BACKEND_URL}/chat", {
            "message": "Say hello in one word.",
            "conversation_id": "local-t1-check",
            "mode": "chat",
        })
        has_text = bool(data.get("text", "").strip())
        _check("Chat response", code == 200 and has_text, f"text={data.get('text', '')[:60]}")
    except Exception as e:
        _check("Chat response", False, str(e))


# ===================================================================
# T2: Project-Scoped Knowledge (RAG)
# ===================================================================

def check_t2():
    print(f"\n{'='*50}")
    print("T2: Project-Scoped Knowledge (RAG)")
    print(f"{'='*50}")

    pid = None

    # Create project
    try:
        code, data = _req("POST", f"{BACKEND_URL}/projects", {
            "name": "Local T2 Check",
            "description": "Integration test",
            "instructions": "You are a helpful assistant.",
        })
        pid = data.get("project", {}).get("id")
        _check("Create project", code in (200, 201) and pid, f"id={pid}")
    except Exception as e:
        _check("Create project", False, str(e))
        return

    # Get project
    try:
        code, data = _req("GET", f"{BACKEND_URL}/projects/{pid}")
        _check("Get project", code == 200 and data.get("ok"), data.get("project", {}).get("name", ""))
    except Exception as e:
        _check("Get project", False, str(e))

    # Chat with project context
    try:
        code, data = _req("POST", f"{BACKEND_URL}/chat", {
            "message": "What is this project about?",
            "conversation_id": "local-t2-check",
            "project_id": pid,
            "mode": "chat",
        })
        _check("Project-scoped chat", code == 200 and bool(data.get("text")), f"text={data.get('text', '')[:60]}")
    except Exception as e:
        _check("Project-scoped chat", False, str(e))

    # Clean up
    try:
        _req("DELETE", f"{BACKEND_URL}/projects/{pid}")
    except Exception:
        pass


# ===================================================================
# T3: Agent-Controlled Tool Use
# ===================================================================

def check_t3():
    print(f"\n{'='*50}")
    print("T3: Agent-Controlled Tool Use")
    print(f"{'='*50}")

    # Agent chat (simple question — should return final answer, no tool call)
    try:
        code, data = _req("POST", f"{BACKEND_URL}/v1/agent/chat", {
            "message": "What is 2 plus 2? Answer briefly.",
            "conversation_id": "local-t3-check",
        })
        has_text = bool(data.get("text", "").strip())
        agent_meta = data.get("agent", {})
        tools_used = agent_meta.get("tool_calls_used", -1)
        _check("Agent chat (no tools)", code == 200 and has_text, f"tools_used={tools_used}")
    except Exception as e:
        _check("Agent chat (no tools)", False, str(e))

    # Agent chat with web.search trigger
    try:
        code, data = _req("POST", f"{BACKEND_URL}/v1/agent/chat", {
            "message": "Search the web for the latest Python release.",
            "conversation_id": "local-t3-search",
            "max_tool_calls": 2,
        })
        agent_meta = data.get("agent", {})
        tools = agent_meta.get("tools_invoked", [])
        _check("Agent web.search", code == 200 and bool(data.get("text")), f"tools={tools}")
    except Exception as e:
        _check("Agent web.search", False, str(e))


# ===================================================================
# T4: Multimodal Knowledge RAG
# ===================================================================

def check_t4():
    print(f"\n{'='*50}")
    print("T4: Multimodal Knowledge RAG")
    print(f"{'='*50}")

    # Check Ollama has a vision model
    vision_available = False
    try:
        code, data = _req("GET", f"{BACKEND_URL}/v1/multimodal/status")
        models = data.get("installed_vision_models", [])
        vision_available = len(models) > 0
        _check("Vision model available", vision_available, f"models={models[:3]}")
    except Exception as e:
        _check("Vision model available", False, str(e))

    if not vision_available:
        print(f"  {YELLOW}SKIP{RESET} Image indexing tests (no vision model installed)")
        print(f"  {YELLOW}TIP{RESET}  Run: ollama pull moondream")
        return

    # Create project for image test
    pid = None
    try:
        code, data = _req("POST", f"{BACKEND_URL}/projects", {
            "name": "Local T4 Image Check",
            "description": "T4 integration test",
            "instructions": "test",
        })
        pid = data.get("project", {}).get("id")
        _check("Create image project", code in (200, 201) and pid)
    except Exception as e:
        _check("Create image project", False, str(e))
        return

    # Upload a test image (1x1 PNG)
    try:
        import io
        import http.client
        from urllib.parse import urlparse

        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        parsed = urlparse(f"{BACKEND_URL}/projects/{pid}/upload")
        boundary = "----LocalT4Check"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="test.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + png_bytes + f"\r\n--{boundary}--\r\n".encode()

        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=60)
        conn.request("POST", parsed.path, body=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        })
        resp = conn.getresponse()
        resp_data = json.loads(resp.read().decode())
        chunks = resp_data.get("chunks_added", 0)
        source_type = resp_data.get("source_type", "")
        _check("Image upload + index", resp.status in (200, 201) and source_type == "image", f"chunks={chunks}")
        conn.close()
    except Exception as e:
        _check("Image upload + index", False, str(e))

    # Clean up
    try:
        _req("DELETE", f"{BACKEND_URL}/projects/{pid}")
    except Exception:
        pass


# ===================================================================
# Main
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="Local topology integration checks")
    parser.add_argument("--topology", "-t", choices=["t1", "t2", "t3", "t4", "all"], default="all")
    parser.add_argument("--backend", "-b", default=None, help="Backend URL override")
    args = parser.parse_args()

    global BACKEND_URL
    if args.backend:
        BACKEND_URL = args.backend.rstrip("/")

    print(f"Backend: {BACKEND_URL}")
    print(f"Ollama:  {OLLAMA_URL}")

    checks = {
        "t1": check_t1,
        "t2": check_t2,
        "t3": check_t3,
        "t4": check_t4,
    }

    if args.topology == "all":
        for fn in checks.values():
            fn()
    else:
        checks[args.topology]()

    # Summary
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    total = len(results)

    print(f"\n{'='*50}")
    print(f"Results: {GREEN}{passed} passed{RESET}, {RED if failed else ''}{failed} failed{RESET}, {total} total")
    print(f"{'='*50}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
