"""
Node Jobs + Artifacts tests — Phase 3 (core execution) of the Cloud Mirror.

Locks the framework guarantees that don't need a GPU:
  - whitelist boundary (unknown operation rejected — no arbitrary execution)
  - job lifecycle: queued -> running -> completed/failed/cancelled, progress
  - honest failure: a raising handler yields status=failed with a reason,
    never fabricated output (design §12)
  - artifact store: content-type + size caps, TTL expiry, opaque ids,
    end-to-end delivery through a job
  - shared guards: localhost-only, feature-flagged

Self-contained: fake handlers, no network, no GPU.
"""
from __future__ import annotations

import importlib
import os
import sys
import time

import pytest

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


@pytest.fixture()
def jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOMEPILOT_MIRROR_JOBS_ENABLED", "true")
    monkeypatch.setenv("OLLABRIDGE_NODE_MANIFEST_ENABLED", "true")
    monkeypatch.setenv("NODE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("NODE_MANIFEST_STATE_PATH", str(tmp_path / "rev.json"))
    import app.node_jobs as j
    importlib.reload(j)
    return j


@pytest.fixture()
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("NODE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    import app.node_artifacts as a
    importlib.reload(a)
    return a


class _FakeReq:
    def __init__(self, host="127.0.0.1"):
        class _C:
            def __init__(s): s.host = host
        self.client = _C()


def _wait(job, jobs_mod, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if job.status in ("completed", "failed", "cancelled"):
            return
        time.sleep(0.01)


# ── Whitelist boundary ───────────────────────────────────────────────────────

class TestWhitelist:
    def test_unknown_operation_rejected(self, jobs):
        with pytest.raises(KeyError):
            jobs.create_job("shell.exec", {"cmd": "rm -rf /"})

    def test_builtins_declared_with_scopes(self, jobs):
        ops = {o["operation"]: o["scope"] for o in jobs.available_operations()}
        assert ops.get("chat.completions") == "chat:run"
        assert ops.get("images.generate") == "image:run"
        assert ops.get("videos.generate") == "video:run"

    def test_endpoint_unknown_op_400(self, jobs):
        resp = jobs.create_node_job(
            jobs.JobCreateRequest(operation="danger"), _FakeReq())
        assert resp.status_code == 400


# ── Lifecycle ────────────────────────────────────────────────────────────────

class TestLifecycle:
    def test_completed_job_carries_output(self, jobs):
        def handler(job, params):
            job.set_progress(50, "work", "halfway")
            return {"echo": params.get("x")}
        jobs.register_operation("test.echo", "node:read", handler)
        job = jobs.create_job("test.echo", {"x": 42})
        _wait(job, jobs)
        assert job.status == "completed"
        assert job.progress == 100
        assert job.output == {"echo": 42}

    def test_failing_handler_fails_honestly(self, jobs):
        def handler(job, params):
            raise ValueError("backend offline")
        jobs.register_operation("test.boom", "node:read", handler)
        job = jobs.create_job("test.boom", {})
        _wait(job, jobs)
        assert job.status == "failed"
        assert "backend offline" in job.error
        assert job.output is None  # never fabricated

    def test_builtin_image_op_fails_without_comfyui(self, jobs):
        # honest failure, not a crash or a fake image
        job = jobs.create_job("images.generate", {"prompt": "x"})
        _wait(job, jobs)
        assert job.status == "failed"
        assert "ComfyUI" in job.error

    def test_cancel(self, jobs):
        def handler(job, params):
            for _ in range(100):
                if job.cancelled():
                    return {}
                time.sleep(0.01)
            return {"done": True}
        jobs.register_operation("test.slow", "node:read", handler)
        job = jobs.create_job("test.slow", {})
        time.sleep(0.05)
        assert jobs.cancel_job(job.id) is True
        _wait(job, jobs)
        assert job.status == "cancelled"

    def test_progress_event_shape(self, jobs):
        def handler(job, params):
            job.set_progress(62, "sampling", "Generating")
            return {}
        jobs.register_operation("test.prog", "node:read", handler)
        job = jobs.create_job("test.prog", {})
        _wait(job, jobs)
        d = job.to_dict()
        assert d["job_id"] == job.id
        assert d["source"]["type"] == "homepilot_node"
        assert set(d) >= {"job_id", "status", "progress", "stage", "output"}


# ── Artifacts ────────────────────────────────────────────────────────────────

class TestArtifacts:
    def test_store_and_read_back(self, artifacts):
        meta = artifacts.store(b"\x89PNG fake", "image/png", "out.png", owner="u1")
        assert meta.artifact_id.startswith("art_")
        assert artifacts.get_path(meta.artifact_id) is not None
        assert artifacts.get_meta(meta.artifact_id).owner == "u1"

    def test_rejects_bad_content_type(self, artifacts):
        with pytest.raises(ValueError):
            artifacts.store(b"x", "application/x-sh", "evil.sh")

    def test_rejects_oversize(self, artifacts, monkeypatch):
        monkeypatch.setenv("NODE_ARTIFACT_MAX_MB", "1")
        import importlib
        importlib.reload(artifacts)
        with pytest.raises(ValueError):
            artifacts.store(b"x" * (2 * 1024 * 1024), "image/png")

    def test_expiry(self, artifacts, monkeypatch):
        monkeypatch.setenv("NODE_ARTIFACT_TTL_SEC", "60")
        import importlib
        importlib.reload(artifacts)
        meta = artifacts.store(b"data", "image/png")
        # force expiry
        mp = artifacts._meta_path(meta.artifact_id)
        m = artifacts.ArtifactMeta.model_validate_json(mp.read_text())
        m.expires_at = time.time() - 1
        mp.write_text(m.model_dump_json())
        assert artifacts.get_meta(meta.artifact_id) is None
        assert artifacts.get_path(meta.artifact_id) is None

    def test_opaque_id_validation(self, artifacts):
        assert artifacts.get_meta("../../etc/passwd") is None
        assert artifacts.get_meta("art_short") is None

    def test_job_delivers_artifact_end_to_end(self, jobs, monkeypatch, tmp_path):
        # a job produces a real artifact retrievable via the artifacts store
        monkeypatch.setenv("NODE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
        import app.node_artifacts as a
        import importlib
        importlib.reload(a)

        def handler(job, params):
            meta = a.store(b"\x89PNG real bytes", "image/png", "scene.png")
            return {"artifacts": [{"artifact_id": meta.artifact_id,
                                   "content_type": meta.content_type,
                                   "delivery": "relay"}]}
        jobs.register_operation("test.render", "image:run", handler)
        job = jobs.create_job("test.render", {})
        _wait(job, jobs)
        assert job.status == "completed"
        art_id = job.output["artifacts"][0]["artifact_id"]
        assert a.get_path(art_id) is not None


# ── Guards ───────────────────────────────────────────────────────────────────

class TestGuards:
    def test_remote_forbidden(self, jobs):
        resp = jobs.create_node_job(
            jobs.JobCreateRequest(operation="chat.completions"),
            _FakeReq(host="203.0.113.5"))
        assert resp.status_code == 403

    def test_disabled_404(self, jobs, monkeypatch):
        monkeypatch.setenv("HOMEPILOT_MIRROR_JOBS_ENABLED", "false")
        resp = jobs.get_node_job("job_x", _FakeReq())
        assert resp.status_code == 404

    def test_artifact_route_404_for_missing(self, jobs):
        resp = jobs.get_node_artifact("art_" + "a" * 24, _FakeReq())
        assert resp.status_code == 404
