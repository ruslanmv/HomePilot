# homepilot/backend/tests/conftest.py
import os
import sys
import tempfile
import importlib
import pytest
from fastapi.testclient import TestClient


def _purge_modules(prefixes: tuple[str, ...]) -> None:
    """Remove cached modules so env var overrides take effect cleanly."""
    for name in list(sys.modules.keys()):
        if name.startswith(prefixes):
            sys.modules.pop(name, None)


def _load_app():
    # Ensure we import the real backend entrypoint
    m = importlib.import_module("app.main")
    app = getattr(m, "app", None)
    if app is None:
        raise RuntimeError("Could not find FastAPI 'app' in app.main")
    return app


@pytest.fixture(scope="session")
def app():
    """
    Session-scoped FastAPI app with deterministic temp paths.
    IMPORTANT: env vars must be set BEFORE importing app.main
    because StaticFiles validates mount directories at import time.
    """
    tmp = tempfile.TemporaryDirectory()
    root = tmp.name

    uploads = os.path.join(root, "uploads")
    os.makedirs(uploads, exist_ok=True)

    os.environ["UPLOAD_DIR"] = uploads
    os.environ["SQLITE_PATH"] = os.path.join(root, "test.db")
    os.environ["OUTPUT_DIR"] = os.path.join(root, "outputs")
    os.makedirs(os.environ["OUTPUT_DIR"], exist_ok=True)

    # Disable API key in tests by default
    os.environ["API_KEY"] = ""

    # Keep outbound targets but they will be mocked
    os.environ["LLM_BASE_URL"] = "http://llm:8001/v1"
    os.environ["LLM_MODEL"] = "mock-model"
    os.environ["OLLAMA_BASE_URL"] = "http://ollama:11434"
    os.environ["OLLAMA_MODEL"] = "mock-ollama"
    os.environ["COMFY_BASE_URL"] = "http://comfyui:8188"
    os.environ["MEDIA_BASE_URL"] = "http://media:8002"
    os.environ["TOOL_TIMEOUT_S"] = "5"
    os.environ["COMFY_POLL_MAX_S"] = "2"

    # Critical: purge cached modules so tests don't import stale stubs
    _purge_modules(("app.",))

    _app = _load_app()
    setattr(_app.state, "_tmpdir", tmp)  # keep tmp alive
    return _app


@pytest.fixture()
def client(app):
    return TestClient(app)


# -------------------- Mock outbound HTTP (httpx + requests) --------------------

class DummyResp:
    def __init__(self, status_code=200, json_data=None, text="OK"):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture()
def mock_outbound(monkeypatch):
    """
    Mocks outbound calls used by:
      - LLM via httpx
      - ComfyUI via httpx
      - Media via requests
    """

    # ---- requests (media) ----
    try:
        import requests

        def _requests_post(url, *args, **kwargs):
            return DummyResp(200, {"ok": True})

        monkeypatch.setattr(requests, "post", _requests_post, raising=True)
    except Exception:
        pass

    # ---- httpx (llm + comfy) ----
    import httpx

    def _httpx_post(url, *args, **kwargs):
        u = str(url)

        # OpenAI-compatible
        if u.endswith("/chat/completions") or "/v1/chat/completions" in u:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "mock-llm: hello"}}]},
            )

        # Ollama chat endpoint
        if u.endswith("/api/chat"):
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "mock-ollama: hello"}},
            )

        # ComfyUI prompt
        if u.rstrip("/").endswith("/prompt"):
            return httpx.Response(200, json={"prompt_id": "mock-prompt-id"})

        return httpx.Response(200, json={})

    def _httpx_get(url, *args, **kwargs):
        u = str(url)

        # ComfyUI history returns an image output
        if "/history/" in u or u.endswith("/history/mock-prompt-id"):
            return httpx.Response(
                200,
                json={
                    "mock-prompt-id": {
                        "outputs": {
                            "0": {
                                "images": [
                                    {"filename": "image.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        }
                    }
                },
            )

        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", _httpx_post, raising=False)
    monkeypatch.setattr(httpx, "get", _httpx_get, raising=False)

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, *a, **k: _httpx_post(url, *a, **k), raising=False)
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, *a, **k: _httpx_get(url, *a, **k), raising=False)

    return True
