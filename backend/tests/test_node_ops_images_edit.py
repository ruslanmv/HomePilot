"""
images.edit node job (HP-2, HP-3) — additive, flag-gated, input-checked.

Self-contained: the compute router is faked; outputs are written to a temp
upload dir and must come back as node artifacts.
"""
from __future__ import annotations

import base64
import importlib
import os
import sys
import time
from types import SimpleNamespace

import pytest

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _load(monkeypatch, tmp_path, *, on: bool):
    monkeypatch.setenv("HOMEPILOT_MIRROR_JOBS_ENABLED", "true")
    monkeypatch.setenv("HOMEPILOT_MIRROR_IMAGE_EDIT_ENABLED", "true" if on else "false")
    monkeypatch.setenv("HOMEPILOT_MIRROR_RESOURCE_MAX_MB", "1")
    monkeypatch.setenv("NODE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    import app.config as config
    import app.node_artifacts as arts
    import app.node_ops_images_edit as ops
    import app.node_jobs as jobs

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "uploads"))
    importlib.reload(arts)
    importlib.reload(ops)
    importlib.reload(jobs)
    return jobs, ops, arts


def _wait(job, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and job.status not in ("completed", "failed", "cancelled"):
        time.sleep(0.01)


def _fake_edit(ops, monkeypatch, tmp_path, *, output=PNG, seen=None):
    async def edit(prompt, image_ref, model, workflow):
        staged = tmp_path / "uploads" / image_ref.replace("/files/", "")
        if seen is not None:
            seen.update(prompt=prompt, image_ref=image_ref, workflow=workflow, staged_bytes=staged.read_bytes())
        out = tmp_path / "uploads" / "outputs" / "result.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(output)
        return SimpleNamespace(images=["/files/outputs/result.png"], meta={"provider": "local"})

    monkeypatch.setattr(ops, "_edit", edit)


def test_flag_off_not_registered(monkeypatch, tmp_path):
    jobs, ops, _ = _load(monkeypatch, tmp_path, on=False)
    assert "images.edit" not in [o["operation"] for o in jobs.available_operations()]
    with pytest.raises(KeyError):
        jobs.create_job("images.edit", {})


def test_edit_runs_and_returns_artifacts(monkeypatch, tmp_path):
    jobs, ops, arts = _load(monkeypatch, tmp_path, on=True)
    assert {"operation": "images.edit", "scope": "image:run"} in jobs.available_operations()
    seen = {}
    _fake_edit(ops, monkeypatch, tmp_path, seen=seen)

    image = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    job = jobs.create_job("images.edit", {"prompt": "Dress the person in a navy blazer", "image": image})
    _wait(job)
    assert job.status == "completed", job.error
    assert seen["staged_bytes"] == JPEG and seen["workflow"] == "edit"
    (art,) = job.output["artifacts"]
    assert art["content_type"] == "image/png"
    assert open(arts.get_path(art["artifact_id"]), "rb").read() == PNG
    # the staged input is removed once the job ends
    assert not (tmp_path / "uploads" / seen["image_ref"].replace("/files/", "")).exists()


def test_artifact_ids_are_accepted_as_input(monkeypatch, tmp_path):
    jobs, ops, arts = _load(monkeypatch, tmp_path, on=True)
    _fake_edit(ops, monkeypatch, tmp_path)
    meta = arts.store(JPEG, "image/jpeg")
    job = jobs.create_job("images.edit", {"prompt": "x", "image": meta.artifact_id})
    _wait(job)
    assert job.status == "completed", job.error


@pytest.mark.parametrize(
    "image,reason",
    [
        (None, "image is required"),
        ("https://example.com/me.jpg", "artifact id or base64"),
        (base64.b64encode(b"GIF89a....").decode(), "only JPEG, PNG or WebP"),
        (base64.b64encode(b"\xff\xd8\xff" + b"0" * (2 * 1024 * 1024)).decode(), "too large"),
        ("art_00000000000000000000", "not found"),
    ],
)
def test_inputs_are_checked(monkeypatch, tmp_path, image, reason):
    jobs, ops, _ = _load(monkeypatch, tmp_path, on=True)
    _fake_edit(ops, monkeypatch, tmp_path)
    job = jobs.create_job("images.edit", {"prompt": "x", "image": image})
    _wait(job)
    assert job.status == "failed"
    assert "RESOURCE_REJECTED" in job.error and reason in job.error


def test_no_image_produced_fails_honestly(monkeypatch, tmp_path):
    jobs, ops, _ = _load(monkeypatch, tmp_path, on=True)
    _fake_edit(ops, monkeypatch, tmp_path, output=b"not an image")
    job = jobs.create_job("images.edit", {"prompt": "x", "image": base64.b64encode(PNG).decode()})
    _wait(job)
    assert job.status == "failed" and "IMAGE_EDIT_FAILED" in job.error
    assert job.output is None


def test_remote_output_urls_are_not_fetched(monkeypatch, tmp_path):
    _, ops, _ = _load(monkeypatch, tmp_path, on=True)
    assert ops._read_output("https://evil.example/x.png") is None
    assert ops._read_output("/files/../../etc/passwd") is None
