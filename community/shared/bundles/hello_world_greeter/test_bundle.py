#!/usr/bin/env python3
"""
Compatibility tests for a HomePilot community bundle.

Validates:
  1. MCP server module imports correctly
  2. /health endpoint returns {"ok": true}
  3. tools/list returns registered tools via JSON-RPC 2.0

Usage:
  python test_bundle.py                   # run all tests
  python test_bundle.py import            # run single test
  python test_bundle.py health tools      # run multiple tests
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[4]  # bundles/<id>/ -> shared/ -> community/ -> HomePilot/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BUNDLE_ID = Path(__file__).resolve().parent.name
MODULE_PATH = f"community.shared.bundles.{BUNDLE_ID}.mcp_server.app"

passed = 0
failed = 0


def test_import():
    """Test that the MCP server module can be imported."""
    global passed, failed
    print("── Test: import server module ──")
    try:
        mod = __import__(MODULE_PATH, fromlist=["app"])
        app = getattr(mod, "app")
        print(f"  OK: app imported successfully")
        print(f"  Type: {type(app).__name__}")
        print("  PASS: import")
        passed += 1
    except Exception as e:
        print(f"  FAIL: import — {e}")
        failed += 1


def test_health():
    """Test the /health endpoint."""
    global passed, failed
    print("── Test: /health endpoint ──")
    try:
        from httpx import ASGITransport, AsyncClient

        mod = __import__(MODULE_PATH, fromlist=["app"])
        app = getattr(mod, "app")

        async def check():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r = await c.get("/health")
                assert r.status_code == 200, f"Health returned {r.status_code}"
                data = r.json()
                assert data.get("ok") is True, f"Health not ok: {data}"
                print(f"  OK: /health -> 200 ok=true")
                print(f"  Server: {data.get('name', 'unknown')}")

        asyncio.run(check())
        print("  PASS: health")
        passed += 1
    except Exception as e:
        print(f"  FAIL: health — {e}")
        failed += 1


def test_tools():
    """Test tools/list via JSON-RPC."""
    global passed, failed
    print("── Test: tools/list via /rpc ──")
    try:
        from httpx import ASGITransport, AsyncClient

        mod = __import__(MODULE_PATH, fromlist=["app"])
        app = getattr(mod, "app")

        async def check():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                r = await c.post(
                    "/rpc",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                assert r.status_code == 200, f"RPC returned {r.status_code}"
                data = r.json()
                tools = data.get("result", {}).get("tools", [])
                assert len(tools) > 0, "No tools returned by tools/list"
                print(f"  OK: tools/list -> {len(tools)} tools")
                for t in tools:
                    print(f"    - {t['name']}: {t.get('description', '')}")

        asyncio.run(check())
        print("  PASS: tools/list")
        passed += 1
    except Exception as e:
        print(f"  FAIL: tools/list — {e}")
        failed += 1


ALL_TESTS = {
    "import": test_import,
    "health": test_health,
    "tools": test_tools,
}


def main():
    requested = sys.argv[1:] if len(sys.argv) > 1 else list(ALL_TESTS.keys())
    for name in requested:
        if name not in ALL_TESTS:
            print(f"Unknown test: {name}")
            print(f"Available: {', '.join(ALL_TESTS.keys())}")
            sys.exit(1)
        ALL_TESTS[name]()
        print()

    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
