# HomePilot Backend

FastAPI orchestrator service for **HomePilot**.

This service provides a **stable HTTP API** consumed by the frontend to power:

- **Chat** (LLM via OpenAI-compatible providers or Ollama)
- **Image generation / editing** (ComfyUI workflows)
- **Image → video** (ComfyUI + optional media pipeline)
- **Uploads** (local, safe image upload endpoints)

## API (high level)

- `GET /health` – health check
- `GET /providers` – available LLM providers (backend routing)
- `GET /settings` – redacted runtime settings for the frontend
- `POST /chat` – unified chat endpoint (chat / imagine / edit / animate)
- `POST /upload` – upload an image and get a URL for subsequent edit/animate prompts

## Local development (uv)

From repo root:

```bash
make uv
make uv-run
```

Run tests:

```bash
make uv-test
```

## Notes

- The backend is **local-first**: it stores state (SQLite) and media on disk.
- Provider selection is controlled by request fields and/or environment defaults.
- ComfyUI integration is workflow-based, so models can be swapped without changing code.
