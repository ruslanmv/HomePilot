"""Seed MCP Context Forge with placeholder tool + A2A agent.

Run this script to register the placeholder services in your local
Context Forge instance so the HomePilot Agent Creation Wizard has
something to display.

Prerequisites:
    1. Context Forge is running at CONTEXT_FORGE_URL (default: http://localhost:4444)
    2. The placeholder servers are running (optional — registration works even if
       endpoints are not reachable yet; Forge marks them as unreachable).

Usage:
    python -m backend.app.agentic.placeholders.seed_forge

Environment variables (optional):
    CONTEXT_FORGE_URL       (default: http://localhost:4444)
    CONTEXT_FORGE_AUTH_USER  (default: admin)
    CONTEXT_FORGE_AUTH_PASS  (default: changeme)
    CONTEXT_FORGE_TOKEN      (default: empty — uses basic auth)
"""

from __future__ import annotations

import json
import os
import sys

import httpx

FORGE_URL = os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444").rstrip("/")
AUTH_USER = os.getenv("CONTEXT_FORGE_AUTH_USER", "admin")
AUTH_PASS = os.getenv("CONTEXT_FORGE_AUTH_PASS", "changeme")
TOKEN = os.getenv("CONTEXT_FORGE_TOKEN", "")

PLACEHOLDER_TOOL = {
    "name": "placeholder_echo",
    "displayName": "Placeholder Echo Tool",
    "description": "Echoes input text back. Use as a wiring test for the HomePilot wizard.",
    "integration_type": "REST",
    "url": "http://localhost:9101/invoke",
    "request_type": "POST",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to echo back"},
        },
        "required": ["text"],
    },
    "tags": ["placeholder", "testing"],
    "visibility": "public",
}

PLACEHOLDER_AGENT = {
    "name": "placeholder_agent",
    "description": "Placeholder A2A agent for wiring the HomePilot wizard. Replace with a real agent later.",
    "endpoint_url": "http://localhost:9100/a2a",
    "agent_type": "generic",
    "protocol_version": "1.0",
    "visibility": "public",
    "tags": ["placeholder", "testing"],
}


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _auth() -> httpx.BasicAuth | None:
    if not TOKEN and AUTH_USER:
        return httpx.BasicAuth(AUTH_USER, AUTH_PASS)
    return None


def _seed_tool(client: httpx.Client) -> None:
    print(f"Registering placeholder tool at {FORGE_URL}/tools ...")
    r = client.post(f"{FORGE_URL}/tools", json=PLACEHOLDER_TOOL, headers=_headers(), auth=_auth())
    if r.status_code in (200, 201):
        data = r.json()
        print(f"  Tool registered: id={data.get('id', '?')}, name={data.get('name', '?')}")
    elif r.status_code == 409:
        print("  Tool already exists (409 conflict) — skipping.")
    else:
        print(f"  Failed ({r.status_code}): {r.text[:200]}")


def _seed_agent(client: httpx.Client) -> None:
    print(f"Registering placeholder A2A agent at {FORGE_URL}/a2a ...")
    r = client.post(f"{FORGE_URL}/a2a", json=PLACEHOLDER_AGENT, headers=_headers(), auth=_auth())
    if r.status_code in (200, 201):
        data = r.json()
        print(f"  Agent registered: id={data.get('id', '?')}, name={data.get('name', '?')}")
    elif r.status_code == 409:
        print("  Agent already exists (409 conflict) — skipping.")
    else:
        print(f"  Failed ({r.status_code}): {r.text[:200]}")


def main() -> None:
    print(f"Context Forge URL: {FORGE_URL}")
    print(f"Auth: {'bearer token' if TOKEN else f'basic ({AUTH_USER})'}")
    print()

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        # Health check
        try:
            r = client.get(f"{FORGE_URL}/health", headers=_headers(), auth=_auth())
            print(f"Forge health: {r.status_code}")
        except Exception as exc:
            print(f"Cannot reach Forge at {FORGE_URL}: {exc}")
            print("Make sure Context Forge is running and try again.")
            sys.exit(1)

        print()
        _seed_tool(client)
        _seed_agent(client)
        print()
        print("Done. The wizard should now show these placeholders under 'Real Tools & Agents'.")


if __name__ == "__main__":
    main()
