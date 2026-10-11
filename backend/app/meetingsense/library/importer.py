"""Importing recordings and transcripts into the library — preview first, then commit.

Preview looks at everything and changes nothing: which meetings the files contain, how long
the audio really is, whether a transcript is usable, whether the recording is silent, whether
it is already in the library, and whether it belongs to a meeting scheduled for that time.
Commit does what the person confirmed, once — repeating it with the same idempotency key
returns the first result instead of importing twice.

Imported files are **copied** into HomePilot's own storage. Sources are read, never written.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import db, media, parsers
from .adapters import Candidate, discover
from .config import load_library_config, media_root

#: How far apart a recording and a scheduled meeting can start and still be proposed as the
#: same meeting. Ambiguous matches are offered, never applied without a confirmation.
MATCH_WINDOW_S = 45 * 60
#: Loudness is measured during preview only for recordings up to this long; longer ones are
#: checked by the transcription job, so a preview of a three-hour file stays quick.
PREVIEW_LOUDNESS_MAX_MS = 20 * 60 * 1000

_SOURCE_LABELS = {"airecord": "Insta360 / AIRecord", "audio": "Audio upload", "transcript": "Transcript"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iso(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else None


def scheduled_matches(started_at: Optional[float], *, exclude: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Scheduled meetings still waiting for a recording that start near ``started_at``."""
    if not started_at:
        return []
    con = db._connect()
    try:
        rows = con.execute(
            "SELECT e.meeting_id, e.scheduled_for, m.title FROM ms_library_entries e"
            " JOIN ms_meetings m ON m.id = e.meeting_id"
            " WHERE e.recording_state = 'awaiting' AND e.scheduled_for IS NOT NULL AND e.hidden_at IS NULL"
            " AND ABS(e.scheduled_for - ?) <= ? ORDER BY ABS(e.scheduled_for - ?) ASC",
            (started_at, MATCH_WINDOW_S, started_at),
        ).fetchall()
    finally:
        con.close()
    return [{"meeting_id": r["meeting_id"], "title": r["title"], "scheduled_for": r["scheduled_for"],
             "minutes_apart": round(abs(r["scheduled_for"] - started_at) / 60)}
            for r in rows if r["meeting_id"] not in exclude]


