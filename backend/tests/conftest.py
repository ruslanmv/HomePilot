# backend/tests/conftest.py
import os
import sys
import tempfile
import importlib
import pytest
from fastapi.testclient import TestClient

def _purge_modules(prefixes: tuple[str, ...]) -> None:
    for name in list(sys.modules.keys()):
        if name.startswith(prefixes):
            sys.modules.pop(name, None)

def _ensure_project_on_syspath() -> None:
    backend_root = os.path.dirname(os.path.abspath(__file__))
    backend_root = os.path.dirname(backend_root)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

def _load_app():
    _ensure_project_on_syspath()
    _purge_modules(("app", "app."))
    m = importlib.import_module("app.main")
    return getattr(m, "app")

@pytest.fixture(scope="session")
def app():
    tmp = tempfile.TemporaryDirectory()
    root = tmp.name
    
    # Set Test Environment Variables
    os.environ["UPLOAD_DIR"] = os.path.join(root, "uploads")
    os.environ["SQLITE_PATH"] = os.path.join(root, "test.db")
    os.environ["API_KEY"] = ""  # Disable API key for tests
    os.environ["MAX_UPLOAD_MB"] = "10"
    os.environ["LLM_MODEL"] = "mock-model"
    os.environ["OLLAMA_MODEL"] = "mock-model"
    
    _purge_modules(("app", "app."))
    _app = _load_app()
    setattr(_app.state, "_tmpdir", tmp)
    return _app

@pytest.fixture()
def client(app):
    return TestClient(app)

# --- Mocks ---

class DummyResp:
    def __init__(self, status_code=200, json_data=None, text="OK"):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
    def json(self): return self._json
    def raise_for_status(self): pass

@pytest.fixture()
def mock_outbound(monkeypatch):
    import httpx
    import requests

    # 1. Mock requests (for media upload calls)
    monkeypatch.setattr(requests, "post", lambda *a, **k: DummyResp(200, {"ok": True}), raising=False)

    # 2. Mock httpx (for LLM/ComfyUI calls)
    async def _mock_post(url, *a, **k):
        u = str(url)
        # Mock LLM response
        if "chat/completions" in u or "/api/chat" in u:
            return httpx.Response(200, json={
                "choices": [{"message": {"role": "assistant", "content": "mocked response"}}],
                "message": {"role": "assistant", "content": "mocked response"}
            })
        # Mock ComfyUI prompt
        if "prompt" in u:
            return httpx.Response(200, json={"prompt_id": "mock-id"})
            
        return httpx.Response(200, json={})

    async def _mock_get(url, *a, **k):
        # Mock ComfyUI history
        return httpx.Response(200, json={
            "mock-id": {"outputs": {"0": {"images": [{"filename": "test.png"}]}}}
        })

    # Apply httpx mocks
    monkeypatch.setattr(httpx, "post", _mock_post, raising=False)
    monkeypatch.setattr(httpx, "get", _mock_get, raising=False)
    monkeypatch.setattr(httpx.Client, "post", lambda s, u, *a, **k: DummyResp(200), raising=False)
    
    # Mock AsyncClient used by app.llm
    class MockAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, *a, **k): return await _mock_post(url, *a, **k)
        async def get(self, url, *a, **k): return await _mock_get(url, *a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient, raising=False)
    return True