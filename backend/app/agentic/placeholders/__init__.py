"""Placeholder MCP tools and A2A agents for development/testing.

When no real MCP Context Forge instance is available, these lightweight
servers can be started locally to give the Agent Creation Wizard
something to display and attach to projects.

Usage:
    # Start the placeholder A2A agent (port 9100):
    uvicorn backend.app.agentic.placeholders.placeholder_a2a:app --host 0.0.0.0 --port 9100

    # Start the placeholder MCP tool server (port 9101):
    uvicorn backend.app.agentic.placeholders.placeholder_tool_server:app --host 0.0.0.0 --port 9101

Then register them in Context Forge using the seed script:
    python -m backend.app.agentic.placeholders.seed_forge
"""
