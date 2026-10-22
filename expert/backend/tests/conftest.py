"""Make ``app`` resolve to the Expert package next to these tests.

The Expert package lives under a namespace-only ``app`` directory (no __init__.py). When the
main backend is installed into the same interpreter — its editable install puts ``backend/``
on sys.path — that regular ``app`` package wins over the namespace one, and every test here
fails to collect with "No module named 'app.expert'". Drop that entry before any test module
imports ``app``; where there is no sibling backend (the Expert image) nothing changes.
"""
import pathlib
import sys

_EXPERT_BACKEND = pathlib.Path(__file__).resolve().parents[1]          # expert/backend
_MAIN_BACKEND = _EXPERT_BACKEND.parents[1] / "backend"                 # <repo>/backend

sys.path[:] = [p for p in sys.path if pathlib.Path(p or ".").resolve() != _MAIN_BACKEND]
if str(_EXPERT_BACKEND) not in sys.path:
    sys.path.insert(0, str(_EXPERT_BACKEND))
sys.modules.pop("app", None)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_state_store(tmp_path):
    """Every test gets its own durable store; the real expert_state.sqlite is never touched,
    and no learned capability fact leaks from one test into the next."""
    from app.expert import providers, state_store, tool_loop

    state_store.configure(tmp_path / "expert_state.sqlite")
    tool_loop._TOOL_FACTS.clear()
    # No request pacing between the fakes' instant answers, and no state from another test.
    providers._PACER.reset(min_interval=0.0, max_interval=0.0, window=0.01)
    yield
    tool_loop._TOOL_FACTS.clear()
