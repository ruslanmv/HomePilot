import os

API_KEY = (os.getenv("API_KEY") or "").strip()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "[http://llm:8001/v1").rstrip("/](http://llm:8001/v1%22%29.rstrip%28%22/)")
LLM_MODEL = os.getenv("LLM_MODEL", "local-model")

COMFY_BASE_URL = os.getenv("COMFY_BASE_URL", "[http://comfyui:8188").rstrip("/](http://comfyui:8188%22%29.rstrip%28%22/)")
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "[http://media:8002").rstrip("/](http://media:8002%22%29.rstrip%28%22/)")

SQLITE_PATH = os.getenv("SQLITE_PATH", "/app/data/homepilot.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/data/uploads")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/outputs")

TOOL_TIMEOUT_S = int(os.getenv("TOOL_TIMEOUT_S", "300"))
COMFY_POLL_INTERVAL_S = float(os.getenv("COMFY_POLL_INTERVAL_S", "1.0"))
COMFY_POLL_MAX_S = float(os.getenv("COMFY_POLL_MAX_S", "240"))

CORS_ORIGINS = [o.strip() for o in (os.getenv("CORS_ORIGINS", "http://localhost:3000")).split(",") if o.strip()]

WORKFLOWS_DIR = "/workflows"
