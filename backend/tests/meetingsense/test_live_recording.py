"""A live meeting's own recording (``library/recording.py``): kept, playable, deleted with it.

Before this, "Record a call" kept the transcript and nothing else: every audio frame was
transcribed and dropped, and ``retention.keeps_audio`` said so in as many words. Now the
browser uploads the call's audio in pieces while it runs, and the library plays it back.

What is pinned here:

* **Who decides.** ``MEETINGSENSE_RETENTION``, when the operator set it, for everyone;
  otherwise each user, from Settings → Meetings, keeping the audio by default. The server
  tells the browser in ``ready`` and refuses pieces for a meeting that keeps only text.
* **The pieces are one file.** Appended strictly in order: a repeat is acknowledged and
  dropped, a gap is refused with the number expected, a first piece that is not audio is
  refused — nothing else can make a stitched recording play.
* **It ends up an ordinary recording.** Registered as the meeting's audio asset, streamed by
  the media route with byte ranges, carrying the offset that lines the transcript up with it,
  and removed with the meeting. A browser that never said "complete" still gets it finished.

Synthetic audio only (FFmpeg-generated tone). Tests that need FFmpeg skip without it.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="FFmpeg is not installed")


def opus_webm(path: Path, seconds: float = 3.0) -> bytes:
    """What Chrome's MediaRecorder produces: Opus in WebM."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-t", str(seconds),
                    "-i", "sine=frequency=440:sample_rate=48000", "-c:a", "libopus", "-b:a", "32k",
                    "-f", "webm", str(path)], check=True)
    return path.read_bytes()


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    import app.meetingsense.library.db as db
    import app.meetingsense.library.projection as projection
    import app.meetingsense.library.recording as recording
    import app.meetingsense.library.routes as lib_routes
    import app.meetingsense.store as store

    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_RETENTION", "MEETINGS_RECORDING_MAX_MB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEETINGS_LIBRARY_UPGRADE", "1")
    monkeypatch.setenv("MEETINGS_INTELLIGENCE", "0")
    monkeypatch.setenv("MEETINGS_LIBRARY_WORKER", "0")
    monkeypatch.setenv("MEETINGS_LIBRARY_DIR", str(tmp_path / "media"))
    dbfile = tmp_path / "meetings.sqlite3"

    def _connect():
        con = sqlite3.connect(dbfile)
        con.row_factory = sqlite3.Row
        return con

    monkeypatch.setattr(store, "_connect", _connect)
    store.migrate()
    db._migrated_paths.clear()
    monkeypatch.setattr(lib_routes, "_viewer", lambda a, s: "")
    monkeypatch.setattr(projection, "_projects_by_id", lambda: {})
    monkeypatch.setattr(projection, "teams_items", lambda: [])

    from app.meetingsense import router

    app = FastAPI()
    app.include_router(router)

    class Lib:
        pass

    out = Lib()
    out.client, out.db, out.store, out.recording, out.tmp = TestClient(app), db, store, recording, tmp_path
    out.client.get("/v1/meetingsense/library")  # migrates the library tables
    return out


def live_meeting(lib, *, retention="all", title="Launch review"):
    mid = lib.store.create_meeting(conversation_id="conv-1", title=title, retention=retention,
                                   started_at=time.time() - 10)
    return mid


def end(lib, mid, *, ago=0.0):
    lib.store.end_meeting(mid, ended_at=time.time() - ago)


def put(lib, mid, seq, data, **params):
    return lib.client.post(f"/v1/meetingsense/library/item/{mid}/recording", params={"seq": seq, **params},
                           content=data, headers={"content-type": "audio/webm;codecs=opus"})


def item(lib, mid):
    return lib.client.get(f"/v1/meetingsense/library/item/{mid}").json()


# ── who decides ─────────────────────────────────────────────────────────────


