"""
Happy-path test for Creator Studio MP4 export.

Verifies the full async flow for a 2-scene project:

  1. POST /studio/videos/{id}/export/mp4 returns 202 + a job descriptor.
  2. Polling the job endpoint surfaces queued → running → done.
  3. The download endpoint returns a real MP4 (ffprobe-readable) with the
     expected canvas dimensions for the chosen platform preset.
  4. Cross-account access to the job (status + download) returns 404 — we
     deliberately treat foreign job ids as not-found rather than 403 so
     that ids cannot be probed.

The renderer needs the ffmpeg + ffprobe binaries on PATH. If they are not
present (CI without the package) the whole module is skipped so this does
not regress green builds.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.studio import render_jobs
from app.studio.repo import init_studio_db


def _create_video(client, *, preset: str = "youtube_16_9") -> str:
    r = client.post(
        "/studio/videos",
        json={"title": "t", "platformPreset": preset},
    )
    assert r.status_code == 200, r.text
    return r.json()["video"]["id"]


def _add_scene(client, video_id: str, image_path: str, duration: float = 1.0) -> str:
    r = client.post(
        f"/studio/videos/{video_id}/scenes",
        json={"narration": "x", "durationSec": duration},
    )
    assert r.status_code == 200, r.text
    scene_id = r.json()["scene"]["id"]
    r = client.patch(
        f"/studio/videos/{video_id}/scenes/{scene_id}",
        json={"imageUrl": image_path, "status": "ready"},
    )
    assert r.status_code == 200, r.text
    return scene_id


# Skip the whole module when the host has no ffmpeg.
pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe not installed on test host",
)


def _register(client, username: str) -> tuple[dict, str]:
    r = client.post(
        "/v1/auth/register",
        json={"username": username, "password": "pw1", "display_name": username},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["user"], body["token"]


def _make_png(path: Path, color: str) -> None:
    """Generate a tiny PNG via ffmpeg's lavfi color source."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d=0.04",
            "-frames:v", "1",
            str(path),
        ],
        check=True,
    )


def _ffprobe_dims(path: str) -> tuple[int, int]:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            path,
        ],
        check=True, capture_output=True, text=True,
    )
    s = json.loads(proc.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


def _wait_done(client, video_id: str, job_id: str, token: str, timeout: float = 60.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(
            f"/studio/videos/{video_id}/export/jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("done", "error"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"job did not finish within {timeout}s; last={last}")


def test_video_mp4_export_end_to_end(client, tmp_path, monkeypatch):
    init_studio_db()
    render_jobs._reset_for_tests()

    user_a, token_a = _register(client, "studio_owner_a")

    # Build a tiny 2-scene video with two single-frame still images.
    img1 = tmp_path / "red.png"
    img2 = tmp_path / "blue.png"
    _make_png(img1, "red")
    _make_png(img2, "blue")

    video_id = _create_video(client, preset="youtube_16_9")
    _add_scene(client, video_id, str(img1))
    _add_scene(client, video_id, str(img2))

    # 1) Submit render.
    r = client.post(
        f"/studio/videos/{video_id}/export/mp4",
        json={"kind": "mp4_plain"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] in ("queued", "running")
    assert job["kind"] == "mp4_plain"
    assert job["video_id"] == video_id
    job_id = job["id"]

    # 2) Poll until done.
    final = _wait_done(client, video_id, job_id, token_a)
    assert final["status"] == "done", final
    assert final["progress"] == 100.0

    # 3) Download and ffprobe.
    r = client.get(
        f"/studio/videos/{video_id}/export/jobs/{job_id}/download",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    out = tmp_path / "out.mp4"
    out.write_bytes(r.content)
    assert out.stat().st_size > 1024, "rendered file looks empty"

    width, height = _ffprobe_dims(str(out))
    # youtube_16_9 → 1920x1080 canvas regardless of source resolution.
    assert (width, height) == (1920, 1080), f"got {width}x{height}"

    # 4) Cross-account access is rejected as 404 (not 403, by design).
    _user_b, token_b = _register(client, "studio_owner_b")
    r = client.get(
        f"/studio/videos/{video_id}/export/jobs/{job_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404, r.text
    r = client.get(
        f"/studio/videos/{video_id}/export/jobs/{job_id}/download",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404, r.text


def test_video_mp4_export_youtube_preset_uses_faststart(client, tmp_path):
    """The mp4_youtube profile must place the moov atom near the start so
    streaming clients can begin playback before the file is fully buffered."""
    init_studio_db()
    render_jobs._reset_for_tests()
    user, token = _register(client, "yt_owner")

    img = tmp_path / "g.png"
    _make_png(img, "green")

    video_id = _create_video(client, preset="shorts_9_16")
    _add_scene(client, video_id, str(img))

    r = client.post(
        f"/studio/videos/{video_id}/export/mp4",
        json={"kind": "mp4_youtube"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    final = _wait_done(client, video_id, job_id, token)
    assert final["status"] == "done", final

    r = client.get(
        f"/studio/videos/{video_id}/export/jobs/{job_id}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    out = tmp_path / "yt.mp4"
    out.write_bytes(r.content)

    # ffprobe the file: shorts canvas + faststart-friendly layout.
    width, height = _ffprobe_dims(str(out))
    assert (width, height) == (1080, 1920)

    # Faststart writes the moov atom near the head of the file. Search the
    # first 64 KiB for the 'moov' box — if it is at the tail, this fails.
    with open(out, "rb") as f:
        head = f.read(64 * 1024)
    assert b"moov" in head, "mp4_youtube must use +faststart (moov atom at head)"
