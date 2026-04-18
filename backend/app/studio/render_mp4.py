"""
MP4 rendering for Creator Studio video projects.

Takes a list of scenes (each with optional image / video / audio) plus a
platform preset and an encode profile, and produces a single MP4 file via
ffmpeg.

Two encode profiles are supported:

- ``mp4_plain``  : balanced size/quality, edit-friendly, universally playable.
- ``mp4_youtube``: matches YouTube's recommended upload spec (H.264 high /
  yuv420p / AAC 48 kHz / faststart) so the file passes ingestion without
  re-mux on YouTube's side.

The renderer is intentionally subprocess-based — no python ffmpeg bindings
are required. It only needs the ``ffmpeg`` and ``ffprobe`` binaries on PATH.

This module is thread-safe: each render writes into its own scratch dir and
final output path. It is also pure-functional with respect to inputs: it
does not mutate scene records, only produces a file at ``output_path``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

# Encode profile labels exposed to callers / wire format.
RenderKind = str  # Literal["mp4_plain", "mp4_youtube"] in routes.

# Platform preset labels (kept in sync with StudioVideo.platformPreset).
PlatformPreset = str  # Literal["youtube_16_9", "shorts_9_16", "slides_16_9"].


@dataclass
class SceneInput:
    """A single scene, normalized for the renderer.

    Either ``image_path`` or ``video_path`` should be provided. If both are
    set, ``video_path`` wins (it is the higher-fidelity asset). If neither
    is set, the scene is rendered as a black frame of ``duration_sec``.

    ``narration`` is the source text used to synthesize subtitles when
    the caller passes ``subtitles="burn_in"`` to :func:`render_scenes`.
    It does not affect rendering when subtitles are off.
    """
    idx: int
    duration_sec: float = 5.0
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    audio_path: Optional[str] = None
    narration: str = ""


@dataclass
class RenderResult:
    """Outcome of a render call."""
    output_path: str
    duration_sec: float
    width: int
    height: int
    profile: str


# ---------------------------------------------------------------------------
# Encode profiles
# ---------------------------------------------------------------------------

def _resolution_for_preset(preset: PlatformPreset) -> tuple[int, int, int]:
    """(width, height, fps) for a platform preset."""
    if preset == "shorts_9_16":
        return (1080, 1920, 30)
    # youtube_16_9 and slides_16_9 share the same canvas.
    return (1920, 1080, 30)


def _encode_args_for_kind(kind: RenderKind, preset: PlatformPreset) -> list[str]:
    """ffmpeg encode arguments for the chosen profile.

    ``mp4_plain``   — ``libx264 medium / crf 20 / yuv420p / aac 128k``
                       Smaller, edit-friendly, plays anywhere.
    ``mp4_youtube`` — ``libx264 slow / crf 18 / high@4.2 / yuv420p /
                       aac 192k @ 48 kHz / +faststart``
                       Matches YouTube's recommended upload spec so the file
                       moves through ingestion without a re-mux.
    """
    if kind == "mp4_youtube":
        return [
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-level", "4.2",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-movflags", "+faststart",
        ]
    # Default: mp4_plain.
    return [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
    ]


# ---------------------------------------------------------------------------
# Tooling availability
# ---------------------------------------------------------------------------

def ffmpeg_available() -> bool:
    """True iff both ``ffmpeg`` and ``ffprobe`` are on PATH."""
    return bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str]) -> None:
    """Run a subprocess, raising RuntimeError with stderr on non-zero exit."""
    logger.debug("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # Keep stderr short — ffmpeg is verbose.
        tail = (proc.stderr or "").strip().splitlines()[-20:]
        raise RuntimeError(
            f"ffmpeg failed (code {proc.returncode}): " + "\n".join(tail)
        )


def _resolve_to_local_path(url_or_path: str, scratch_dir: Path) -> Optional[str]:
    """Best-effort resolve a scene asset URL to a local file path.

    Strategy:
      1. Absolute filesystem path that exists  → return as-is.
      2. ``http(s)://`` URL                    → download into scratch_dir.
      3. Backend-relative ``/files/...`` path  → look up in UPLOAD_DIR.
      4. Anything else                         → None (renderer skips it).
    """
    if not url_or_path:
        return None

    # Already a local path.
    p = Path(url_or_path)
    if p.is_absolute() and p.exists():
        return str(p)

    # Absolute URL: download.
    if url_or_path.startswith(("http://", "https://")):
        try:
            parsed = urllib.parse.urlparse(url_or_path)
            suffix = Path(parsed.path).suffix or ".bin"
            tmp = tempfile.NamedTemporaryFile(
                dir=str(scratch_dir), suffix=suffix, delete=False
            )
            tmp.close()
            with urllib.request.urlopen(url_or_path, timeout=30) as resp, \
                    open(tmp.name, "wb") as out:
                shutil.copyfileobj(resp, out)
            return tmp.name
        except Exception as exc:
            logger.warning("download failed for %s: %s", url_or_path, exc)
            return None

    # Backend-relative /files/... → UPLOAD_DIR.
    if url_or_path.startswith("/files/"):
        try:
            from ..config import UPLOAD_DIR
            rel = url_or_path[len("/files/"):].split("?", 1)[0]
            candidate = Path(UPLOAD_DIR) / rel
            if candidate.exists():
                return str(candidate)
        except Exception:
            pass

    return None


def _per_scene_args(
    scene: SceneInput,
    width: int,
    height: int,
    fps: int,
    scratch: Path,
) -> tuple[list[str], list[str], str]:
    """Build ffmpeg input/filter args for a single scene.

    Returns ``(input_args, filter_complex_args, label)`` where ``label`` is
    the labelled output stream name used by the concat filter downstream.
    """
    inputs: list[str] = []
    filters: list[str] = []

    # Common video-side filter: scale + pad to canvas, fps lock, sar reset.
    vf_chain = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )

    if scene.video_path:
        # Video clip: clamp duration and reformat to canvas.
        inputs += ["-t", f"{scene.duration_sec:.3f}", "-i", scene.video_path]
        filters.append(f"[{scene.idx}:v]{vf_chain}[v{scene.idx}]")
    elif scene.image_path:
        # Still image: loop into a clip of duration.
        inputs += [
            "-loop", "1",
            "-t", f"{scene.duration_sec:.3f}",
            "-i", scene.image_path,
        ]
        filters.append(f"[{scene.idx}:v]{vf_chain}[v{scene.idx}]")
    else:
        # No media: black frame of duration.
        inputs += [
            "-f", "lavfi",
            "-t", f"{scene.duration_sec:.3f}",
            "-i", f"color=c=black:s={width}x{height}:r={fps}",
        ]
        filters.append(f"[{scene.idx}:v]format=yuv420p[v{scene.idx}]")

    return inputs, filters, f"v{scene.idx}"


def _audio_transform_chain(rate: float, pitch: float) -> Optional[str]:
    """Build the ffmpeg audio-filter chain for the chosen rate + pitch.

    Returns None when both are 1.0 (caller skips the transform stage).

    Rate is applied with ``atempo``. Pitch uses the industry-standard
    ``asetrate=48000*pitch, atempo=1/pitch`` compound so the tempo is
    preserved while the pitch shifts. When both are non-unit we stack the
    pitch compound first, then an outer atempo for rate.

    ``atempo`` only accepts 0.5–2.0 per stage; we clamp inputs upstream
    to stay within that range so we never need to chain multiple stages.
    """
    rate = max(0.5, min(2.0, float(rate or 1.0)))
    pitch = max(0.5, min(2.0, float(pitch or 1.0)))
    if rate == 1.0 and pitch == 1.0:
        return None
    parts: list[str] = []
    if pitch != 1.0:
        parts.append(f"asetrate=48000*{pitch:.6f}")
        parts.append(f"atempo={1.0 / pitch:.6f}")
    if rate != 1.0:
        parts.append(f"atempo={rate:.6f}")
    return ",".join(parts)


def _ass_escape(text: str) -> str:
    """Escape a string for embedding inside a libass SRT/ASS cue."""
    return (text or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _srt_timestamp(seconds: float) -> str:
    """Convert seconds to an SRT timestamp (HH:MM:SS,mmm)."""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _split_narration_for_subtitles(text: str, max_chars: int = 42) -> list[str]:
    """Chunk narration into subtitle-sized lines.

    Subtitles read best at ~42 chars/line (YouTube's auto-caption default).
    We split on sentence boundaries first, then on commas when a chunk is
    still too long, falling back to hard-wrap at word boundaries.
    """
    import re
    if not text:
        return []
    # Sentence split on ., !, ?, or newline.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    chunks: list[str] = []
    for s in sentences:
        if len(s) <= max_chars:
            chunks.append(s)
            continue
        # Try splitting on commas first.
        sub = [p.strip() for p in s.split(",") if p.strip()]
        if all(len(p) <= max_chars for p in sub):
            chunks.extend(sub)
            continue
        # Fallback: greedy word-wrap.
        cur = ""
        for word in s.split():
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= max_chars:
                cur = f"{cur} {word}"
            else:
                chunks.append(cur)
                cur = word
        if cur:
            chunks.append(cur)
    return chunks


def _write_srt_for_scene(
    narration: str,
    duration_sec: float,
    srt_path: Path,
    *,
    start_offset: float = 0.0,
) -> bool:
    """Write an SRT file whose cues span [0, duration_sec] for a single scene.

    Returns True on success, False when the narration is empty (no SRT
    should be emitted — and the caller should not try to burn an empty
    subtitle file, which would fail).
    """
    chunks = _split_narration_for_subtitles(narration)
    if not chunks:
        return False
    dur = max(0.5, float(duration_sec or 5.0))
    # Distribute the duration evenly across chunks. Cap per-cue at 5s so
    # slow voices don't hold a single cue on screen forever.
    per = min(dur / len(chunks), 5.0)
    lines: list[str] = []
    for i, chunk in enumerate(chunks):
        start = start_offset + i * per
        end = min(start_offset + dur, start + per)
        if end <= start:
            end = start + 0.1
        lines.append(str(i + 1))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(_ass_escape(chunk))
        lines.append("")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _has_audio(path: str) -> bool:
    """Probe a media file and return True iff it has at least one audio stream."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "json",
                path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout or "{}")
        return bool(data.get("streams"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------

def render_scenes(
    scenes: List[SceneInput],
    *,
    preset: PlatformPreset,
    kind: RenderKind,
    output_path: str,
    on_progress: Optional[Callable[[float], None]] = None,
    audio_rate: float = 1.0,
    audio_pitch: float = 1.0,
    subtitles: str = "none",
) -> RenderResult:
    """Render a list of scenes into a single MP4 at ``output_path``.

    The renderer pre-encodes each scene to a normalized intermediate clip,
    then concatenates the intermediates with ffmpeg's concat demuxer. This
    is slower than a single filter graph but far more robust against scenes
    with very different codecs / resolutions / sample rates / pixel formats.

    Extra knobs:

    - ``audio_rate`` (0.5–2.0, default 1.0): tempo multiplier for the
      narration/audio track. Applied as ffmpeg ``atempo``.
    - ``audio_pitch`` (0.5–2.0, default 1.0): pitch-shift multiplier.
      Implemented via ``asetrate=48000*pitch, atempo=1/pitch`` so the
      output duration is unchanged (tempo is preserved, pitch shifts).
    - ``subtitles`` (``"burn_in"`` | ``"none"``, default ``"none"``):
      when ``burn_in``, each scene's ``narration`` is chunked into an
      SRT file and burned into the video via libass. A sidecar .srt
      is also written next to the MP4 so editors can re-style.
    """
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg/ffprobe not found on PATH. Install ffmpeg to enable MP4 export."
        )
    if not scenes:
        raise ValueError("At least one scene is required.")

    width, height, fps = _resolution_for_preset(preset)
    encode_args = _encode_args_for_kind(kind, preset)
    audio_transform = _audio_transform_chain(audio_rate, audio_pitch)
    burn_subtitles = (subtitles or "none").lower() == "burn_in"

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hp_render_") as scratch_str:
        scratch = Path(scratch_str)
        intermediates: list[Path] = []
        total = len(scenes)

        # Pass 1: pre-encode each scene to a normalized .mp4 in scratch.
        for i, scene in enumerate(scenes):
            # Normalize asset paths into scratch (may download).
            video_local = (
                _resolve_to_local_path(scene.video_path, scratch)
                if scene.video_path else None
            )
            image_local = (
                _resolve_to_local_path(scene.image_path, scratch)
                if scene.image_path and not video_local else None
            )
            audio_local = (
                _resolve_to_local_path(scene.audio_path, scratch)
                if scene.audio_path else None
            )

            normalized = SceneInput(
                idx=0,  # only one input in the per-scene call
                duration_sec=max(0.5, float(scene.duration_sec or 5.0)),
                image_path=image_local,
                video_path=video_local,
                audio_path=audio_local,
                narration=scene.narration,
            )

            inputs, filters, vlabel = _per_scene_args(
                normalized, width, height, fps, scratch
            )

            # If subtitles are burning in, write a per-scene SRT into
            # scratch and append a ``subtitles`` filter to the video chain.
            # ffmpeg's subtitles filter uses libass under the hood. A
            # sidecar .srt is also written next to the final MP4 below.
            if burn_subtitles and scene.narration:
                srt_path = scratch / f"scene_{i:04d}.srt"
                wrote = _write_srt_for_scene(
                    scene.narration,
                    normalized.duration_sec,
                    srt_path,
                )
                if wrote:
                    # Escape the path for ffmpeg's filter-arg parser.
                    esc = str(srt_path).replace("\\", "/").replace(":", r"\:")
                    force_style = (
                        "Fontname=DejaVu Sans,Fontsize=28,"
                        "PrimaryColour=&H00FFFFFF&,"
                        "OutlineColour=&H80000000&,"
                        "BorderStyle=3,Outline=2,Shadow=0,MarginV=48"
                    )
                    # Replace the last video-chain step's output label so
                    # the subtitle filter sits at the end of the pipeline.
                    new_last = (
                        f"[{vlabel}]subtitles='{esc}':"
                        f"force_style='{force_style}'[{vlabel}_sub]"
                    )
                    filters.append(new_last)
                    vlabel = f"{vlabel}_sub"

            # Audio handling: prefer explicit audio_path; otherwise reuse the
            # video's audio track if present; otherwise generate silence so
            # every clip has the same stream layout for the concat demuxer.
            audio_inputs: list[str] = []
            audio_filter: list[str] = []
            audio_label = "a0"
            # Common tail applied to every audio path: resample to 48 kHz
            # stereo + apply the optional rate/pitch transform the caller
            # requested. Consolidating the tail here keeps the three
            # branches below in sync.
            tail = "aresample=48000,aformat=channel_layouts=stereo"
            if audio_transform:
                tail = f"{tail},{audio_transform}"
            if audio_local:
                audio_inputs += ["-i", audio_local]
                # Index 1 is the audio file (after the single video input).
                audio_filter.append(f"[1:a]{tail}[{audio_label}]")
            elif video_local and _has_audio(video_local):
                audio_filter.append(f"[0:a]{tail}[{audio_label}]")
            else:
                audio_inputs += [
                    "-f", "lavfi",
                    "-t", f"{normalized.duration_sec:.3f}",
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                ]
                # Position depends on whether we have an audio input.
                # With no audio_local and no inherent audio, the lavfi anullsrc
                # is the second input (index 1). Pass through directly.
                audio_filter.append(f"[1:a]aformat=channel_layouts=stereo[{audio_label}]")

            filter_complex = ";".join(filters + audio_filter)

            inter_path = scratch / f"scene_{i:04d}.mp4"
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                *inputs,
                *audio_inputs,
                "-filter_complex", filter_complex,
                "-map", f"[{vlabel}]",
                "-map", f"[{audio_label}]",
                "-r", str(fps),
                "-shortest",
                # Intermediates use a fast encode; the final pass re-encodes
                # with the chosen profile to keep the spec consistent.
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                str(inter_path),
            ]
            _run(cmd)
            intermediates.append(inter_path)

            if on_progress:
                # Pass 1 fills 0..80% of the bar.
                on_progress(80.0 * (i + 1) / max(total, 1))

        # Pass 2: concat all intermediates via the concat demuxer.
        list_file = scratch / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{p}'" for p in intermediates) + "\n",
            encoding="utf-8",
        )

        concat_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            *encode_args,
            str(out),
        ]
        _run(concat_cmd)

        # Sidecar SRT: full-video timeline, cue timings chained across
        # scenes. Written whenever burn_subtitles=True, so editors get the
        # same timing they saw burned in. Named <output>.srt.
        if burn_subtitles:
            sidecar = out.with_suffix(".srt")
            running_offset = 0.0
            cue_idx = 1
            lines: list[str] = []
            for s in scenes:
                dur = max(0.5, float(s.duration_sec or 5.0))
                chunks = _split_narration_for_subtitles(s.narration or "")
                if chunks:
                    per = min(dur / len(chunks), 5.0)
                    for j, chunk in enumerate(chunks):
                        start = running_offset + j * per
                        end = min(running_offset + dur, start + per)
                        if end <= start:
                            end = start + 0.1
                        lines.append(str(cue_idx))
                        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
                        lines.append(_ass_escape(chunk))
                        lines.append("")
                        cue_idx += 1
                running_offset += dur
            try:
                sidecar.write_text("\n".join(lines), encoding="utf-8")
            except OSError:
                # Non-fatal — the burned-in subs are still present.
                pass

        if on_progress:
            on_progress(100.0)

    total_duration = sum(max(0.5, float(s.duration_sec or 5.0)) for s in scenes)
    return RenderResult(
        output_path=str(out),
        duration_sec=total_duration,
        width=width,
        height=height,
        profile=kind,
    )