class TestWhoDecides:
    def test_unset_lets_each_user_choose_and_keeps_the_audio_by_default(self, monkeypatch):
        from app.meetingsense.config import load_config
        from app.meetingsense.retention import meeting_retention

        monkeypatch.delenv("MEETINGSENSE_RETENTION", raising=False)
        cfg = load_config()
        assert cfg.retention_locked is False
        assert meeting_retention(cfg, None) == "all"     # a client that does not say
        assert meeting_retention(cfg, True) == "all"
        assert meeting_retention(cfg, False) == "text"   # Settings → Meetings, switched off

    @pytest.mark.parametrize("policy", ["text", "text+frames", "all"])
    def test_an_operator_policy_wins_over_the_user(self, monkeypatch, policy):
        from app.meetingsense.config import load_config
        from app.meetingsense.retention import meeting_retention

        monkeypatch.setenv("MEETINGSENSE_RETENTION", policy)
        cfg = load_config()
        assert cfg.retention_locked is True
        assert meeting_retention(cfg, True) == policy
        assert meeting_retention(cfg, False) == policy

    def test_an_unreadable_policy_locks_to_the_least(self, monkeypatch):
        from app.meetingsense.config import load_config
        from app.meetingsense.retention import meeting_retention

        monkeypatch.setenv("MEETINGSENSE_RETENTION", "keep-it-all")
        assert meeting_retention(load_config(), True) == "text"

    def test_status_says_whether_the_choice_is_the_users(self, lib, monkeypatch):
        body = lib.client.get("/v1/meetingsense/status").json()
        assert body["retention"] == "all" and body["retention_policy"] is None
        monkeypatch.setenv("MEETINGSENSE_RETENTION", "text")
        body = lib.client.get("/v1/meetingsense/status").json()
        assert body["retention"] == "text" and body["retention_policy"] == "text"

    @pytest.mark.parametrize("keep, expected", [(None, True), (True, True), (False, False)])
    def test_ready_tells_the_browser_whether_to_record(self, lib, monkeypatch, keep, expected):
        import app.voice.providers as providers

        class STT:
            name, available, supports_segments = "stub", True, True

            async def transcribe_segments(self, data, *, fmt="wav", duration_s=None):
                return []

        monkeypatch.setattr(providers, "get_meeting_stt_provider", lambda: STT())
        frame = {"type": "start", "conversation_id": "conv-1"}
        if keep is not None:
            frame["keep_audio"] = keep
        with lib.client.websocket_connect("/v1/meetingsense/session") as ws:
            ws.send_json(frame)
            ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["recording"] == {"keep": expected}
        assert lib.store.get_meeting(ready["meeting_id"])["retention"] == ("all" if expected else "text")


# ── the pieces ──────────────────────────────────────────────────────────────


class TestPieces:
    def test_a_meeting_that_keeps_only_text_refuses_audio(self, lib):
        mid = live_meeting(lib, retention="text")
        r = put(lib, mid, 0, b"\x1a\x45\xdf\xa3" + b"\0" * 64)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_kept"
        assert not (lib.tmp / "media" / mid).exists()

    def test_the_first_piece_must_be_audio(self, lib):
        mid = live_meeting(lib)
        r = put(lib, mid, 0, b"<html>not audio</html>")
        assert r.status_code == 415

    def test_pieces_go_in_order_repeats_are_dropped_and_gaps_refused(self, lib):
        mid = live_meeting(lib)
        head = b"\x1a\x45\xdf\xa3" + b"\x01" * 60
        assert put(lib, mid, 0, head).json() == {"ok": True, "next_seq": 1}
        assert put(lib, mid, 1, b"\x02" * 40).json()["next_seq"] == 2
        again = put(lib, mid, 1, b"\x02" * 40).json()
        assert again["duplicate"] is True and again["next_seq"] == 2
        gap = put(lib, mid, 5, b"\x03" * 40)
        assert gap.status_code == 409 and gap.json()["detail"] == {
            "code": "out_of_order", "message": "A piece is missing before this one.", "expected": 2}
        part = lib.tmp / "media" / mid / "recording.webm.part"
        assert part.read_bytes() == head + b"\x02" * 40   # the repeat was not appended twice

    def test_a_piece_too_large_is_refused(self, lib, monkeypatch):
        mid = live_meeting(lib)
        monkeypatch.setattr(lib.recording, "CHUNK_MAX_BYTES", 100)
        assert put(lib, mid, 0, b"\x1a\x45\xdf\xa3" + b"\0" * 200).status_code == 413

    def test_the_tail_is_accepted_after_the_stop_but_not_much_later(self, lib):
        mid = live_meeting(lib)
        end(lib, mid, ago=5)
        assert put(lib, mid, 0, b"\x1a\x45\xdf\xa3" + b"\0" * 32).status_code == 200
        late = live_meeting(lib)
        end(lib, late, ago=lib.recording.TAIL_GRACE_S + 60)
        assert put(lib, late, 0, b"\x1a\x45\xdf\xa3" + b"\0" * 32).status_code == 410

    def test_a_stranger_cannot_add_to_someone_elses_meeting(self, lib, monkeypatch):
        import app.meetingsense.library.routes as lib_routes

        mid = live_meeting(lib)
        lib.db.ensure_entry(mid, owner_user_id="alice")
        monkeypatch.setattr(lib_routes, "_viewer", lambda a, s: "mallory")
        assert put(lib, mid, 0, b"\x1a\x45\xdf\xa3" + b"\0" * 32).status_code == 404


