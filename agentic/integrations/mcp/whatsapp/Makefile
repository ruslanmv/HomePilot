PYTHON ?= python3
PORT ?= 9130

install:
	$(PYTHON) -m pip install --no-build-isolation -e ".[dev]"

run:
	PYTHONPATH=../../../../ $(PYTHON) -m uvicorn agentic.integrations.mcp.whatsapp.app:app --host 0.0.0.0 --port $(PORT)

test:
	PYTHONPATH=../../../../ $(PYTHON) -m pytest -q tests
