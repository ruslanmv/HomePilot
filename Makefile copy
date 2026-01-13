SHELL := /bin/bash

.PHONY: help install run up down logs health dev build test clean download

help: ## Show help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install frontend deps and build images
	@echo "Installing frontend deps..."
	cd frontend && npm install
	@echo "Building docker images..."
	docker compose -f infra/docker-compose.yml build

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
