"""Model discovery + resolution rules (docs/design/LOCAL_MODEL_RESOLUTION.md).

Regressions covered:
- a configured model that is not installed must fall back to an installed one
  instead of failing ("Ollama has no model selected and none were found");
- a machine whose Ollama lives on the WSL/Docker host must be probed there;
- when nothing can serve a role the answer is explicit, with a remedy the UI
  can act on (download / start / bridge), never a shell command in prose only.

The module is resolved inside a fixture, not at import: the session-scoped
``app`` fixture in conftest purges ``app.*`` modules, and a module object bound
at import time would then be a stale copy that monkeypatching cannot reach.
"""
import asyncio
import importlib
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


@pytest.fixture()
def mr():
    return importlib.import_module("app.model_resolver")


def _models(mr, *names, loaded=(), modified=None):
    out = []
    for i, n in enumerate(names):
        out.append(mr.ModelInfo(
            name=n,
            modified_at=(modified or {}).get(n, f"2026-01-{i + 1:02d}T00:00:00Z"),
            loaded=n in loaded,
        ))
    return out


def _run(coro):
    # A fresh loop per call: other tests in the suite close or replace the
    # default loop, so get_event_loop() is not safe here.
    return asyncio.run(coro)


def _stub_runtimes(monkeypatch, mr, runtimes):
    async def _active(base_url=None, force=False):
        return mr.pick_runtime(runtimes), runtimes
    monkeypatch.setattr(mr, "active_runtime", _active)


# ── choose_model (pure) ───────────────────────────────────────────────────────

def test_configured_installed_wins(mr):
    m, src, _ = mr.choose_model("chat", "qwen2.5:7b", _models(mr, "llama3.2:3b", "qwen2.5:7b"))
    assert (m, src) == ("qwen2.5:7b", "configured")


def test_configured_stem_matches_installed_tag(mr):
    # OllaBridge's default is "deepseek-r1"; Ollama stores "deepseek-r1:latest".
    m, src, reason = mr.choose_model("chat", "deepseek-r1", _models(mr, "deepseek-r1:latest"))
    assert (m, src) == ("deepseek-r1:latest", "configured")
    assert "resolved" in reason


def test_configured_missing_falls_back_to_installed(mr):
    m, src, reason = mr.choose_model("chat", "llama3:8b", _models(mr, "deepseek-r1:latest"))
    assert (m, src) == ("deepseek-r1:latest", "fallback")
    assert "llama3:8b" in reason and "not installed" in reason


def test_loaded_model_preferred_over_priority(mr):
    # A model already resident in memory answers without a cold load.
    m, src, reason = mr.choose_model(
        "chat", "", _models(mr, "llama3.2:3b", "deepseek-r1:latest", loaded=("deepseek-r1:latest",)),
    )
    assert m == "deepseek-r1:latest" and src == "fallback"
    assert "already loaded" in reason


def test_priority_then_recency(mr):
    assert mr.choose_model("chat", "", _models(mr, "mistral:7b", "llama3.2:3b"))[0] == "llama3.2:3b"
    unknown = _models(
        mr, "foo-chat:1b", "bar-chat:2b",
        modified={"foo-chat:1b": "2026-02-01T00:00:00Z", "bar-chat:2b": "2026-03-01T00:00:00Z"},
    )
    assert mr.choose_model("chat", "", unknown)[0] == "bar-chat:2b"


def test_text_turn_never_lands_on_vision_or_embedding_model(mr):
    m, src, _ = mr.choose_model("chat", "", _models(mr, "moondream:latest", "nomic-embed-text"))
    assert (m, src) == ("", "none")


def test_vision_role_picks_vision_model(mr):
    m, _, _ = mr.choose_model("vision", "", _models(mr, "llama3.2:3b", "moondream:latest"))
    assert m == "moondream:latest"


def test_fast_role_prefers_small_models(mr):
    m, _, _ = mr.choose_model("fast", "", _models(mr, "qwen2.5:7b", "llama3.2:1b"))
    assert m == "llama3.2:1b"


def test_auto_is_not_treated_as_a_model_name(mr):
    m, src, _ = mr.choose_model("chat", "auto", _models(mr, "llama3.2:3b"))
    assert (m, src) == ("llama3.2:3b", "fallback")


