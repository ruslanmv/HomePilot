#!/bin/bash
# HomePilot test launcher — sets env vars for local testing
export DEFAULT_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=qwen2:0.5b
export API_KEY=my-secret

cd /home/user/HomePilot/backend
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
