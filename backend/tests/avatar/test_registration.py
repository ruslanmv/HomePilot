"""``avatar.enabled=false`` mounts no route and imports nothing (batch B8).

The second half is the one worth a test of its own. "No route mounted" is easy to satisfy
and easy to check; "imports nothing" is the half that quietly stops being true the first
time someone moves an import to the top of a file for tidiness. So it is asserted against
``sys.modules`` directly.
"""

from __future__ import annotations

import sys

from app.avatar_director import AvatarDirectorConfig, register

SESSION_MODULE = "app.avatar_director.session"


class FakeApp:
    """Just enough of FastAPI to see whether anything was mounted."""

    def __init__(self) -> None:
        self.routers = []

    def include_router(self, router) -> None:
        self.routers.append(router)


def _forget_session_module() -> None:
    sys.modules.pop(SESSION_MODULE, None)


def test_disabled_mounts_no_route():
    app = FakeApp()
    assert register(app, AvatarDirectorConfig(enabled=False)) is False
    assert app.routers == []


def test_disabled_imports_nothing():
    _forget_session_module()
    app = FakeApp()
    register(app, AvatarDirectorConfig(enabled=False))
    assert SESSION_MODULE not in sys.modules, "the session module was imported while disabled"


def test_enabled_mounts_the_session_and_the_control_route():
    """Two, as of B17: the §6.9 socket and the loopback route the MCP tool server calls.
    The count is asserted rather than the routers' contents because what matters is that a
    batch cannot mount a third without saying so here."""
    app = FakeApp()
    assert register(app, AvatarDirectorConfig(enabled=True)) is True
    assert len(app.routers) == 2


def test_vision_adds_a_third_only_when_a_model_is_configured():
    from app.avatar_director.config import VisionConfig

    app = FakeApp()
    register(app, AvatarDirectorConfig(enabled=True))
    assert len(app.routers) == 2

    with_model = FakeApp()
    register(with_model, AvatarDirectorConfig(enabled=True, vision=VisionConfig(model="moondream")))
    assert len(with_model.routers) == 3


def test_the_package_itself_is_cheap_to_import():
    """Importing the package must not drag FastAPI in: the config tests rely on that, and
    so does anyone reading the config without a full environment."""
    _forget_session_module()
    import importlib

    importlib.reload(importlib.import_module("app.avatar_director"))
    assert SESSION_MODULE not in sys.modules
