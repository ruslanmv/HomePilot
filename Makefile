SHELL := /bin/bash

# Fix uv hardlink warning on WSL / multi-filesystem setups (optional, safe default)
export UV_LINK_MODE ?= copy

# Agentic mode: set AGENTIC=0 to disable MCP gateway & agent features
AGENTIC ?= 1

# MCP Context Forge settings
MCP_DIR          ?= mcp-context-forge
MCP_REPO         ?= https://github.com/ruslanmv/mcp-context-forge.git
MCP_GATEWAY_PORT ?= 4444
MCP_GATEWAY_HOST ?= 127.0.0.1

# New MCP server directories (functional contract servers)
MCP_NEW_SERVERS := local_notes local_projects web shell_safe gmail google_calendar microsoft_graph slack github notion
MCP_SERVERS_DIR := agentic/integrations/mcp

.PHONY: help install setup run up down stop logs health dev build test test-local test-edit-session test-frontend test-mcp-servers test-docker clean \
        download download-minimal download-minimum download-recommended download-full \
        download-edit download-enhance download-video download-verify download-health \
        download-avatar-models-basic download-avatar-models-full \
        start start-backend start-frontend start-no-agentic start-agentic-servers \
        install-mcp start-mcp stop-mcp mcp-status mcp-install-server verify-mcp \
        mcp-register-homepilot mcp-list-tools mcp-list-gateways mcp-list-agents \
        mcp-register-tool mcp-register-gateway mcp-register-agent mcp-start-full \
        mcp-inventory \
        install-mcp-servers test-mcp-new-servers \
        persona-launch persona-check persona-stop persona-status persona-list

help: ## Show help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- Installation & Setup -----------------------------------------------------

