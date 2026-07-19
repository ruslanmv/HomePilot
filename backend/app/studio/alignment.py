"""
Forced alignment for the essay-to-video pipeline (Batch 2).

Given the essay's existing narration audio and the script-mode scenes (whose
narration is the essay's own sentences, verbatim - Batch 0 guarantees this),
compute where each scene's words actually fall in the audio. Two things fall
out: real per-scene durations (cutting on sentence boundaries, not the flat
5-second default) and word-level timestamps persisted for caption
materialization in the promote-to-project bridge (Batch 4) - no re-run needed.

Two alignment tiers, best available wins:

  whisperx     - word-level timestamps via WhisperX (Whisper + wav2vec2).
                 Heavy optional dependency; imported lazily and only when
                 installed. Env: WHISPERX_MODEL (default large-v3),
                 WHISPERX_DEVICE (default cuda; falls back to cpu).
  proportional - deterministic fallback: total audio duration (ffprobe, or
                 the wave module for WAV) distributed across scenes by word
                 count. No dependencies. Scene boundaries are already
                 sentence boundaries, so cuts stay clean - just less exact.

Alignment is strictly opt-in: no audio URL, no alignment, and the Batch 0
flat-duration behavior is untouched.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class AlignedWord(BaseModel):
    word: str
    start: float
    end: float


class SceneSpan(BaseModel):
    scene_number: int
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


class AlignmentResult(BaseModel):
    ok: bool
    method: str = ""                      # "whisperx" | "proportional"
    audio_duration_sec: float = 0.0
    words: List[AlignedWord] = Field(default_factory=list)
    scene_spans: List[SceneSpan] = Field(default_factory=list)
    message: str = ""


# ── Audio helpers ────────────────────────────────────────────────────────────

def fetch_audio(url_or_path: str, timeout: float = 60.0) -> str:
    """Return a local file path for the audio, downloading if it's a URL.

    Local filesystem paths are refused unless STUDIO_ALLOW_LOCAL_AUDIO=true:
    existing_audio_url is API-supplied, and quietly reading server paths from
    it would be an SSRF-style hole in multi-user deployments. Single-user
    installs that want to point at local files opt in explicitly."""
    if not url_or_path.startswith(("http://", "https://")):
        allow_local = os.getenv("STUDIO_ALLOW_LOCAL_AUDIO", "false").strip().lower() in (
            "1", "true", "yes")
        if not allow_local:
            raise PermissionError(
                "Local audio paths are disabled (set STUDIO_ALLOW_LOCAL_AUDIO=true "
                "on trusted single-user installs); pass an http(s) URL instead.")
        if not Path(url_or_path).is_file():
            raise FileNotFoundError(url_or_path)
        return url_or_path

    import httpx

    suffix = Path(url_or_path.split("?", 1)[0]).suffix or ".mp3"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="essay-audio-")
    os.close(fd)
    with httpx.stream("GET", url_or_path, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    return path


def audio_duration_sec(path: str) -> Optional[float]:
    """Duration via ffprobe, falling back to the wave module for WAV files."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", path],
                capture_output=True, check=True, timeout=30,
            )
            dur = float(json.loads(out.stdout).get("format", {}).get("duration", 0))
            if dur > 0:
                return dur
        except Exception:
            pass
    if path.lower().endswith(".wav"):
        try:
            with wave.open(path, "rb") as wf:
                return wf.getnframes() / float(wf.getframerate())
        except Exception:
            pass
    return None


# ── WhisperX tier ────────────────────────────────────────────────────────────

def whisperx_available() -> bool:
    try:
        import whisperx  # noqa: F401
        return True
    except Exception:
        return False


def _whisperx_words(audio_path: str) -> List[AlignedWord]:
    """Transcribe + align, returning word-level timestamps."""
    import whisperx

    device = os.getenv("WHISPERX_DEVICE", "cuda").strip() or "cuda"
    model_name = os.getenv("WHISPERX_MODEL", "large-v3").strip() or "large-v3"

    try:
        model = whisperx.load_model(model_name, device)
    except Exception:
        device = "cpu"
        model = whisperx.load_model(model_name, device, compute_type="int8")

    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio)
    align_model, align_meta = whisperx.load_align_model(
        language_code=result["language"], device=device)
    aligned = whisperx.align(result["segments"], align_model, align_meta,
                             audio, device)

    words: List[AlignedWord] = []
    for seg in aligned.get("word_segments", []):
        w = str(seg.get("word", "")).strip()
        if w and seg.get("start") is not None and seg.get("end") is not None:
            words.append(AlignedWord(word=w, start=float(seg["start"]),
                                     end=float(seg["end"])))
    return words


# ── Scene span mapping ───────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[\w']+")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _spans_from_words(scenes: List[dict], words: List[AlignedWord],
                      audio_duration: float) -> List[SceneSpan]:
    """
    Map scenes onto the aligned word list by cumulative word position.

    The narration is the same text the audio narrates (Batch 0's verbatim
    guarantee), but the transcript may differ slightly (numbers, hyphens),
    so exact token matching is brittle. Cumulative-proportional indexing
    into the *aligned* word list keeps boundaries on real word timestamps
    while tolerating small transcription drift.
    """
    counts = [max(1, _word_count(s.get("narration", ""))) for s in scenes]
    total = sum(counts)
    n_words = len(words)

    spans: List[SceneSpan] = []
    cursor = 0
    consumed = 0
    for i, scene in enumerate(scenes):
        consumed += counts[i]
        end_idx = min(n_words - 1, round(consumed / total * n_words) - 1)
        start_sec = words[cursor].start if cursor < n_words else audio_duration
        end_sec = words[end_idx].end if end_idx >= cursor else start_sec
        if i == len(scenes) - 1:
            end_sec = max(end_sec, audio_duration)
        spans.append(SceneSpan(scene_number=scene.get("scene_number", i + 1),
                               start_sec=round(start_sec, 3),
                               end_sec=round(end_sec, 3)))
        cursor = min(n_words - 1, end_idx + 1)
    return spans