# ── candidate URLs ────────────────────────────────────────────────────────────

def test_candidates_include_wsl_host_when_under_wsl(mr, monkeypatch):
    monkeypatch.setenv("OLLAMA_DISCOVERY", "auto")
    monkeypatch.setattr(mr, "is_wsl", lambda: True)
    monkeypatch.setattr(mr, "is_docker", lambda: False)
    monkeypatch.setattr(mr, "wsl_networking_mode", lambda: "nat")
    monkeypatch.setattr(mr, "wsl_host_ips", lambda: ["172.20.16.1"])
    urls = [u for _, u in mr.candidate_urls()]
    assert urls[0] == mr.OLLAMA_BASE_URL.rstrip("/")
    assert "http://172.20.16.1:11434" in urls
    assert len(urls) == len(set(urls))


def test_mirrored_wsl_skips_the_host_addresses(mr, monkeypatch):
    """Mirrored networking shares Windows' loopback: the gateway is the LAN router."""
    monkeypatch.setenv("OLLAMA_DISCOVERY", "auto")
    monkeypatch.setattr(mr, "is_wsl", lambda: True)
    monkeypatch.setattr(mr, "is_docker", lambda: False)
    monkeypatch.setattr(mr, "wsl_networking_mode", lambda: "mirrored")
    monkeypatch.setattr(mr, "wsl_host_ips", lambda: ["192.168.1.254", "10.255.255.254"])
    urls = [u for _, u in mr.candidate_urls()]
    assert "http://127.0.0.1:11434" in urls and not any("192.168.1.254" in u or "10.255.255.254" in u for u in urls)


def test_discovery_off_probes_only_the_configured_url(mr, monkeypatch):
    monkeypatch.setenv("OLLAMA_DISCOVERY", "off")
    monkeypatch.setattr(mr, "is_wsl", lambda: True)
    monkeypatch.setattr(mr, "wsl_host_ips", lambda: ["172.20.16.1"])
    assert mr.candidate_urls() == [("configured", mr.OLLAMA_BASE_URL.rstrip("/"))]


def test_no_local_model_counts_as_unreachable_for_meetings(mr):
    from app.meetingsense.notes_engine import MODEL_UNREACHABLE, classify_model_failure
    res = mr.Resolution(role="chat", configured="", model="", runtime_url="", source="none", reason="none")
    assert classify_model_failure(mr.NoLocalModelError(res)) == MODEL_UNREACHABLE


def test_explicit_base_url_restricts_candidates(mr):
    assert mr.candidate_urls("http://10.0.0.5:11434/") == [("explicit", "http://10.0.0.5:11434")]


def test_gateway_parsed_from_proc_net_route(mr, monkeypatch):
    route = "Iface\tDestination\tGateway\n eth0\t00000000\t0110140A\t0003\n"
    monkeypatch.setattr(mr, "_read_text", lambda p: route if p == "/proc/net/route" else "")
    assert mr._default_gateway_from_proc() == "10.20.16.1"


def test_parse_tags_distinguishes_empty_from_unknown(mr):
    assert mr._parse_tags({"models": []}) == ([], True)
    assert mr._parse_tags({"ok": True}) == ([], False)
    models, known = mr._parse_tags({"models": [{"name": "a:1b", "size": 5, "details": {"family": "x"}}]})
    assert known and models[0].name == "a:1b" and models[0].family == "x"


# ── resolve() with stubbed discovery ─────────────────────────────────────────

def test_resolve_falls_back_and_reports_reason(mr, monkeypatch):
    rt = mr.Runtime(url="http://172.20.16.1:11434", label="wsl-host", reachable=True, models=_models(mr, "deepseek-r1:latest"))
    _stub_runtimes(monkeypatch, mr, [mr.Runtime(url="http://localhost:11434", label="configured"), rt])
    res = _run(mr.resolve("chat", "llama3:8b"))
    assert res.model == "deepseek-r1:latest"
    assert res.source == "fallback"
    assert res.runtime_url == "http://172.20.16.1:11434"
    assert res.configured_installed is False
    assert res.remedy is None


