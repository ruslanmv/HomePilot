#!/usr/bin/env python3
"""
Integration test: 3D Avatar Chatbot → OllaBridge → HomePilot → Ollama

Prerequisites:
  1. Ollama running on :11434 with a model (e.g. qwen2:0.5b)
  2. HomePilot backend running on :8000 with DEFAULT_PROVIDER=ollama API_KEY=my-secret
  3. OllaBridge gateway running on :11435 with HOMEPILOT_ENABLED=true
  4. (Optional) 3D Avatar Chatbot on :8080

Usage:
  python tests/test_ollabridge_pipeline.py
"""
import json
import sys
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434"
HOMEPILOT_URL = "http://localhost:8000"
OLLABRIDGE_URL = "http://localhost:11435"
AVATAR_URL = "http://localhost:8080"

HP_API_KEY = "my-secret"
OB_API_KEY = "sk-ollabridge-test-key"

errors = []


def check(name: str, url: str) -> bool:
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        print(f"  [OK]   {name}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        errors.append(name)
        return False


def chat(base_url: str, api_key: str, model: str, message: str) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "temperature": 0.7,
        "max_tokens": 100,
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode() if hasattr(e, "read") else ""
        raise RuntimeError(f"HTTP {e.code}: {body}") from e


def main():
    print("=" * 60)
    print("  OllaBridge Pipeline Integration Test")
    print("=" * 60)

    # 1. Health checks
    print("\n--- Service Health ---")
    check("Ollama", f"{OLLAMA_URL}/api/tags")
    hp_ok = check("HomePilot", f"{HOMEPILOT_URL}/health")
    ob_ok = check("OllaBridge", f"{OLLABRIDGE_URL}/health")
    check("3D Avatar", AVATAR_URL)

    if not hp_ok or not ob_ok:
        print("\nCritical services down. Aborting.")
        sys.exit(1)

    # 2. Enable HomePilot persona API
    print("\n--- Enable Persona API ---")
    try:
        payload = json.dumps({"enabled": True, "api_key": HP_API_KEY}).encode()
        req = urllib.request.Request(
            f"{HOMEPILOT_URL}/settings/ollabridge",
            data=payload,
            headers={"Content-Type": "application/json", "X-API-Key": HP_API_KEY},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        print(f"  Persona API: {data.get('message', 'ok')}")
    except Exception as e:
        print(f"  [WARN] Could not toggle API: {e}")

    # 3. Direct HomePilot persona chat
    print("\n--- Direct HomePilot Chat ---")
    try:
        reply = chat(HOMEPILOT_URL, HP_API_KEY, "personality:assistant", "Say hello world.")
        print(f"  Assistant: {reply}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        errors.append("Direct HP chat")

    # 4. OllaBridge → HomePilot persona
    print("\n--- OllaBridge → HomePilot Persona ---")
    try:
        reply = chat(OLLABRIDGE_URL, OB_API_KEY, "personality:assistant", "Say hello world.")
        print(f"  Assistant: {reply}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        errors.append("OB→HP persona")

    # 5. OllaBridge → Direct Ollama
    print("\n--- OllaBridge → Direct Ollama ---")
    try:
        reply = chat(OLLABRIDGE_URL, OB_API_KEY, "qwen2:0.5b", "Say hello world.")
        print(f"  Qwen2: {reply}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        errors.append("OB→Ollama")

    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"  FAILED: {', '.join(errors)}")
        sys.exit(1)
    else:
        print("  ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
