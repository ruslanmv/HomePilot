from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

ProjectType = Literal["video", "slideshow", "video_series", "youtube_video", "youtube_short", "slides"]
ExportKind = Literal["video_mp4", "youtube_mp4", "shorts_mp4"]


@dataclass
class SceneSource:
    scene_id: str
    title: str = ""
    kind: Literal["video", "image"] = "image"
    source_url: str = ""
    duration_sec: float = 4.0
    transition_sec: float = 0.25
    narration_url: Optional[str] = None
    music_url: Optional[str] = None
    subtitle_text: str = ""
    effect: Literal["none", "ken_burns"] = "none"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimelinePlan:
    project_id: str
    project_type: ProjectType
    export_kind: ExportKind
    width: int
    height: int
    fps: int
    scenes: list[SceneSource] = field(default_factory=list)
    voiceover_url: Optional[str] = None
    music_url: Optional[str] = None
    subtitle_items: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_type": self.project_type,
            "export_kind": self.export_kind,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "scenes": [asdict(s) for s in self.scenes],
            "voiceover_url": self.voiceover_url,
            "music_url": self.music_url,
            "subtitle_items": self.subtitle_items,
            "metadata": self.metadata,
        }


@dataclass
class WorkingFiles:
    workdir: Path
    sources_dir: Path
    renders_dir: Path
    concat_list_path: Path
    subtitles_path: Path
    final_output_path: Path
    thumbnail_path: Path
    manifest_path: Path


@dataclass
class ExportPreset:
    name: str
    width: int
    height: int
    fps: int
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 18
    preset: str = "medium"
    pix_fmt: str = "yuv420p"
    movflags: str = "+faststart"
    audio_bitrate: str = "192k"
    sample_rate: int = 48000
    allow_letterbox: bool = True
    background_color: str = "black"

    def to_ffmpeg_args(self) -> list[str]:
        return [
            "-c:v",
            self.video_codec,
            "-crf",
            str(self.crf),
            "-preset",
            self.preset,
            "-pix_fmt",
            self.pix_fmt,
            "-movflags",
            self.movflags,
            "-c:a",
            self.audio_codec,
            "-b:a",
            self.audio_bitrate,
            "-ar",
            str(self.sample_rate),
        ]


@dataclass
class ExportResult:
    export_id: str
    project_id: str
    kind: ExportKind
    status: Literal["ready", "error"]
    output_path: str
    output_url: str
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    manifest_path: Optional[str] = None
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    fps: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