def test_resolve_no_runtime_gives_bridge_remedy_under_wsl(mr, monkeypatch):
    monkeypatch.setattr(mr, "is_wsl", lambda: True)
    monkeypatch.setattr(mr, "wsl_networking_mode", lambda: "nat")
    _stub_runtimes(monkeypatch, mr, [
        mr.Runtime(url="http://localhost:11434", label="configured", error="ConnectError"),
        mr.Runtime(url="http://172.20.16.1:11434", label="wsl-host", error="ConnectError"),
    ])
    res = _run(mr.resolve("chat", ""))
    assert res.source == "none" and res.model == ""
    assert res.remedy["kind"] == "wsl_bridge"
    assert "mirrored" in res.remedy["message"]


def test_mirrored_wsl_says_ollama_is_stopped_or_busy_not_unreachable(mr, monkeypatch):
    monkeypatch.setattr(mr, "is_wsl", lambda: True)
    monkeypatch.setattr(mr, "wsl_networking_mode", lambda: "mirrored")
    _stub_runtimes(monkeypatch, mr, [mr.Runtime(url="http://127.0.0.1:11434", label="loopback", error="ReadTimeout")])
    res = _run(mr.resolve("chat", ""))
    assert res.remedy["kind"] == "start"
    msg = res.remedy["message"]
    assert "mirrored networking" in msg and "Check again" in msg and "networkingMode" not in msg


def test_nothing_answered_is_remembered_only_briefly(mr):
    down = [mr.Runtime(url="http://127.0.0.1:11434", label="loopback")]
    up = [mr.Runtime(url="http://127.0.0.1:11434", label="loopback", reachable=True)]
    assert mr._fresh(0.0, down, mr.NEGATIVE_TTL_S - 0.1) and not mr._fresh(0.0, down, mr.NEGATIVE_TTL_S + 0.1)
    assert mr._fresh(0.0, up, mr.NEGATIVE_TTL_S + 0.1)
    assert mr.NEGATIVE_TTL_S < mr.CACHE_TTL_S


def test_resolve_runtime_without_models_offers_download(mr, monkeypatch):
    _stub_runtimes(monkeypatch, mr, [mr.Runtime(url="http://localhost:11434", label="configured", reachable=True, models=[])])
    res = _run(mr.resolve("chat", ""))
    assert res.source == "none"
    assert res.remedy["kind"] == "pull"
    names = [s["name"] for s in res.remedy["suggested"]]
    assert "llama3.2:3b" in names and "moondream" not in names
    assert res.remedy["command"] == "ollama pull llama3.2:3b"


def test_runtime_without_tag_list_trusts_configured_name(mr, monkeypatch):
    # The test suite's Ollama stub answers /api/tags with {"ok": true}; a proxy
    # may do the same. A configured name must still be used, not refused.
    rt = mr.Runtime(url="http://localhost:11434", label="configured", reachable=True, models=[], models_known=False)
    _stub_runtimes(monkeypatch, mr, [rt])
    res = _run(mr.resolve("chat", "mock-ollama"))
    assert (res.model, res.source) == ("mock-ollama", "configured")


def test_pick_runtime_prefers_configured_then_any_with_models(mr):
    empty_cfg = mr.Runtime(url="http://localhost:11434", label="configured", reachable=True, models=[])
    host = mr.Runtime(url="http://172.20.16.1:11434", label="wsl-host", reachable=True, models=_models(mr, "llama3.2:3b"))
    assert mr.pick_runtime([empty_cfg, host]) is host
    assert mr.pick_runtime([mr.Runtime(url="x", label="configured")]) is None


def test_no_local_model_error_payload(mr, monkeypatch):
    _stub_runtimes(monkeypatch, mr, [mr.Runtime(url="http://localhost:11434", label="configured", reachable=True, models=[])])
    res = _run(mr.resolve("chat", ""))
    err = mr.NoLocalModelError(res)
    body = err.payload()
    assert body["code"] == "no_local_model" and body["remedy"]["kind"] == "pull"
    assert "no models installed" in str(err)


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(mr):
    routes = importlib.import_module("app.model_resolver_routes")
    assert routes.mr is mr, "routes module bound to a different model_resolver copy"
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_pull_rejects_bad_names(client):
    r = client.post("/v1/models/pull", json={"name": "../etc/passwd"})
    assert r.status_code == 400 and r.json()["code"] == "invalid_model_name"


