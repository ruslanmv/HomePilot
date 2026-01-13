SHELL := /bin/bash

# Fix uv hardlink warning on WSL / multi-filesystem setups (optional, safe default)
export UV_LINK_MODE ?= copy

.PHONY: help install run up down logs health dev build test clean download uv uv-run uv-test

help: ## Show help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install frontend deps and build images
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@echo "Building docker images..."
	docker compose -f infra/docker-compose.yml build

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

run: up ## Alias for up

up: ## Start full stack (docker)
	docker compose -f infra/docker-compose.yml up -d --build
	@echo ""
	@echo "UI      : http://localhost:3000"
	@echo "Backend : http://localhost:8000/docs"
	@echo "LLM API : http://localhost:8001/v1"
	@echo "ComfyUI : http://localhost:8188"
	@echo ""

down: ## Stop stack
	docker compose -f infra/docker-compose.yml down

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
