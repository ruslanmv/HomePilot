PYTHON ?= $(shell [ -x /root/.pyenv/versions/3.11.14/bin/python3.11 ] && echo /root/.pyenv/versions/3.11.14/bin/python3.11 || echo 3.11)
PORT ?= 8100
BACKEND_VENV_PYTEST ?= pytest
BACKEND_VENV_PYTHON ?= python3

install:
	uv sync --python $(PYTHON) || (echo "⚠️ uv sync failed; validating shared backend venv instead" && $(BACKEND_VENV_PYTHON) -c "import fastapi,uvicorn,pytest")

run:
	uv run --python $(PYTHON) uvicorn app:app --host 0.0.0.0 --port $(PORT)

test:
	@if [ -x .venv/bin/pytest ]; then \
		.venv/bin/pytest -q; \
	elif command -v $(BACKEND_VENV_PYTEST) >/dev/null 2>&1; then \
		$(BACKEND_VENV_PYTEST) -q; \
	else \
		echo "❌ pytest not available"; \
		exit 1; \
	fi