install: ## Install HomePilot locally with uv (Python 3.11+)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Installing HomePilot Locally (uv + Python 3.11)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@# Check for uv
	@command -v uv >/dev/null 2>&1 || { \
		echo "ERROR: 'uv' not found."; \
		echo ""; \
		echo "Install it with:"; \
		echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo ""; \
		echo "Then reopen your terminal and run: make install"; \
		exit 1; \
	}
	@# Check Python version
	@python3 --version 2>&1 | grep -q "Python 3.11" || python3 --version 2>&1 | grep -q "Python 3.12" || { \
		echo "WARNING: Python 3.11 or 3.12 recommended. Current version:"; \
		python3 --version; \
		echo ""; \
	}
	@echo "✓ Installing backend with uv..."
	@cd backend && uv venv .venv --python 3.11 || uv venv .venv
	@cd backend && uv pip install -e .
	@cd backend && uv pip install --group dev
	@echo ""
	@echo "✓ Installing edit-session service with uv..."
	@cd edit-session && uv venv .venv --python 3.11 || uv venv .venv
	cd edit-session && uv pip install -e . --python .venv/bin/python
	@cd edit-session && uv pip install --group dev --python .venv/bin/python 2>/dev/null || true
	@test -f edit-session/.venv/bin/uvicorn || (echo "  ❌ ERROR: edit-session uvicorn not found after install"; exit 1)
	@echo "  ✓ Edit-session service installed"
	@echo ""
	@echo "✓ Installing frontend dependencies..."
	@cd frontend && npm install
	@echo ""
	@echo "✓ Installing ComfyUI..."
	@if [ ! -f "ComfyUI/main.py" ]; then \
		echo "  Cloning ComfyUI repository..."; \
		rm -rf ComfyUI; \
		git clone https://github.com/comfyanonymous/ComfyUI.git ComfyUI; \
	else \
		echo "  ComfyUI already present"; \
	fi
	@echo "  Setting up ComfyUI virtual environment..."
	@if [ ! -d "ComfyUI/.venv" ]; then \
		python3 -m venv ComfyUI/.venv; \
	fi
	@echo "  Installing ComfyUI dependencies..."
	@ComfyUI/.venv/bin/pip install -U pip setuptools wheel >/dev/null 2>&1 || true
	@ComfyUI/.venv/bin/pip install -r ComfyUI/requirements.txt
	@echo "  Installing face restoration dependencies (GFPGAN/CodeFormer)..."
	@if ComfyUI/.venv/bin/pip install facexlib gfpgan >/dev/null 2>&1; then \
		echo "  ✓ Face restoration dependencies installed"; \
		echo "  Patching basicsr for torchvision >= 0.18 compatibility..."; \
		SITE_PKG=$$(ComfyUI/.venv/bin/python -c "import site; print(site.getsitepackages()[0])" 2>/dev/null); \
		if [ -f "$$SITE_PKG/basicsr/data/degradations.py" ]; then \
			sed -i 's/from torchvision.transforms.functional_tensor import rgb_to_grayscale/from torchvision.transforms.functional import rgb_to_grayscale/' \
				"$$SITE_PKG/basicsr/data/degradations.py" && \
			echo "  ✓ basicsr patched (functional_tensor → functional)"; \
		fi; \
	else \
		echo "    (optional: facexlib/gfpgan install skipped)"; \
	fi
	@echo "  Installing ComfyUI-Impact-Pack for face restore nodes..."
	@if [ ! -d "ComfyUI/custom_nodes/ComfyUI-Impact-Pack" ]; then \
		mkdir -p ComfyUI/custom_nodes && \
		if git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git ComfyUI/custom_nodes/ComfyUI-Impact-Pack 2>/dev/null && \
		   ComfyUI/.venv/bin/pip install -r ComfyUI/custom_nodes/ComfyUI-Impact-Pack/requirements.txt >/dev/null 2>&1; then \
			echo "  ✓ ComfyUI-Impact-Pack installed"; \
		else \
			echo "    (optional: Impact-Pack install skipped)"; \
		fi; \
	else \
		echo "  ✓ ComfyUI-Impact-Pack already installed"; \
	fi
	@echo "  Installing ComfyUI-InstantID for identity-preserving generation..."
	@if [ ! -d "ComfyUI/custom_nodes/ComfyUI-InstantID" ]; then \
		mkdir -p ComfyUI/custom_nodes && \
		if git clone https://github.com/cubiq/ComfyUI_InstantID.git ComfyUI/custom_nodes/ComfyUI-InstantID 2>/dev/null; then \
			if [ -f "ComfyUI/custom_nodes/ComfyUI-InstantID/requirements.txt" ]; then \
				ComfyUI/.venv/bin/pip install -r ComfyUI/custom_nodes/ComfyUI-InstantID/requirements.txt >/dev/null 2>&1 || true; \
			fi; \
			echo "  ✓ ComfyUI-InstantID installed"; \
		else \
			echo "    (optional: ComfyUI-InstantID install skipped)"; \
		fi; \
	else \
		echo "  ✓ ComfyUI-InstantID already installed"; \
	fi
	@echo "  Installing Python dev headers + build tools (needed by InsightFace C++ extensions)..."
	@if [ -f /etc/os-release ] && grep -qi 'ubuntu\|debian' /etc/os-release 2>/dev/null; then \
		PY_VER=$$(ComfyUI/.venv/bin/python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.11"); \
		if dpkg -s "python$${PY_VER}-dev" >/dev/null 2>&1 && dpkg -s build-essential >/dev/null 2>&1; then \
			echo "  ✓ python$${PY_VER}-dev and build-essential already installed"; \
		else \
			echo "  Installing python$${PY_VER}-dev and build-essential (may require sudo)..."; \
			if sudo apt-get update -qq >/dev/null 2>&1 && sudo apt-get install -y -qq "python$${PY_VER}-dev" build-essential >/dev/null 2>&1; then \
				echo "  ✓ Build dependencies installed"; \
			else \
				echo "    (optional: could not install python$${PY_VER}-dev / build-essential — insightface may fail)"; \
				echo "    Run manually: sudo apt-get install -y python$${PY_VER}-dev build-essential"; \
			fi; \
		fi; \
	else \
		echo "  (non-Debian system — skipping apt-get; ensure Python dev headers are available)"; \
	fi
	@echo "  Installing InsightFace + ONNX Runtime in ComfyUI venv (needed by InstantID)..."
	@if ComfyUI/.venv/bin/pip install insightface onnxruntime >/dev/null 2>&1; then \
		echo "  ✓ InsightFace + ONNX Runtime installed in ComfyUI venv"; \
	else \
		echo "    (optional: insightface/onnxruntime install skipped)"; \
		echo "    If this failed with 'Python.h not found', run:"; \
		echo "      sudo apt-get install -y python3-dev build-essential"; \
		echo "    Then retry: make install"; \
	fi
	@echo ""
	@echo "✓ Setting up model directories..."
	@mkdir -p models/comfy/checkpoints models/comfy/unet models/comfy/clip models/comfy/vae models/comfy/controlnet models/comfy/sams models/comfy/rembg models/comfy/upscale_models models/comfy/gfpgan models/comfy/insightface/models models/comfy/instantid models/comfy/photomaker models/comfy/pulid models/comfy/avatar models/comfy/ipadapter models/comfy/controlnet/InstantID
	@echo "  Linking ComfyUI models to ./models/comfy..."
	@rm -rf ComfyUI/models
	@ln -s $$(pwd)/models/comfy ComfyUI/models
	@test -L ComfyUI/models || (echo "  ❌ ERROR: Failed to create symlink"; exit 1)
	@echo "  ✓ Symlink created successfully"
	@echo ""
	@echo "✓ Verifying ComfyUI install..."
	@test -f ComfyUI/main.py || (echo "  ❌ ERROR: ComfyUI/main.py missing"; exit 1)
	@test -x ComfyUI/.venv/bin/python || (echo "  ❌ ERROR: ComfyUI venv missing"; exit 1)
	@ComfyUI/.venv/bin/python -c "import torch; print('  ✓ torch:', torch.__version__)" 2>/dev/null || echo "  ✓ torch: (will be loaded at runtime)"
	@echo ""
	@# ── MCP Context Forge (agentic features) ──
	@if [ "$(AGENTIC)" = "1" ]; then \
		echo ""; \
		echo "✓ Installing MCP Context Forge (agentic gateway)..."; \
		bash scripts/mcp-setup.sh "$(MCP_DIR)" || { \
			echo "  ⚠  MCP install failed (non-fatal). You can retry with: make install-mcp"; \
			echo "  Or skip agentic features with: make install AGENTIC=0"; \
		}; \
	else \
		echo ""; \
		echo "⏭  Skipping MCP Context Forge (AGENTIC=0)"; \
	fi
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Installation Complete!"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Download models: make download-recommended (~14GB)"
	@echo "  2. Start Ollama: ollama serve"
	@echo "  3. Pull a model: ollama pull llama3:8b"
	@echo "  4. Start HomePilot: make start"
	@if [ "$(AGENTIC)" = "1" ]; then \
		echo ""; \
		echo "  MCP Gateway will start on port $(MCP_GATEWAY_PORT)"; \
		echo "  To start without MCP: make start-no-agentic"; \
	fi
	@echo ""

verify-install: ## Verify that all components are properly installed
	@echo "Verifying installation..."
	@test -f backend/.venv/bin/uvicorn || (echo "❌ backend not installed"; exit 1)
	@echo "  ✓ Backend installed"
	@test -f edit-session/.venv/bin/uvicorn || (echo "❌ edit-session not installed"; exit 1)
	@echo "  ✓ Edit-session installed"
	@test -d frontend/node_modules || (echo "❌ frontend not installed"; exit 1)
	@echo "  ✓ Frontend installed"
	@test -f ComfyUI/main.py || (echo "❌ ComfyUI missing"; exit 1)
	@echo "  ✓ ComfyUI cloned"
	@test -x ComfyUI/.venv/bin/python || (echo "❌ ComfyUI deps missing"; exit 1)
	@echo "  ✓ ComfyUI dependencies installed"
	@test -L ComfyUI/models || (echo "❌ ComfyUI/models not linked"; exit 1)
	@echo "  ✓ ComfyUI models linked"
	@test -d models/comfy/checkpoints || (echo "❌ model directories missing"; exit 1)
	@echo "  ✓ Model directories created"
	@if [ -d "ComfyUI/custom_nodes/ComfyUI-Impact-Pack" ]; then \
		echo "  ✓ ComfyUI-Impact-Pack installed (face restore nodes)"; \
	else \
		echo "  ⚠  ComfyUI-Impact-Pack not installed (optional - Fix Faces needs it)"; \
	fi
	@if [ -d "ComfyUI/custom_nodes/ComfyUI-InstantID" ]; then \
		echo "  ✓ ComfyUI-InstantID installed (Same Person generation)"; \
	else \
		echo "  ⚠  ComfyUI-InstantID not installed (optional - Same Person mode needs it)"; \
	fi
	@if ComfyUI/.venv/bin/python -c "import gfpgan" 2>/dev/null; then \
		echo "  ✓ GFPGAN importable in ComfyUI venv (face restoration ready)"; \
	else \
		echo "  ⚠  GFPGAN not importable in ComfyUI venv (Fix Faces needs it)"; \
		echo "     Fix: ComfyUI/.venv/bin/pip install facexlib gfpgan && make install"; \
	fi
	@if ComfyUI/.venv/bin/python -c "import insightface" 2>/dev/null; then \
		echo "  ✓ InsightFace available in ComfyUI venv"; \
	else \
		echo "  ⚠  InsightFace not in ComfyUI venv (optional - identity features need it)"; \
	fi
	@if [ -d "$(MCP_DIR)/.venv" ] || command -v mcpgateway >/dev/null 2>&1; then \
		echo "  ✓ MCP Context Forge installed"; \
	else \
		echo "  ⚠  MCP Context Forge not installed (optional - run: make install-mcp)"; \
	fi
	@echo ""
	@echo "✅ All components verified successfully!"

setup: ## Setup Docker environment (install deps + build images)
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@echo "Building docker images..."
	docker compose -f infra/docker-compose.yml build

# --- Local development (no Docker) --------------------------------------------

start: ## Start HomePilot locally (backend + frontend + ComfyUI)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot LOCALLY (All Services)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Prerequisites:"
	@echo "  ✓ Run 'make install' first"
	@echo "  ✓ Ollama running: ollama serve"
	@echo "  ✓ Ollama model: ollama pull llama3:8b (or your preferred model)"
	@echo ""
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "❌ Frontend not installed. Run: make install"; \
		exit 1; \
	fi
	@if [ ! -f "edit-session/.venv/bin/uvicorn" ]; then \
		echo "❌ Edit-session not installed or incomplete. Run: make install"; \
		echo "   Or manually: cd edit-session && uv pip install -e ."; \
		exit 1; \
	fi
	@if [ ! -f "ComfyUI/main.py" ]; then \
		echo "⚠️  ComfyUI not found. Run: make install"; \
		echo "    Image/video generation will not work without ComfyUI."; \
		echo ""; \
	fi
	@echo "Services:"
	@echo "  Backend:      http://localhost:8000"
	@echo "  Edit-Session: http://localhost:8010"
	@echo "  Frontend:     http://localhost:3000"
	@if [ -f "ComfyUI/main.py" ]; then \
		echo "  ComfyUI:      http://localhost:8188"; \
	fi
	@if [ "$(AGENTIC)" = "1" ] && ([ -d "$(MCP_DIR)/.venv" ] || command -v mcpgateway >/dev/null 2>&1); then \
		echo "  MCP Gateway:  http://localhost:$(MCP_GATEWAY_PORT)"; \
		echo "  MCP Servers:  http://localhost:9101-9105"; \
		echo "  A2A Agents:   http://localhost:9201-9202"; \
	fi
	@echo ""
	@echo "Press Ctrl+C to stop ALL services"
	@echo ""
	@bash -c ' \
		set -e; \
		ROOT="$$(pwd)"; \
		pids=""; \
		cleanup() { \
			echo ""; \
			echo "════════════════════════════════════════════════════════════════════════════════"; \
			echo "  Stopping all services..."; \
			echo "════════════════════════════════════════════════════════════════════════════════"; \
			[ -n "$$pids" ] && kill $$pids 2>/dev/null || true; \
			wait 2>/dev/null || true; \
			echo "All services stopped."; \
		}; \
		trap cleanup INT TERM EXIT; \
		\
		echo "Starting backend..."; \
		cd "$$ROOT/backend" && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 & \
		pids="$$pids $$!"; \
		\
		echo "Starting edit-session service..."; \
		cd "$$ROOT/edit-session" && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8010 & \
		pids="$$pids $$!"; \
		\
		echo "Starting frontend..."; \
		cd "$$ROOT/frontend" && npm run dev -- --host 0.0.0.0 --port 3000 & \
		pids="$$pids $$!"; \
		\
		if [ -f "$$ROOT/ComfyUI/main.py" ] && [ -f "$$ROOT/ComfyUI/.venv/bin/python" ]; then \
			if [ -d "$$ROOT/models/comfy" ] && [ ! -L "$$ROOT/ComfyUI/models" ]; then \
				echo "Linking ComfyUI models to ./models/comfy..."; \
				rm -rf "$$ROOT/ComfyUI/models"; \
				ln -s "$$ROOT/models/comfy" "$$ROOT/ComfyUI/models"; \
			fi; \
			echo "Starting ComfyUI..."; \
			cd "$$ROOT/ComfyUI" && .venv/bin/python main.py --listen 0.0.0.0 --port 8188 & \
			pids="$$pids $$!"; \
		fi; \
		\
		if [ "$(AGENTIC)" = "1" ] && ([ -d "$$ROOT/$(MCP_DIR)/.venv" ] || command -v mcpgateway >/dev/null 2>&1); then \
			echo ""; \
			echo "Starting MCP Context Forge Gateway on port $(MCP_GATEWAY_PORT)..."; \
			mcp_pids=$$(bash "$$ROOT/scripts/mcp-start.sh" --with-servers 2>&1 | tail -1); \
			pids="$$pids $$mcp_pids"; \
			echo "  ✓ MCP Gateway started"; \
			\
			echo ""; \
			echo "Starting HomePilot agentic servers (MCP + A2A) + seeding Forge..."; \
			agentic_pids=$$(bash "$$ROOT/scripts/agentic-start.sh" 2>&1 | tail -1); \
			pids="$$pids $$agentic_pids"; \
			echo "  ✓ Agentic servers started and Forge seeded"; \
			\
			echo ""; \
			echo "  Running final health check..."; \
			forge_ok=false; \
			for _hc in $$(seq 1 5); do \
				if curl -sf "http://localhost:$(MCP_GATEWAY_PORT)/health" >/dev/null 2>&1; then \
					forge_ok=true; \
					break; \
				fi; \
				sleep 1; \
			done; \
			if [ "$$forge_ok" = "true" ]; then \
				echo "  ✓ Context Forge (port $(MCP_GATEWAY_PORT)): healthy"; \
			else \
				echo "  ⚠ Context Forge (port $(MCP_GATEWAY_PORT)): not responding"; \
			fi; \
			mcp_ok=0; mcp_total=5; \
			for _p in 9101 9102 9103 9104 9105; do \
				if curl -sf "http://127.0.0.1:$$_p/health" >/dev/null 2>&1; then \
					mcp_ok=$$((mcp_ok + 1)); \
				fi; \
			done; \
			echo "  ✓ MCP Servers: $$mcp_ok/$$mcp_total healthy"; \
			a2a_ok=0; a2a_total=2; \
			for _p in 9201 9202; do \
				if curl -sf "http://127.0.0.1:$$_p/health" >/dev/null 2>&1; then \
					a2a_ok=$$((a2a_ok + 1)); \
				fi; \
			done; \
			echo "  ✓ A2A Agents: $$a2a_ok/$$a2a_total healthy"; \
		fi; \
		\
		echo ""; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
		if [ "$(AGENTIC)" = "1" ] && ([ -d "$$ROOT/$(MCP_DIR)/.venv" ] || command -v mcpgateway >/dev/null 2>&1); then \
			echo "  ✅ All services started! (with MCP agentic features)"; \
			echo ""; \
			echo "  Agentic servers:"; \
			echo "    MCP:  personal-assistant(:9101) knowledge(:9102) decision(:9103) briefing(:9104) web-search(:9105)"; \
			echo "    A2A:  everyday-assistant(:9201) chief-of-staff(:9202)"; \
			echo "    Forge Admin: http://localhost:$(MCP_GATEWAY_PORT)/admin"; \
		else \
			echo "  ✅ All services started!"; \
		fi; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
		echo ""; \
		wait \
	'

start-backend: ## Start backend locally with uv
	@echo "Starting backend..."
	@if [ ! -d "backend/.venv" ]; then \
		echo "Virtual environment not found. Run: make install"; \
		exit 1; \
	fi
	@cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

start-edit-session: ## Start edit-session sidecar locally (port 8010)
	@echo "Starting edit-session service..."
	@if [ ! -d "edit-session/.venv" ]; then \
		echo "Virtual environment not found. Run: make install"; \
		exit 1; \
	fi
	@cd edit-session && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8010

start-frontend: ## Start frontend locally
	@echo "Starting frontend..."
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "Node modules not found. Run: make install"; \
		exit 1; \
	fi
	@cd frontend && npm run dev -- --host 0.0.0.0 --port 3000

start-comfyui: ## Start ComfyUI locally (required for image/video generation)
	@echo "Starting ComfyUI..."
	@if [ ! -f "ComfyUI/main.py" ]; then \
		echo "❌ ComfyUI not found. Run: make install"; \
		exit 1; \
	fi
	@if [ ! -f "ComfyUI/.venv/bin/python" ]; then \
		echo "❌ ComfyUI venv not found. Run: make install"; \
		exit 1; \
	fi
	@if [ -d "models/comfy" ] && [ ! -L "ComfyUI/models" ]; then \
		echo "ℹ️  Auto-linking models..."; \
		rm -rf ComfyUI/models; \
		ln -s $$(pwd)/models/comfy ComfyUI/models; \
	fi
	@cd ComfyUI && .venv/bin/python main.py --listen 0.0.0.0 --port 8188

# --- Testing & Development ----------------------------------------------------

test: test-local test-edit-session test-frontend test-mcp-servers  ## Run all tests (backend + edit-session + frontend + MCP)
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ All tests passed!"
	@echo "════════════════════════════════════════════════════════════════════════════════"

test-local: ## Run backend API tests locally with pytest
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Running HomePilot Backend Tests"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@echo ""
	@echo "Testing backend API endpoints..."
	@cd backend && .venv/bin/pytest -v --tb=short --ignore=tests/test_mcp_servers.py
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Backend tests passed!"
	@echo "════════════════════════════════════════════════════════════════════════════════"

test-edit-session: ## Run edit-session sidecar tests
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Running Edit-Session Sidecar Tests"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "edit-session/.venv" ]; then \
		echo "⚠️  Edit-session not installed — skipping (run: make install)"; \
	else \
		cd edit-session && .venv/bin/pytest app/tests/ -v --tb=short; \
		echo ""; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
		echo "  ✅ Edit-session tests passed!"; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
	fi

test-frontend: ## Run frontend TypeScript type-check
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Running Frontend TypeScript Check"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "⚠️  Frontend not installed — skipping (run: cd frontend && npm install)"; \
	else \
		cd frontend && npx tsc --noEmit; \
		echo ""; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
		echo "  ✅ Frontend TypeScript check passed!"; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
	fi

test-mcp-servers: ## Run MCP server & A2A agent integration tests
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Running MCP Server & A2A Agent Tests"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@echo ""
	@echo "Testing all MCP servers (Personal Assistant, Knowledge, Decision, Briefing)..."
	@echo "Testing all A2A agents (Everyday Assistant, Chief of Staff)..."
	@cd backend && .venv/bin/pytest tests/test_mcp_servers.py -v --tb=short
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ MCP server & A2A agent tests passed!"
	@echo "════════════════════════════════════════════════════════════════════════════════"

# --- Docker stack -------------------------------------------------------------

run: ## Production: Start full stack with Ollama container (docker)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot PRODUCTION (All Containers + Ollama)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	docker compose -f infra/docker-compose.yml --profile ollama up -d --build
	@echo ""
	@echo "✅ All containers started (including Ollama)"
	@echo ""
	@echo "Services:"
	@echo "  UI      : http://localhost:3000"
	@echo "  Backend : http://localhost:8000/docs"
	@echo "  LLM API : http://localhost:8001/v1"
	@echo "  ComfyUI : http://localhost:8188"
	@echo "  Ollama  : http://localhost:11434"
	@echo ""
	@echo "NOTE: Ollama is running in Docker. Pull models with:"
	@echo "  docker exec -it homepilot_ollama ollama pull llama3:8b"
	@echo ""
	@echo "For local development without Ollama container, use: make local"
	@echo ""

up: ## Development: Start stack WITHOUT Ollama container (use host Ollama)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot DEVELOPMENT (Containers without Ollama)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	docker compose -f infra/docker-compose.yml up -d --build
	@echo ""
	@echo "✅ Containers started (without Ollama - use host Ollama)"
	@echo ""
	@echo "Services:"
	@echo "  UI      : http://localhost:3000"
	@echo "  Backend : http://localhost:8000/docs"
	@echo "  LLM API : http://localhost:8001/v1"
	@echo "  ComfyUI : http://localhost:8188"
	@echo ""
	@echo "NOTE: Using Ollama on your host machine at host.docker.internal:11434"
	@echo "  Make sure Ollama is running: ollama serve"
	@echo ""
	@echo "For production with Ollama in Docker, use: make run"
	@echo ""

down: ## Stop all containers (including Ollama if running)
	docker compose -f infra/docker-compose.yml --profile ollama down

stop: ## Stop all local HomePilot processes (kills processes on all service ports)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Stopping HomePilot Services"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@# Kill processes by port (works on Linux/macOS/WSL)
	@# Core: 3000(frontend) 8000(backend) 8010(edit-session) 8188(comfyui)
	@# MCP:  9101-9105(MCP servers) 9201-9202(A2A agents)
	@for port in 3000 8000 8010 8188 9101 9102 9103 9104 9105 9201 9202; do \
		echo "Checking port $$port..."; \
		pid=$$(lsof -ti :$$port 2>/dev/null || true); \
		if [ -n "$$pid" ]; then \
			echo "  Killing process(es) on port $$port: $$pid"; \
			echo "$$pid" | xargs -r kill -9 2>/dev/null || true; \
		else \
			echo "  No process on port $$port"; \
		fi; \
	done
	@# Also kill by process name as backup (in case lsof misses something)
	@echo ""
	@echo "Cleaning up by process name..."
	@-pkill -9 -f "ComfyUI/main.py" 2>/dev/null && echo "  Killed ComfyUI" || true
	@-pkill -9 -f "uvicorn app.main:app" 2>/dev/null && echo "  Killed backend" || true
	@-pkill -9 -f "vite.*--port 3000" 2>/dev/null && echo "  Killed frontend" || true
	@-pkill -9 -f "mcpgateway.main:app" 2>/dev/null && echo "  Killed MCP Gateway" || true
	@-pkill -9 -f "server_fastmcp" 2>/dev/null && echo "  Killed MCP servers" || true
	@echo "  Done"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ All HomePilot services stopped"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "You can now safely run: make start"
	@echo ""

logs: ## Tail logs
	docker compose -f infra/docker-compose.yml logs -f --tail=200

health: ## Health checks (best-effort)
	@curl -fsS http://localhost:8000/health | jq . || true
	@curl -fsS http://localhost:8188/system_stats | jq . || true
	@curl -fsS http://localhost:8001/v1/models | jq . || true

dev: ## Frontend dev locally; backend stack in docker
	docker compose -f infra/docker-compose.yml up -d backend llm comfyui media
	cd frontend && npm run dev -- --host 0.0.0.0 --port 3000

build: ## Build production frontend bundle
	cd frontend && npm run build

test-docker: ## Run backend tests (pytest) inside backend container
	docker compose -f infra/docker-compose.yml run --rm backend pytest -q

download: download-recommended ## Download models (alias for download-recommended)

download-minimal: ## Download minimal models (~7GB - FLUX Schnell + encoders)
	@bash scripts/download_models.sh minimal

download-recommended: ## Download recommended models (~24GB - FLUX Schnell + SDXL + edit models)
	@bash scripts/download_models.sh recommended

download-full: ## Download all models (~63GB - FLUX, SDXL, SD1.5, SVD, all edit models)
	@bash scripts/download_models.sh full

download-edit: ## Download only edit mode models (inpainting, controlnet, etc.)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Edit Mode Models"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@mkdir -p models/comfy/checkpoints models/comfy/controlnet models/comfy/sams models/comfy/rembg
	@echo ""
	@echo "[1/5] Downloading SDXL Inpainting 0.1..."
	@wget -c --progress=bar:force -O models/comfy/checkpoints/sd_xl_base_1.0_inpainting_0.1.safetensors \
		"https://huggingface.co/wangqyqq/sd_xl_base_1.0_inpainting_0.1.safetensors/resolve/main/sd_xl_base_1.0_inpainting_0.1.safetensors" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[2/5] Downloading SD 1.5 Inpainting..."
	@wget -c --progress=bar:force -O models/comfy/checkpoints/sd-v1-5-inpainting.ckpt \
		"https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-inpainting/resolve/main/sd-v1-5-inpainting.ckpt" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[3/5] Downloading ControlNet Inpaint..."
	@wget -c --progress=bar:force -O models/comfy/controlnet/control_v11p_sd15_inpaint.safetensors \
		"https://huggingface.co/lllyasviel/control_v11p_sd15_inpaint/resolve/main/diffusion_pytorch_model.safetensors" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[4/5] Downloading SAM ViT-H..."
	@wget -c --progress=bar:force -O models/comfy/sams/sam_vit_h_4b8939.pth \
		"https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[5/5] Downloading U2Net..."
	@wget -c --progress=bar:force -O models/comfy/rembg/u2net.onnx \
		"https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Edit mode model download complete!"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@du -sh models/comfy/checkpoints/*inpaint* models/comfy/controlnet/* models/comfy/sams/* models/comfy/rembg/* 2>/dev/null || true

download-enhance: ## Download upscale/enhance models (4x-UltraSharp, RealESRGAN, SwinIR, GFPGAN)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Upscale/Enhance Models"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@mkdir -p models/comfy/upscale_models models/comfy/gfpgan
	@echo ""
	@echo "[1/5] Downloading 4x-UltraSharp (REQUIRED - default upscaler)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/4x-UltraSharp.pth \
		"https://huggingface.co/philz1337x/upscaler/resolve/main/4x-UltraSharp.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[2/5] Downloading RealESRGAN x4+ (Photo upscaler)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/RealESRGAN_x4plus.pth \
		"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[3/5] Downloading SwinIR 4x (Restoration upscaler)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/SwinIR_4x.pth \
		"https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[4/5] Downloading Real-ESRGAN General x4v3 (Mixed content)..."
	@wget -c --progress=bar:force -O models/comfy/upscale_models/realesr-general-x4v3.pth \
		"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[5/5] Downloading GFPGAN v1.4 (Face restoration)..."
	@wget -c --progress=bar:force -O models/comfy/gfpgan/GFPGANv1.4.pth \
		"https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Upscale/Enhance model download complete!"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@du -sh models/comfy/upscale_models/* models/comfy/gfpgan/* 2>/dev/null || true

download-avatar-models-basic: ## Download basic avatar models (~1.8GB — InsightFace + InstantID adapter + ControlNet)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Avatar Models (Basic)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@mkdir -p models/comfy/insightface/models models/comfy/instantid models/comfy/controlnet/InstantID
	@echo ""
	@echo "[1/3] Downloading InsightFace AntelopeV2 (face detection + embeddings)..."
	@wget -c --progress=bar:force -O models/comfy/insightface/models/antelopev2.zip \
		"https://huggingface.co/MonsterMMORPG/tools/resolve/main/antelopev2.zip" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[2/3] Downloading InstantID ip-adapter.bin..."
	@wget -c --progress=bar:force -O models/comfy/instantid/ip-adapter.bin \
		"https://huggingface.co/InstantX/InstantID/resolve/main/ip-adapter.bin" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[3/3] Downloading InstantID ControlNet..."
	@wget -c --progress=bar:force -O models/comfy/controlnet/InstantID/diffusion_pytorch_model.safetensors \
		"https://huggingface.co/InstantX/InstantID/resolve/main/ControlNetModel/diffusion_pytorch_model.safetensors" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Basic avatar models downloaded."
	@echo ""
	@echo "  Note: AntelopeV2 is a zip. Some ComfyUI nodes expect it extracted:"
	@echo "    unzip -o models/comfy/insightface/models/antelopev2.zip \\"
	@echo "      -d models/comfy/insightface/models/"
	@echo ""
	@echo "  These models enable: InstantID face-identity generation in PersonaWizard."
	@echo "  For more models: make download-avatar-models-full"
	@echo "════════════════════════════════════════════════════════════════════════════════"

download-avatar-models-full: download-avatar-models-basic ## Download full avatar model stack (adds PhotoMaker/PuLID/FaceSwap/StyleGAN2)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Avatar Models (Full — additive to Basic)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@mkdir -p models/comfy/photomaker models/comfy/pulid models/comfy/avatar models/comfy/insightface models/comfy/ipadapter
	@echo ""
	@echo "[1/6] Downloading PhotoMaker V2 (Apache 2.0)..."
	@wget -c --progress=bar:force -O models/comfy/photomaker/photomaker-v2.bin \
		"https://huggingface.co/TencentARC/PhotoMaker-V2/resolve/main/photomaker-v2.bin" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[2/6] Downloading PuLID for FLUX (Apache 2.0)..."
	@wget -c --progress=bar:force -O models/comfy/pulid/pulid_flux_v0.9.0.safetensors \
		"https://huggingface.co/guozinan/PuLID/resolve/main/pulid_flux_v0.9.0.safetensors" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[3/6] Downloading InsightFace InSwapper 128 (ONNX)..."
	@wget -c --progress=bar:force -O models/comfy/insightface/inswapper_128.onnx \
		"https://huggingface.co/ezioruan/inswapper_128.onnx/resolve/main/inswapper_128.onnx" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[4/6] Downloading IP-Adapter FaceID PlusV2 SDXL (Non-Commercial)..."
	@wget -c --progress=bar:force -O models/comfy/ipadapter/ip-adapter-faceid-plusv2_sdxl.bin \
		"https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl.bin" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[5/6] Downloading StyleGAN2 FFHQ 256 (NON-COMMERCIAL — NVIDIA)..."
	@wget -c --progress=bar:force -O models/comfy/avatar/stylegan2-ffhq-256x256.pkl \
		"https://api.ngc.nvidia.com/v2/models/nvidia/research/stylegan2/versions/1/files/stylegan2-ffhq-256x256.pkl" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "[6/6] Downloading StyleGAN2 FFHQ 1024 (NON-COMMERCIAL — NVIDIA)..."
	@wget -c --progress=bar:force -O models/comfy/avatar/stylegan2-ffhq-1024x1024.pkl \
		"https://api.ngc.nvidia.com/v2/models/nvidia/research/stylegan2/versions/1/files/stylegan2-ffhq-1024x1024.pkl" 2>&1 || echo "Failed - retry or download manually"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Full avatar model download complete."
	@echo ""
	@echo "  License summary:"
	@echo "    Apache 2.0 (commercial OK): InstantID, PhotoMaker V2, PuLID"
	@echo "    Non-commercial:             StyleGAN2 FFHQ (NVIDIA), IP-Adapter FaceID"
	@echo "    MIT (code):                 InsightFace"
	@echo ""
	@echo "  For commercial deployments use the Apache 2.0 stack only."
	@echo "════════════════════════════════════════════════════════════════════════════════"

download-video: ## Download video generation models (LTX-Video + T5 encoder, ~11GB for RTX 4080 12GB)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Downloading Video Generation Models (RTX 4080 12GB Optimized)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "This will download:"
	@echo "  • LTX-Video 2B v0.9.1 - 5.72 GB (video checkpoint)"
	@echo "  • T5-XXL FP8 Encoder  - 4.89 GB (text encoder for 12GB VRAM)"
	@echo ""
	@echo "Total: ~11 GB"
	@echo ""
	@mkdir -p models/comfy/checkpoints models/comfy/clip
	@echo "[1/2] Downloading LTX-Video 2B v0.9.1..."
	@python3 scripts/download.py --model ltx-video-2b-v0.9.1.safetensors || echo "  ⚠️  Failed - check output above"
	@echo ""
	@echo "[2/2] Downloading T5-XXL FP8 Text Encoder (required for LTX-Video on 12GB VRAM)..."
	@if [ ! -f "models/comfy/clip/t5xxl_fp8_e4m3fn.safetensors" ]; then \
		wget -c --progress=bar:force -O models/comfy/clip/t5xxl_fp8_e4m3fn.safetensors \
			"https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors" 2>&1 || echo "  ⚠️  Failed - retry or download manually"; \
	else \
		echo "  ✓ T5-XXL FP8 already exists, skipping"; \
	fi
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Video model download complete!"
	@echo ""
	@echo "  Installed models:"
	@ls -lh models/comfy/checkpoints/ltx*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || true
	@ls -lh models/comfy/clip/t5xxl*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || true
	@echo ""
	@echo "  For 24GB+ VRAM (RTX 4090), also download T5-XXL FP16 for better quality:"
	@echo "    wget -O models/comfy/clip/t5xxl_fp16.safetensors \\"
	@echo "      https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"
	@echo ""
	@echo "  Additional video models available:"
	@echo "    python3 scripts/download.py --model svd_xt_1_1.safetensors"
	@echo "    python3 scripts/download.py --model hunyuanvideo_t2v_720p_gguf_q4_k_m_pack"
	@echo "    python3 scripts/download.py --model wan2.2_5b_fp16_pack"
	@echo "════════════════════════════════════════════════════════════════════════════════"

download-minimum: download-minimal  ## Alias for download-minimal (RTX 4080 12GB optimized)

download-health: ## Check health of model download URLs
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Checking Model Download URL Health"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@python scripts/check_model_health.py

download-verify: ## Verify downloaded models and show disk usage
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Model Verification"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@if [ -d "models/comfy" ]; then \
		echo "ComfyUI Models:"; \
		echo ""; \
		echo "  Checkpoints (image generation):"; \
		ls -lh models/comfy/checkpoints/*.safetensors models/comfy/checkpoints/*.ckpt 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  UNET Models (FLUX/Video):"; \
		ls -lh models/comfy/unet/*.safetensors models/comfy/unet/*.gguf 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Diffusion Models (Video):"; \
		ls -lh models/comfy/diffusion_models/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  CLIP Encoders:"; \
		ls -lh models/comfy/clip/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  VAE Models:"; \
		ls -lh models/comfy/vae/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  ControlNet (edit guidance):"; \
		ls -lh models/comfy/controlnet/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  SAM Models (segmentation):"; \
		ls -lh models/comfy/sams/*.pth 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Rembg Models (background removal):"; \
		ls -lh models/comfy/rembg/*.onnx 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Upscale Models (image enhancement):"; \
		ls -lh models/comfy/upscale_models/*.pth 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  GFPGAN Models (face restoration):"; \
		ls -lh models/comfy/gfpgan/*.pth 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Avatar Models (identity-preserving generation):"; \
		ls -lh models/comfy/instantid/* models/comfy/insightface/models/*.zip models/comfy/insightface/*.onnx models/comfy/photomaker/* models/comfy/pulid/* models/comfy/ipadapter/* models/comfy/avatar/* models/comfy/controlnet/InstantID/* 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  Total ComfyUI storage: $$(du -sh models/comfy 2>/dev/null | cut -f1)"; \
		echo ""; \
	else \
		echo "❌ models/comfy directory not found"; \
		echo "   Run: make download-recommended"; \
		echo ""; \
	fi
	@if [ -d "models/llm" ]; then \
		echo "LLM Models:"; \
		ls -lh models/llm/ 2>/dev/null | tail -n +2 || echo "  (managed by Ollama/vLLM)"; \
		echo ""; \
	fi
	@echo "════════════════════════════════════════════════════════════════════════════════"

start-avatar-service: ## Start the optional Avatar Service microservice (StyleGAN random faces, port 8020)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting Avatar Service (port 8020)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@cd avatar-service && bash scripts/run_dev.sh

verify-avatar: ## Verify Avatar Studio installation (packs, workflows, service)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Avatar Studio Verification"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "1. Checking workflow templates..."
	@ls workflows/avatar/*.json 2>/dev/null && echo "   ✅ Workflow templates found" || echo "   ❌ No workflow templates in workflows/avatar/"
	@echo ""
	@echo "2. Checking model pack markers..."
	@if [ -f "models/packs/avatar-basic.installed" ]; then \
		echo "   ✅ avatar-basic pack: installed"; \
	else \
		echo "   ⚠️  avatar-basic pack: not installed (run: make download-avatar-models-basic)"; \
	fi
	@if [ -f "models/packs/avatar-stylegan2.installed" ]; then \
		echo "   ✅ avatar-stylegan2 pack: installed"; \
	else \
		echo "   ℹ️  avatar-stylegan2 pack: not installed (optional — run: make download-avatar-models-full)"; \
	fi
	@echo ""
	@echo "3. Checking backend avatar module..."
	@python3 -c "from backend.app.avatar import router; print('   ✅ Avatar router importable')" 2>/dev/null || echo "   ❌ Avatar module import failed"
	@echo ""
	@echo "4. Checking avatar-service (optional)..."
	@curl -fsS http://localhost:8020/docs 2>/dev/null >/dev/null && echo "   ✅ Avatar service running on port 8020" || echo "   ℹ️  Avatar service not running (optional — run: make start-avatar-service)"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"

mark-avatar-packs: ## Create marker files to indicate avatar packs are installed (dev shortcut)
	@mkdir -p models/packs
	@touch models/packs/avatar-basic.installed
	@echo "✅ Marked avatar-basic as installed"
	@echo "ℹ️  To also enable StyleGAN random faces, run: touch models/packs/avatar-stylegan2.installed"

clean: ## Remove local artifacts
	rm -rf frontend/node_modules frontend/dist
	rm -rf backend/data/*.db || true

health-check: ## Comprehensive health check of all services
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  HomePilot Health Check"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Checking all services..."
	@echo ""
	@echo "1. Backend API"
	@curl -fsS http://localhost:8000/health 2>/dev/null | jq '.' || echo "❌ Backend not running"
	@echo ""
	@echo "2. Detailed Service Health"
	@curl -fsS http://localhost:8000/health/detailed 2>/dev/null | jq '.' || echo "❌ Backend not running"
	@echo ""
	@echo "3. Direct Service Checks:"
	@echo ""
	@echo "   Ollama:"
	@curl -fsS http://localhost:11434 2>/dev/null && echo "   ✅ Ollama is running" || echo "   ❌ Ollama not reachable at localhost:11434"
	@echo ""
	@echo "   ComfyUI:"
	@curl -fsS http://localhost:8188/system_stats 2>/dev/null >/dev/null && echo "   ✅ ComfyUI is running" || echo "   ❌ ComfyUI not reachable at localhost:8188"
	@echo ""
	@echo "   vLLM:"
	@curl -fsS http://localhost:8001/v1/models 2>/dev/null >/dev/null && echo "   ✅ vLLM is running" || echo "   ❌ vLLM not reachable at localhost:8001"
	@echo ""
	@echo "   MCP Gateway:"
	@curl -fsS http://localhost:$(MCP_GATEWAY_PORT)/health 2>/dev/null >/dev/null && echo "   ✅ MCP Gateway is running" || echo "   ⚠  MCP Gateway not running (optional - start with: make start-mcp)"
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"

# --- MCP Context Forge (Agentic Features) ------------------------------------

start-no-agentic: ## Start HomePilot WITHOUT MCP gateway/agentic features
	@$(MAKE) start AGENTIC=0

start-agentic-servers: ## Start HomePilot MCP servers + A2A agents + seed Forge (standalone)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot Agentic Servers"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@echo ""
	@echo "  MCP servers:  ports 9101-9105"
	@echo "  A2A agents:   ports 9201-9202"
	@echo ""
	@echo "  Press Ctrl+C to stop"
	@echo ""
	@bash -c ' \
		ROOT="$$(pwd)"; \
		pids=""; \
		cleanup() { \
			echo ""; \
			echo "Stopping agentic servers..."; \
			[ -n "$$pids" ] && kill $$pids 2>/dev/null || true; \
			wait 2>/dev/null || true; \
			echo "Done."; \
		}; \
		trap cleanup INT TERM EXIT; \
		agentic_pids=$$(bash "$$ROOT/scripts/agentic-start.sh" 2>&1 | tail -1); \
		pids="$$agentic_pids"; \
		echo ""; \
		echo "  ✅ Agentic servers running!"; \
		echo ""; \
		echo "  MCP:  personal-assistant(:9101) knowledge(:9102) decision(:9103) briefing(:9104) web-search(:9105)"; \
		echo "  A2A:  everyday-assistant(:9201) chief-of-staff(:9202)"; \
		echo ""; \
		wait \
	'

install-mcp: ## Install MCP Context Forge separately (gateway + servers + agent)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Installing MCP Context Forge"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@bash scripts/mcp-setup.sh "$(MCP_DIR)"

start-mcp: ## Start only the MCP Gateway (port 4444)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting MCP Context Forge Gateway"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "$(MCP_DIR)/.venv" ] && ! command -v mcpgateway >/dev/null 2>&1; then \
		echo "❌ MCP not installed. Run: make install-mcp"; \
		exit 1; \
	fi
	@echo ""
	@echo "  MCP Gateway:  http://localhost:$(MCP_GATEWAY_PORT)"
	@echo "  Admin UI:     http://localhost:$(MCP_GATEWAY_PORT)/admin"
	@echo ""
	@echo "  Press Ctrl+C to stop"
	@echo ""
	@if [ -d "$(MCP_DIR)/.venv" ]; then \
		cd $(MCP_DIR) && \
		HOST=0.0.0.0 \
		BASIC_AUTH_USER=admin BASIC_AUTH_PASSWORD=changeme \
		AUTH_REQUIRED=false \
		MCPGATEWAY_UI_ENABLED=true \
		MCPGATEWAY_ADMIN_API_ENABLED=true \
		.venv/bin/python -m uvicorn mcpgateway.main:app \
		--host $(MCP_GATEWAY_HOST) --port $(MCP_GATEWAY_PORT) --reload; \
	else \
		HOST=0.0.0.0 \
		BASIC_AUTH_USER=admin BASIC_AUTH_PASSWORD=changeme \
		AUTH_REQUIRED=false \
		MCPGATEWAY_UI_ENABLED=true \
		MCPGATEWAY_ADMIN_API_ENABLED=true \
		mcpgateway mcpgateway.main:app \
		--host $(MCP_GATEWAY_HOST) --port $(MCP_GATEWAY_PORT) --reload; \
	fi

stop-mcp: ## Stop MCP Gateway and MCP server processes
	@echo "Stopping MCP processes..."
	@-pkill -f "mcpgateway.main:app" 2>/dev/null && echo "  Killed MCP Gateway" || echo "  MCP Gateway not running"
	@-pkill -f "server_fastmcp" 2>/dev/null && echo "  Killed MCP servers" || echo "  No MCP servers running"
	@echo "  Done"

mcp-status: ## Show status of MCP Gateway and registered tools
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  MCP Context Forge Status"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Installation:"
	@if [ -d "$(MCP_DIR)/.venv" ] || command -v mcpgateway >/dev/null 2>&1; then \
		echo "  ✓ Gateway installed"; \
	else \
		echo "  ❌ Gateway not installed (run: make install-mcp)"; \
	fi
	@echo ""
	@echo "Gateway Health:"
	@curl -fsS http://localhost:$(MCP_GATEWAY_PORT)/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  ❌ Gateway not running (start with: make start-mcp)"
	@echo ""
	@echo "Registered Tools:"
	@curl -fsS http://localhost:$(MCP_GATEWAY_PORT)/tools 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  (gateway not reachable)"
	@echo ""

mcp-install-server: ## Install an individual MCP server (usage: make mcp-install-server NAME=csv_pandas_chat_server)
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make mcp-install-server NAME=<server-name>"; \
		echo ""; \
		echo "Available servers:"; \
		ls -1 $(MCP_DIR)/mcp-servers/python/ 2>/dev/null || echo "  (MCP not installed)"; \
		exit 1; \
	fi
	@echo "Installing MCP server: $(NAME)..."
	@MCP_SERVERS="$(NAME)" bash scripts/mcp-setup.sh "$(MCP_DIR)"

verify-mcp: ## Verify MCP Context Forge installation
	@echo "Verifying MCP installation..."
	@if [ -d "$(MCP_DIR)/.venv" ]; then \
		echo "  ✓ Repository cloned"; \
		echo "  ✓ Gateway virtual environment"; \
		test -f "$(MCP_DIR)/.venv/bin/python" && echo "  ✓ Gateway Python interpreter" || echo "  ❌ Gateway python missing"; \
		$(MCP_DIR)/.venv/bin/python -c "import mcpgateway" 2>/dev/null && echo "  ✓ mcpgateway package importable" || echo "  ⚠  mcpgateway not importable (may need reinstall)"; \
	elif command -v mcpgateway >/dev/null 2>&1; then \
		echo "  ✓ mcpgateway installed via pip ($$(which mcpgateway))"; \
		python3 -c "import mcpgateway" 2>/dev/null && echo "  ✓ mcpgateway package importable" || echo "  ⚠  mcpgateway not importable"; \
	else \
		echo "❌ MCP Context Forge not installed"; exit 1; \
	fi
	@echo ""
	@echo "Installed MCP Servers:"
	@for d in $(MCP_DIR)/mcp-servers/python/*/; do \
		name=$$(basename $$d); \
		if [ -d "$$d/.venv" ]; then \
			echo "  ✓ $$name"; \
		fi; \
	done
	@echo ""
	@echo "✅ MCP verification complete"

mcp-start-full: ## Start MCP Gateway + servers + agent (full agentic stack)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting Full MCP Agentic Stack"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "$(MCP_DIR)/.venv" ] && ! command -v mcpgateway >/dev/null 2>&1; then \
		echo "❌ MCP not installed. Run: make install-mcp"; \
		exit 1; \
	fi
	@echo ""
	@echo "  MCP Gateway:  http://localhost:$(MCP_GATEWAY_PORT)"
	@echo "  Admin UI:     http://localhost:$(MCP_GATEWAY_PORT)/admin"
	@echo "  MCP Servers:  ports 9100+"
	@echo "  Agent:        http://localhost:9200"
	@echo ""
	@echo "  Press Ctrl+C to stop"
	@echo ""
	@bash -c ' \
		ROOT="$$(pwd)"; \
		pids=""; \
		cleanup() { echo ""; echo "Stopping MCP stack..."; [ -n "$$pids" ] && kill $$pids 2>/dev/null || true; wait 2>/dev/null || true; echo "Done."; }; \
		trap cleanup INT TERM EXIT; \
		mcp_pids=$$(bash "$$ROOT/scripts/mcp-start.sh" --all 2>&1 | tail -1); \
		pids="$$mcp_pids"; \
		echo ""; \
		echo "  ✅ Full MCP stack running!"; \
		echo ""; \
		wait \
	'

mcp-inventory: ## List all MCP Context Forge inventory (gateways, servers, tools, agents)
	@MCPF_BASE_URL="http://localhost:$(MCP_GATEWAY_PORT)" \
		MCPF_BASIC_USER=admin MCPF_BASIC_PASS=changeme \
		PYTHON=$$([ -x backend/.venv/bin/python ] && echo backend/.venv/bin/python || echo python3) && \
		cd backend && $$PYTHON -m app.agentic.list_forge_inventory

mcp-register-homepilot: ## Register HomePilot default tools with MCP Gateway
	@bash scripts/mcp-register.sh homepilot

mcp-list-tools: ## List all tools registered in MCP Gateway
	@bash scripts/mcp-register.sh list tools

mcp-list-gateways: ## List all gateways registered in MCP Gateway
	@bash scripts/mcp-register.sh list gateways

mcp-list-agents: ## List all A2A agents registered in MCP Gateway
	@bash scripts/mcp-register.sh list agents

mcp-register-tool: ## Register a custom tool (usage: make mcp-register-tool JSON='{"tool":{...}}')
	@if [ -z "$(JSON)" ]; then \
		echo "Usage: make mcp-register-tool JSON='{\"tool\":{\"name\":\"my-tool\",\"description\":\"...\"}}'"; \
		exit 1; \
	fi
	@bash scripts/mcp-register.sh tool '$(JSON)'

mcp-register-gateway: ## Register an MCP gateway (usage: make mcp-register-gateway JSON='{"gateway":{...}}')
	@if [ -z "$(JSON)" ]; then \
		echo "Usage: make mcp-register-gateway JSON='{\"gateway\":{\"name\":\"my-gw\",\"url\":\"http://...\"}}'"; \
		exit 1; \
	fi
	@bash scripts/mcp-register.sh gateway '$(JSON)'

mcp-register-agent: ## Register an A2A agent (usage: make mcp-register-agent JSON='{"agent":{...}}')
	@if [ -z "$(JSON)" ]; then \
		echo "Usage: make mcp-register-agent JSON='{\"agent\":{\"name\":\"my-agent\",\"endpoint_url\":\"http://...\"}}'"; \
		exit 1; \
	fi
	@bash scripts/mcp-register.sh agent '$(JSON)'

# --- New MCP Servers (Functional Contract) ------------------------------------

install-mcp-servers: ## Install all 10 new MCP servers (each in its own venv with uv)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Installing 10 MCP Servers (independent venvs)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@failed=""; \
	for srv in $(MCP_NEW_SERVERS); do \
		echo "─── Installing mcp-$$srv ───"; \
		if $(MAKE) -C $(MCP_SERVERS_DIR)/$$srv install; then \
			echo "  ✓ mcp-$$srv installed"; \
		else \
			echo "  ✗ mcp-$$srv FAILED"; \
			failed="$$failed $$srv"; \
		fi; \
		echo ""; \
	done; \
	echo "════════════════════════════════════════════════════════════════════════════════"; \
	if [ -z "$$failed" ]; then \
		echo "  ✅ All 10 MCP servers installed successfully!"; \
	else \
		echo "  ⚠  Failed servers:$$failed"; \
		exit 1; \
	fi; \
	echo "════════════════════════════════════════════════════════════════════════════════"

test-mcp-new-servers: ## Run tests for all 10 new MCP servers
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Testing 10 MCP Servers"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@passed=0; failed=0; fail_list=""; \
	for srv in $(MCP_NEW_SERVERS); do \
		echo "─── Testing mcp-$$srv ───"; \
		if cd "$(MCP_SERVERS_DIR)/$$srv" && \
		   PYTHONPATH="$(CURDIR):$$PYTHONPATH" \
		   "$(CURDIR)/backend/.venv/bin/python" -m pytest tests/ -v --tb=short; then \
			echo "  ✓ mcp-$$srv tests passed"; \
			passed=$$((passed + 1)); \
		else \
			echo "  ✗ mcp-$$srv tests FAILED"; \
			failed=$$((failed + 1)); \
			fail_list="$$fail_list $$srv"; \
		fi; \
		cd "$(CURDIR)"; \
		echo ""; \
	done; \
	echo "════════════════════════════════════════════════════════════════════════════════"; \
	echo "  Results: $$passed passed, $$failed failed (out of 10)"; \
	if [ $$failed -gt 0 ]; then \
		echo "  Failed:$$fail_list"; \
		echo "════════════════════════════════════════════════════════════════════════════════"; \
		exit 1; \
	fi; \
	echo "  ✅ All 10 MCP server tests passed!"; \
	echo "════════════════════════════════════════════════════════════════════════════════"

# --- Persona Launcher ----------------------------------------------------------

persona-launch: ## Launch MCP servers for a persona (usage: make persona-launch PERSONA=diana)
	@if [ -z "$(PERSONA)" ]; then \
		echo "Usage: make persona-launch PERSONA=<slug-or-path>"; \
		echo ""; \
		echo "Examples:"; \
		echo "  make persona-launch PERSONA=diana        # Start Diana's servers"; \
		echo "  make persona-launch PERSONA=kai          # Start Kai's servers"; \
		echo "  make persona-launch PERSONA=nora         # Start Nora's servers"; \
		echo ""; \
		bash scripts/persona-launch.sh --list; \
		exit 0; \
	fi
	@bash scripts/persona-launch.sh "$(PERSONA)"

persona-check: ## Dry-run: show what servers a persona needs (usage: make persona-check PERSONA=diana)
	@if [ -z "$(PERSONA)" ]; then \
		echo "Usage: make persona-check PERSONA=<slug>"; \
		exit 1; \
	fi
	@bash scripts/persona-launch.sh "$(PERSONA)" --check

persona-stop: ## Stop MCP servers for a persona (usage: make persona-stop PERSONA=diana)
	@if [ -z "$(PERSONA)" ]; then \
		echo "Usage: make persona-stop PERSONA=<slug>"; \
		exit 1; \
	fi
	@bash scripts/persona-launch.sh "$(PERSONA)" --stop

persona-status: ## Show health status of a persona's servers (usage: make persona-status PERSONA=diana)
	@if [ -z "$(PERSONA)" ]; then \
		echo "Usage: make persona-status PERSONA=<slug>"; \
		exit 1; \
	fi
	@bash scripts/persona-launch.sh "$(PERSONA)" --status

persona-list: ## List all available personas and their MCP server requirements
	@bash scripts/persona-launch.sh --list

# --- Community Gallery ---------------------------------------------------------

community-bootstrap: ## Bootstrap Cloudflare R2 + Worker + Pages for Community Gallery
	@echo "Bootstrapping Community Gallery..."
	@cd community && bash bootstrap.sh

community-deploy-worker: ## Deploy the Community Gallery Cloudflare Worker
	@echo "Deploying Community Gallery Worker..."
	@cd community/worker && npm install && npx wrangler deploy

community-deploy-pages: ## Deploy the Community Gallery static site (Cloudflare Pages)
	@echo "Deploying Community Gallery Pages..."
	@cd community && npx wrangler pages deploy pages/ --project-name homepilot-persona-gallery-pages

# --- Backward Compatibility Aliases -------------------------------------------

local: start  ## Alias for 'make start' (backward compatibility)

local-backend: start-backend  ## Alias for 'make start-backend' (backward compatibility)

local-frontend: start-frontend  ## Alias for 'make start-frontend' (backward compatibility)
