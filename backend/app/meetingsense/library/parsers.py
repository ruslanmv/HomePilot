"""Reading transcripts people bring in — SRT, WebVTT, plain text / Markdown, JSON.

Each parser returns a :class:`Parsed` with the segments it found and *how much it knows*:
``timing`` is ``imported`` when the file carried timestamps and ``none`` when it did not. A
transcript without times is still a transcript — it is stored, searched and summarised — but
nothing pretends its lines happened at a particular second.

Speakers are kept exactly as written. Nothing here invents a name for an unlabelled line.

An empty result is reported as empty. A JSON file whose ``Result_info`` is ``[]`` (an
Insta360 export with no recognised speech) parses to zero segments and the importer says
"Needs transcription" — never "Transcribed".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

Segment = Dict[str, Any]

TEXT_EXTENSIONS = (".txt", ".md", ".markdown")
TRANSCRIPT_EXTENSIONS = (".srt", ".vtt", ".json") + TEXT_EXTENSIONS


@dataclass
class Parsed:
    segments: List[Segment] = field(default_factory=list)
    timing: str = "none"  # "imported" when times came from the file
    format: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return any((s.get("text") or "").strip() for s in self.segments)


_TS = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?")


def parse_timestamp(value: str) -> Optional[int]:
    """``01:02:03,456`` / ``02:03.4`` / ``1:02:03`` → milliseconds, or None."""
    m = _TS.fullmatch(value.strip())
    if not m:
        return None
    h, mi, s, frac = m.groups()
    ms = int((frac or "0").ljust(3, "0")[:3])
    return ((int(h or 0) * 60 + int(mi)) * 60 + int(s)) * 1000 + ms


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)  # VTT voice/style tags
    return re.sub(r"\s+", " ", text).strip()


_SPEAKER_PREFIX = re.compile(r"^([A-Z][\w .'\-]{0,40}?|Speaker\s*\d+|SPEAKER_\d+)\s*:\s+(.+)$")


def _split_speaker(text: str):
    m = _SPEAKER_PREFIX.match(text)
    if m and len(m.group(1).split()) <= 4:
        return m.group(1).strip(), m.group(2).strip()
    return None, text


def parse_srt(raw: str) -> Parsed:
    out = Parsed(format="srt", timing="imported")
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n").strip())
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start, _, end = lines[0].partition("-->")
        t0 = parse_timestamp(start)
        t1 = parse_timestamp(end.split()[0] if end.split() else "")
        text = _clean(" ".join(lines[1:]))
        if t0 is None or not text:
            continue
        speaker, text = _split_speaker(text)
        out.segments.append({"t0_ms": t0, "t1_ms": t1, "speaker": speaker, "text": text, "conf": None})
    return out


def parse_vtt(raw: str) -> Parsed:
    out = Parsed(format="vtt", timing="imported")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        start, _, rest = lines[idx].partition("-->")
        t0 = parse_timestamp(start)
        t1 = parse_timestamp(rest.split()[0] if rest.split() else "")
        body = " ".join(lines[idx + 1:])
        voice = re.match(r"<v(?:\.[\w.]+)?\s+([^>]+)>", body)
        speaker = voice.group(1).strip() if voice else None
        body = _clean(body)
        if not speaker:
            speaker, body = _split_speaker(body)
        if t0 is None or not body:
            continue
        out.segments.append({"t0_ms": t0, "t1_ms": t1, "speaker": speaker, "text": body, "conf": None})
    return out


# "[00:01:23] Alice: hello", "00:01:23 - Alice: hello", "Alice (01:23): hello", "(01:23) hello"
_LINE_TIMED = (
    re.compile(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]?\s*[-–—]?\s*(.*)$"),
    re.compile(r"^(.{1,40}?)\s*[\[(](\d{1,2}:\d{2}(?::\d{2})?)[\])]\s*:?\s*(.*)$"),
)


def parse_text(raw: str, *, fmt: str = "txt") -> Parsed:
    """Plain text or Markdown. Timestamps at the start of a line are read; others are not."""
    out = Parsed(format=fmt)
    timed = 0
    paragraph: List[str] = []

    def flush():
        if paragraph:
            text = _clean(" ".join(paragraph))
            if text:
                speaker, text = _split_speaker(text)
                out.segments.append({"t0_ms": 0, "t1_ms": None, "speaker": speaker, "text": text, "conf": None})
            paragraph.clear()

    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if fmt in ("md", "markdown"):
            stripped = re.sub(r"^(#{1,6}\s+|[-*+]\s+|>\s+)", "", stripped)
            stripped = stripped.replace("**", "").replace("__", "")
        if not stripped:
            flush()
            continue
        m = _LINE_TIMED[0].match(stripped)
        if m and parse_timestamp(m.group(1)) is not None and m.group(2).strip():
            flush()
            speaker, text = _split_speaker(_clean(m.group(2)))
            out.segments.append({"t0_ms": parse_timestamp(m.group(1)), "t1_ms": None,
                                 "speaker": speaker, "text": text, "conf": None})
            timed += 1
            continue
        m = _LINE_TIMED[1].match(stripped)
        if m and parse_timestamp(m.group(2)) is not None and m.group(3).strip():
            flush()
            out.segments.append({"t0_ms": parse_timestamp(m.group(2)), "t1_ms": None,
                                 "speaker": m.group(1).strip(), "text": _clean(m.group(3)), "conf": None})
            timed += 1
            continue
        paragraph.append(stripped)
    flush()
    if timed and timed >= max(1, len(out.segments) // 2):
        out.timing = "imported"
        _fill_ends(out.segments)
    return out


def _fill_ends(segments: List[Segment]) -> None:
    """An end is the next start when the file only gave starts. Last one stays unknown."""
    for cur, nxt in zip(segments, segments[1:]):
        if cur.get("t1_ms") is None and nxt.get("t0_ms") is not None and nxt["t0_ms"] >= cur["t0_ms"]:
            cur["t1_ms"] = nxt["t0_ms"]


def _num_ms(value: Any, *, seconds: bool) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        ts = parse_timestamp(value)
        if ts is not None:
            return ts
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return int(round(value * 1000)) if seconds else int(round(value))
    return None


_TEXT_KEYS = ("text", "content", "sentence", "transcript", "onebest", "words_text")
_START_KEYS = ("start", "begin", "bg", "start_time", "startTime", "t0", "from", "offset")
_END_KEYS = ("end", "ed", "end_time", "endTime", "t1", "to")
_SPEAKER_KEYS = ("speaker", "spk", "speaker_name", "speakerName", "speaker_id", "role", "name")


def _looks_seconds(items: List[Dict[str, Any]], key: str) -> bool:
    """Whisper writes seconds (floats); many exporters write milliseconds (big ints)."""
    values = [i.get(key) for i in items if isinstance(i.get(key), (int, float))]
    if not values:
        return True
    if any(isinstance(v, float) and not float(v).is_integer() for v in values):
        return True
    return max(values) < 36_000  # under ten hours if read as seconds


def _segments_from_items(items: Iterable[Any]) -> List[Segment]:
    items = [i for i in items if isinstance(i, dict)]
    if not items:
        return []
    start_key = next((k for k in _START_KEYS if any(k in i for i in items)), None)
    end_key = next((k for k in _END_KEYS if any(k in i for i in items)), None)
    seconds = _looks_seconds(items, start_key) if start_key else True
    out: List[Segment] = []
    for item in items:
        text = next((item[k] for k in _TEXT_KEYS if isinstance(item.get(k), str) and item[k].strip()), "")
        if not text and isinstance(item.get("words"), list):
            text = " ".join(str(w.get("word") or w.get("text") or "") for w in item["words"] if isinstance(w, dict))
        text = _clean(text)
        if not text:
            continue
        speaker = next((str(item[k]).strip() for k in _SPEAKER_KEYS if item.get(k) not in (None, "")), None)
        out.append({
            "t0_ms": _num_ms(item.get(start_key), seconds=seconds) if start_key else None,
            "t1_ms": _num_ms(item.get(end_key), seconds=seconds) if end_key else None,
            "speaker": speaker,
            "text": text,
            "conf": item.get("confidence") if isinstance(item.get("confidence"), (int, float)) else None,
        })
    return out


def parse_json(raw: str) -> Parsed:
    out = Parsed(format="json")
    try:
        body = json.loads(raw)
    except ValueError:
        out.warnings.append("The JSON file could not be read.")
        return out
    items: Any = None
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        # Whisper verbose_json, generic {segments|utterances|transcript}, Insta360 AIRecord.
        for key in ("segments", "utterances", "transcript", "results", "Result_info", "result_info", "sentences"):
            value = body.get(key)
            if isinstance(value, list):
                items = value
                break
            if isinstance(value, dict) and isinstance(value.get("segments"), list):
                items = value["segments"]
                break
        if items is None and isinstance(body.get("text"), str) and body["text"].strip():
            out.segments = [{"t0_ms": 0, "t1_ms": None, "speaker": None, "text": _clean(body["text"]), "conf": None}]
            return out
    if items is None:
        out.warnings.append("No transcript was found in the JSON file.")
        return out
    segments = _segments_from_items(items)
    if segments and all(s["t0_ms"] is not None for s in segments):
        out.timing = "imported"
        _fill_ends(segments)
    for s in segments:
        if s["t0_ms"] is None:
            s["t0_ms"] = 0
    out.segments = segments
    return out


def parse_transcript(name: str, raw: bytes) -> Parsed:
    """Pick a parser by extension (the content is text in every case)."""
    text = raw.decode("utf-8-sig", errors="replace")
    lower = name.lower()
    if lower.endswith(".srt"):
        return parse_srt(text)
    if lower.endswith(".vtt"):
        return parse_vtt(text)
    if lower.endswith(".json"):
        return parse_json(text)
    if lower.endswith((".md", ".markdown")):
        return parse_text(text, fmt="md")
    return parse_text(text, fmt="txt")


def monotonic(segments: List[Segment]) -> List[Segment]:
    """Sort by start and clamp ends that run backwards; keeps every line."""
    ordered = sorted(segments, key=lambda s: (int(s.get("t0_ms") or 0)))
    for seg in ordered:
        if seg.get("t1_ms") is not None and seg["t1_ms"] < seg["t0_ms"]:
            seg["t1_ms"] = seg["t0_ms"]
    return ordered
