from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .models import ExportPreset


class FFmpegError(RuntimeError):
    pass


def run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip() or proc.stdout.strip())


def run_ffprobe_json(path: str | Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout)


def media_duration_sec(path: str | Path) -> float:
    info = run_ffprobe_json(path)
    fmt = info.get("format", {})
    try:
        return float(fmt.get("duration", 0.0))
    except Exception:
        return 0.0


def detect_has_audio(path: str | Path) -> bool:
    info = run_ffprobe_json(path)
    streams = info.get("streams", [])
    return any(s.get("codec_type") == "audio" for s in streams)


def make_scale_pad_filter(width: int, height: int, background_color: str = "black") -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:{background_color}"
    )


def render_image_clip(
    image_path: str | Path,
    output_path: str | Path,
    duration_sec: float,
    preset: ExportPreset,
    effect: str = "ken_burns",
) -> None:
    vf_base = make_scale_pad_filter(preset.width, preset.height, preset.background_color)
    if effect == "ken_burns":
        vf = (
            f"{vf_base},"
            f"zoompan=z='min(zoom+0.0008,1.08)':d={int(duration_sec * preset.fps)}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={preset.width}x{preset.height},"
            f"fps={preset.fps}"
        )
    else:
        vf = f"{vf_base},fps={preset.fps}"

    args = [
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-t",
        f"{duration_sec:.3f}",
        "-vf",
        vf,
        *preset.to_ffmpeg_args(),
        "-an",
        str(output_path),
    ]
    run_ffmpeg(args)


def normalize_video_clip(video_path: str | Path, output_path: str | Path, preset: ExportPreset) -> None:
    vf = make_scale_pad_filter(preset.width, preset.height, preset.background_color)
    args = [
        "-i",
        str(video_path),
        "-vf",
        f"{vf},fps={preset.fps}",
        *preset.to_ffmpeg_args(),
        str(output_path),
    ]
    run_ffmpeg(args)


def concat_videos(concat_list_path: str | Path, output_path: str | Path, preset: ExportPreset) -> None:
    args = [
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-c:v",
        preset.video_codec,
        "-crf",
        str(preset.crf),
        "-preset",
        preset.preset,
        "-pix_fmt",
        preset.pix_fmt,
        "-movflags",
        preset.movflags,
        "-c:a",
        preset.audio_codec,
        "-b:a",
        preset.audio_bitrate,
        "-ar",
        str(preset.sample_rate),
        str(output_path),
    ]
    run_ffmpeg(args)


def mux_audio(
    video_path: str | Path,
    output_path: str | Path,
    voiceover_path: Optional[str | Path] = None,
    music_path: Optional[str | Path] = None,
    preset: Optional[ExportPreset] = None,
) -> None:
    if not voiceover_path and not music_path:
        shutil.copyfile(video_path, output_path)
        return

    inputs = ["-i", str(video_path)]
    audio_inputs: list[tuple[int, float]] = []
    input_index = 1

    if voiceover_path:
        inputs += ["-i", str(voiceover_path)]
        audio_inputs.append((input_index, 1.0))
        input_index += 1

    if music_path:
        inputs += ["-i", str(music_path)]
        audio_inputs.append((input_index, 0.25))

    if len(audio_inputs) == 1:
        idx, volume = audio_inputs[0]
        filter_complex = f"[{idx}:a]volume={volume}[aout]"
    else:
        chains = []
        mix_inputs = []
        for i, volume in audio_inputs:
            name = f"a{i}"
            chains.append(f"[{i}:a]volume={volume}[{name}]")
            mix_inputs.append(f"[{name}]")
        filter_complex = ";".join(chains) + ";" + "".join(mix_inputs) + f"amix=inputs={len(audio_inputs)}:normalize=0[aout]"

    args = [
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-shortest",
        "-c:v",
        "copy",
        "-c:a",
        preset.audio_codec if preset else "aac",
        "-b:a",
        preset.audio_bitrate if preset else "192k",
        str(output_path),
    ]
    run_ffmpeg(args)


def write_srt(subtitle_items: list[dict], output_path: str | Path) -> None:
    def fmt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines: list[str] = []
    for i, item in enumerate(subtitle_items, start=1):
        start = float(item.get("start", 0.0))
        end = float(item.get("end", 0.0))
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        lines.extend([str(i), f"{fmt_time(start)} --> {fmt_time(end)}", text, ""])

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


def burn_subtitles(video_path: str | Path, srt_path: str | Path, output_path: str | Path, preset: ExportPreset) -> None:
    safe_srt = str(srt_path).replace("\\", "/").replace(":", r"\:")
    args = [
        "-i",
        str(video_path),
        "-vf",
        f"subtitles={safe_srt}",
        *preset.to_ffmpeg_args(),
        str(output_path),
    ]
    run_ffmpeg(args)


def extract_thumbnail(video_path: str | Path, output_path: str | Path, timestamp_sec: float = 0.2) -> None:
    args = [
        "-ss",
        f"{timestamp_sec:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    run_ffmpeg(args)
