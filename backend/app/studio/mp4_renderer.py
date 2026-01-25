# backend/app/studio/mp4_renderer.py
"""
MP4 renderer using FFmpeg.
Creates YouTube-ready MP4 files from project scenes.
"""
import os
import re
import json
import time
import shutil
import subprocess
from typing import Any, Dict, Optional, List
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont

from .models import ProjectScene, CaptionSegment, AudioTrack


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_")
    return name or "file"


def _url_to_local_path(url: str, upload_dir: str) -> Optional[str]:
    """
    Map /files/... URLs back to filesystem path under UPLOAD_DIR.
    Your backend mounts StaticFiles at /files with directory=UPLOAD_PATH.
    """
    if not url:
        return None
    if url.startswith("/files/"):
        rel = url[len("/files/"):]
        return os.path.join(upload_dir, rel)
    return None


def _download_to(path: str, url: str, timeout: int = 30) -> None:
    ensure_dir(os.path.dirname(path))
    r = requests.get(url, stream=True, timeout=timeout)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)


def _resolve_image(scene: ProjectScene, tmp_dir: str, upload_dir: str) -> str:
    """
    Returns a local PNG path.
    If scene.imageUrl is local (/files/...) -> read from disk.
    If remote -> download.
    If missing -> generate placeholder.
    """
    out_png = os.path.join(tmp_dir, f"scene_{scene.idx:04d}.png")

    # Prefer imageUrl if provided
    if scene.imageUrl:
        local = _url_to_local_path(scene.imageUrl, upload_dir)
        if local and os.path.exists(local):
            # Convert to PNG if needed
            img = Image.open(local).convert("RGB")
            img.save(out_png, "PNG")
            return out_png

        parsed = urlparse(scene.imageUrl)
        if parsed.scheme in ("http", "https"):
            # download
            dl_path = os.path.join(tmp_dir, f"dl_{scene.idx:04d}_{_safe_filename(os.path.basename(parsed.path))}")
            _download_to(dl_path, scene.imageUrl)
            img = Image.open(dl_path).convert("RGB")
            img.save(out_png, "PNG")
            return out_png

    # Placeholder (no image)
    img = Image.new("RGB", (1280, 720), color=(18, 18, 18))
    draw = ImageDraw.Draw(img)
    title = f"Scene {scene.idx + 1}"
    body = (scene.narration or "").strip()

    # basic font fallback
    try:
        font_title = ImageFont.truetype("DejaVuSans.ttf", 48)
        font_body = ImageFont.truetype("DejaVuSans.ttf", 28)
    except Exception:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()

    draw.text((60, 60), title, fill=(220, 220, 220), font=font_title)
    if body:
        draw.text((60, 140), body[:900], fill=(180, 180, 180), font=font_body)
    img.save(out_png, "PNG")
    return out_png


