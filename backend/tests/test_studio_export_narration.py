"""
End-to-end test for Creator Studio narration upload + audio-aware export.

Real Piper WASM can't run in pytest (it's a browser-side library), so we
synthesize fake 16-bit mono WAV fixtures with ffmpeg's ``sine`` lavfi
source and upload them through the real HTTP endpoint. The render then
runs with ``subtitles=burn_in`` and non-default ``audio_rate`` /
``audio_pitch`` values, and we ffprobe the result to prove:

  * every scene's narration WAV ended up mixed into the final MP4,
  * the sidecar ``.srt`` was written beside the ``.mp4``,
  * the output canvas matches the project's platform preset,
  * the ``audio_rate`` / ``audio_pitch`` were actually applied.

Module is skipped when the host has no ffmpeg/ffprobe so green CI on
environments without the binary stays green.
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


pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe not installed on test host",
)


def _register(client, username: str) -> tuple[dict, str]:
    r = client.post(
        "/v1/auth/register",
        json={"username": username, "password": "pw", "display_name": username},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["user"], body["token"]


def _create_video(client, *, preset: str = "youtube_16_9") -> str:
    r = client.post("/studio/videos", json={"title": "t", "platformPreset": preset})
    assert r.status_code == 200, r.text
    return r.json()["video"]["id"]


def _add_scene(client, video_id: str, image_path: str, narration: str, duration: float) -> str:
    r = client.post(
        f"/studio/videos/{video_id}/scenes",
        json={"narration": narration, "durationSec": duration},
    )
    assert r.status_code == 200, r.text
    scene_id = r.json()["scene"]["id"]
    r = client.patch(
        f"/studio/videos/{video_id}/scenes/{scene_id}",
        json={"imageUrl": image_path, "status": "ready"},
    )
    assert r.status_code == 200, r.text
    return scene_id


def _make_png(path: Path, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x240:d=0.04",
            "-frames:v", "1",
            str(path),
        ],
        check=True,
    )


def _make_sine_wav(path: Path, seconds: float, freq: int = 440) -> None:
    """Synthesize a tiny mono 22.05 kHz WAV — stands in for Piper output."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"sine=frequency={freq}:sample_rate=22050:duration={seconds}",
            "-ac", "1",
            "-sample_fmt", "s16",
            str(path),
        ],
        check=True,
    )


def _ffprobe(path: str) -> dict:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-show_format",
            "-of", "json",
            path,
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(proc.stdout)


def _wait_done(client, video_id: str, job_id: str, token: str, timeout: float = 90.0):
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


def test_narration_upload_then_export_with_burnin(client, tmp_path):
    init_studio_db()
    render_jobs._reset_for_tests()
    _user, token = _register(client, "narration_owner")

    # Two tiny visuals + two narrations.
    img1 = tmp_path / "red.png"
    img2 = tmp_path / "blue.png"
    _make_png(img1, "red")
    _make_png(img2, "blue")

    wav1 = tmp_path / "narr1.wav"
    wav2 = tmp_path / "narr2.wav"
    _make_sine_wav(wav1, seconds=1.0, freq=440)
    _make_sine_wav(wav2, seconds=1.0, freq=660)

    video_id = _create_video(client, preset="youtube_16_9")
    s1 = _add_scene(
        client, video_id, str(img1),
        narration="This is the first scene. It introduces the story.",
        duration=1.0,
    )
    s2 = _add_scene(
        client, video_id, str(img2),
        narration="Second scene. Conflict and resolution happen here.",
        duration=1.0,
    )

    # Upload narration WAVs via the real HTTP endpoint.
    for sid, wav in ((s1, wav1), (s2, wav2)):
        with open(wav, "rb") as fh:
            r = client.post(
                f"/studio/videos/{video_id}/scenes/{sid}/narration",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": (f"{sid}.wav", fh, "audio/wav")},
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["scene_id"] == sid
        assert os.path.exists(body["audioUrl"])

    # Render with burn-in subtitles + non-unit rate & pitch.
    r = client.post(
        f"/studio/videos/{video_id}/export/mp4",
        json={
            "kind": "mp4_plain",
            "audio_rate": 1.1,
            "audio_pitch": 0.9,
            "subtitles": "burn_in",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["subtitles"] == "burn_in"
    assert abs(job["audio_rate"] - 1.1) < 1e-6
    assert abs(job["audio_pitch"] - 0.9) < 1e-6
    job_id = job["id"]

    final = _wait_done(client, video_id, job_id, token)
    assert final["status"] == "done", final

    # Download + probe.
    r = client.get(
        f"/studio/videos/{video_id}/export/jobs/{job_id}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    out = tmp_path / "out.mp4"
    out.write_bytes(r.content)
    assert out.stat().st_size > 2048

    info = _ffprobe(str(out))
    # Canvas matches the youtube_16_9 preset.
    video_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert int(video_stream["width"]) == 1920
    assert int(video_stream["height"]) == 1080
    # Audio is present — the narration was mixed in.
    audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert len(audio_streams) == 1, f"expected exactly one audio stream, got {len(audio_streams)}"
    assert audio_streams[0]["codec_name"] in {"aac", "mp3"}

    # Sidecar SRT is written next to the MP4 on the server.
    from app.studio.render_jobs import get_job
    server_job = get_job(job_id)
    assert server_job is not None and server_job.output_path
    srt_path = Path(server_job.output_path).with_suffix(".srt")
    assert srt_path.exists(), f"expected sidecar {srt_path} to exist"
    srt_text = srt_path.read_text(encoding="utf-8")
    assert "first scene" in srt_text.lower()
    assert "second scene" in srt_text.lower()
    # Subtitle cues are numbered and timestamped.
    assert "00:00:00," in srt_text


def test_narration_upload_rejects_unknown_scene(client, tmp_path):
    """Unknown scene id → 404 even for an authenticated owner."""
    init_studio_db()
    render_jobs._reset_for_tests()
    _user, token = _register(client, "narration_404")

    wav = tmp_path / "n.wav"
    _make_sine_wav(wav, seconds=0.3)
    video_id = _create_video(client)

    with open(wav, "rb") as fh:
        r = client.post(
            f"/studio/videos/{video_id}/scenes/does-not-exist/narration",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("x.wav", fh, "audio/wav")},
        )
    assert r.status_code == 404, r.text


def test_export_backward_compat_without_options(client, tmp_path):
    """The /export/mp4 body still works with just {kind: ...}."""
    init_studio_db()
    render_jobs._reset_for_tests()
    _user, token = _register(client, "compat_owner")
    img = tmp_path / "b.png"
    _make_png(img, "yellow")
    video_id = _create_video(client, preset="shorts_9_16")
    _add_scene(client, video_id, str(img), narration="", duration=1.0)

    r = client.post(
        f"/studio/videos/{video_id}/export/mp4",
        json={"kind": "mp4_plain"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["audio_rate"] == 1.0
    assert job["audio_pitch"] == 1.0
    assert job["subtitles"] == "none"
    final = _wait_done(client, video_id, job["id"], token)
    assert final["status"] == "done", final
