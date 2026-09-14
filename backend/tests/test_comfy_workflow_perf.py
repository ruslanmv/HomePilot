"""
``run_workflow()`` after the preflight was taken off the hot path.

── The change under test ────────────────────────────────────────────────────────────────────

Node preflight is **diagnostic**: it exists to turn a cryptic ``invalid_prompt`` into "install
this custom node package". ``POST /prompt`` is the authoritative validator and runs microseconds
later regardless. So the preflight now reads cached metadata and never opens a socket, because
fetching it fresh cost up to thirty seconds *per image* — ComfyUI answers ``/object_info`` from
the process running the workflow, and is therefore slowest exactly when asked.

What that trade must not break, and what is asserted here:

* an unreachable or cold ``/object_info`` never blocks or fails a generation;
* the architecture guard, which is local and needs no metadata, still runs;
* when metadata *is* cached, missing nodes are still caught with the same message;
* the return schema is unchanged — instrumentation is logging, not payload;
* timeouts and execution errors still propagate.

Timings themselves are never asserted. A test that depends on a measured duration is a test that
fails on a loaded CI runner.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.comfy as comfy


GRAPH_OK = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
}

HISTORY = {
    "pid-1": {
        "status": {"completed": True, "status_str": "success"},
        "outputs": {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}},
    }
}


@pytest.fixture()
def wired(monkeypatch):
    """Stub everything around `run_workflow` except the code under test."""
    monkeypatch.setattr(comfy, "_load_workflow", lambda name: dict(GRAPH_OK))
    monkeypatch.setattr(comfy, "_preprocess_image_paths", lambda v: dict(v))
    monkeypatch.setattr(comfy, "_validate_prompt_graph", lambda *a, **k: None)
    monkeypatch.setattr(comfy, "_post_prompt", lambda client, graph: "pid-1")
    monkeypatch.setattr(comfy, "_get_history", lambda client, pid: HISTORY)

    client_ctx = MagicMock()
    client_ctx.__enter__ = MagicMock(return_value=client_ctx)
    client_ctx.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(comfy.httpx, "Client", MagicMock(return_value=client_ctx))
    return client_ctx


class TestTheHotPathDoesNotTouchObjectInfo:
    def test_preflight_is_cache_only(self, wired):
        # The assertion the whole change rests on: whatever the cache decides, the generation
        # path asked it not to use the network.
        with patch.object(comfy, "get_available_node_names", return_value=[]) as names:
            comfy.run_workflow("txt2img", {"seed": 1})
        assert names.call_args.kwargs.get("allow_network") is False

    def test_an_unreachable_comfy_does_not_block_generation(self, wired):
        # Previously this path waited up to 30s for metadata it only needed to phrase an error.
        #
        # Asserted against the cache's own fetch rather than by patching `httpx.Client`:
        # `comfy.httpx` and `object_info_cache.httpx` are the same module object, so patching
        # the transport to fail would break the workflow's *own* client and prove nothing about
        # the preflight.
        real_cache = comfy._object_info_cache
        cache = comfy.ComfyObjectInfoCache("http://mock:8188")
        cache._fetch_locked = MagicMock(side_effect=AssertionError("preflight hit the network"))
        comfy._object_info_cache = cache
        try:
            out = comfy.run_workflow("txt2img", {"seed": 1})
            assert out["images"]
            cache._fetch_locked.assert_not_called()
        finally:
            comfy._object_info_cache = real_cache

    def test_an_empty_cache_does_not_reject_the_workflow(self, wired):
        # "No metadata" must mean "skip the check", never "refuse". `/prompt` validates.
        with patch.object(comfy, "get_available_node_names", return_value=[]):
            out = comfy.run_workflow("txt2img", {"seed": 1})
        assert out["prompt_id"] == "pid-1"


class TestWhatThePreflightStillDoes:
    def test_the_architecture_guard_still_runs(self, wired):
        # Local, needs no metadata, and catches the one mismatch `/prompt` reports as an opaque
        # tensor error — so it is deliberately outside the cache-only gate.
        with patch.object(comfy, "_check_controlnet_architecture") as guard:
            with patch.object(comfy, "get_available_node_names", return_value=[]):
                comfy.run_workflow("txt2img", {"seed": 1})
        guard.assert_called_once()

    def test_missing_nodes_are_still_caught_when_metadata_is_cached(self, wired):
        with patch.object(comfy, "get_available_node_names", return_value=["KSampler"]):
            with pytest.raises(RuntimeError, match="SaveImage"):
                comfy.run_workflow("txt2img", {"seed": 1})

    def test_a_complete_cache_lets_the_workflow_through(self, wired):
        with patch.object(comfy, "get_available_node_names", return_value=["KSampler", "SaveImage"]):
            assert comfy.run_workflow("txt2img", {"seed": 1})["images"]

    def test_explicit_callers_can_still_force_the_network(self):
        # Endpoints that ask "what does ComfyUI have right now" must keep working.
        with patch.object(comfy, "get_available_node_names", return_value=["KSampler", "SaveImage"]) as names:
            comfy.validate_workflow_nodes("txt2img", dict(GRAPH_OK))
        assert names.call_args.kwargs.get("allow_network") is True


class TestSchemaAndFailuresAreUnchanged:
    def test_the_return_schema_is_unchanged(self, wired):
        with patch.object(comfy, "get_available_node_names", return_value=[]):
            out = comfy.run_workflow("txt2img", {"seed": 1})
        # Instrumentation is logging. Nothing about it may leak into the payload.
        assert set(out) == {"images", "videos", "prompt_id"}
        assert out["images"] == [
            f"{comfy.COMFY_BASE_URL.rstrip('/')}/view?filename=a.png&subfolder=&type=output"
        ]

    def test_a_timeout_still_raises(self, monkeypatch, wired):
        monkeypatch.setattr(comfy, "_get_history", lambda client, pid: {})
        monkeypatch.setattr(comfy, "COMFY_POLL_MAX_S", 0.01)
        monkeypatch.setattr(comfy.time, "sleep", lambda _s: None)
        with patch.object(comfy, "get_available_node_names", return_value=[]):
            with pytest.raises(TimeoutError, match="timed out"):
                comfy.run_workflow("txt2img", {"seed": 1})

    def test_a_post_failure_propagates(self, monkeypatch, wired):
        monkeypatch.setattr(
            comfy, "_post_prompt",
            MagicMock(side_effect=RuntimeError("invalid_prompt")),
        )
        with patch.object(comfy, "get_available_node_names", return_value=[]):
            with pytest.raises(RuntimeError, match="invalid_prompt"):
                comfy.run_workflow("txt2img", {"seed": 1})


class TestInstrumentation:
    def test_every_phase_is_reported(self, wired, capsys):
        with patch.object(comfy, "get_available_node_names", return_value=[]):
            comfy.run_workflow("txt2img", {"seed": 1})
        out = capsys.readouterr().out
        for phase in comfy._PERF_PHASES:
            assert f"[COMFY PERF] {phase}=" in out, phase

    def test_a_timeout_still_reports_where_the_budget_went(self, monkeypatch, wired, capsys):
        # The case where knowing the breakdown matters most, and the one path that never
        # reaches the success log.
        monkeypatch.setattr(comfy, "_get_history", lambda client, pid: {})
        monkeypatch.setattr(comfy, "COMFY_POLL_MAX_S", 0.01)
        monkeypatch.setattr(comfy.time, "sleep", lambda _s: None)
        with patch.object(comfy, "get_available_node_names", return_value=[]):
            with pytest.raises(TimeoutError):
                comfy.run_workflow("txt2img", {"seed": 1})
        out = capsys.readouterr().out
        assert "outcome=timeout" in out
        assert "[COMFY PERF] total_workflow_ms=" in out

    def test_total_is_not_a_sum_of_nothing(self, wired, capsys):
        # Guards against the previous log's actual defect: a reported total that started its
        # clock after the expensive part had already happened.
        with patch.object(comfy, "get_available_node_names", return_value=[]):
            comfy.run_workflow("txt2img", {"seed": 1})
        lines = dict(
            line.removeprefix("[COMFY PERF] ").split("=", 1)
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("[COMFY PERF] ") and "=" in line and "workflow=" not in line
        )
        total = float(lines["total_workflow_ms"])
        parts = sum(
            float(v) for k, v in lines.items()
            # `history_fetch_ms` is nested inside `queue_and_execution_ms`, so counting both
            # would double-count the polling.
            if k not in ("total_workflow_ms", "history_fetch_ms")
        )
        assert total >= parts


class TestWarmup:
    def test_warmup_uses_the_network(self):
        with patch.object(comfy, "get_available_node_names", return_value=["KSampler"]) as names:
            comfy.warm_object_info_cache()
        # The whole point: metadata has to arrive from somewhere, and it is no longer the
        # generation path.
        assert names.call_args.kwargs.get("allow_network", True) is True

    def test_warmup_never_raises(self):
        # A HomePilot that starts before ComfyUI is ordinary, not a misconfiguration.
        with patch.object(comfy, "get_available_node_names", side_effect=RuntimeError("down")):
            comfy.warm_object_info_cache()
