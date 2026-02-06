#!/usr/bin/env bash
# ==============================================================================
#  MCP Context Forge - Install & Setup Script for HomePilot
# ==============================================================================
set -euo pipefail

MCP_DIR="${1:-mcp-context-forge}"
MCP_REPO="https://github.com/ruslanmv/mcp-context-forge.git"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_PATH="$ROOT/$MCP_DIR"

echo ""
echo "  Installing MCP Context Forge (Agentic Gateway)"
echo "  ─────────────────────────────────────────────────"
echo ""

# ── 1. Clone or update the repo ──────────────────────────────────────────────
if [ -d "$MCP_PATH/.git" ]; then
    echo "  MCP Context Forge already cloned, pulling latest..."
    cd "$MCP_PATH" && git pull --ff-only origin main 2>/dev/null || echo "  (pull skipped - offline or detached)"
    cd "$ROOT"
else
    echo "  Cloning MCP Context Forge from $MCP_REPO ..."
    rm -rf "$MCP_PATH"
    git clone --depth 1 "$MCP_REPO" "$MCP_PATH"
fi

echo "  ✓ Repository ready at $MCP_DIR/"

# ── 1b. Create .env with admin UI settings (if not already present) ───────────
if [ ! -f "$MCP_PATH/.env" ]; then
    echo "  Creating MCP Gateway .env with admin UI enabled..."
    cat > "$MCP_PATH/.env" <<'ENVEOF'
# HomePilot MCP Context Forge defaults
# These ensure the Admin UI is available at /admin

HOST=0.0.0.0
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme

# Disable login prompt so the Admin UI opens without password
AUTH_REQUIRED=false

# Admin UI & API — required for "Open Tool & Agent Manager" in HomePilot Settings
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
ENVEOF
    echo "  ✓ .env created at $MCP_DIR/.env"
else
    echo "  ✓ .env already exists"
fi

# ── 2. Create a virtual environment for the gateway ──────────────────────────
if [ ! -d "$MCP_PATH/.venv" ]; then
    echo ""
    echo "  Creating MCP Gateway virtual environment..."
    cd "$MCP_PATH"
    if command -v uv >/dev/null 2>&1; then
        uv venv .venv --python 3.11 || uv venv .venv
    else
        python3 -m venv .venv
    fi
    cd "$ROOT"
fi

echo "  ✓ Virtual environment ready"

# ── 3. Install the gateway package ───────────────────────────────────────────
echo ""
echo "  Installing MCP Gateway dependencies..."
cd "$MCP_PATH"

if command -v uv >/dev/null 2>&1; then
    uv pip install -e . --python .venv/bin/python 2>&1 | tail -3
else
    .venv/bin/pip install -e . 2>&1 | tail -3
fi

cd "$ROOT"
echo "  ✓ MCP Gateway installed"

# ── 4. Install a few useful Python MCP servers ───────────────────────────────
echo ""
echo "  Installing bundled MCP servers..."

MCP_SERVERS_PYTHON="$MCP_PATH/mcp-servers/python"

install_mcp_server() {
    local server_name="$1"
    local server_path="$MCP_SERVERS_PYTHON/$server_name"

    if [ ! -d "$server_path" ]; then
        echo "    ⚠  Server '$server_name' not found, skipping"
        return 0
    fi

    # Check if it has a pyproject.toml or setup.py
    if [ -f "$server_path/pyproject.toml" ] || [ -f "$server_path/setup.py" ]; then
        echo "    Installing $server_name ..."
        cd "$server_path"
        if [ ! -d ".venv" ]; then
            if command -v uv >/dev/null 2>&1; then
                uv venv .venv --python 3.11 2>/dev/null || uv venv .venv 2>/dev/null || python3 -m venv .venv
            else
                python3 -m venv .venv
            fi
        fi
        if command -v uv >/dev/null 2>&1; then
            uv pip install -e . --python .venv/bin/python 2>/dev/null || true
        else
            .venv/bin/pip install -e . 2>/dev/null || true
        fi
        cd "$ROOT"
        echo "    ✓ $server_name"
    else
        echo "    ⚠  $server_name has no pyproject.toml, skipping"
    fi
}

# Install a curated set of useful MCP servers
# Users can install more later via: make mcp-install-server NAME=<server>
SERVERS_TO_INSTALL="${MCP_SERVERS:-csv_pandas_chat_server plotly_server python_sandbox_server}"

for server in $SERVERS_TO_INSTALL; do
    install_mcp_server "$server" || true
done

# ── 5. Setup the LangChain agent runtime ─────────────────────────────────────
AGENT_PATH="$MCP_PATH/agent_runtimes/langchain_agent"
if [ -d "$AGENT_PATH" ]; then
    echo ""
    echo "  Setting up LangChain Agent runtime..."
    cd "$AGENT_PATH"
    if [ ! -d ".venv" ]; then
        if command -v uv >/dev/null 2>&1; then
            uv venv .venv --python 3.11 2>/dev/null || uv venv .venv 2>/dev/null || python3 -m venv .venv
        else
            python3 -m venv .venv
        fi
    fi
    if [ -f "requirements.txt" ]; then
        if command -v uv >/dev/null 2>&1; then
            uv pip install -r requirements.txt --python .venv/bin/python 2>/dev/null || true
        else
            .venv/bin/pip install -r requirements.txt 2>/dev/null || true
        fi
    elif [ -f "pyproject.toml" ]; then
        if command -v uv >/dev/null 2>&1; then
            uv pip install -e . --python .venv/bin/python 2>/dev/null || true
        else
            .venv/bin/pip install -e . 2>/dev/null || true
        fi
    fi
    cd "$ROOT"
    echo "  ✓ LangChain Agent runtime ready"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "  ✅ MCP Context Forge installation complete!"
echo ""
echo "  Gateway:  $MCP_DIR/"
echo "  Servers:  $MCP_DIR/mcp-servers/python/"
echo "  Agent:    $MCP_DIR/agent_runtimes/langchain_agent/"
echo ""
