"""ComfyUI health: running, not running, and running-but-frozen are told apart."""
import httpx

from app.services.comfyui import client as cc


def _get(monkeypatch, behaviour):
    def fake_get(url, timeout=None):
        if isinstance(behaviour, Exception):
            raise behaviour
        return httpx.Response(behaviour, request=httpx.Request("GET", url))
    monkeypatch.setattr(cc.httpx, "get", fake_get)


def test_ok(monkeypatch):
    _get(monkeypatch, 200)
    assert cc.comfyui_state("http://c") == "ok" and cc.comfyui_healthy("http://c")


def test_down(monkeypatch):
    _get(monkeypatch, httpx.ConnectError("refused"))
    assert cc.comfyui_state("http://c") == "down"


def test_frozen(monkeypatch):
    _get(monkeypatch, httpx.ReadTimeout("no answer"))
    assert cc.comfyui_state("http://c") == "frozen" and not cc.comfyui_healthy("http://c")


def test_outfit_503_names_the_case(monkeypatch, app):
    import sys
    outfit = sys.modules["app.avatar.outfit"]
    monkeypatch.setattr("app.services.comfyui.client.comfyui_state", lambda url: "frozen")
    assert "not responding" in outfit._no_modes_reason()
    monkeypatch.setattr("app.services.comfyui.client.comfyui_state", lambda url: "down")
    assert "not running" in outfit._no_modes_reason()
    monkeypatch.setattr("app.services.comfyui.client.comfyui_state", lambda url: "ok")
    assert "not installed" in outfit._no_modes_reason()
