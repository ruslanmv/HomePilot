PYTHON ?= python3
PORT ?= 9131

install:
	$(PYTHON) -m pip install --no-build-isolation -e ".[dev]"

run:
	PYTHONPATH=../../../../ $(PYTHON) -m uvicorn agentic.integrations.mcp.telegram.app:app --host 0.0.0.0 --port $(PORT)

test:
	PYTHONPATH=../../../../ $(PYTHON) -m pytest -q tests
