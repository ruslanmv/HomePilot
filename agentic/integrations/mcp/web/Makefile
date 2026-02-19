SHELL := /bin/bash
export UV_LINK_MODE ?= copy

SERVER_NAME   := homepilot-mcp-web
SERVER_MODULE := agentic.integrations.mcp.web_mcp_server:app
PORT          ?= 9112
REPO_ROOT     := $(shell git rev-parse --show-toplevel 2>/dev/null || echo $(abspath ../../../..))

.PHONY: help install test run clean lint

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "\033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install server into its own venv with uv
	@echo "Installing $(SERVER_NAME)..."
	@command -v uv >/dev/null 2>&1 || { echo "ERROR: uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	uv venv .venv --python 3.11 || uv venv .venv
	uv pip install -e ".[dev]" --python .venv/bin/python
	uv pip install -e "$(REPO_ROOT)" --python .venv/bin/python 2>/dev/null || true
	@if [ ! -f .venv/lib/python*/site-packages/agentic/__init__.py ] 2>/dev/null; then \
		echo "  Linking repo root for agentic imports..."; \
		SITE_DIR=$$(find .venv/lib -name "site-packages" -type d | head -1); \
		if [ -n "$$SITE_DIR" ] && [ ! -e "$$SITE_DIR/agentic" ]; then \
			ln -s "$(REPO_ROOT)/agentic" "$$SITE_DIR/agentic"; \
		fi; \
	fi
	@echo "$(SERVER_NAME) installed."

test: ## Run tests for this server
	@echo "Testing $(SERVER_NAME)..."
	@if [ ! -d ".venv" ]; then echo "Run 'make install' first."; exit 1; fi
	PYTHONPATH="$(REPO_ROOT):$$PYTHONPATH" .venv/bin/python -m pytest tests/ -v --tb=short
	@echo "$(SERVER_NAME) tests passed."

run: ## Start the server locally
	@if [ ! -d ".venv" ]; then echo "Run 'make install' first."; exit 1; fi
	PYTHONPATH="$(REPO_ROOT):$$PYTHONPATH" .venv/bin/uvicorn $(SERVER_MODULE) --host 0.0.0.0 --port $(PORT) --reload

clean: ## Remove virtual environment
	rm -rf .venv __pycache__ .pytest_cache tests/__pycache__

lint: ## Run basic linting
	@if [ -d ".venv" ]; then \
		.venv/bin/python -m py_compile app.py && echo "  app.py OK"; \
	else \
		echo "Run 'make install' first."; exit 1; \
	fi
