SHELL := /bin/bash

# Fix uv hardlink warning on WSL / multi-filesystem setups (optional, safe default)
export UV_LINK_MODE ?= copy

.PHONY: help install run up down logs health dev build test clean download uv uv-run uv-test local local-backend local-frontend

help: ## Show help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install frontend deps and build images
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@echo "Building docker images..."
	docker compose -f infra/docker-compose.yml build

# --- Local development (no Docker) --------------------------------------------

local: ## Run everything locally (backend + frontend, no Docker). Requires Ollama running on host.
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Running HomePilot LOCALLY (no Docker)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Prerequisites:"
	@echo "  ✓ Ollama running: ollama serve"
	@echo "  ✓ Ollama model: ollama pull llama3.1:latest (or your preferred model)"
	@echo "  ✓ ComfyUI running (optional): cd ComfyUI && python main.py"
	@echo ""
	@echo "Starting services..."
	@echo ""
	@echo "Backend will run on: http://localhost:8000"
	@echo "Frontend will run on: http://localhost:3000"
	@echo ""
	@echo "Press Ctrl+C to stop both services"
	@echo ""
	@$(MAKE) local-backend & $(MAKE) local-frontend

local-backend: ## Run backend locally (requires Python 3.11+)
	@echo "Starting backend..."
	@if [ ! -d "backend/.venv" ]; then \
		echo "Virtual environment not found. Creating..."; \
		cd backend && python3 -m venv .venv && \
		.venv/bin/pip install -e .; \
	fi
	@cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

local-frontend: ## Run frontend locally (requires Node.js)
	@echo "Starting frontend..."
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "Node modules not found. Installing..."; \
		cd frontend && npm install; \
	fi
	@cd frontend && npm run dev -- --host 0.0.0.0 --port 3000

# --- Local backend with uv -----------------------------------------------------

uv: ## Install backend locally using uv (creates backend/.venv and installs deps + dev group)
	@command -v uv >/dev/null 2>&1 || { \
		echo "ERROR: 'uv' not found."; \
		echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		echo "Then reopen your terminal and run: make uv"; \
		exit 1; \
	}
	@test -f backend/pyproject.toml || { \
		echo "ERROR: backend/pyproject.toml missing."; \
		exit 1; \
	}
	@test -f backend/README.md || { \
		echo "ERROR: backend/README.md missing (required by pyproject readme)."; \
		echo "Create it (can be short) then rerun: make uv"; \
		exit 1; \
	}
	@echo "Setting up backend venv with uv..."
	cd backend && uv venv .venv
	@echo "Installing backend (editable)..."
	cd backend && uv pip install -e .
	@echo "Installing backend dev dependencies (dependency-groups.dev)..."
	cd backend && uv pip install --group dev
	@echo ""
	@echo "✅ Backend installed locally with uv."
	@echo "Next:"
	@echo "  make uv-run   # run backend locally (uvicorn --reload)"
	@echo "  make uv-test  # run backend tests locally"
	@echo ""

uv-run: ## Run backend locally with uv (reload)
	@command -v uv >/dev/null 2>&1 || { echo "ERROR: 'uv' not found. Run: make uv"; exit 1; }
	cd backend && uv run dev

uv-test: ## Run backend tests locally with uv (pytest)
	@command -v uv >/dev/null 2>&1 || { echo "ERROR: 'uv' not found. Run: make uv"; exit 1; }
	cd backend && uv run test

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
	@echo "  docker exec -it homepilot_ollama ollama pull llama3.1:latest"
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

test: ## Run backend tests (pytest) inside backend container
	docker compose -f infra/docker-compose.yml run --rm backend pytest -q

download: ## Download helper (requires huggingface-cli on host)
	@bash scripts/download_models.sh

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
	@echo "════════════════════════════════════════════════════════════════════════════════"