def analyse(cand: Candidate, *, quick: bool = True) -> Dict[str, Any]:
    """Describe one candidate meeting for the preview. Reads files; writes nothing."""
    item: Dict[str, Any] = {
        "key": cand.key,
        "kind": cand.kind,
        "source_label": _SOURCE_LABELS.get(cand.kind, cand.kind),
        "title": cand.title,
        "started_at": cand.started_at,
        "ended_at": cand.ended_at,
        "time_source": cand.time_source,
        "files": [f.as_dict() for f in cand.files],
        "ignored_files": [f.as_dict() for f in cand.ignored],
        "warnings": list(cand.warnings),
        "origin": list(cand.origin) if cand.origin else None,
        "duplicate_of": None,
        "scheduled_matches": [],
        "audio": None,
        "transcript": None,
        "outcome": "import",
        "transcript_state": "none",
    }
    if cand.raw_metadata.get("description"):
        item["description"] = cand.raw_metadata["description"]

    if cand.audio is not None:
        info = media.probe(cand.audio.path)
        with cand.audio.path.open("rb") as fh:
            sniffed = media.sniff_audio(fh.read(16))
        audio: Dict[str, Any] = {"name": cand.audio.as_dict()["name"], "size": cand.audio.size,
                                 "mime": sniffed, "readable": bool(info.get("ok"))}
        if info.get("ok"):
            audio.update({k: info.get(k) for k in ("duration_ms", "codec", "sample_rate", "channels")})
            if cand.claimed_duration_ms or (cand.started_at and cand.ended_at):
                _note_time_mismatch(item, cand, info.get("duration_ms") or 0)
            if not quick or (info.get("duration_ms") or 0) <= PREVIEW_LOUDNESS_MAX_MS:
                level = media.loudness(cand.audio.path)
                audio["max_db"] = level.get("max_db")
                audio["mean_db"] = level.get("mean_db")
                audio["silent"] = media.is_silent(level)
        else:
            audio["error"] = info.get("error")
            item["warnings"].append(info.get("error") or "The recording could not be read.")
        audio["sha256"] = sha256_file(cand.audio.path)
        item["audio"] = audio

    if cand.transcript is not None:
        parsed = parsers.parse_transcript(cand.transcript.path.name, cand.transcript.path.read_bytes())
        item["transcript"] = {
            "name": cand.transcript.as_dict()["name"],
            "format": parsed.format,
            "segments": len(parsed.segments),
            "usable": parsed.usable,
            "timing": parsed.timing,
            "speakers": sorted({s["speaker"] for s in parsed.segments if s.get("speaker")})[:12],
            "preview": " ".join(s["text"] for s in parsed.segments[:3])[:240],
        }
        item["warnings"].extend(parsed.warnings)
        if not parsed.usable and cand.kind == "airecord":
            item["warnings"].append("The recorder's transcript is empty — it has to be transcribed.")

    # Outcome — what will happen to the transcript.
    audio = item["audio"] or {}
    transcript = item["transcript"] or {}
    if transcript.get("usable"):
        item["transcript_state"] = "imported"
    elif cand.audio is None:
        item["transcript_state"] = "transcript_only" if transcript else "none"
        if not transcript.get("usable"):
            item["outcome"] = "skip"
            item["warnings"].append("Nothing usable to import: the transcript is empty.")
    elif not audio.get("readable"):
        item["transcript_state"] = "failed"
    elif audio.get("silent"):
        item["transcript_state"] = "no_speech"
        item["warnings"].append(
            f"No speech detected — the recording is silent (loudest moment {audio.get('max_db')} dB)."
        )
    else:
        item["transcript_state"] = "needs_transcription"
    if cand.audio is not None and transcript.get("usable"):
        item["transcript_state"] = "imported"

    # Already in the library?
    existing = None
    if cand.origin:
        existing = db.origin_meeting(*cand.origin)
    if not existing and audio.get("sha256"):
        hits = db.assets_with_sha(audio["sha256"])
        existing = hits[0]["meeting_id"] if hits else None
    if existing:
        item["duplicate_of"] = existing
        item["outcome"] = "skip"
    else:
        item["scheduled_matches"] = scheduled_matches(cand.started_at)
        if len(item["scheduled_matches"]) == 1 and cand.audio is not None:
            item["outcome"] = "attach"
            item["attach_to"] = item["scheduled_matches"][0]["meeting_id"]
    return item


def _note_time_mismatch(item: Dict[str, Any], cand: Candidate, media_ms: int) -> None:
    claims = []
    if cand.claimed_duration_ms:
        claims.append(("the recorder's duration", cand.claimed_duration_ms))
    if cand.started_at and cand.ended_at and cand.ended_at > cand.started_at:
        claims.append(("its start/end times", int((cand.ended_at - cand.started_at) * 1000)))
    off = [(label, ms) for label, ms in claims if abs(ms - media_ms) > max(2000, media_ms * 0.1)]
    if off:
        parts = ", ".join(f"{label} say {ms / 1000:.0f} s" for label, ms in off)
        item["warnings"].append(
            f"The recording plays for {media_ms / 1000:.1f} s; {parts}. The playable length is used "
            "and the original values are kept."
        )


# ── preview / commit for uploads ────────────────────────────────────────────


def staging_dir(import_id: str) -> Path:
    return media_root() / "staging" / import_id


def preview_tree(tree: Path) -> Dict[str, Any]:
    candidates = discover(tree)
    items = [analyse(c) for c in candidates]
    to_transcribe_ms = sum((i.get("audio") or {}).get("duration_ms") or 0
                           for i in items if i["transcript_state"] == "needs_transcription" and i["outcome"] != "skip")
    return {
        "items": items,
        "totals": {
            "meetings": len(items),
            "duplicates": sum(1 for i in items if i["duplicate_of"]),
            "needs_transcription": sum(1 for i in items if i["transcript_state"] == "needs_transcription"),
            "audio_minutes_to_transcribe": round(to_transcribe_ms / 60000, 1),
        },
    }


