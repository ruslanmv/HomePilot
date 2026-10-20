"""HTTP routes for the Meetings Library (all additive, all under ``/v1/meetingsense``).

Registered **before** MeetingSense's own router: its ``GET /v1/meetingsense/{meeting_id}``
would otherwise read ``library`` or ``imports`` as a meeting id. Every existing route keeps
its path and its payload.

Gated by ``MEETINGS_LIBRARY_UPGRADE`` (default off) — with it off these answer 404 and the
legacy Meetings view is what the app shows. ``/library/status`` always answers, so the
frontend can ask which one to show.

Who may see what: imported, synced and scheduled meetings belong to the user who created
them (the data-layer rule HomePilot uses elsewhere); meetings recorded live are visible as
they always were.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import store
from ..config import load_config
from . import db, importer, jobs, media, projection, recording, sync
from .config import load_library_config, media_root

router = APIRouter(tags=["meetings-library"])


def _viewer(authorization: Optional[str], session: Optional[str]) -> str:
    try:
        from ...inventory import _resolve_inventory_user_id  # noqa: PLC0415

        return _resolve_inventory_user_id(authorization or "", session)
    except Exception:  # noqa: BLE001
        return ""


def _require_enabled() -> None:
    if not (load_config().enabled and load_library_config().enabled):
        raise HTTPException(status_code=404, detail="not found")
    db.ensure_migrated()
    # Started lazily as well as at startup: a test client or a reload may skip startup.
    jobs.start_worker()
    sync.start_sync_loop()


def _error(status: int, code: str, message: str, hint: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "hint": hint})


def _owned_entry(meeting_id: str, viewer: str) -> Dict[str, Any]:
    """The meeting, if it exists and this viewer may act on it (404 otherwise, never 403 —
    a stranger must not learn which ids exist)."""
    meeting = store.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="not found")
    entry = db.get_entry(meeting_id) or {}
    owner = entry.get("owner_user_id") or ""
    # Fail closed: an owned meeting is never shown to an empty viewer. On a single-user
    # install the viewer resolves to that user, so this only bites when several accounts
    # exist and a request arrives with no token — which used to see everything.
    if owner and (not viewer or owner != viewer):
        raise HTTPException(status_code=404, detail="not found")
    return {"meeting": meeting, "entry": entry}


def _require_intelligence() -> None:
    """The analysis routes exist only with ``MEETINGS_INTELLIGENCE`` on (404 otherwise, like
    every other gated route, so a caller cannot tell a flag from a missing id)."""
    if not load_library_config().intelligence:
        raise HTTPException(status_code=404, detail="not found")


# ── status ──────────────────────────────────────────────────────────────────


@router.get("/v1/meetingsense/library/status")
async def library_status() -> Dict[str, Any]:
    cfg = load_library_config()
    body: Dict[str, Any] = {**cfg.as_dict(), "enabled": bool(cfg.enabled and load_config().enabled),
                            "ffmpeg": media.ffmpeg_available()}
    if body["enabled"]:
        try:
            body["stt"] = jobs.stt_setup_hint()
        except Exception:  # noqa: BLE001
            body["stt"] = {"available": False}
    return body


# ── library ─────────────────────────────────────────────────────────────────


@router.get("/v1/meetingsense/library")
async def library_list(
    tab: str = Query("all"), q: str = Query(""), source: str = Query(""), project_id: str = Query(""),
    state: str = Query(""), date_from: Optional[float] = Query(None), date_to: Optional[float] = Query(None),
    sort: str = Query("newest"), cursor: str = Query(""), limit: int = Query(24),
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    viewer = _viewer(authorization, homepilot_session)
    # A recording whose browser closed before saying it was complete is completed here, so
    # the list never shows a meeting as still saving its audio.
    await asyncio.to_thread(recording.finalize_stale)
    return await asyncio.to_thread(
        projection.list_library, viewer=viewer, tab=tab, q=q.strip(), source=source, project_id=project_id,
        state=state, date_from=date_from, date_to=date_to, sort=sort, cursor=cursor, limit=limit,
    )


def _public_asset(asset: Dict[str, Any]) -> Dict[str, Any]:
    """An asset as the browser sees it: provenance yes, server paths no."""
    return {k: asset.get(k) for k in (
        "id", "kind", "role", "original_name", "relative_path", "sha256", "mime", "size_bytes",
        "media_duration_ms", "source_id", "origin_type", "created_at", "metadata",
    )} | {"source_available": bool(asset.get("source_available"))}


@router.get("/v1/meetingsense/library/item/{library_id}")
async def library_item(
    library_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """Everything the Meeting Detail page shows, for any kind of library item."""
    _require_enabled()
    viewer = _viewer(authorization, homepilot_session)
    await asyncio.to_thread(recording.finalize_stale)
    item = await asyncio.to_thread(projection.find_item, library_id, viewer)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    if item["origin_type"] == "teams_room":
        from ...teams import rooms as rooms_mod  # noqa: PLC0415

        room = rooms_mod.get_room(item["origin_id"]) or {}
        msgs = room.get("messages") or []
        return {"item": item, "teams_room": {
            "id": room.get("id"), "name": room.get("name"), "topic": room.get("topic"),
            "participants": room.get("participant_ids") or [], "message_count": len(msgs),
            "messages": [{"speaker": m.get("sender_name"), "text": m.get("content"), "t": m.get("timestamp")}
                         for m in msgs[:200]],
        }}
    meeting_id = item["meeting_id"]
    from .. import minutes as minutes_mod  # noqa: PLC0415

    entry = db.get_entry(meeting_id) or {}
    return {
        "item": item,
        "meeting": store.get_meeting(meeting_id),
        "entry": {k: entry.get(k) for k in ("origin_type", "category", "description", "scheduled_for",
                                            "recording_plan", "outputs", "raw_metadata", "warnings")},
        "segments": store.get_segments(meeting_id),
        "keyframes": store.get_keyframes(meeting_id),
        "notes": store.get_notes(meeting_id),
        "summaries": minutes_mod.summaries(meeting_id),
        "assets": [_public_asset(a) for a in db.assets_for(meeting_id)],
        "jobs": db.list_jobs(meeting_id=meeting_id, limit=20),
        "versions": db.list_versions(meeting_id),
    }


_EDITABLE = ("title", "category", "description", "scheduled_for")


@router.patch("/v1/meetingsense/library/item/{meeting_id}")
async def library_update(
    meeting_id: str, body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    found = _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    body = body or {}
    if "title" in body:
        title = str(body.get("title") or "").strip()
        if not title:
            raise _error(400, "empty_title", "A meeting needs a title.")
        store.update_meeting(meeting_id, {"title": title[:200]})
    entry_fields = {}
    for key in ("category", "description"):
        if key in body:
            entry_fields[key] = (str(body.get(key) or "").strip() or None)
    if "scheduled_for" in body and body["scheduled_for"] is not None:
        entry_fields["scheduled_for"] = float(body["scheduled_for"])
    if entry_fields:
        if not found["entry"]:
            db.ensure_entry(meeting_id)
        db.update_entry(meeting_id, **entry_fields)
    return {"ok": True, "item": projection.find_item(meeting_id, _viewer(authorization, homepilot_session))}


@router.post("/v1/meetingsense/library/meetings")
async def library_create_meeting(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """A meeting that exists before its recording: "Schedule for later" or "External recorder".

    Its recording arrives later — by upload or from a synced folder, matched by time and
    confirmed when the match is not certain.
    """
    _require_enabled()
    viewer = _viewer(authorization, homepilot_session)
    body = body or {}
    title = str(body.get("title") or "").strip()
    if not title:
        raise _error(400, "empty_title", "A meeting needs a title.")
    plan = str(body.get("recording_plan") or "external")
    if plan not in ("live", "external", "hybrid", "later"):
        raise _error(400, "bad_plan", "recording_plan must be live, external, hybrid or later.")
    try:
        when = float(body.get("scheduled_for")) if body.get("scheduled_for") is not None else None
    except (TypeError, ValueError):
        raise _error(400, "bad_time", "scheduled_for must be a Unix time in seconds.") from None
    outputs = body.get("outputs") if isinstance(body.get("outputs"), dict) else None
    mid = db.create_meeting_entry(
        title=title[:200], origin_type="scheduled", owner_user_id=viewer, started_at=when, status="scheduled",
        source="scheduled", project_id=str(body.get("project_id") or "").strip() or None,
        category=str(body.get("category") or "").strip() or None,
        description=str(body.get("description") or "").strip() or None, scheduled_for=when,
        recording_plan=plan, recording_state="awaiting", transcript_state="none", outputs=outputs,
    )
    return JSONResponse(status_code=201, content={"ok": True, "meeting_id": mid,
                                                  "item": projection.find_item(mid, viewer)})


@router.delete("/v1/meetingsense/library/item/{meeting_id}")
async def library_remove(
    meeting_id: str, mode: str = Query("remove"),
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """``remove`` hides the meeting from the library (reversible); ``delete`` deletes its data.

    A full delete removes the meeting's rows, its transcript versions and the copies
    HomePilot made. The originals in a synced folder are never touched.
    """
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    if mode == "remove":
        db.ensure_entry(meeting_id)
        import time as _t  # noqa: PLC0415

        db.update_entry(meeting_id, hidden_at=_t.time())
        return {"ok": True, "mode": "remove"}
    if mode != "delete":
        raise _error(400, "bad_mode", "mode must be remove or delete.")
    from .. import retention as retention_mod  # noqa: PLC0415
    from .. import session as session_mod  # noqa: PLC0415

    session = session_mod.get(meeting_id)
    if session is not None:
        try:
            await session.stop()
        except Exception:  # noqa: BLE001
            pass
        session_mod.unregister(meeting_id)
    for job in db.list_jobs(meeting_id=meeting_id, states=("queued", "running")):
        db.update_job(job["id"], state="cancelled", finished=True)
    library_rows = db.delete_library_rows(meeting_id)
    # The meeting's own folder first — its copies and its live recording — so the count is
    # this route's; the retention delete below then finds nothing of it left to remove.
    folder = media_root() / meeting_id
    removed_files = 0
    if folder.is_dir() and folder.resolve().parent == media_root().resolve():
        removed_files = sum(1 for p in folder.rglob("*") if p.is_file())
        shutil.rmtree(folder, ignore_errors=True)
    result = retention_mod.delete_meeting(meeting_id) or {}
    return {"ok": True, "mode": "delete", "removed": {**result, **library_rows, "files": removed_files}}


@router.put("/v1/meetingsense/library/item/{meeting_id}/projects")
async def library_project_links(
    meeting_id: str, body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """Link a meeting to projects — the same meeting in each, never a copy."""
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    ids = body.get("project_ids") if isinstance(body, dict) else None
    if not isinstance(ids, list):
        raise _error(400, "bad_projects", "project_ids must be a list.")
    return {"ok": True, "project_ids": db.set_project_links(meeting_id, [str(i) for i in ids])}


# ── media ───────────────────────────────────────────────────────────────────


def _asset_path(meeting_id: str, asset_id: str, viewer: str) -> tuple:
    _owned_entry(meeting_id, viewer)
    asset = db.get_asset(asset_id)
    if not asset or asset.get("meeting_id") != meeting_id or not asset.get("storage_ref"):
        raise HTTPException(status_code=404, detail="not found")
    root = media_root().resolve()
    path = (root / asset["storage_ref"]).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return asset, path


_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


@router.get("/v1/meetingsense/library/item/{meeting_id}/media/{asset_id}")
async def library_media(
    meeting_id: str, asset_id: str, request: Request, download: int = Query(0),
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
    token: str = Query(""),
) -> Response:
    """Stream a meeting's file, with byte ranges so the player can seek."""
    _require_enabled()
    viewer = _viewer(authorization or (f"Bearer {token}" if token else None), homepilot_session)
    asset, path = _asset_path(meeting_id, asset_id, viewer)
    size = path.stat().st_size
    mime = asset.get("mime") or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if download:
        safe = asset["original_name"].encode("ascii", "replace").decode().replace('"', "")
        headers["Content-Disposition"] = f'attachment; filename="{safe}"'
    rng = _RANGE.match(request.headers.get("range", "").strip())
    start, end = 0, size - 1
    status = 200
    if rng and size:
        a, b = rng.groups()
        if a == "" and b:
            start = max(0, size - int(b))
        else:
            start = int(a or 0)
            end = min(size - 1, int(b)) if b else size - 1
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1 if size else 0
    headers["Content-Length"] = str(length)

    def body():
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(body(), status_code=status, media_type=mime, headers=headers)


