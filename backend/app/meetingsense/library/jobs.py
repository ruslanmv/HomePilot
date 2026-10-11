"""Background processing for library meetings — transcribe, index, summarise.

A durable queue in SQLite (``ms_library_jobs``) worked by one in-process worker. Durable
because a three-hour recording outlives a request: a job survives a restart (an expired
lease is picked up again) and its progress can be shown while it runs.

Transcription uses **HomePilot's own speech provider** — ``get_meeting_stt_provider()``,
the same local-first choice live meetings use. Nothing here ships audio anywhere: when no
local model is installed the job stops at *Needs speech-to-text setup* and the recording
waits, stored and playable, for the user to install one.

One job at a time, and transcription steps aside while a live meeting is recording so an
import never makes a meeting in progress fall behind.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db, media
from .config import load_library_config, media_root

log = logging.getLogger(__name__)

_worker: Optional[asyncio.Task] = None
_wake: Optional[asyncio.Event] = None

#: Seconds of overlap between transcription chunks — enough that a word cut by the chunk
#: boundary is heard whole in one of them.
CHUNK_OVERLAP_S = 1.0
#: Words per notes window when an imported transcript is turned into notes.
NOTES_WINDOW_WORDS = 600


class JobCancelled(Exception):
    pass


class JobFailed(Exception):
    """A failure that retrying will not fix (unreadable file, missing asset)."""


def wake() -> None:
    if _wake is not None:
        _wake.set()


def start_worker() -> bool:
    """Start the worker if the library and processing are on. Safe to call more than once."""
    global _worker, _wake
    cfg = load_library_config()
    if not (cfg.enabled and cfg.processing) or os.getenv("MEETINGS_LIBRARY_WORKER", "1").strip().lower() in ("0", "false", "off"):
        return False
    if _worker is not None and not _worker.done():
        return True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _wake = asyncio.Event()
    _worker = loop.create_task(_loop())
    return True


async def stop_worker() -> None:
    global _worker
    if _worker is not None:
        _worker.cancel()
        try:
            await _worker
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _worker = None


async def _loop() -> None:
    db.ensure_migrated()
    while True:
        try:
            job = await asyncio.to_thread(db.lease_next_job)
        except Exception:  # noqa: BLE001 — a locked database is a reason to wait, not to die
            log.exception("meetings library: could not lease a job")
            job = None
        if job is None:
            assert _wake is not None
            _wake.clear()
            try:
                await asyncio.wait_for(_wake.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
            continue
        await run_job(job)


async def run_job(job: Dict[str, Any]) -> str:
    """Run one leased job to an end state. Returns that state."""
    handlers = {"transcribe": _transcribe, "index": _index, "summarize": _summarize}
    handler = handlers.get(job["type"])
    if handler is None:
        db.update_job(job["id"], state="failed", error=f"unknown job type {job['type']}", finished=True)
        return "failed"
    try:
        state = await handler(job) or "done"
        db.update_job(job["id"], state=state, stage=state, progress=1.0 if state == "done" else None, finished=True)
        return state
    except JobCancelled:
        db.update_job(job["id"], state="cancelled", stage="cancelled", finished=True)
        if job["type"] == "transcribe":
            db.update_entry(job["meeting_id"], transcript_state="none")
        return "cancelled"
    except Exception as exc:  # noqa: BLE001
        message = str(exc) or type(exc).__name__
        log.warning("meetings library: job %s (%s) failed: %s", job["id"], job["type"], message)
        retry = not isinstance(exc, JobFailed) and int(job.get("attempt") or 1) < int(job.get("max_attempts") or 1)
        if retry:
            db.update_job(job["id"], state="queued", stage="retrying", error=message)
            return "queued"
        db.update_job(job["id"], state="failed", stage="failed", error=message, finished=True)
        if job["type"] == "transcribe":
            db.update_entry(job["meeting_id"], transcript_state="failed")
        elif job["type"] == "summarize":
            db.update_entry(job["meeting_id"], summary_state="failed")
        return "failed"


def _check_cancel(job_id: str) -> None:
    if db.job_state(job_id) == "cancelled":
        raise JobCancelled()


def _primary_audio(meeting_id: str) -> Optional[Dict[str, Any]]:
    for asset in db.assets_for(meeting_id):
        if asset["kind"] == "audio" and asset.get("storage_ref"):
            return asset
    return None


def _live_meeting_running() -> bool:
    try:
        from .. import session as session_mod  # noqa: PLC0415

        return any(getattr(s, "state", None) == session_mod.MeetingState.LIVE
                   for s in list(session_mod._SESSIONS.values()))
    except Exception:  # noqa: BLE001
        return False


def stt_setup_hint() -> Dict[str, Any]:
    """Why transcription cannot run here, from the same probe the status route uses."""
    try:
        from ..routes import stt_capability  # noqa: PLC0415

        cap = stt_capability()
    except Exception as exc:  # noqa: BLE001
        cap = {"available": False, "hint": f"Speech providers unavailable: {exc}"}
    return {"available": bool(cap.get("available")), "provider": cap.get("provider"),
            "hint": cap.get("hint"), "offer_remote": bool(cap.get("offer_remote"))}


def _get_provider():
    from ...voice.providers import get_meeting_stt_provider  # noqa: PLC0415

    return get_meeting_stt_provider()


async def _transcribe(job: Dict[str, Any]) -> str:
    meeting_id = job["meeting_id"]
    job_id = job["id"]
    asset = _primary_audio(meeting_id)
    if asset is None:
        raise JobFailed("This meeting has no recording to transcribe.")
    path = media_root() / asset["storage_ref"]
    if not path.is_file():
        raise JobFailed("The meeting's recording is missing from HomePilot's storage.")

    db.update_job(job_id, stage="validating", progress=0.0, lease_s=600)
    info = await asyncio.to_thread(media.probe, path)
    if not info.get("ok"):
        raise JobFailed(info.get("error") or "The recording could not be read.")
    duration_s = max(0.1, (info.get("duration_ms") or 0) / 1000.0)

    level = await asyncio.to_thread(media.loudness, path)
    if media.is_silent(level):
        db.update_entry(meeting_id, transcript_state="no_speech")
        db.add_warning(meeting_id, f"No speech detected — the recording is silent (loudest moment {level.get('max_db')} dB).")
        db.update_job(job_id, diagnostic={"silent": True, **level})
        return "done"

    provider = _get_provider()
    if not getattr(provider, "available", False):
        hint = stt_setup_hint()
        db.update_entry(meeting_id, transcript_state="needs_setup")
        db.update_job(job_id, stage="needs_setup", diagnostic=hint,
                      error=hint.get("hint") or "No local speech-to-text model is installed.")
        return "needs_setup"

    db.update_entry(meeting_id, transcript_state="transcribing")
    cfg = load_library_config()
    chunk_s = float(cfg.stt_chunk_s)
    chunks = max(1, math.ceil(duration_s / chunk_s))
    segments: List[Dict[str, Any]] = []
    last_end_ms = -1
    started = time.time()
    for index in range(chunks):
        _check_cancel(job_id)
        while _live_meeting_running():  # a live meeting has the model first
            db.update_job(job_id, stage="waiting for live meeting", lease_s=600)
            await asyncio.sleep(5)
            _check_cancel(job_id)
        start_s = index * chunk_s
        length_s = min(chunk_s + CHUNK_OVERLAP_S, duration_s - start_s)
        if length_s <= 0.05:
            break
        db.update_job(job_id, stage="decoding", progress=index / chunks, lease_s=900)
        wav = await asyncio.to_thread(media.decode_chunk, path, start_s=start_s, length_s=length_s)
        db.update_job(job_id, stage="transcribing", progress=(index + 0.2) / chunks, lease_s=900)
        spans = await provider.transcribe_segments(wav, fmt="wav", duration_s=length_s)
        for span in spans or []:
            text = (span.get("text") or "").strip()
            if not text:
                continue
            t0 = int(round((float(span.get("t0") or 0.0) + start_s) * 1000))
            t1_raw = span.get("t1")
            t1 = None if t1_raw is None else int(round((float(t1_raw) + start_s) * 1000))
            # The overlap: a line the previous chunk already heard is not written twice.
            if t0 < last_end_ms - 200:
                continue
            segments.append({"t0_ms": t0, "t1_ms": t1, "speaker": None, "text": text,
                             "conf": span.get("conf")})
            last_end_ms = max(last_end_ms, t1 if t1 is not None else t0)
        db.update_job(job_id, progress=(index + 1) / chunks,
                      diagnostic={"chunks": chunks, "done": index + 1, "segments": len(segments),
                                  "provider": getattr(provider, "name", None),
                                  "elapsed_s": round(time.time() - started, 1)})

    _check_cancel(job_id)
    db.update_job(job_id, stage="persisting")
    if not segments:
        db.update_entry(meeting_id, transcript_state="no_speech")
        db.add_warning(meeting_id, "No speech was recognised in the recording.")
        return "done"
    timing = "measured" if getattr(provider, "supports_segments", False) else "approximate"
    model_name = os.getenv("WHISPER_MODEL", "").strip() or getattr(provider, "model_name", None)
    vid = db.create_version(meeting_id, segments, origin="stt", timing=timing,
                            provider=getattr(provider, "name", None), model=model_name,
                            note="Transcribed on this computer.")
    db.publish_version(meeting_id, vid)
    db.update_entry(meeting_id, transcript_state="ready" if timing == "measured" else "ready_warnings")
    from .importer import _queue_followups  # noqa: PLC0415

    _queue_followups(meeting_id)
    return "done"


async def _index(job: Dict[str, Any]) -> str:
    from .. import retrieval  # noqa: PLC0415

    rows = await asyncio.to_thread(retrieval.index_meeting, job["meeting_id"])
    db.update_job(job["id"], diagnostic={"indexed_rows": rows})
    return "done"


def _model_call(options: Dict[str, Any]):
    from ..notes_engine import call_model  # noqa: PLC0415

    target = options.get("model_target") or {}

    async def call(messages, **kw):
        return await call_model(messages, provider=target.get("provider", ""), model=target.get("model", ""),
                                base_url=target.get("base_url", ""), **kw)

    return call


def _only_outline(document: Dict[str, Any]) -> bool:
    """True for the document minutes writes when no model answered (its first line says so)."""
    text = (document.get("text") or "").lstrip()
    return bool(document.get("degraded")) and text.startswith("*No language model was reachable")


async def _summarize(job: Dict[str, Any]) -> str:
    """Minutes, then decisions and action items — if a model answers. Never fakes either."""
    from .. import minutes as minutes_mod  # noqa: PLC0415
    from .. import store  # noqa: PLC0415
    from ..notes_engine import NotesEngine  # noqa: PLC0415

    meeting_id = job["meeting_id"]
    options = job.get("options") or {}
    call = _model_call(options)
    outputs = (options.get("outputs") or {})
    db.update_job(job["id"], stage="summarising", progress=0.1, lease_s=1800)
    opts = None
    style = outputs.get("style")
    length = outputs.get("length")
    if style or length:
        opts = minutes_mod.options_from({"style": style or "minutes", "length": length or "standard"})
    document = await minutes_mod.autogenerate(meeting_id, call=call, options=opts)
    if document is None or _only_outline(document):
        # An outline assembled from the transcript is kept (the Summary tab shows it as one),
        # but it is not a summary, and the meeting must not say it has one.
        db.update_entry(meeting_id, summary_state="unavailable")
        db.update_job(job["id"], diagnostic={"reason": "No language model answered, or there is no transcript."})
        return "done"

    if outputs.get("actions", True) and not store.get_notes(meeting_id):
        db.update_job(job["id"], stage="notes", progress=0.6)
        engine = NotesEngine(meeting_id, call=call, max_words=NOTES_WINDOW_WORDS)
        window: List[Dict[str, Any]] = []
        words = 0
        for seg in store.get_segments(meeting_id):
            window.append(seg)
            words += len((seg.get("text") or "").split())
            if words >= NOTES_WINDOW_WORDS:
                engine.add(window)
                await engine.run(force=True)
                window, words = [], 0
        if window:
            engine.add(window)
            await engine.run(force=True)
    db.update_entry(meeting_id, summary_state="ready")
    return "done"
