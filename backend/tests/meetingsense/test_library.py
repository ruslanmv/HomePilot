"""Meetings Library (MEETINGS_LIBRARY_UPGRADE): imports, folder sync, offline transcription,
the unified list, and the rule that none of it changes MeetingSense when the flag is off.

Synthetic recordings only (FFmpeg-generated tone or silence) and a fake speech provider; no
model, no network. Tests that need FFmpeg skip without it.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg is not installed")

NAME = "2026_10_10 12∶31∶51"  # the Insta360 name, with its RATIO characters


def ffmpeg_audio(path: Path, *, seconds: float, silent: bool) -> Path:
    src = "anullsrc=r=48000:cl=stereo" if silent else "sine=frequency=440:sample_rate=48000"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-t", str(seconds),
                    "-i", src, "-ac", "2", "-b:a", "128k", str(path)], check=True)
    return path


def make_airecord(root: Path, *, silent: bool = True, local_id: str = "20261010_123151_268_TEST") -> Path:
    folder = root / NAME
    data = folder / ".airecord_data"
    (data / "asr_audio_slice").mkdir(parents=True)
    ffmpeg_audio(folder / f"{NAME}.mp3", seconds=7.68, silent=silent)
    ffmpeg_audio(data / "asr_audio_slice" / "asr_audio_0.ogg", seconds=1, silent=True)
    (data / "record_info.json").write_text(json.dumps({
        "meetingname": NAME, "username": "default", "localMeetingId": local_id, "meetingId": "none",
        "startTime": 1791628311, "project_type": "record", "transcription_language": "AUTOT",
        "description": "xxxx会议描述", "endTime": 1791628322, "duration": 7000, "mark_count": 0,
    }, ensure_ascii=False), encoding="utf-8")
    (data / "audio_asr_total.json").write_text(json.dumps(
        {"SD_info": {"Labels": [], "Speaker_library": {}, "Stamps": []}, "Result_info": []}))
    (data / "dot.txt").write_bytes(b"")
    return folder


def zip_dir(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.rglob("*")):
            zf.write(p, p.relative_to(folder.parent).as_posix())
    return buf.getvalue()


class FakeProvider:
    name = "fake-local"
    available = True
    supports_segments = True

    def __init__(self):
        self.calls = []

    async def transcribe_segments(self, audio, *, fmt="wav", duration_s=None):
        n = len(self.calls) + 1
        self.calls.append(duration_s)
        assert audio[:4] == b"RIFF"  # 16 kHz WAV from the library's copy
        return [
            {"t0": 0.5, "t1": 5.0, "text": f"Part {n} begins.", "conf": 0.9},
            {"t0": max(0.0, duration_s - 0.8), "t1": duration_s - 0.1, "text": f"Part {n} ends.", "conf": 0.8},
        ]


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    import app.meetingsense.library.db as db
    import app.meetingsense.library.jobs as jobs
    import app.meetingsense.library.projection as projection
    import app.meetingsense.library.routes as lib_routes
    import app.meetingsense.store as store

    for name in ("MEETINGSENSE_ENABLED", "MEETINGS_SYNC_ALLOWED_ROOTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEETINGS_LIBRARY_UPGRADE", "1")
    # Insights are on by default; these tests are about the library alone and count the
    # jobs an import queues. test_intelligence.py covers the analysis job.
    monkeypatch.setenv("MEETINGS_INTELLIGENCE", "0")
    monkeypatch.setenv("MEETINGS_LIBRARY_WORKER", "0")
    monkeypatch.setenv("MEETINGS_LIBRARY_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("MEETINGS_SYNC_STABILITY_S", "0")
    dbfile = tmp_path / "meetings.sqlite3"

    def _connect():
        con = sqlite3.connect(dbfile)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(store, "_connect", _connect)
    db._migrated_paths.clear()
    monkeypatch.setattr(lib_routes, "_viewer", lambda a, s: "")
    monkeypatch.setattr(projection, "_projects_by_id", lambda: {"p1": {"id": "p1", "name": "HomePilot"},
                                                                  "p2": {"id": "p2", "name": "DayPilot"}})
    monkeypatch.setattr(projection, "teams_items", lambda: [])
    fake = FakeProvider()
    monkeypatch.setattr(jobs, "_get_provider", lambda: fake)

    from app.meetingsense import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    class Lib:
        pass

    out = Lib()
    out.client, out.db, out.jobs, out.store, out.fake, out.tmp = client, db, jobs, store, fake, tmp_path
    return out


def run_jobs(lib, limit: int = 20):
    """Work the queue the way the background worker would."""
    states = []
    for _ in range(limit):
        job = lib.db.lease_next_job()
        if job is None:
            break
        states.append((job["type"], asyncio.run(lib.jobs.run_job(job))))
    return states


def preview(lib, files):
    r = lib.client.post("/v1/meetingsense/imports/preview", files=[("files", f) for f in files])
    assert r.status_code == 200, r.text
    return r.json()


def commit(lib, prev, **body):
    r = lib.client.post("/v1/meetingsense/imports", json={"import_id": prev["import_id"], **body})
    assert r.status_code in (200, 202), r.text
    return r.json()


# ── off means off ───────────────────────────────────────────────────────────


def test_with_the_flag_off_the_library_does_not_exist_and_meetingsense_is_unchanged(lib, monkeypatch):
    monkeypatch.setenv("MEETINGS_LIBRARY_UPGRADE", "0")
    assert lib.client.get("/v1/meetingsense/library").status_code == 404
    assert lib.client.get("/v1/meetingsense/library/status").json()["enabled"] is False
    # The core routes answer exactly as before (the library is registered first, and does
    # not shadow them).
    assert lib.client.get("/v1/meetingsense/meetings").json() == {"meetings": []}
    assert lib.client.get("/v1/meetingsense/no-such-meeting").status_code == 404


# ── the Insta360 / AIRecord archive ─────────────────────────────────────────


@needs_ffmpeg
def test_an_airecord_archive_imports_audio_and_metadata_and_is_not_called_transcribed(lib, tmp_path):
    folder = make_airecord(tmp_path / "src", silent=True)
    original = hashlib.sha256((folder / f"{NAME}.mp3").read_bytes()).hexdigest()
    prev = preview(lib, [(f"{NAME}.zip", zip_dir(folder), "application/zip")])
    [item] = prev["items"]
    assert item["kind"] == "airecord"
    assert item["title"] == "Imported meeting · Oct 10, 12:31"
    assert item["origin"] == ["airecord", "20261010_123151_268_TEST"]
    assert item["transcript"]["usable"] is False                     # Result_info is []
    assert item["transcript_state"] == "no_speech"                   # and the audio is silent
    assert item["audio"]["duration_ms"] == pytest.approx(7680, abs=60)
    joined = " ".join(item["warnings"])
    assert "No speech detected" in joined and "plays for 7.7 s" in joined
    assert {f["name"] for f in item["ignored_files"]} == {"asr_audio_0.ogg"}

    result = commit(lib, prev, idempotency_key="k1")
    [res] = result["results"]
    mid = res["meeting_id"]
    assert res["status"] == "created" and res["transcript_state"] == "no_speech"
    detail = lib.client.get(f"/v1/meetingsense/library/item/{mid}").json()
    assert detail["item"]["transcript_state"] == "no_speech"
    assert detail["item"]["recording_state"] == "present" and detail["item"]["media_present"] is True
    assert detail["item"]["source"]["label"] == "Insta360 Import"
    assert detail["segments"] == []                                  # nothing invented
    kinds = sorted(a["kind"] for a in detail["assets"])
    assert kinds == ["audio", "metadata", "transcript"]
    audio = next(a for a in detail["assets"] if a["kind"] == "audio")
    assert audio["original_name"] == f"{NAME}.mp3" and audio["sha256"] == original
    assert detail["entry"]["raw_metadata"]["record_info"]["duration"] == 7000   # raw values kept
    assert "description" not in detail["entry"]["raw_metadata"]       # the device placeholder is dropped

    # The same commit again is the same result, and a second upload is a duplicate.
    again = commit(lib, prev, idempotency_key="k1")
    assert again["results"][0]["meeting_id"] == mid
    second = preview(lib, [(f"{NAME}.zip", zip_dir(folder), "application/zip")])
    assert second["items"][0]["duplicate_of"] == mid and second["items"][0]["outcome"] == "skip"
    assert lib.client.get("/v1/meetingsense/library").json()["total"] == 1


# ── plain files ─────────────────────────────────────────────────────────────


def test_a_text_transcript_on_its_own_is_a_finished_meeting(lib):
    text = "[00:00:05] Alice: We ship on Friday.\n[00:00:12] Bob: I'll write the release notes.\n"
    prev = preview(lib, [("Weekly sync 2026-10-09 10-00-00.txt", text.encode(), "text/plain")])
    [item] = prev["items"]
    assert item["kind"] == "transcript" and item["transcript_state"] == "imported"
    [res] = commit(lib, prev)["results"]
    detail = lib.client.get(f"/v1/meetingsense/library/item/{res['meeting_id']}").json()
    assert detail["item"]["transcript_state"] == "transcript_only"
    assert detail["item"]["media_present"] is False
    segs = detail["segments"]
    assert [(s["t0_ms"], s["speaker"], s["text"]) for s in segs] == [
        (5000, "Alice", "We ship on Friday."), (12000, "Bob", "I'll write the release notes.")]
    assert segs[0]["t1_ms"] == 12000
    [version] = detail["versions"]
    assert version["origin"] == "imported" and version["timing"] == "imported" and version["active"] == 1
    # Search finds it by what was said.
    found = lib.client.get("/v1/meetingsense/library", params={"q": "release notes"}).json()
    assert [i["meeting_id"] for i in found["items"]] == [res["meeting_id"]]
    # Index + summary were queued (no jobs run here).
    assert {j["type"] for j in lib.db.list_jobs(meeting_id=res["meeting_id"])} == {"index", "summarize"}


def test_srt_and_vtt_keep_their_times_and_speakers(lib):
    from app.meetingsense.library import parsers

    srt = "1\n00:00:01,000 --> 00:00:03,500\nAlice: Hello there\n\n2\n00:00:04,000 --> 00:00:06,000\nGeneral Kenobi\n"
    p = parsers.parse_transcript("a.srt", srt.encode())
    assert [(s["t0_ms"], s["t1_ms"], s["speaker"], s["text"]) for s in p.segments] == [
        (1000, 3500, "Alice", "Hello there"), (4000, 6000, None, "General Kenobi")]
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.000\n<v Bob>Hi</v>\n\n00:00:03.000 --> 00:00:04.000\nThere\n"
    v = parsers.parse_transcript("a.vtt", vtt.encode())
    assert [(s["t0_ms"], s["speaker"], s["text"]) for s in v.segments] == [(1000, "Bob", "Hi"), (3000, None, "There")]
    whisper = {"segments": [{"start": 0.0, "end": 1.5, "text": " one"}, {"start": 1.5, "end": 2.0, "text": "two"}]}
    w = parsers.parse_transcript("a.json", json.dumps(whisper).encode())
    assert w.timing == "imported" and [s["t1_ms"] for s in w.segments] == [1500, 2000]
    empty = parsers.parse_transcript("audio_asr_total.json", b'{"Result_info": []}')
    assert empty.usable is False and empty.segments == []


def test_titles_drop_the_timestamp_but_keep_the_words():
    from app.meetingsense.library.adapters import display_title, time_from_name

    assert display_title("Design Review 2026-02-10 13-00-00") == "Design Review"
    assert display_title("2026_10_10 12∶31∶51") == "Imported meeting · Oct 10, 12:31"
    assert display_title("2026-03-02 09-15-00", fallback_prefix="Recording") == "Recording · Mar 2, 09:15"
    assert display_title("weekly sync (2026-02-27 09-30-00)") == "weekly sync"
    assert display_title("Kickoff notes") == "Kickoff notes"
    assert time_from_name("Design Review 2026-02-10 13-00-00").hour == 13


@needs_ffmpeg
def test_an_mp3_with_speech_is_queued_then_transcribed_locally_without_duplicated_overlap(lib, monkeypatch, tmp_path):
    monkeypatch.setenv("MEETINGS_STT_CHUNK_S", "30")
    audio = ffmpeg_audio(tmp_path / "Client call 2026-10-08 14-00-00.mp3", seconds=70, silent=False)
    prev = preview(lib, [(audio.name, audio.read_bytes(), "audio/mpeg")])
    [item] = prev["items"]
    assert item["transcript_state"] == "needs_transcription"
    assert prev["totals"]["audio_minutes_to_transcribe"] == pytest.approx(1.2, abs=0.1)
    [res] = commit(lib, prev)["results"]
    mid = res["meeting_id"]
    assert res["transcript_state"] == "queued"
    states = run_jobs(lib)
    assert states[0] == ("transcribe", "done")
    assert len(lib.fake.calls) == 3                                   # 70 s in 30 s chunks
    segs = lib.store.get_segments(mid)
    starts = [s["t0_ms"] for s in segs]
    assert starts == sorted(starts)                                   # monotonic
    texts = [s["text"] for s in segs]
    assert len(texts) == len(set(texts))
    assert "Part 2 begins." not in texts                              # the overlap was heard once
    assert all(s["speaker"] is None for s in segs)                    # no invented speakers
    entry = lib.db.get_entry(mid)
    assert entry["transcript_state"] == "ready"
    versions = lib.db.list_versions(mid)
    assert versions[-1]["origin"] == "stt" and versions[-1]["provider"] == "fake-local"
    assert {"index", "summarize"} <= {t for t, _ in states}


@needs_ffmpeg
def test_without_local_speech_the_recording_waits_with_a_setup_hint(lib, monkeypatch, tmp_path):
    class Missing:
        name = "none"
        available = False

    monkeypatch.setattr(lib.jobs, "_get_provider", lambda: Missing())
    monkeypatch.setattr(lib.jobs, "stt_setup_hint", lambda: {"available": False, "hint": "Install local speech."})
    audio = ffmpeg_audio(tmp_path / "talk.mp3", seconds=3, silent=False)
    [res] = commit(lib, preview(lib, [(audio.name, audio.read_bytes(), "audio/mpeg")]))["results"]
    assert run_jobs(lib) == [("transcribe", "needs_setup")]
    assert lib.db.get_entry(res["meeting_id"])["transcript_state"] == "needs_setup"
    [job] = lib.db.list_jobs(meeting_id=res["meeting_id"])
    assert job["error"] == "Install local speech." and job["state"] == "needs_setup"
    # The recording is still there and plays (with ranges, so the player can seek).
    detail = lib.client.get(f"/v1/meetingsense/library/item/{res['meeting_id']}").json()
    aid = next(a["id"] for a in detail["assets"] if a["kind"] == "audio")
    r = lib.client.get(f"/v1/meetingsense/library/item/{res['meeting_id']}/media/{aid}",
                       headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100 and r.headers["content-range"].startswith("bytes 0-99/")


# ── safety ──────────────────────────────────────────────────────────────────


def test_an_archive_that_escapes_its_folder_is_refused(lib):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.txt", "x")
    r = lib.client.post("/v1/meetingsense/imports/preview", files=[("files", ("bad.zip", buf.getvalue(), "application/zip"))])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unsafe_archive"
    assert not (lib.tmp / "evil.txt").exists()


def test_files_with_nothing_to_import_are_refused_with_a_reason(lib):
    r = lib.client.post("/v1/meetingsense/imports/preview", files=[("files", ("photo.png", b"\x89PNG...", "image/png"))])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "nothing_found"


# ── the unified list ────────────────────────────────────────────────────────


def test_live_meetings_and_imports_are_listed_once_with_their_projects(lib, monkeypatch):
    import app.meetingsense.library.projection as projection

    lib.db.migrate()
    live = lib.store.create_meeting(conversation_id="c1", project_id="p1", title="Architecture Review")
    lib.store.add_segments(live, [{"t0_ms": 0, "text": "We adopt a modular architecture."}])
    lib.store.end_meeting(live)
    sched = lib.client.post("/v1/meetingsense/library/meetings",
                            json={"title": "Client Discovery Call", "scheduled_for": time.time() + 3600,
                                  "recording_plan": "external", "project_id": "p2"}).json()["meeting_id"]
    lib.db.set_project_links(live, ["p1", "p2"])
    monkeypatch.setattr(projection, "teams_items", lambda: [{
        "library_id": "teams_room:r1", "meeting_id": None, "origin_type": "teams_room", "origin_id": "r1",
        "title": "Team Retrospective", "description": "", "category": "Team Meeting", "started_at": 1.0,
        "ended_at": 2.0, "scheduled_for": None, "duration_ms": None, "projects": [],
        "source": {"kind": "teams_room", "label": "Teams room"}, "media_present": False,
        "recording_state": "none", "transcript_state": "transcript_only", "summary_state": "none",
        "segments": 6, "conversation_id": None, "status": "active", "live": False, "warnings": []}])
    body = lib.client.get("/v1/meetingsense/library").json()
    ids = [i["library_id"] for i in body["items"]]
    assert sorted(ids) == sorted([live, sched, "teams_room:r1"]) and len(ids) == len(set(ids))
    live_item = next(i for i in body["items"] if i["meeting_id"] == live)
    assert [p["name"] for p in live_item["projects"]] == ["HomePilot", "DayPilot"]
    assert live_item["transcript_state"] == "ready" and live_item["conversation_id"] == "c1"
    teams = next(i for i in body["items"] if i["origin_type"] == "teams_room")
    assert teams["media_present"] is False and teams["recording_state"] == "none"
    assert body["counts"]["project"] == 2 and body["counts"]["unsorted"] == 0
    by_project = lib.client.get("/v1/meetingsense/library", params={"project_id": "p2"}).json()
    assert sorted(i["meeting_id"] for i in by_project["items"]) == sorted([live, sched])
    # The live meeting's own row and column are untouched.
    assert lib.store.get_meeting(live)["project_id"] == "p1"


@needs_ffmpeg
def test_a_recording_near_a_scheduled_meeting_is_offered_as_its_recording(lib, tmp_path):
    lib.db.migrate()
    when = 1791628311.0
    sched = lib.client.post("/v1/meetingsense/library/meetings",
                            json={"title": "Board Prep", "scheduled_for": when - 300, "recording_plan": "external"}
                            ).json()["meeting_id"]
    folder = make_airecord(tmp_path / "src", silent=False)
    prev = preview(lib, [(f"{NAME}.zip", zip_dir(folder), "application/zip")])
    [item] = prev["items"]
    assert item["outcome"] == "attach" and item["attach_to"] == sched
    [res] = commit(lib, prev)["results"]
    assert res["status"] == "attached" and res["meeting_id"] == sched
    detail = lib.client.get(f"/v1/meetingsense/library/item/{sched}").json()
    assert detail["item"]["title"] == "Board Prep" and detail["item"]["recording_state"] == "present"
    assert detail["item"]["transcript_state"] == "queued"


# ── transcript versions ─────────────────────────────────────────────────────


def test_publishing_another_version_keeps_the_live_transcript(lib):
    lib.db.migrate()
    mid = lib.store.create_meeting(conversation_id="c1", title="Sync")
    lib.store.add_segments(mid, [{"t0_ms": 0, "text": "original line"}])
    lib.store.end_meeting(mid)
    r = lib.client.post(f"/v1/meetingsense/library/item/{mid}/versions",
                        json={"segments": [{"t0_ms": 0, "text": "corrected line", "speaker": "Alice"}]})
    assert r.status_code == 201
    versions = r.json()["versions"]
    assert [v["origin"] for v in versions] == ["live", "edit"]
    assert [s["text"] for s in lib.store.get_segments(mid)] == ["corrected line"]
    live_v = versions[0]["id"]
    lib.client.post(f"/v1/meetingsense/library/item/{mid}/versions/{live_v}/publish")
    assert [s["text"] for s in lib.store.get_segments(mid)] == ["original line"]
    txt = lib.client.get(f"/v1/meetingsense/library/item/{mid}/transcript", params={"fmt": "vtt"})
    assert txt.status_code == 200 and txt.text.startswith("WEBVTT") and "original line" in txt.text


# ── folder sync ─────────────────────────────────────────────────────────────


def test_a_windows_path_is_the_wsl_mount_and_nothing_is_read_without_an_allowed_root(lib, monkeypatch, tmp_path):
    from app.meetingsense.library import sync

    if os.name != "nt":
        assert sync.server_path("D:\\AIRecord") == "/mnt/d/AIRecord"
        assert sync.server_path("d:/AIRecord/sub") == "/mnt/d/AIRecord/sub"
    r = lib.client.post("/v1/meetingsense/sync-sources", json={"path": str(tmp_path)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "sync_not_enabled"
    allowed = tmp_path / "AIRecord"
    allowed.mkdir()
    monkeypatch.setenv("MEETINGS_SYNC_ALLOWED_ROOTS", str(allowed))
    outside = tmp_path / "Documents"
    outside.mkdir()
    r = lib.client.post("/v1/meetingsense/sync-sources", json={"path": str(outside)})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_allowed"
    r = lib.client.post("/v1/meetingsense/sync-sources", json={"path": str(allowed / ".." / "Documents")})
    assert r.status_code == 403                                      # no escaping with ..


@needs_ffmpeg
def test_folder_sync_imports_finished_recordings_once_and_leaves_the_source_alone(lib, monkeypatch, tmp_path):
    root = tmp_path / "AIRecord"
    root.mkdir()
    monkeypatch.setenv("MEETINGS_SYNC_ALLOWED_ROOTS", str(root))
    folder = make_airecord(root, silent=False)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}
    source = lib.client.post("/v1/meetingsense/sync-sources", json={"path": str(root)}).json()["source"]
    assert "resolved_path" not in source
    first = lib.client.post(f"/v1/meetingsense/sync-sources/{source['id']}/scan").json()["counts"]
    assert first["imported"] == 1 and first["failed"] == 0
    second = lib.client.post(f"/v1/meetingsense/sync-sources/{source['id']}/scan").json()["counts"]
    assert second["imported"] == 0 and second["already"] == 1
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()} == before
    items = lib.client.get("/v1/meetingsense/library", params={"tab": "imported"}).json()["items"]
    assert len(items) == 1 and items[0]["origin_type"] == "sync"
    # A recording still being written waits for the next scan.
    monkeypatch.setenv("MEETINGS_SYNC_STABILITY_S", "3600")
    ffmpeg_audio(root / "fresh 2026-10-11 09-00-00.mp3", seconds=2, silent=False)
    third = lib.client.post(f"/v1/meetingsense/sync-sources/{source['id']}/scan").json()["counts"]
    assert third["waiting"] == 1 and third["imported"] == 0
    # The original disappears: the meeting stays, marked unavailable at the source.
    shutil.rmtree(folder)
    lib.client.post(f"/v1/meetingsense/sync-sources/{source['id']}/scan")
    detail = lib.client.get(f"/v1/meetingsense/library/item/{items[0]['meeting_id']}").json()
    audio = next(a for a in detail["assets"] if a["kind"] == "audio")
    assert audio["source_available"] is False
    # Disconnecting the folder keeps its meetings.
    assert lib.client.delete(f"/v1/meetingsense/sync-sources/{source['id']}").json()["ok"] is True
    assert lib.client.get("/v1/meetingsense/library").json()["total"] == 1


# ── deletion ────────────────────────────────────────────────────────────────


def test_remove_hides_and_delete_removes_the_copies(lib):
    prev = preview(lib, [("notes 2026-10-01 09-00-00.md", b"# Notes\n\nWe agreed.", "text/markdown")])
    [res] = commit(lib, prev)["results"]
    mid = res["meeting_id"]
    folder = lib.tmp / "media" / mid
    assert folder.is_dir()
    lib.client.delete(f"/v1/meetingsense/library/item/{mid}", params={"mode": "remove"})
    assert lib.client.get("/v1/meetingsense/library").json()["total"] == 0
    assert lib.store.get_meeting(mid) is not None                    # hidden, not deleted
    r = lib.client.delete(f"/v1/meetingsense/library/item/{mid}", params={"mode": "delete"}).json()
    assert r["removed"]["files"] >= 1 and not folder.exists()
    assert lib.store.get_meeting(mid) is None


def test_an_outline_without_a_model_is_not_reported_as_a_summary(lib, monkeypatch):
    from app.meetingsense import minutes

    prev = preview(lib, [("Sync 2026-02-27 09-30-00.txt", b"[00:00:04] Anna: Beta shipped.\n[00:01:00] Tom: Thanks.\n", "text/plain")])
    [res] = commit(lib, prev)["results"]
    mid = res["meeting_id"]
    lib.store.save_notes(mid, {"summary": "", "actions": []})  # keep the notes engine out of it

    outline = {"text": "*No language model was reachable, so this is assembled from the meeting's own words "
                       "rather than written.*\n\n## The meeting in order\n\n**00:00–00:01** — Beta shipped.",
               "degraded": "extractive"}

    async def no_model(meeting_id, *, call=None, options=None):
        return outline

    monkeypatch.setattr(minutes, "autogenerate", no_model)
    assert ("summarize", "done") in run_jobs(lib)  # queued by the import
    assert lib.db.get_entry(mid)["summary_state"] == "unavailable"

    async def written(meeting_id, *, call=None, options=None):
        return {"text": "The beta shipped to 40 testers.", "degraded": None}

    monkeypatch.setattr(minutes, "autogenerate", written)
    lib.db.create_job(mid, "summarize")
    assert run_jobs(lib) == [("summarize", "done")]
    assert lib.db.get_entry(mid)["summary_state"] == "ready"


def test_ask_without_a_model_quotes_the_lines_that_match_the_question(lib, monkeypatch):
    import app.meetingsense.notes_engine as notes_engine

    async def no_model(*a, **k):
        raise RuntimeError("no model configured")

    monkeypatch.setattr(notes_engine, "call_model", no_model)
    lines = ["Good morning, this is the budget review.", "The beta goes out on Friday.",
             "We keep the current servers until the end of the quarter.",
             "I will send the updated cost estimate to finance by Wednesday.",
             "Please book a follow-up meeting for Tuesday.", "Thanks everyone."]
    body = "".join(f"[00:00:{i * 5:02d}] Host: {t}\n" for i, t in enumerate(lines)).encode()
    prev = preview(lib, [("Budget 2026-03-04 14-00-00.txt", body, "text/plain")])
    [res] = commit(lib, prev)["results"]
    r = lib.client.post(f"/v1/meetingsense/library/item/{res['meeting_id']}/ask", json={"text": "When is the cost estimate due?"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["degraded"] == "extractive"
    assert "cost estimate" in out["text"] and "00:00:15" in out["text"]
    assert "Thanks everyone" not in out["text"]
