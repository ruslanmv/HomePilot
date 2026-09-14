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


def _ensure_project_on_syspath() -> None:
    """Make sure the backend root is importable.

    Some runners (including `uv run` under Python safety modes) may not include
    the current working directory on sys.path. We insert the backend directory
    so `import app.main` resolves to this repo.
    """

    backend_root = os.path.dirname(os.path.abspath(__file__))
    backend_root = os.path.dirname(backend_root)  # .../backend
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)


def _load_app():
    _ensure_project_on_syspath()
    # Ensure we import the real backend entrypoint
    _purge_modules(("app", "app."))
    m = importlib.import_module("app.main")
    # Guard against accidentally importing a third-party package also named `app`.
    project_root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    mod_path = os.path.abspath(m.__file__)
    assert mod_path.startswith(project_root), f"Unexpected app.main import: {mod_path} (expected under {project_root})"
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
    _purge_modules(("app", "app."))

    _app = _load_app()
    setattr(_app.state, "_tmpdir", tmp)  # keep tmp alive
    return _app


@pytest.fixture()
def client(app):
    return TestClient(app)


# -------------------- No ambient vector store --------------------
#
# `retrieval._client()` falls back to the real Chroma client when a caller passes none, so a
# test that indexes, searches or deletes without naming a store asserts one thing on a laptop
# and another in CI:
#
#   - here, `chromadb` is usually not installed, `_client()` returns `None`, and "no vector
#     store" is what the test observed;
#   - in CI, `backend/requirements.txt` pins `chromadb>=0.4.0`, so a real — and *persistent* —
#     store answers. Rows written by one test are still there for the next one, which is how
#     "a live meeting has not been indexed yet" came back as `1 match`.
#
# So "no store" is this suite's deterministic default. Every test that wants a store already
# says so, by passing `client=` or by patching `_client` itself.
#
# Two details this has already been got wrong on, both worth keeping:
#
# **The module is resolved inside the fixture, not at import.** The session-scoped `app`
# fixture calls `_purge_modules(("app", "app."))`, so a module object bound when this file was
# imported is not the one the tests end up using, and the patch lands on a corpse. Scope
# ordering makes the lazy lookup safe: the session-scoped `app` is instantiated before any
# function-scoped autouse fixture, so by the time this runs the purge has already happened.
#
# **It lives here rather than in `tests/meetingsense/`.** The MCP tests that reach the same
# code sit at this level, and a fixture one directory down never applied to them.
#
# The stub would also happily keep a green suite over a `_client` that had stopped calling
# `get_chroma_client` at all, so the real function is handed back through `unstubbed_client`
# and the tests that are *about* the fallback call it directly.


@pytest.fixture(autouse=True)
def _no_ambient_vector_store(monkeypatch):
    """An unnamed vector store is no vector store, on every machine.

    Returns the real `_client` so `unstubbed_client` can hand it on; autouse fixtures are
    instantiated before the non-autouse ones of the same scope, so it cannot capture the
    original itself.
    """
    _ensure_project_on_syspath()
    retrieval = importlib.import_module("app.meetingsense.retrieval")
    real = retrieval._client
    monkeypatch.setattr(retrieval, "_client", lambda client=None: client)
    return real


@pytest.fixture()
def unstubbed_client(_no_ambient_vector_store):
    """The real `_client`, for the tests that check the fallback still exists."""
    return _no_ambient_vector_store


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

    class DummyAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *a, **k):
            return _httpx_post(url, *a, **k)

        async def get(self, url, *a, **k):
            return _httpx_get(url, *a, **k)

    def _mock_request(url: str) -> httpx.Request:
        """Build a dummy Request so httpx.Response.raise_for_status() works."""
        return httpx.Request("POST", url)

    def _httpx_post(url, *args, **kwargs):
        u = str(url)

        # OpenAI-compatible
        if u.endswith("/chat/completions") or "/v1/chat/completions" in u:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "mock-llm: hello"}}]},
                request=_mock_request(u),
            )

        # Ollama chat endpoint
        if u.endswith("/api/chat"):
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "mock-ollama: hello"}},
                request=_mock_request(u),
            )

        # ComfyUI prompt
        if u.rstrip("/").endswith("/prompt"):
            return httpx.Response(200, json={"prompt_id": "mock-prompt-id"}, request=_mock_request(u))

        return httpx.Response(200, json={}, request=_mock_request(u))

    def _httpx_get(url, *args, **kwargs):
        u = str(url)
        _get_req = httpx.Request("GET", u)

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
                request=_get_req,
            )

        return httpx.Response(200, json={"ok": True}, request=_get_req)

    monkeypatch.setattr(httpx, "post", _httpx_post, raising=False)
    monkeypatch.setattr(httpx, "get", _httpx_get, raising=False)

    # AsyncClient is used by the backend in production code.
    monkeypatch.setattr(httpx, "AsyncClient", DummyAsyncClient, raising=False)


    return True


@pytest.fixture()
def compute_db(monkeypatch, tmp_path):
    """Isolate the compute registry on a fresh temp SQLite DB and reset the
    shared health cache, so registry/router tests don't leak state into each
    other or into the session `app` fixture's DB."""
    import app.storage as storage
    prev_resolved = storage._RESOLVED_DB_PATH
    prev_sqlite = storage.SQLITE_PATH
    # storage binds SQLITE_PATH at import, so patch the module attr (not just env)
    # and reset the resolved-path cache so _get_db_path() re-resolves to the temp DB.
    monkeypatch.setattr(storage, "SQLITE_PATH", str(tmp_path / "compute.db"), raising=False)
    storage._RESOLVED_DB_PATH = None
    try:
        from app.compute import health
        health.shared_cache().invalidate()
    except Exception:
        pass
    yield
    storage._RESOLVED_DB_PATH = prev_resolved
    storage.SQLITE_PATH = prev_sqlite
