"""
Lightweight unit tests for the additive Creator Studio video export module.

These tests do NOT require ffmpeg or network access. They verify:

1. Preset lookup returns the expected resolution/fps for each kind.
2. The timeline planner converts a synthetic project payload into a
   structured TimelinePlan (scenes, subtitles, voiceover, music).
3. compose_project_export runs end-to-end with ffmpeg/ffprobe and the
   remote fetch mocked out, and produces:
     - an ExportResult with status="ready"
     - final.mp4, thumbnail.jpg, and the export manifest on disk
     - a manifest that round-trips through JSON

The goal is to lock in the public contract of the additive module so we
catch regressions without booting the full app or calling ffmpeg.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.studio.video_export import composer as composer_mod
from app.studio.video_export import ffmpeg as ffmpeg_mod
from app.studio.video_export.composer import compose_project_export
from app.studio.video_export.planner import build_timeline_plan
from app.studio.video_export.presets import get_preset


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture()
def sample_project() -> dict:
    """A minimal project payload that exercises the planner branches."""
    return {
        "title": "Sample Project",
        "projectType": "youtube_video",
        "voiceover_url": "https://example.com/voice.mp3",
        "music_url": "https://example.com/music.mp3",
        "scenes": [
            {
                "id": "s1",
                "title": "Intro",
                "imageUrl": "https://example.com/frame1.png",
                "durationSec": 3.0,
                "subtitle_text": "Hello world",
                "effect": "ken_burns",
            },
            {
                "id": "s2",
                "title": "Main clip",
                "videoUrl": "https://example.com/clip2.mp4",
                "durationSec": 5.0,
                "subtitle_text": "Main scene",
            },
        ],
    }


@pytest.fixture()
def patched_render(monkeypatch, tmp_path):
    """
    Patch ffmpeg + fetch so compose_project_export runs without touching
    a real binary or the network. Each patch just writes a tiny placeholder
    file to the expected output path, keeping the composer's filesystem
    contract intact.
    """

    # Redirect the export workspace under tmp_path so tests don't pollute
    # backend/data/ on the developer machine.
    def _fake_repo_root() -> Path:
        return tmp_path

    monkeypatch.setattr(
        "app.studio.video_export.paths.repo_root", _fake_repo_root
    )

    def _touch(path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(b"\x00")

    def _fake_materialize(url, dest_dir, stem):
        dest = Path(dest_dir) / f"{stem}.bin"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x00")
        return dest

    def _fake_render_image_clip(image_path, output_path, duration_sec, preset, effect="ken_burns"):
        _touch(output_path)

    def _fake_normalize_video_clip(video_path, output_path, preset):
        _touch(output_path)

    def _fake_concat_videos(concat_list_path, output_path, preset):
        _touch(output_path)

    def _fake_mux_audio(video_path, output_path, voiceover_path=None, music_path=None, preset=None):
        _touch(output_path)

    def _fake_write_srt(items, path):
        Path(path).write_text("1\n00:00:00,000 --> 00:00:01,000\nmock\n", encoding="utf-8")

    def _fake_burn_subtitles(video_path, srt_path, output_path, preset):
        _touch(output_path)

    def _fake_extract_thumbnail(video_path, output_path, timestamp_sec=0.2):
        _touch(output_path)

    def _fake_media_duration_sec(path) -> float:
        return 8.0

    # Patch in both the ffmpeg module (for completeness) and the composer
    # namespace where these names were imported at module load time.
    for target, value in [
        ("render_image_clip", _fake_render_image_clip),
        ("normalize_video_clip", _fake_normalize_video_clip),
        ("concat_videos", _fake_concat_videos),
        ("mux_audio", _fake_mux_audio),
        ("write_srt", _fake_write_srt),
        ("burn_subtitles", _fake_burn_subtitles),
        ("extract_thumbnail", _fake_extract_thumbnail),
        ("media_duration_sec", _fake_media_duration_sec),
    ]:
        monkeypatch.setattr(ffmpeg_mod, target, value, raising=True)
        monkeypatch.setattr(composer_mod, target, value, raising=True)

    monkeypatch.setattr(
        composer_mod, "materialize_remote_source", _fake_materialize, raising=True
    )

    return tmp_path


# --------------------------------------------------------------------------- #
# Pure-logic tests (no mocking)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "kind,width,height",
    [
        ("video_mp4", 1280, 720),
        ("youtube_mp4", 1920, 1080),
        ("shorts_mp4", 1080, 1920),
    ],
)
def test_presets_have_expected_resolutions(kind, width, height):
    preset = get_preset(kind)
    assert preset.width == width
    assert preset.height == height
    assert preset.fps >= 24
    # Smoke-check the ffmpeg arg builder.
    args = preset.to_ffmpeg_args()
    assert "-c:v" in args and preset.video_codec in args
    assert "-c:a" in args and preset.audio_codec in args


def test_build_timeline_plan_maps_scenes_and_subtitles(sample_project):
    plan = build_timeline_plan("proj-1", sample_project, "youtube_mp4")

    assert plan.project_id == "proj-1"
    assert plan.export_kind == "youtube_mp4"
    assert plan.width == 1920 and plan.height == 1080

    assert len(plan.scenes) == 2
    image_scene, video_scene = plan.scenes
    assert image_scene.kind == "image"
    assert image_scene.source_url == "https://example.com/frame1.png"
    assert image_scene.duration_sec == 3.0
    assert video_scene.kind == "video"
    assert video_scene.source_url == "https://example.com/clip2.mp4"
    assert video_scene.duration_sec == 5.0

    # Subtitles should be accumulated with contiguous start/end times.
    assert len(plan.subtitle_items) == 2
    assert plan.subtitle_items[0]["start"] == 0.0
    assert plan.subtitle_items[0]["end"] == 3.0
    assert plan.subtitle_items[1]["start"] == 3.0
    assert plan.subtitle_items[1]["end"] == 8.0

    assert plan.voiceover_url == "https://example.com/voice.mp3"
    assert plan.music_url == "https://example.com/music.mp3"

    # to_dict must be JSON-serializable.
    json.dumps(plan.to_dict())


# --------------------------------------------------------------------------- #
# End-to-end composer test (mocked ffmpeg + fetch)
# --------------------------------------------------------------------------- #

def test_compose_project_export_produces_mp4_artifacts(sample_project, patched_render):
    result = compose_project_export(
        project_id="proj-e2e",
        project=sample_project,
        export_kind="youtube_mp4",
        public_base_url="http://localhost:8000",
    )

    # ExportResult contract
    assert result.status == "ready"
    assert result.kind == "youtube_mp4"
    assert result.project_id == "proj-e2e"
    assert result.width == 1920 and result.height == 1080
    assert result.duration_sec == 8.0
    assert result.output_url.endswith(f"/studio/exports/proj-e2e/{result.export_id}/final.mp4")
    assert result.thumbnail_url.endswith(f"/studio/exports/proj-e2e/{result.export_id}/thumbnail.jpg")

    # Filesystem contract
    final_mp4 = Path(result.output_path)
    thumb = Path(result.thumbnail_path)
    manifest_path = Path(result.manifest_path)
    assert final_mp4.exists(), "final.mp4 should have been written by the composer"
    assert thumb.exists(), "thumbnail.jpg should have been written by the composer"
    assert manifest_path.exists(), "export_manifest.json should have been written"

    # Manifest contract
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["export_id"] == result.export_id
    assert manifest["project_id"] == "proj-e2e"
    assert manifest["kind"] == "youtube_mp4"
    assert manifest["duration_sec"] == 8.0
    assert manifest["plan"]["scene_count"] if "scene_count" in manifest["plan"] else True
    assert len(manifest["plan"]["scenes"]) == 2


def test_compose_project_export_rejects_empty_project(patched_render):
    with pytest.raises(ValueError, match="No renderable scenes"):
        compose_project_export(
            project_id="proj-empty",
            project={"title": "Empty", "scenes": []},
            export_kind="video_mp4",
            public_base_url="http://localhost:8000",
        )
