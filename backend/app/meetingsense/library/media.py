"""Audio helpers for imported meetings — probing, silence detection, decoding, waveforms.

FFmpeg does the decoding (HomePilot already needs it for Creator Studio), always on a copy
the library owns and never on the source file. Every call has a timeout and none of them
raises into a request: a file FFmpeg cannot read is reported as unreadable, which is an
answer the import preview can show.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".ogg", ".oga", ".opus", ".flac", ".webm", ".aac", ".mp4")

#: Content signatures — the extension is a hint, these are the check.
_MAGIC = (
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\xff\xf3", "audio/mpeg"),
    (b"\xff\xf2", "audio/mpeg"),
    (b"OggS", "audio/ogg"),
    (b"fLaC", "audio/flac"),
    (b"\x1a\x45\xdf\xa3", "audio/webm"),
)

#: Loudest moment below this means nobody spoke: a recorder left on in a quiet room, or a
#: file that is technically audio and contains nothing. Not transcribed; reported as such.
SILENCE_MAX_DB = -55.0


def sniff_audio(head: bytes) -> Optional[str]:
    """The audio MIME type a file's first bytes prove, or None."""
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[4:8] == b"ftyp":
        return "audio/mp4"
    if len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xF6) == 0xF0:
        return "audio/aac"
    return None


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(args: List[str], *, timeout: float, input_bytes: Optional[bytes] = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout, check=False)


def probe(path: Path) -> Dict[str, Any]:
    """Duration, codec, rate and channels as FFprobe measures them (not as metadata claims)."""
    if not shutil.which("ffprobe"):
        return {"ok": False, "error": "FFmpeg is not installed on this computer."}
    try:
        res = _run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration,bit_rate:stream=codec_type,codec_name,sample_rate,channels",
             "-of", "json", str(path)],
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"Could not read the audio ({type(exc).__name__})."}
    if res.returncode != 0:
        return {"ok": False, "error": "This file is not audio FFmpeg can read."}
    try:
        body = json.loads(res.stdout or b"{}")
    except ValueError:
        return {"ok": False, "error": "This file is not audio FFmpeg can read."}
    streams = [s for s in body.get("streams") or [] if s.get("codec_type") == "audio"]
    if not streams:
        return {"ok": False, "error": "The file has no audio track."}
    stream = streams[0]
    try:
        duration_ms = int(round(float((body.get("format") or {}).get("duration") or 0) * 1000))
    except ValueError:
        duration_ms = 0
    return {
        "ok": True,
        "duration_ms": duration_ms,
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate") or 0) or None,
        "channels": stream.get("channels"),
    }


def loudness(path: Path) -> Dict[str, Optional[float]]:
    """Mean and peak level in dB (FFmpeg ``volumedetect``)."""
    if not shutil.which("ffmpeg"):
        return {"mean_db": None, "max_db": None}
    try:
        res = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect",
                    "-vn", "-f", "null", "-"], timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return {"mean_db": None, "max_db": None}
    text = (res.stderr or b"").decode("utf-8", errors="replace")

    def grab(key: str) -> Optional[float]:
        for line in text.splitlines():
            if f"{key}:" in line:
                try:
                    return float(line.split(f"{key}:")[1].strip().split()[0])
                except (IndexError, ValueError):
                    return None
        return None

    return {"mean_db": grab("mean_volume"), "max_db": grab("max_volume")}


def is_silent(level: Dict[str, Optional[float]]) -> bool:
    peak = level.get("max_db")
    return peak is not None and peak < SILENCE_MAX_DB


def decode_chunk(path: Path, *, start_s: float, length_s: float) -> bytes:
    """One stretch of the recording as 16 kHz mono 16-bit WAV — what speech models expect.

    Resampled from the library's copy; the original file is never rewritten.
    """
    res = _run(
        ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-ss", f"{max(0.0, start_s):.3f}",
         "-t", f"{max(0.1, length_s):.3f}", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
         "-sample_fmt", "s16", "-f", "wav", "-"],
        timeout=max(120.0, length_s * 2),
    )
    if res.returncode != 0:
        raise RuntimeError((res.stderr or b"").decode("utf-8", errors="replace").strip()[:300] or "decode failed")
    return res.stdout


def peaks(path: Path, *, bars: int = 400) -> List[float]:
    """A waveform: ``bars`` values 0..1 from 8 kHz mono PCM. Empty when it cannot be read."""
    if not shutil.which("ffmpeg"):
        return []
    try:
        res = _run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(path), "-vn",
                    "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return []
    data = res.stdout or b""
    count = len(data) // 2
    if res.returncode != 0 or count == 0:
        return []
    import array  # noqa: PLC0415

    samples = array.array("h")
    samples.frombytes(data[: count * 2])
    if sys.byteorder == "big":  # pragma: no cover — little-endian PCM from FFmpeg
        samples.byteswap()
    step = max(1, count // bars)
    out: List[float] = []
    for i in range(0, count, step):
        window = samples[i:i + step]
        if not window:
            break
        out.append(max(abs(min(window)), abs(max(window))) / 32768.0)
        if len(out) >= bars:
            break
    top = max(out) if out else 0.0
    # Normalised for display, but a silent file stays flat rather than being blown up to noise.
    if top > 0.02:
        out = [round(v / top, 3) for v in out]
    else:
        out = [round(v, 3) for v in out]
    return out