def _spans_proportional(scenes: List[dict], audio_duration: float) -> List[SceneSpan]:
    counts = [max(1, _word_count(s.get("narration", ""))) for s in scenes]
    total = sum(counts)
    spans: List[SceneSpan] = []
    t = 0.0
    for i, scene in enumerate(scenes):
        dur = audio_duration * counts[i] / total
        end = audio_duration if i == len(scenes) - 1 else t + dur
        spans.append(SceneSpan(scene_number=scene.get("scene_number", i + 1),
                               start_sec=round(t, 3), end_sec=round(end, 3)))
        t = end
    return spans


# ── Entry points ─────────────────────────────────────────────────────────────

def align_scenes(audio_path: str, scenes: List[dict]) -> AlignmentResult:
    """Align scenes against a local audio file. Never raises for missing
    optional dependencies - degrades to the proportional tier."""
    duration = audio_duration_sec(audio_path)
    if not duration or duration <= 0:
        return AlignmentResult(ok=False, message="Could not determine audio duration "
                                                 "(is ffprobe installed?)")

    if whisperx_available():
        try:
            words = _whisperx_words(audio_path)
            if words:
                return AlignmentResult(
                    ok=True, method="whisperx", audio_duration_sec=duration,
                    words=words, scene_spans=_spans_from_words(scenes, words, duration),
                )
        except Exception as e:
            print(f"[Alignment] whisperx failed ({e}); falling back to proportional")

    return AlignmentResult(
        ok=True, method="proportional", audio_duration_sec=duration,
        scene_spans=_spans_proportional(scenes, duration),
    )


def align_from_url(audio_url: str, scenes: List[dict]) -> AlignmentResult:
    """Fetch audio (if remote) and align. Cleans up its own temp download."""
    path = fetch_audio(audio_url)
    is_temp = path != audio_url
    try:
        return align_scenes(path, scenes)
    finally:
        if is_temp:
            try:
                os.unlink(path)
            except OSError:
                pass


class CaptionCue(BaseModel):
    start_sec: float
    end_sec: float
    text: str


def caption_cues(result: AlignmentResult, scenes: List[dict],
                 max_chars: int = 42) -> List[CaptionCue]:
    """
    Build caption cues from a persisted AlignmentResult - the data source
    for CaptionSegment rows in promote-to-project (Batch 4), with no
    re-run of alignment.

    whisperx tier: group aligned words into <= max_chars cues on real word
    timestamps. proportional tier: chunk each scene's narration and spread
    the chunks evenly across the scene's span.
    """
    cues: List[CaptionCue] = []

    if result.words:
        line: List[str] = []
        start = result.words[0].start
        for w in result.words:
            probe = " ".join(line + [w.word])
            if line and len(probe) > max_chars:
                cues.append(CaptionCue(start_sec=round(start, 3),
                                       end_sec=round(w.start, 3),
                                       text=" ".join(line)))
                line, start = [w.word], w.start
            else:
                line.append(w.word)
        if line:
            cues.append(CaptionCue(start_sec=round(start, 3),
                                   end_sec=round(result.words[-1].end, 3),
                                   text=" ".join(line)))
        return cues

    by_number = {sp.scene_number: sp for sp in result.scene_spans}
    for i, scene in enumerate(scenes):
        span = by_number.get(scene.get("scene_number", i + 1))
        text = (scene.get("narration") or "").strip()
        if not span or not text:
            continue
        words = text.split()
        chunks: List[str] = []
        line: List[str] = []
        for w in words:
            if line and len(" ".join(line + [w])) > max_chars:
                chunks.append(" ".join(line))
                line = [w]
            else:
                line.append(w)
        if line:
            chunks.append(" ".join(line))
        step = span.duration_sec / max(1, len(chunks))
        for j, chunk in enumerate(chunks):
            cues.append(CaptionCue(
                start_sec=round(span.start_sec + j * step, 3),
                end_sec=round(span.start_sec + (j + 1) * step, 3),
                text=chunk))
    return cues


def apply_spans_to_scenes(scenes: List[dict], result: AlignmentResult) -> int:
    """Write real durations (and audio offsets, for Batch 4 caption/audio
    slicing) into outline scene dicts. Returns how many scenes were updated."""
    by_number = {sp.scene_number: sp for sp in result.scene_spans}
    updated = 0
    for i, scene in enumerate(scenes):
        span = by_number.get(scene.get("scene_number", i + 1))
        if not span or span.duration_sec <= 0:
            continue
        scene["duration_sec"] = round(span.duration_sec, 3)
        scene["audio_start_sec"] = span.start_sec
        scene["audio_end_sec"] = span.end_sec
        updated += 1
    return updated