def _write_srt(captions: List[CaptionSegment], out_path: str) -> None:
    def fmt(t: float) -> str:
        # SRT: HH:MM:SS,mmm
        ms = int(round(t * 1000))
        hh = ms // 3600000
        ms -= hh * 3600000
        mm = ms // 60000
        ms -= mm * 60000
        ss = ms // 1000
        ms -= ss * 1000
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

    ensure_dir(os.path.dirname(out_path))
    with open(out_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(captions, start=1):
            f.write(f"{i}\n")
            f.write(f"{fmt(c.startSec)} --> {fmt(c.endSec)}\n")
            f.write((c.text or "").replace("\r", "").strip() + "\n\n")


def _ffmpeg_run(args: List[str], log_path: str) -> None:
    ensure_dir(os.path.dirname(log_path))
    with open(log_path, "a", encoding="utf-8") as log:
        log.write("\n\n=== FFmpeg ===\n")
        log.write(" ".join(args) + "\n")
        proc = subprocess.run(args, stdout=log, stderr=log)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (code={proc.returncode}). See log: {log_path}")


def _make_scene_segment(
    *,
    png_path: str,
    out_mp4: str,
    duration: float,
    width: int,
    height: int,
    fps: int,
    log_path: str,
) -> None:
    # Keep aspect ratio, pad to final
    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    args = [
        _which("ffmpeg") or "ffmpeg",
        "-y",
        "-loop", "1",
        "-t", f"{max(duration, 0.1):.3f}",
        "-i", png_path,
        "-r", str(fps),
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        out_mp4,
    ]
    _ffmpeg_run(args, log_path)


def _concat_segments(segment_paths: List[str], out_path: str, log_path: str) -> None:
    concat_txt = os.path.join(os.path.dirname(out_path), "concat.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")

    args = [
        _which("ffmpeg") or "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_txt,
        "-c", "copy",
        out_path,
    ]
    _ffmpeg_run(args, log_path)


def _mix_audio(
    *,
    video_in: str,
    voice_path: Optional[str],
    music_path: Optional[str],
    out_path: str,
    log_path: str,
) -> None:
    """
    MVP audio:
    - if no audio at all -> add silent track
    - if voice only -> voice
    - if music only -> music
    - if both -> simple amix with music lowered
    """
    ffmpeg = _which("ffmpeg") or "ffmpeg"

    if not voice_path and not music_path:
        args = [
            ffmpeg, "-y",
            "-i", video_in,
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-shortest",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            out_path,
        ]
        _ffmpeg_run(args, log_path)
        return

    inputs = [ffmpeg, "-y", "-i", video_in]
    filter_complex = None
    map_audio = None

    if voice_path:
        inputs += ["-i", voice_path]
    if music_path:
        inputs += ["-i", music_path]

    if voice_path and music_path:
        # voice is input 1:a, music is input 2:a
        filter_complex = "[2:a]volume=0.15[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]"
        map_audio = ["-map", "0:v:0", "-map", "[a]"]
    elif voice_path:
        map_audio = ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        map_audio = ["-map", "0:v:0", "-map", "1:a:0"]

    args = inputs
    if filter_complex:
        args += ["-filter_complex", filter_complex]
    args += (map_audio or [])
    args += ["-shortest", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out_path]
    _ffmpeg_run(args, log_path)


def _burn_captions(video_in: str, srt_path: str, out_path: str, log_path: str) -> None:
    ffmpeg = _which("ffmpeg") or "ffmpeg"
    # Escape special characters in path for FFmpeg subtitles filter
    escaped_srt = srt_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    vf = f"subtitles='{escaped_srt}':force_style='Fontsize=28,Outline=2,Shadow=1,MarginV=20'"
    args = [
        ffmpeg, "-y",
        "-i", video_in,
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        out_path,
    ]
    _ffmpeg_run(args, log_path)


def _make_thumbnail(video_in: str, out_jpg: str, log_path: str) -> None:
    ffmpeg = _which("ffmpeg") or "ffmpeg"
    args = [
        ffmpeg, "-y",
        "-ss", "1.0",
        "-i", video_in,
        "-vframes", "1",
        "-q:v", "3",
        out_jpg,
    ]
    _ffmpeg_run(args, log_path)


def render_project_to_mp4(
    *,
    project_id: str,
    scenes: List[ProjectScene],
    captions: List[CaptionSegment],
    audio_tracks: List[AudioTrack],
    out_dir: str,
    upload_dir: str,
    width: int,
    height: int,
    fps: int,
    burn_in_captions: bool = True,
) -> Dict[str, str]:
    """
    Returns paths:
      - mp4_path
      - log_path
      - thumb_path (optional)
      - srt_path (optional)
    """
    if not _which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH. Install ffmpeg to enable MP4 export.")

    ensure_dir(out_dir)
    tmp_dir = os.path.join(out_dir, "_tmp")
    ensure_dir(tmp_dir)

    log_path = os.path.join(out_dir, "render.log")
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("HomePilot MP4 render\n")
        log.write(f"project_id={project_id}\n")
        log.write(f"ts={time.time()}\n")
        log.write(f"settings={json.dumps({'width': width, 'height': height, 'fps': fps})}\n")

    # 1) Build segments
    segment_paths: List[str] = []
    for s in sorted(scenes, key=lambda x: x.idx):
        png = _resolve_image(s, tmp_dir, upload_dir)
        seg = os.path.join(tmp_dir, f"seg_{s.idx:04d}.mp4")
        _make_scene_segment(
            png_path=png,
            out_mp4=seg,
            duration=float(max(s.durationSec or 5.0, 0.5)),
            width=width,
            height=height,
            fps=fps,
            log_path=log_path,
        )
        segment_paths.append(seg)

    # 2) Concat (video only)
    video_no_audio = os.path.join(out_dir, "video_no_audio.mp4")
    _concat_segments(segment_paths, video_no_audio, log_path)

    # 3) Resolve audio track paths (MVP: first voiceover + first music)
    voice_path = None
    music_path = None
    for t in audio_tracks:
        if t.kind == "voiceover" and not voice_path:
            voice_path = _url_to_local_path(t.url or "", upload_dir)
        if t.kind == "music" and not music_path:
            music_path = _url_to_local_path(t.url or "", upload_dir)

    # 4) Mix/attach audio
    video_with_audio = os.path.join(out_dir, "video_with_audio.mp4")
    _mix_audio(video_in=video_no_audio, voice_path=voice_path, music_path=music_path, out_path=video_with_audio, log_path=log_path)

    # 5) Captions
    srt_path = None
    final_mp4 = os.path.join(out_dir, "output.mp4")
    if captions:
        srt_path = os.path.join(out_dir, "captions.srt")
        _write_srt(captions, srt_path)
        if burn_in_captions:
            _burn_captions(video_with_audio, srt_path, final_mp4, log_path)
        else:
            shutil.copyfile(video_with_audio, final_mp4)
    else:
        shutil.copyfile(video_with_audio, final_mp4)

    # 6) Thumbnail
    thumb_path = os.path.join(out_dir, "thumb.jpg")
    try:
        _make_thumbnail(final_mp4, thumb_path, log_path)
    except Exception:
        thumb_path = ""

    return {
        "mp4_path": final_mp4,
        "log_path": log_path,
        "thumb_path": thumb_path,
        "srt_path": srt_path or "",
    }
