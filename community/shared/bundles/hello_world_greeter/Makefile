SHELL := /bin/bash

# ── Bundle Configuration ─────────────────────────────────────────────────────
BUNDLE_ID     := hello_world_greeter
SERVER_ID     := hp-community-greeter
SERVER_PORT   := 9200
SERVER_MODULE := community.shared.bundles.$(BUNDLE_ID).mcp_server.app:app

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT  := $(shell git rev-parse --show-toplevel 2>/dev/null || echo "../../../..")
BUNDLE_DIR    := $(PROJECT_ROOT)/community/shared/bundles/$(BUNDLE_ID)
SCRIPTS_DIR   := $(PROJECT_ROOT)/community/shared/scripts
PYTHON        := $(shell if [ -x "$(PROJECT_ROOT)/.venv/bin/python" ]; then echo "$(PROJECT_ROOT)/.venv/bin/python"; else command -v python3 2>/dev/null || echo python; fi)

.PHONY: help install test uninstall clean server-start server-stop

help: ## Show available targets
	@echo ""
	@echo "  HomePilot Community Bundle: $(BUNDLE_ID)"
	@echo "  Server: $(SERVER_ID) (port $(SERVER_PORT))"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

# ── Install ──────────────────────────────────────────────────────────────────

install: ## Install bundle into HomePilot (entry point + YAML + .hpersona)
	@echo "════════════════════════════════════════════════════════════════"
	@echo "  Installing bundle: $(BUNDLE_ID)"
	@echo "════════════════════════════════════════════════════════════════"
	@cd $(PROJECT_ROOT) && $(PYTHON) $(SCRIPTS_DIR)/install_bundle.py $(BUNDLE_ID)
	@echo ""
	@echo "Done. Run 'make test' to verify compatibility."

uninstall: ## Uninstall bundle from HomePilot
	@cd $(PROJECT_ROOT) && $(PYTHON) $(SCRIPTS_DIR)/install_bundle.py --uninstall $(BUNDLE_ID)

# ── Test ─────────────────────────────────────────────────────────────────────

test: ## Run all compatibility tests (import, health, tools/list)
	@cd $(PROJECT_ROOT) && $(PYTHON) $(BUNDLE_DIR)/test_bundle.py

# ── Development ──────────────────────────────────────────────────────────────

server-start: ## Start the MCP server locally (foreground)
	@echo "Starting $(SERVER_ID) on port $(SERVER_PORT)..."
	@cd $(PROJECT_ROOT) && $(PYTHON) -m uvicorn $(SERVER_MODULE) --host 127.0.0.1 --port $(SERVER_PORT)

server-stop: ## Stop the MCP server if running
	@echo "Stopping $(SERVER_ID)..."
	@-pkill -f "uvicorn.*$(SERVER_MODULE)" 2>/dev/null && echo "  Stopped" || echo "  Not running"

clean: ## Remove generated .hpersona file
	@rm -f $(BUNDLE_DIR)/$(BUNDLE_ID).hpersona
	@echo "Cleaned $(BUNDLE_ID).hpersona"
