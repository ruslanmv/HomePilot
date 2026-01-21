SHELL := /bin/bash

# Fix uv hardlink warning on WSL / multi-filesystem setups (optional, safe default)
export UV_LINK_MODE ?= copy

.PHONY: help install setup run up down logs health dev build test clean download download-minimal download-recommended download-full download-verify start start-backend start-frontend

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
	@echo "✓ Installing frontend dependencies..."
	@cd frontend && npm install
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ Installation Complete!"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Start Ollama: ollama serve"
	@echo "  2. Pull a model: ollama pull llama3:8b"
	@echo "  3. Start HomePilot: make start"
	@echo ""

setup: ## Setup Docker environment (install deps + build images)
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@echo "Building docker images..."
	docker compose -f infra/docker-compose.yml build

# --- Local development (no Docker) --------------------------------------------

start: ## Start HomePilot locally (backend + frontend, no Docker)
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Starting HomePilot LOCALLY (no Docker)"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Prerequisites:"
	@echo "  ✓ Ollama running: ollama serve"
	@echo "  ✓ Ollama model: ollama pull llama3:8b (or your preferred model)"
	@echo "  ✓ ComfyUI running (optional): cd ComfyUI && python main.py"
	@echo ""
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "❌ Frontend not installed. Run: make install"; \
		exit 1; \
	fi
	@echo "Starting services..."
	@echo ""
	@echo "Backend will run on: http://localhost:8000"
	@echo "Frontend will run on: http://localhost:3000"
	@echo ""
	@echo "Press Ctrl+C to stop both services"
	@echo ""
	@$(MAKE) start-backend & $(MAKE) start-frontend

start-backend: ## Start backend locally with uv
	@echo "Starting backend..."
	@if [ ! -d "backend/.venv" ]; then \
		echo "Virtual environment not found. Run: make install"; \
		exit 1; \
	fi
	@cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

start-frontend: ## Start frontend locally
	@echo "Starting frontend..."
	@if [ ! -d "frontend/node_modules" ]; then \
		echo "Node modules not found. Run: make install"; \
		exit 1; \
	fi
	@cd frontend && npm run dev -- --host 0.0.0.0 --port 3000

# --- Testing & Development ----------------------------------------------------

test: test-local  ## Run all tests (alias for test-local)

test-local: ## Run backend tests locally with pytest
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Running HomePilot Tests"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@if [ ! -d "backend/.venv" ]; then \
		echo "❌ Backend not installed. Run: make install"; \
		exit 1; \
	fi
	@echo ""
	@echo "Testing backend API endpoints..."
	@cd backend && .venv/bin/pytest -v --tb=short
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  ✅ All tests passed!"
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

download: download-recommended ## Download models (alias for download-recommended)

download-minimal: ## Download minimal models (~7GB - FLUX Schnell + encoders)
	@bash scripts/download_models.sh minimal

download-recommended: ## Download recommended models (~14GB - FLUX Schnell + SDXL + encoders)
	@bash scripts/download_models.sh recommended

download-full: ## Download all models (~65GB - FLUX Schnell + Dev, SDXL, SD1.5, SVD + encoders)
	@bash scripts/download_models.sh full

download-verify: ## Verify downloaded models and show disk usage
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo "  Model Verification"
	@echo "════════════════════════════════════════════════════════════════════════════════"
	@echo ""
	@if [ -d "models/comfy" ]; then \
		echo "ComfyUI Models:"; \
		echo ""; \
		echo "  Checkpoints:"; \
		ls -lh models/comfy/checkpoints/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  UNET Models:"; \
		ls -lh models/comfy/unet/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  CLIP Encoders:"; \
		ls -lh models/comfy/clip/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
		echo ""; \
		echo "  VAE Models:"; \
		ls -lh models/comfy/vae/*.safetensors 2>/dev/null | awk '{print "    " $$9 " (" $$5 ")"}' || echo "    (none)"; \
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

# --- Backward Compatibility Aliases -------------------------------------------

local: start  ## Alias for 'make start' (backward compatibility)

local-backend: start-backend  ## Alias for 'make start-backend' (backward compatibility)

local-frontend: start-frontend  ## Alias for 'make start-frontend' (backward compatibility)
