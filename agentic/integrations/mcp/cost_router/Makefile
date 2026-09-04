PYTHON ?= 3.11
PORT ?= 8100
BACKEND_VENV_PYTHON ?= python3

install:
	uv sync --python $(PYTHON) || (echo "⚠️ uv sync failed; validating shared backend venv instead" && $(BACKEND_VENV_PYTHON) -c "import fastapi,uvicorn,pytest")

run:
	uv run --python $(PYTHON) uvicorn app:app --host 0.0.0.0 --port $(PORT)

test:
	uv run --python $(PYTHON) pytest -q