def test_pull_503_when_no_runtime(client, mr, monkeypatch):
    _stub_runtimes(monkeypatch, mr, [mr.Runtime(url="http://localhost:11434", label="configured", error="ConnectError")])
    r = client.post("/v1/models/pull", json={"name": "llama3.2:3b"})
    assert r.status_code == 503
    assert r.json()["code"] == "no_runtime" and r.json()["remedy"]["kind"] in ("start", "wsl_bridge")


def test_pull_starts_job_on_active_runtime(client, mr, monkeypatch):
    rt = mr.Runtime(url="http://172.20.16.1:11434", label="wsl-host", reachable=True, models=[])
    _stub_runtimes(monkeypatch, mr, [rt])
    started = {}

    def _start(name, runtime_url):
        started.update(name=name, url=runtime_url)
        return mr.PullJob(name=name, runtime_url=runtime_url, status="queued")

    monkeypatch.setattr(mr.pull_manager, "start", _start)
    r = client.post("/v1/models/pull", json={"name": "llama3.2:3b"})
    assert r.status_code == 202
    assert started == {"name": "llama3.2:3b", "url": "http://172.20.16.1:11434"}
    assert client.get("/v1/models/pull/nope").status_code == 404


def test_resolution_endpoint_shape(client, mr, monkeypatch):
    rt = mr.Runtime(url="http://localhost:11434", label="configured", reachable=True, models=_models(mr, "llama3.2:3b", "moondream:latest"))
    _stub_runtimes(monkeypatch, mr, [rt])
    data = client.get("/v1/models/resolution?configured=llama3:8b").json()
    assert data["ok"] is True
    assert data["chat"]["model"] == "llama3.2:3b" and data["chat"]["source"] == "fallback"
    assert data["vision"]["model"] == "moondream:latest"
    assert data["runtime_url"] == "http://localhost:11434"
    assert data["fingerprint"].startswith("http://localhost:11434|")
    assert isinstance(data["suggested"], list)


# ── an explicit Base URL that is not an Ollama ───────────────────────────────

def test_ollama_root_strips_openai_and_api_paths(mr):
    assert mr.ollama_root("http://localhost:11434/v1/") == "http://localhost:11434"
    assert mr.ollama_root("http://localhost:11434/api") == "http://localhost:11434"
    assert mr.ollama_root("http://host:11434") == "http://host:11434"


def test_a_gateway_base_url_falls_back_to_the_real_ollama(mr, monkeypatch):
    """The chat Base URL holds OllaBridge's /v1 (404 on /api/tags): Ollama on its own port is
    found and used, and the reason says so — instead of "No Ollama runtime is reachable"."""
    gateway = mr.Runtime(url="http://localhost:11435", label="explicit", reachable=False, error="HTTP 404")
    ollama = mr.Runtime(url="http://127.0.0.1:11434", label="loopback", reachable=True,
                        models=_models(mr, "qwen2.5:1.5b", "llama3:8b", "deepseek-r1:latest"))

    async def fake_url(url, force=False):
        assert url == "http://localhost:11435"                 # /v1 stripped
        return gateway

    async def fake_discover(force=False):
        return [ollama]

    monkeypatch.setattr(mr, "discover_url", fake_url)
    monkeypatch.setattr(mr, "discover", fake_discover)
    rt, tried = _run(mr.active_runtime("http://localhost:11435/v1"))
    assert rt is ollama and tried == [gateway, ollama]
    res = _run(mr.resolve("chat", "llama3:8b", base_url="http://localhost:11435/v1"))
    assert res.model == "llama3:8b" and res.runtime_url == "http://127.0.0.1:11434"
    assert "is not an Ollama runtime" in res.reason and "found Ollama at http://127.0.0.1:11434" in res.reason


def test_a_reachable_explicit_url_still_wins(mr, monkeypatch):
    explicit = mr.Runtime(url="http://10.0.0.5:11434", label="explicit", reachable=True, models=_models(mr, "llama3.2:3b"))

    async def fake_url(url, force=False):
        return explicit

    async def no_discover(force=False):  # pragma: no cover - must not be reached
        raise AssertionError("an Ollama that answers is used as it is")

    monkeypatch.setattr(mr, "discover_url", fake_url)
    monkeypatch.setattr(mr, "discover", no_discover)
    rt, tried = _run(mr.active_runtime("http://10.0.0.5:11434"))
    assert rt is explicit and tried == [explicit]