def commit_import(import_row: Dict[str, Any], choices: Sequence[Dict[str, Any]], *,
                  owner_user_id: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Create (or attach) the meetings a person confirmed in the preview."""
    tree = Path(import_row["staging_dir"]) / "tree"
    by_key = {c.key: c for c in discover(tree)}
    manifest = import_row.get("manifest") or {}
    analysed = {i["key"]: i for i in manifest.get("items") or []}
    wanted = {str(c.get("key")): c for c in choices or [] if c.get("key")}
    if not wanted:
        # No explicit choices: the preview's own defaults.
        wanted = {k: {"key": k, "action": v.get("outcome"), "attach_to": v.get("attach_to")} for k, v in analysed.items()}
    results: List[Dict[str, Any]] = []
    for key, choice in wanted.items():
        cand = by_key.get(key)
        item = analysed.get(key) or {}
        action = str(choice.get("action") or item.get("outcome") or "import")
        if cand is None:
            results.append({"key": key, "status": "missing"})
            continue
        if action == "skip":
            results.append({"key": key, "status": "skipped", "meeting_id": item.get("duplicate_of")})
            continue
        result = ingest(
            cand, source_id="upload", origin_type="import", owner_user_id=owner_user_id,
            title=str(choice.get("title") or "").strip() or None,
            project_id=str(choice.get("project_id") or project_id or "").strip() or None,
            category=str(choice.get("category") or "").strip() or None,
            attach_to=str(choice.get("attach_to") or "").strip() or None if action == "attach" else None,
            transcribe=bool(choice.get("transcribe", True)),
            analysed=item,
        )
        results.append({"key": key, **result})
    return {"results": results}


# ── ingest (shared with folder sync) ────────────────────────────────────────


def _copy_into(meeting_id: str, src: Path, name: str) -> str:
    """Copy a file into the meeting's own folder; return its path relative to the media root."""
    folder = media_root() / meeting_id
    folder.mkdir(parents=True, exist_ok=True)
    safe = name.replace("/", "_").replace("\\", "_").strip() or "file"
    target = folder / safe
    if target.exists():
        target = folder / f"{uuid.uuid4().hex[:8]}_{safe}"
    shutil.copy2(src, target)
    return target.relative_to(media_root()).as_posix()


def ingest(cand: Candidate, *, source_id: str, origin_type: str, owner_user_id: str = "",
           title: Optional[str] = None, project_id: Optional[str] = None, category: Optional[str] = None,
           attach_to: Optional[str] = None, transcribe: bool = True,
           analysed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make one candidate a library meeting (or add its recording to a scheduled one)."""
    item = analysed or analyse(cand)
    if item.get("duplicate_of") and not attach_to:
        return {"status": "duplicate", "meeting_id": item["duplicate_of"]}
    audio = item.get("audio") or {}
    duration_ms = audio.get("duration_ms") or cand.claimed_duration_ms
    started_at = cand.started_at or time.time()
    ended_at = started_at + duration_ms / 1000.0 if duration_ms else cand.ended_at
    warnings = list(dict.fromkeys(item.get("warnings") or []))
    source_name = "insta360" if cand.kind == "airecord" else ("transcript" if cand.kind == "transcript" else "upload")
    if origin_type == "sync":
        source_name = "insta360" if cand.kind == "airecord" else "folder"

    if attach_to and db.get_entry(attach_to):
        meeting_id = attach_to
        con = db._connect()
        try:
            con.execute("UPDATE ms_meetings SET started_at = ?, ended_at = ?, status = 'ended',"
                        " source = COALESCE(source, ?) WHERE id = ?",
                        (started_at, ended_at, source_name, meeting_id))
            con.commit()
        finally:
            con.close()
        db.update_entry(meeting_id, recording_state="present", duration_ms=duration_ms, media_present=1,
                        warnings=warnings, raw_metadata=cand.raw_metadata or None)
        status = "attached"
    else:
        meeting_id = db.create_meeting_entry(
            title=title or cand.title, origin_type=origin_type, owner_user_id=owner_user_id,
            started_at=started_at, ended_at=ended_at, status="ended", source=source_name,
            project_id=project_id, category=category or ("Imported" if origin_type == "import" else "Synced"),
            description=item.get("description"),
            recording_state="present" if cand.audio is not None else "none",
            transcript_state="none", duration_ms=duration_ms, raw_metadata=cand.raw_metadata or None,
            warnings=warnings,
        )
        status = "created"
    if cand.origin:
        db.link_origin(cand.origin[0], cand.origin[1], meeting_id)

    # Files: the recording, the transcript and the recorder's metadata — copies.
    if cand.audio is not None:
        ref = _copy_into(meeting_id, cand.audio.path, cand.audio.path.name)
        db.add_asset(meeting_id=meeting_id, source_id=source_id, origin_type=origin_type,
                     relative_path=cand.audio.rel, original_name=cand.audio.path.name, kind="audio",
                     role="primary", sha256=audio.get("sha256") or sha256_file(cand.audio.path),
                     mime=audio.get("mime"), size_bytes=cand.audio.size, storage_ref=ref,
                     media_duration_ms=audio.get("duration_ms"),
                     metadata={k: audio.get(k) for k in ("codec", "sample_rate", "channels", "max_db", "mean_db")
                               if audio.get(k) is not None} | {"source_mtime": cand.audio.mtime})
    parsed = None
    if cand.transcript is not None:
        raw = cand.transcript.path.read_bytes()
        parsed = parsers.parse_transcript(cand.transcript.path.name, raw)
        ref = _copy_into(meeting_id, cand.transcript.path, cand.transcript.path.name)
        db.add_asset(meeting_id=meeting_id, source_id=source_id, origin_type=origin_type,
                     relative_path=cand.transcript.rel, original_name=cand.transcript.path.name,
                     kind="transcript", role="primary", sha256=hashlib.sha256(raw).hexdigest(),
                     mime="text/plain", size_bytes=cand.transcript.size, storage_ref=ref,
                     metadata={"format": parsed.format, "segments": len(parsed.segments), "usable": parsed.usable})
    for meta in cand.metadata_files:
        ref = _copy_into(meeting_id, meta.path, meta.path.name)
        db.add_asset(meeting_id=meeting_id, source_id=source_id, origin_type=origin_type,
                     relative_path=meta.rel, original_name=meta.path.name, kind="metadata", role="secondary",
                     sha256=sha256_file(meta.path), mime="application/json", size_bytes=meta.size,
                     storage_ref=ref)

    # Transcript state.
    state = "none"
    if parsed is not None and parsed.usable:
        segments = parsers.monotonic(parsed.segments)
        vid = db.create_version(meeting_id, segments, origin="imported", timing=parsed.timing,
                                source_ref=cand.transcript.rel, note=f"Imported from {cand.transcript.path.name}")
        db.publish_version(meeting_id, vid)
        state = "transcript_only" if cand.audio is None else "imported"
        if cand.audio is None and parsed.timing == "imported":
            # No recording to measure: the transcript's own times give the length.
            span_ms = max((s.get("t1_ms") or s.get("t0_ms") or 0) for s in segments)
            if span_ms > 0:
                db.update_entry(meeting_id, duration_ms=int(span_ms))
                con = db._connect()
                try:
                    con.execute("UPDATE ms_meetings SET ended_at = started_at + ? WHERE id = ?",
                                (span_ms / 1000.0, meeting_id))
                    con.commit()
                finally:
                    con.close()
        _queue_followups(meeting_id)
    elif cand.audio is not None:
        if not audio.get("readable", True):
            state = "failed"
        elif audio.get("silent"):
            state = "no_speech"
        elif transcribe and load_library_config().processing:
            db.create_job(meeting_id, "transcribe")
            state = "queued"
    db.update_entry(meeting_id, transcript_state=state)
    return {"status": status, "meeting_id": meeting_id, "transcript_state": state}


def _queue_followups(meeting_id: str) -> None:
    """After a transcript lands: make it searchable, then (if a model answers) summarise."""
    if not load_library_config().processing:
        return
    db.create_job(meeting_id, "index", max_attempts=1)
    entry = db.get_entry(meeting_id) or {}
    outputs = entry.get("outputs") or {}
    if outputs.get("summary", True):
        db.create_job(meeting_id, "summarize", max_attempts=1, options={"outputs": outputs})
        db.update_entry(meeting_id, summary_state="pending")


def cleanup_staging(import_id: str) -> None:
    shutil.rmtree(staging_dir(import_id), ignore_errors=True)
