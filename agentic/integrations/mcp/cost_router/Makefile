PYTHON ?= 3.11
PORT ?= 8100

install:
	uv sync --python $(PYTHON)

run:
	uv run --python $(PYTHON) uvicorn app:app --host 0.0.0.0 --port $(PORT)

test:
	uv run --python $(PYTHON) pytest -q