# ── the recording ───────────────────────────────────────────────────────────


@needs_ffmpeg
class TestRecording:
    def upload(self, lib, mid, data, pieces=3, offset_ms=1500):
        size = -(-len(data) // pieces)
        for seq in range(pieces):
            chunk = data[seq * size:(seq + 1) * size]
            params = {"offset_ms": offset_ms} if seq == 0 else {}
            assert put(lib, mid, seq, chunk, **params).status_code == 200

    def test_a_recorded_meeting_can_be_played_back_from_the_library(self, lib):
        data = opus_webm(lib.tmp / "call.webm")
        mid = live_meeting(lib)
        self.upload(lib, mid, data)
        assert item(lib, mid)["item"]["recording_state"] == "recording"   # still live
        end(lib, mid)
        assert item(lib, mid)["item"]["recording_state"] == "saving"      # the audio is arriving

        done = lib.client.post(f"/v1/meetingsense/library/item/{mid}/recording/complete").json()
        assert done["ok"] is True
        asset = done["asset"]
        assert asset["kind"] == "audio" and asset["mime"] == "audio/webm"
        assert asset["metadata"]["recorded"] == "live" and asset["metadata"]["offset_ms"] == 1500
        assert 2500 <= asset["media_duration_ms"] <= 3500
        assert asset["original_name"] == "Launch review.webm"

        body = item(lib, mid)
        assert body["item"]["recording_state"] == "present" and body["item"]["media_present"] is True
        assert [a["id"] for a in body["assets"]] == [asset["id"]]

        whole = lib.client.get(f"/v1/meetingsense/library/item/{mid}/media/{asset['id']}")
        assert whole.status_code == 200 and whole.content[:4] == b"\x1a\x45\xdf\xa3"
        ranged = lib.client.get(f"/v1/meetingsense/library/item/{mid}/media/{asset['id']}",
                                headers={"range": "bytes=0-99"})
        assert ranged.status_code == 206 and len(ranged.content) == 100
        peaks = lib.client.get(f"/v1/meetingsense/library/item/{mid}/media/{asset['id']}/peaks").json()
        assert max(peaks["peaks"]) > 0.5                                   # a tone, not silence

        again = lib.client.post(f"/v1/meetingsense/library/item/{mid}/recording/complete").json()
        assert again["asset"]["id"] == asset["id"]                          # idempotent
        assert put(lib, mid, 3, b"\0" * 10).json()["detail"]["code"] == "finalized"

    def test_a_browser_that_closed_mid_call_still_leaves_a_recording(self, lib):
        data = opus_webm(lib.tmp / "call.webm")
        mid = live_meeting(lib)
        self.upload(lib, mid, data)
        end(lib, mid)
        # Nothing said "complete". Too soon to call it finished…
        assert lib.recording.finalize_stale() == []
        # …but once the pieces have stopped, reading the library completes it.
        assert lib.recording.finalize_stale(now=time.time() + lib.recording.IDLE_FINALIZE_S + 5) == [mid]
        body = item(lib, mid)
        assert body["item"]["recording_state"] == "present"
        assert body["assets"][0]["kind"] == "audio"

    def test_deleting_the_meeting_deletes_the_recording(self, lib):
        data = opus_webm(lib.tmp / "call.webm")
        mid = live_meeting(lib)
        self.upload(lib, mid, data)
        end(lib, mid)
        lib.client.post(f"/v1/meetingsense/library/item/{mid}/recording/complete")
        folder = lib.tmp / "media" / mid
        assert (folder / "recording.webm").is_file()
        r = lib.client.delete(f"/v1/meetingsense/library/item/{mid}", params={"mode": "delete"}).json()
        assert r["removed"]["files"] >= 1 and not folder.exists()

    def test_the_legacy_delete_removes_it_too(self, lib):
        from app.meetingsense import retention

        data = opus_webm(lib.tmp / "call.webm")
        mid = live_meeting(lib)
        self.upload(lib, mid, data)
        end(lib, mid)
        lib.client.post(f"/v1/meetingsense/library/item/{mid}/recording/complete")
        result = retention.delete_meeting(mid)
        assert result["files"]["recording"] >= 1
        assert not (lib.tmp / "media" / mid).exists()