@router.post("/v1/meetingsense/library/item/{meeting_id}/recording")
async def library_recording_piece(
    meeting_id: str, request: Request, seq: int = Query(..., ge=0), offset_ms: int = Query(0, ge=0),
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """One piece of a live meeting's recording, in order (see ``library/recording.py``)."""
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > recording.CHUNK_MAX_BYTES:
        return JSONResponse(status_code=413, content=recording.RecordingError(413, "too_large", "That piece is too large.").body())
    data = await request.body()
    try:
        result = await asyncio.to_thread(recording.append, meeting_id, seq, data,
                                         mime=request.headers.get("content-type", ""), offset_ms=offset_ms)
    except recording.RecordingError as exc:
        return JSONResponse(status_code=exc.status, content=exc.body())
    return JSONResponse(content=result)


@router.post("/v1/meetingsense/library/item/{meeting_id}/recording/complete")
async def library_recording_complete(
    meeting_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """The browser has sent its last piece: make the recording the meeting's audio."""
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    try:
        asset = await asyncio.to_thread(recording.finalize, meeting_id)
    except recording.RecordingError as exc:
        return JSONResponse(status_code=exc.status, content=exc.body())
    return JSONResponse(content={"ok": asset is not None, "asset": _public_asset(asset) if asset else None})


@router.get("/v1/meetingsense/library/item/{meeting_id}/media/{asset_id}/peaks")
async def library_peaks(
    meeting_id: str, asset_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    asset, path = _asset_path(meeting_id, asset_id, _viewer(authorization, homepilot_session))
    meta = asset.get("metadata") or {}
    if isinstance(meta.get("peaks"), list):
        return {"peaks": meta["peaks"]}
    values = await asyncio.to_thread(media.peaks, path)
    db.update_asset(asset_id, metadata={**meta, "peaks": values})
    return {"peaks": values}


# ── imports ─────────────────────────────────────────────────────────────────


def _safe_name(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/")).strip() or "upload"
    return re.sub(r"[\x00-\x1f]", "", name)[:200]


@router.post("/v1/meetingsense/imports/preview")
async def import_preview(
    files: List[UploadFile] = File(...), project_id: str = Form(""),
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """Look at uploaded files and say what importing them would do. Changes nothing."""
    _require_enabled()
    viewer = _viewer(authorization, homepilot_session)
    cfg = load_library_config()
    max_bytes = cfg.max_upload_mb * 1024 * 1024
    import_id = uuid.uuid4().hex
    staging = importer.staging_dir(import_id)
    raw_dir, tree = staging / "raw", staging / "tree"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tree.mkdir(parents=True, exist_ok=True)
    try:
        for upload in files:
            name = _safe_name(upload.filename or "")
            target = raw_dir / name
            written = 0
            with open(target, "wb") as out:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise _error(413, "too_large", f"{name} is larger than {cfg.max_upload_mb} MB.")
                    out.write(chunk)
            await upload.close()
            with open(target, "rb") as fh:
                head = fh.read(8)
            if head.startswith(b"PK\x03\x04") or name.lower().endswith(".zip"):
                from .adapters import UnsafeArchive, extract_zip  # noqa: PLC0415

                try:
                    await asyncio.to_thread(extract_zip, target, tree / Path(name).stem, max_total_bytes=max_bytes * 2)
                except UnsafeArchive as exc:
                    raise _error(422, "unsafe_archive", str(exc)) from None
            else:
                shutil.copy2(target, tree / name)
        manifest = await asyncio.to_thread(importer.preview_tree, tree)
    except HTTPException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(staging, ignore_errors=True)
        raise _error(422, "unreadable", f"The files could not be read: {exc}") from None
    manifest["project_id"] = project_id.strip() or None
    if not manifest["items"]:
        shutil.rmtree(staging, ignore_errors=True)
        raise _error(422, "nothing_found", "No recordings or transcripts were found in those files.",
                     "Supported: MP3, M4A, WAV, OGG, FLAC, WebM; TXT, MD, SRT, VTT, JSON; ZIP archives; Insta360 AIRecord folders.")
    db.create_import(owner_user_id=viewer, source_id="upload", manifest=manifest, staging_dir=str(staging),
                     import_id=import_id)
    return {"import_id": import_id, **manifest}


@router.post("/v1/meetingsense/imports")
async def import_commit(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """Do what the preview showed, as confirmed. Idempotent per ``idempotency_key``."""
    _require_enabled()
    viewer = _viewer(authorization, homepilot_session)
    import_id = str((body or {}).get("import_id") or "")
    key = str((body or {}).get("idempotency_key") or "").strip() or None
    if key:
        done = db.import_by_key(viewer, key)
        if done and done["status"] == "committed":
            return JSONResponse(status_code=200, content={"import_id": done["id"], "status": "committed",
                                                          **(done["manifest"].get("result") or {})})
    row = db.get_import(import_id)
    if row is None or (row.get("owner_user_id") or "") != (viewer or ""):
        raise HTTPException(status_code=404, detail="not found")
    if row["status"] == "committed":
        return JSONResponse(status_code=200, content={"import_id": import_id, "status": "committed",
                                                      **(row["manifest"].get("result") or {})})
    if row["status"] == "committing":
        raise _error(409, "in_progress", "This import is already being committed.")
    db.update_import(import_id, status="committing", idempotency_key=key)
    try:
        result = await asyncio.to_thread(
            importer.commit_import, row, (body or {}).get("choices") or [], owner_user_id=viewer,
            project_id=str((body or {}).get("project_id") or row["manifest"].get("project_id") or "").strip() or None,
        )
    except Exception as exc:  # noqa: BLE001
        db.update_import(import_id, status="failed", error=str(exc))
        raise _error(500, "import_failed", f"The import failed: {exc}") from None
    manifest = {**row["manifest"], "result": result}
    db.update_import(import_id, status="committed", manifest=manifest, committed=True)
    importer.cleanup_staging(import_id)
    jobs.wake()
    return JSONResponse(status_code=202, content={"import_id": import_id, "status": "committed", **result})


@router.get("/v1/meetingsense/imports/{import_id}")
async def import_get(
    import_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    row = db.get_import(import_id)
    if row is None or (row.get("owner_user_id") or "") != (_viewer(authorization, homepilot_session) or ""):
        raise HTTPException(status_code=404, detail="not found")
    return {"import_id": row["id"], "status": row["status"], "error": row.get("error"), **row["manifest"]}


# ── folder sync ─────────────────────────────────────────────────────────────


def _refused(exc: "sync.SyncRefused") -> HTTPException:
    status = {"sync_not_enabled": 403, "not_allowed": 403, "not_found": 422, "not_a_folder": 422,
              "missing_path": 400}.get(exc.code, 400)
    return _error(status, exc.code, str(exc), exc.hint)


def _visible(owner: str, viewer: str) -> bool:
    return not viewer or not owner or owner == viewer


def _owned_source(source_id: str, viewer: str) -> Dict[str, Any]:
    source = db.get_source(source_id)
    if source is None or not _visible(source.get("owner_user_id") or "", viewer):
        raise HTTPException(status_code=404, detail="not found")
    return source


@router.get("/v1/meetingsense/sync-sources")
async def sync_list(
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    cfg = load_library_config()
    viewer = _viewer(authorization, homepilot_session)
    sources = [s for s in db.list_sources() if _visible(s.get("owner_user_id") or "", viewer)]
    for s_ in sources:
        s_.pop("resolved_path", None)
    return {"sources": sources, "enabled": bool(cfg.sync_roots), "allowed_roots": list(cfg.sync_roots),
            "suggestion": cfg.as_dict()["sync_suggestion"], "interval_s": cfg.sync_interval_s}


@router.post("/v1/meetingsense/sync-sources")
async def sync_add(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    _require_enabled()
    try:
        source = sync.add_source(str((body or {}).get("path") or ""),
                                 display_name=str((body or {}).get("display_name") or ""),
                                 owner_user_id=_viewer(authorization, homepilot_session),
                                 project_id=str((body or {}).get("project_id") or "").strip() or None)
    except sync.SyncRefused as exc:
        raise _refused(exc) from None
    source = dict(source)
    source.pop("resolved_path", None)
    return JSONResponse(status_code=201, content={"source": source})


@router.post("/v1/meetingsense/sync-sources/{source_id}/scan")
async def sync_scan(
    source_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    _require_enabled()
    _owned_source(source_id, _viewer(authorization, homepilot_session))
    try:
        counts = await sync.scan_async(source_id)
    except sync.SyncRefused as exc:
        raise _refused(exc) from None
    source = db.get_source(source_id) or {}
    source.pop("resolved_path", None)
    return JSONResponse(status_code=202, content={"counts": counts, "source": source})


@router.patch("/v1/meetingsense/sync-sources/{source_id}")
async def sync_update(
    source_id: str, body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    _owned_source(source_id, _viewer(authorization, homepilot_session))
    fields = {}
    if "enabled" in (body or {}):
        fields["enabled"] = bool(body["enabled"])
    if "display_name" in (body or {}):
        fields["display_name"] = str(body["display_name"] or "").strip() or "Folder"
    if "project_id" in (body or {}):
        fields["project_id"] = str(body["project_id"] or "").strip() or None
    db.update_source(source_id, **fields)
    source = db.get_source(source_id) or {}
    source.pop("resolved_path", None)
    return {"source": source}


@router.delete("/v1/meetingsense/sync-sources/{source_id}")
async def sync_delete(
    source_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """Disconnect the folder. Meetings already imported from it stay in the library."""
    _require_enabled()
    _owned_source(source_id, _viewer(authorization, homepilot_session))
    db.delete_source(source_id)
    return {"ok": True}


# ── jobs and transcripts ────────────────────────────────────────────────────


@router.get("/v1/meetingsense/jobs")
async def jobs_list(
    meeting_id: str = Query(""), active: bool = Query(False), limit: int = Query(50),
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    viewer = _viewer(authorization, homepilot_session)
    states = ("queued", "running", "needs_setup", "failed") if active else None
    rows = db.list_jobs(meeting_id=meeting_id or None, states=states, limit=max(1, min(limit, 200)))
    owners = {mid: (e.get("owner_user_id") or "") for mid, e in db.entries_by_id({j["meeting_id"] for j in rows}).items()}
    rows = [j for j in rows if _visible(owners.get(j["meeting_id"], ""), viewer)]
    titles: Dict[str, str] = {}
    for job in rows:
        if job["meeting_id"] not in titles:
            m = store.get_meeting(job["meeting_id"])
            titles[job["meeting_id"]] = (m or {}).get("title") or "Meeting"
        job["meeting_title"] = titles[job["meeting_id"]]
    return {"jobs": rows, "stt": jobs.stt_setup_hint()}


@router.post("/v1/meetingsense/jobs/{job_id}/cancel")
async def jobs_cancel(
    job_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    _owned_entry(job["meeting_id"], _viewer(authorization, homepilot_session))
    if job["state"] in ("queued", "running"):
        db.update_job(job_id, state="cancelled", stage="cancelled", finished=job["state"] == "queued")
        if job["type"] == "transcribe" and job["state"] == "queued":
            db.update_entry(job["meeting_id"], transcript_state="none")
    return {"job": db.get_job(job_id)}


@router.post("/v1/meetingsense/jobs/{job_id}/retry")
async def jobs_retry(
    job_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    _owned_entry(job["meeting_id"], _viewer(authorization, homepilot_session))
    if job["state"] in ("queued", "running"):
        raise _error(409, "in_progress", "That job is still running.")
    new_id = db.create_job(job["meeting_id"], job["type"], options=job.get("options"))
    if job["type"] == "transcribe":
        db.update_entry(job["meeting_id"], transcript_state="queued")
    jobs.wake()
    return {"job": db.get_job(new_id)}


@router.post("/v1/meetingsense/library/item/{meeting_id}/transcriptions")
async def transcribe_again(
    meeting_id: str, body: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """Transcribe (again) on this computer. The current transcript stays until the new one
    is ready, and stays as a version afterwards."""
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    if jobs._primary_audio(meeting_id) is None:
        raise _error(409, "no_audio", "This meeting has no recording to transcribe.")
    for job in db.list_jobs(meeting_id=meeting_id, states=("queued", "running")):
        if job["type"] == "transcribe":
            raise _error(409, "in_progress", "A transcription is already running for this meeting.")
    jid = db.create_job(meeting_id, "transcribe", options=body or {})
    db.ensure_entry(meeting_id)
    db.update_entry(meeting_id, transcript_state="queued")
    jobs.wake()
    return JSONResponse(status_code=202, content={"job": db.get_job(jid)})


@router.post("/v1/meetingsense/library/item/{meeting_id}/ask")
async def ask_library_meeting(
    meeting_id: str, body: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """The meeting's own Ask, for a finished library meeting.

    The answer comes from the existing MeetingSense route, unchanged. Only when no model
    answered (``degraded == "extractive"``) and the meeting is not live are the quoted lines
    chosen again: the core fallback quotes the newest lines, which suits a live meeting, but for
    a finished one the lines that match the question are the useful evidence.
    """
    from .. import ask as ask_mod  # noqa: PLC0415
    from .. import export as export_mod  # noqa: PLC0415
    from .. import session as session_mod  # noqa: PLC0415
    from ..routes import ask_meeting  # noqa: PLC0415

    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    result = await ask_meeting(meeting_id, body or {})
    if result.get("degraded") != "extractive":
        return result
    live = session_mod.get(meeting_id)
    if live is not None and live.state == session_mod.MeetingState.LIVE:
        return result
    question = str((body or {}).get("text") or "")
    rows = ask_mod.retrieve(store.get_segments(meeting_id), [], question, limit=3)
    rendered = "\n".join(
        f"[{export_mod.clock(r.get('t0_ms'))}] " + (f"{r['speaker']}: " if r.get("speaker") else "") + r["text"].strip()
        for r in rows if (r.get("text") or "").strip()
    )
    if not rendered:
        return result
    text = f"From the meeting transcript:\n{rendered}"
    cited = sorted({export_mod.clock(r.get("t0_ms")) for r in rows})
    return {**result, "text": text, "cited": cited, "sources": len(rows)}


@router.post("/v1/meetingsense/library/item/{meeting_id}/summarize")
async def summarize_again(
    meeting_id: str, body: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    if not store.get_segments(meeting_id):
        raise _error(409, "no_transcript", "There is no transcript to summarise yet.")
    db.ensure_entry(meeting_id)
    jid = db.create_job(meeting_id, "summarize", max_attempts=1, options=body or {})
    db.update_entry(meeting_id, summary_state="pending")
    jobs.wake()
    return JSONResponse(status_code=202, content={"job": db.get_job(jid)})


# ── meeting intelligence ────────────────────────────────────────────────────


def _analysis_jobs(meeting_id: str) -> List[Dict[str, Any]]:
    return [j for j in db.list_jobs(meeting_id=meeting_id, limit=20) if j["type"] in ("analyze", "layout")]


def _analysis_payload(meeting_id: str) -> Dict[str, Any]:
    from ..intelligence import service as intelligence  # noqa: PLC0415

    current = intelligence.current(meeting_id)
    pending = [j for j in _analysis_jobs(meeting_id) if j["state"] in ("queued", "running")]
    failed = [j for j in _analysis_jobs(meeting_id) if j["state"] == "failed"]
    if pending:
        state = "pending"
    elif current:
        state = "ready"
    elif failed:
        state = "failed"
    elif store.get_segments(meeting_id):
        state = "none"
    else:
        state = "no_transcript"
    return {
        "state": state,
        "job": (pending or failed or [None])[0],
        **({k: current.get(k) for k in ("id", "created_at", "model", "degraded", "schema_version", "versions",
                                         "analysis", "visual", "questions", "report")} if current else {}),
    }


@router.get("/v1/meetingsense/library/item/{meeting_id}/analysis")
async def analysis_read(
    meeting_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """The newest analysis with its visual page, questions and validator report, plus the
    state the page should show (``none`` / ``pending`` / ``ready`` / ``failed`` / ``no_transcript``)."""
    _require_enabled()
    _require_intelligence()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    return await asyncio.to_thread(_analysis_payload, meeting_id)


@router.post("/v1/meetingsense/library/item/{meeting_id}/analysis")
async def analysis_run(
    meeting_id: str, body: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """Queue the analysis (again). The current page stays until the new one is ready."""
    _require_enabled()
    _require_intelligence()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    if not store.get_segments(meeting_id):
        raise _error(409, "no_transcript", "There is no transcript to analyse yet.",
                     "Transcribe the recording first; the analysis is written from the transcript.")
    for job in _analysis_jobs(meeting_id):
        if job["state"] in ("queued", "running"):
            return JSONResponse(status_code=202, content={"job": job, "state": "pending"})
    db.ensure_entry(meeting_id)
    jid = db.create_job(meeting_id, "analyze", max_attempts=1, options={k: v for k, v in (body or {}).items() if k == "model_target"})
    jobs.wake()
    return JSONResponse(status_code=202, content={"job": db.get_job(jid), "state": "pending"})


@router.get("/v1/meetingsense/library/item/{meeting_id}/visual")
async def visual_read(
    meeting_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    from ..intelligence import service as intelligence  # noqa: PLC0415

    _require_enabled()
    _require_intelligence()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    current = await asyncio.to_thread(intelligence.current, meeting_id)
    if not current:
        raise _error(404, "no_analysis", "This meeting has not been analysed yet.")
    return {"visual": current.get("visual"), "analysis": current.get("analysis"), "id": current.get("id")}


@router.post("/v1/meetingsense/library/item/{meeting_id}/visual")
async def visual_relayout(
    meeting_id: str, body: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """Write the Executive Brief again from the latest analysis (no re-extraction). 409
    ``no_analysis`` until an analysis exists; the current page stays until the new one lands."""
    from ..intelligence import service as intelligence  # noqa: PLC0415

    _require_enabled()
    _require_intelligence()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    if not await asyncio.to_thread(intelligence.current, meeting_id):
        raise _error(409, "no_analysis", "This meeting has not been analysed yet.", "Generate the insights first.")
    for job in _analysis_jobs(meeting_id):
        if job["state"] in ("queued", "running"):
            return JSONResponse(status_code=202, content={"job": job, "state": "pending"})
    jid = db.create_job(meeting_id, "layout", max_attempts=1,
                        options={k: v for k, v in (body or {}).items() if k in ("model_target", "template")})
    jobs.wake()
    return JSONResponse(status_code=202, content={"job": db.get_job(jid), "state": "pending"})


@router.get("/v1/meetingsense/library/item/{meeting_id}/questions")
async def questions_read(
    meeting_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    from ..intelligence import service as intelligence  # noqa: PLC0415

    _require_enabled()
    _require_intelligence()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    current = await asyncio.to_thread(intelligence.current, meeting_id)
    return {"questions": (current or {}).get("questions") or []}


@router.get("/v1/meetingsense/library/item/{meeting_id}/actions")
async def actions_read(
    meeting_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    from ..intelligence import store as intelligence_store  # noqa: PLC0415

    _require_enabled()
    _require_intelligence()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    return {"actions": await asyncio.to_thread(intelligence_store.actions, meeting_id)}


@router.patch("/v1/meetingsense/library/item/{meeting_id}/actions/{item_id}")
async def actions_update(
    meeting_id: str, item_id: str, body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    """Tick, reassign or re-date an action item. Kept on the server, so it follows the meeting
    to every device and survives a regenerated analysis."""
    from ..intelligence import store as intelligence_store  # noqa: PLC0415

    _require_enabled()
    _require_intelligence()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    row = await asyncio.to_thread(
        intelligence_store.update_action, meeting_id, item_id,
        **{k: body.get(k) for k in intelligence_store.UPDATABLE if k in body},
    )
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"action": row}


@router.get("/v1/meetingsense/library/schema")
async def intelligence_schema() -> Dict[str, Any]:
    """The published analysis contract, for other consumers (DayPilot reads this)."""
    from ..intelligence import schema as schema_mod  # noqa: PLC0415

    _require_enabled()
    _require_intelligence()
    return schema_mod.json_schema()


@router.get("/v1/meetingsense/library/item/{meeting_id}/versions")
async def versions_list(
    meeting_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    return {"versions": db.list_versions(meeting_id)}


@router.post("/v1/meetingsense/library/item/{meeting_id}/versions")
async def versions_create(
    meeting_id: str, body: Dict[str, Any],
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """Save an edited transcript as a new version and show it. Earlier versions stay."""
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    segments = (body or {}).get("segments")
    if not isinstance(segments, list) or not segments:
        raise _error(400, "no_segments", "segments must be a non-empty list.")
    clean = []
    for seg in segments:
        if not isinstance(seg, dict) or not str(seg.get("text") or "").strip():
            continue
        clean.append({"t0_ms": int(seg.get("t0_ms") or 0),
                      "t1_ms": None if seg.get("t1_ms") is None else int(seg["t1_ms"]),
                      "speaker": (str(seg.get("speaker")).strip() or None) if seg.get("speaker") else None,
                      "text": str(seg["text"]).strip()[:4000], "conf": None})
    if not clean:
        raise _error(400, "no_segments", "Every segment was empty.")
    active = next((v for v in db.list_versions(meeting_id) if v["active"]), None)
    vid = db.create_version(meeting_id, clean, origin="edit", timing=(active or {}).get("timing") or "imported",
                            note=str((body or {}).get("note") or "Edited by hand")[:200])
    db.publish_version(meeting_id, vid)
    return JSONResponse(status_code=201, content={"version_id": vid, "versions": db.list_versions(meeting_id)})


@router.post("/v1/meetingsense/library/item/{meeting_id}/versions/{version_id}/publish")
async def versions_publish(
    meeting_id: str, version_id: str,
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Dict[str, Any]:
    _require_enabled()
    _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    try:
        count = db.publish_version(meeting_id, version_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found") from None
    return {"ok": True, "segments": count, "versions": db.list_versions(meeting_id)}


@router.get("/v1/meetingsense/library/item/{meeting_id}/transcript")
async def transcript_export(
    meeting_id: str, fmt: str = Query("txt"),
    authorization: Optional[str] = Header(default=None), homepilot_session: Optional[str] = Cookie(default=None),
) -> Response:
    """TXT / SRT / VTT / JSON / MD of the transcript shown now (MeetingSense export covers
    md, srt and json; TXT and VTT are added here for imported meetings)."""
    _require_enabled()
    found = _owned_entry(meeting_id, _viewer(authorization, homepilot_session))
    segments = store.get_segments(meeting_id)
    title = (found["meeting"].get("title") or "meeting").strip()
    fname = re.sub(r"[^\w\-. ]+", "_", title)[:80] or "meeting"

    def clock(ms: Optional[int], sep: str) -> str:
        ms = int(ms or 0)
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"

    fmt = fmt.lower()
    if fmt == "json":
        content = json.dumps({"title": title, "segments": segments}, ensure_ascii=False, indent=2)
        media_type = "application/json"
    elif fmt in ("srt", "vtt"):
        sep = "," if fmt == "srt" else "."
        lines = ["WEBVTT", ""] if fmt == "vtt" else []
        for i, seg in enumerate(segments, 1):
            end = seg["t1_ms"] if seg.get("t1_ms") is not None else int(seg["t0_ms"] or 0) + 3000
            if fmt == "srt":
                lines.append(str(i))
            text = f"{seg['speaker']}: {seg['text']}" if seg.get("speaker") else seg["text"]
            lines += [f"{clock(seg['t0_ms'], sep)} --> {clock(end, sep)}", text, ""]
        content = "\n".join(lines)
        media_type = "text/vtt" if fmt == "vtt" else "application/x-subrip"
    elif fmt in ("txt", "md"):
        head = [f"# {title}", ""] if fmt == "md" else [title, ""]
        body_lines = [
            f"[{clock(seg['t0_ms'], '.')[:8]}] " + (f"{seg['speaker']}: " if seg.get("speaker") else "") + seg["text"]
            for seg in segments
        ]
        content = "\n".join(head + body_lines) + "\n"
        media_type = "text/markdown" if fmt == "md" else "text/plain"
    else:
        raise _error(400, "bad_format", "fmt must be txt, md, srt, vtt or json.")
    return Response(content=content, media_type=f"{media_type}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.{fmt}"'})
