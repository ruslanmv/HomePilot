# ─────────────────────────────────────────────────────────────────────────────
# HomePilot — Generic MCP Server & A2A Agent Image
# ─────────────────────────────────────────────────────────────────────────────
#
# A single reusable image for all 17 MCP servers and 2 A2A agents.
# Parameterized at runtime via SERVER_MODULE and PORT.
#
# Build (from repo root):
#   docker build -t homepilot/mcp-server:latest -f agentic/integrations/Dockerfile .
#
# Run any server:
#   docker run -p 9110:9110 -e SERVER_MODULE=agentic.integrations.mcp.local_notes_server:app -e PORT=9110 homepilot/mcp-server:latest
#   docker run -p 9114:9114 -e SERVER_MODULE=agentic.integrations.mcp.gmail_server:app -e PORT=9114 homepilot/mcp-server:latest
#   docker run -p 9201:9201 -e SERVER_MODULE=agentic.integrations.a2a.everyday_assistant_agent:app -e PORT=9201 homepilot/mcp-server:latest
#
# Or use docker-compose.mcp.yml to start any combination.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

LABEL maintainer="Ruslan Magana Vsevolodovna <ruslanmv@gmail.com>"
LABEL org.opencontainers.image.title="HomePilot MCP Server"
LABEL org.opencontainers.image.description="Generic runtime for HomePilot MCP tool servers and A2A agents"
LABEL org.opencontainers.image.source="https://github.com/ruslanmv/HomePilot"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ── Install the union of all server dependencies ─────────────────────────────
# Every MCP server and A2A agent in the ecosystem uses a subset of these.
# Installing all of them adds ~50 MB but means one image serves every server.
RUN pip install --no-cache-dir \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.27" \
    "pydantic>=2.0" \
    "python-dotenv>=1.0" \
    "httpx>=0.27" \
    "google-auth>=2.0" \
    "google-auth-oauthlib>=1.0" \
    "google-api-python-client>=2.0" \
    "msal>=1.24"

# ── Copy the agentic package (all servers + shared framework) ────────────────
# This includes _common/server.py, all *_server.py entry points, and all
# sub-packages (local_notes/, gmail/, web_search/, etc.)
COPY agentic/ agentic/

# ── Runtime configuration ────────────────────────────────────────────────────
# Override these at runtime to select which server to start.
ENV SERVER_MODULE=agentic.integrations.mcp.local_notes_server:app
ENV HOST=0.0.0.0
ENV PORT=9110

# Safety defaults — every server respects these
ENV WRITE_ENABLED=false
ENV DRY_RUN=true

EXPOSE ${PORT}

# Health check — works for both MCP servers (/health) and A2A agents (/health)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\",\"9110\")}/health')" || exit 1

# ── Entrypoint ───────────────────────────────────────────────────────────────
# Shell form so ${SERVER_MODULE}, ${HOST}, and ${PORT} are expanded at runtime.
CMD uvicorn ${SERVER_MODULE} --host ${HOST} --port ${PORT}
