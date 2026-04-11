from __future__ import annotations

from .models import ExportKind, ExportPreset

YOUTUBE_MP4 = ExportPreset(
    name="youtube_mp4",
    width=1920,
    height=1080,
    fps=30,
    crf=18,
    preset="medium",
)

SHORTS_MP4 = ExportPreset(
    name="shorts_mp4",
    width=1080,
    height=1920,
    fps=30,
    crf=18,
    preset="medium",
)

VIDEO_MP4 = ExportPreset(
    name="video_mp4",
    width=1280,
    height=720,
    fps=30,
    crf=18,
    preset="medium",
)

PRESETS: dict[ExportKind, ExportPreset] = {
    "video_mp4": VIDEO_MP4,
    "youtube_mp4": YOUTUBE_MP4,
    "shorts_mp4": SHORTS_MP4,
}


def get_preset(kind: ExportKind) -> ExportPreset:
    return PRESETS[kind]
