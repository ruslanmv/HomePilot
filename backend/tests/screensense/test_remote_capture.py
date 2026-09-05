"""Remote screen capture (batch RS1).

Four claims carry this batch, and each has a test that fails when it stops holding:

* **the sharing tab is tried first.** Path B — photographing the desktop with no browser in
  the way — can satisfy every request path A can, so if the order ever flips, the browser's
  own "Sharing your screen" bar stops being the thing that tells a user a picture was taken.
  That ordering is not a preference, it is the consent story;
* **path B is off until somebody says otherwise, on the machine being photographed.** Not
  from the cloud, not from the chat, not by a request;
* **a frame dies.** Past its TTL it is a 404 whether or not the sweep has run, and the file
  is gone from disk even across a restart that emptied the in-memory index;
* **"explain" reads a frame that already exists.** It never captures.

The rate limiter gets its own tests because it is the difference between a screenshot
feature and a video feed nobody agreed to.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.screensense import broker, capture as capture_mod, config, frames
from app.screensense import routes


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


#: The smallest thing that parses as a JPEG well enough for the size reader to try.
JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000") + b"\x00" * 64


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    # `config` reads UPLOAD_DIR through `app.config`, which resolved it at import. Point the
    # frames directory at the tmp path directly rather than reloading half the app.
    monkeypatch.setattr(config, "frames_dir", lambda: tmp_path / "screensense")
    (tmp_path / "screensense").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOMEPILOT_DEVICE_NAME", "Home PC")
    monkeypatch.delenv("HOMEPILOT_REMOTE_CAPTURE", raising=False)
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE_MIN_INTERVAL_S", "0")
    frames.reset()
    broker.reset()
    capture_mod.reset()
    yield
    frames.reset()
    broker.reset()
    capture_mod.reset()


# ── the flag ────────────────────────────────────────────────────────────────


def test_headless_capture_is_off_by_default():
    assert config.headless_allowed() is False
    data, why = capture_mod.grab()
    assert data is None
    assert why == "disabled"


def test_the_flag_is_local_only(monkeypatch):
    # There is no route, body field or header in this package that sets it. The only way in
    # is the environment of the process being photographed.
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE", "true")
    assert config.headless_allowed() is True
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE", "false")
    assert config.headless_allowed() is False


def test_a_refusal_names_the_machine_the_fix_is_on():
    cap = routes._capability()
    message = routes._explain("disabled", cap)
    assert "Home PC" in message
    # No status codes, no env var names, no tracebacks in something a person reads.
    assert "409" not in message
    assert "HOMEPILOT_REMOTE_CAPTURE" not in message


# ── the order of the two mechanisms ─────────────────────────────────────────


def test_the_sharing_tab_is_asked_before_the_desktop_is_photographed(monkeypatch):
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE", "true")
    grabbed = {"count": 0}

    def never(*_a, **_k):
        grabbed["count"] += 1
        return JPEG, "ok"

    monkeypatch.setattr(capture_mod, "grab", never)

    # A tab is listening and answers.
    broker.agent_seen()

    async def scenario():
        task = asyncio.ensure_future(routes.capture(routes.CaptureIn()))
        # Wait for the request to be queued, then answer it as the tab would.
        for _ in range(100):
            job = await broker.poll(0.5)
            if job:
                broker.deliver(job["request_id"], JPEG)
                break
        return await task

    response = run(scenario())
    assert response.status_code == 200
    # The desktop grabber was never reached — which is the whole consent argument.
    assert grabbed["count"] == 0


def test_falls_through_to_the_desktop_when_no_tab_is_listening(monkeypatch):
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE", "true")
    monkeypatch.setattr(capture_mod, "grab", lambda *_a, **_k: (JPEG, "ok"))
    assert broker.agent_present() is False

    response = run(routes.capture(routes.CaptureIn()))
    assert response.status_code == 200


def test_with_neither_mechanism_it_refuses_in_words():
    response = run(routes.capture(routes.CaptureIn()))
    assert response.status_code == 409
    body = response.body.decode()
    assert "Home PC" in body
    assert "off on" in body


def test_a_tab_that_stopped_polling_is_not_there(monkeypatch):
    broker.agent_seen(now=time.time() - config.agent_fresh_s() - 1)
    assert broker.agent_present() is False
    # And a capture does not wait out the agent timeout for it.
    started = time.time()
    run(routes.capture(routes.CaptureIn()))
    assert time.time() - started < config.agent_wait_s()


# ── the frame's lifetime ────────────────────────────────────────────────────


def test_a_frame_is_readable_then_it_is_not(monkeypatch):
    frame = frames.store(JPEG, "share")
    assert frames.get(frame.frame_id) is not None

    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE_TTL_S", "30")
    # Move the frame's own creation back past the TTL rather than waiting 30 seconds.
    frames._index[frame.frame_id] = frame.__class__(
        **{**frame.__dict__, "created": time.time() - 31}
    )
    assert frames.get(frame.frame_id) is None
    assert not frame.path.exists()


def test_the_sweep_deletes_by_file_age_so_a_restart_still_cleans_up(monkeypatch):
    frame = frames.store(JPEG, "share")
    path = frame.path
    # A restart: the index is empty, the file is not. Without a filesystem sweep this
    # screenshot of somebody's desktop would stay on disk forever.
    frames._index.clear()
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE_TTL_S", "30")
    import os

    os.utime(path, (time.time() - 60, time.time() - 60))
    frames.sweep()
    assert not path.exists()


def test_expired_and_never_existed_are_the_same_answer():
    # Telling them apart would let a caller ask this endpoint whether an id was ever issued.
    assert frames.get("neverexisted") is None
    assert frames.get("../../etc/passwd") is None
    assert frames.get("") is None


def test_the_frame_route_refuses_to_cache():
    frame = frames.store(JPEG, "share")
    response = run(routes.frame(frame.frame_id))
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]


# ── the rate limits ─────────────────────────────────────────────────────────


def test_the_interval_stops_a_loop_becoming_a_video_feed(monkeypatch):
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE_MIN_INTERVAL_S", "5")
    assert capture_mod.rate_check() is None
    capture_mod.record("share")
    denied = capture_mod.rate_check()
    assert denied and "Too soon" in denied


def test_the_hourly_cap_stops_a_patient_loop_doing_it_slowly(monkeypatch):
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE_HOURLY_CAP", "3")
    for _ in range(3):
        capture_mod.record("share")
    denied = capture_mod.rate_check()
    assert denied and "Hourly limit" in denied


def test_both_mechanisms_count_against_the_limit(monkeypatch):
    monkeypatch.setenv("HOMEPILOT_REMOTE_CAPTURE_HOURLY_CAP", "2")
    capture_mod.record("share")
    capture_mod.record("desktop")
    assert capture_mod.rate_check() is not None


def test_only_the_unindicated_mechanism_is_written_to_the_audit_log(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "audit_path", lambda: tmp_path / "audit.log")
    capture_mod.record("share")
    assert not (tmp_path / "audit.log").exists()
    capture_mod.record("desktop")
    assert "desktop-capture" in (tmp_path / "audit.log").read_text()


# ── explaining a frame ──────────────────────────────────────────────────────


def test_explain_reads_the_frame_it_was_given_and_captures_nothing(monkeypatch):
    frame = frames.store(JPEG, "share")
    seen = {}

    async def fake_analyze(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "analysis_text": "A code editor with an error.", "meta": {"model": "moondream"}}

    import app.multimodal as mm

    monkeypatch.setattr(mm, "analyze_image", fake_analyze)
    monkeypatch.setattr(capture_mod, "grab", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("captured")))

    response = run(routes.explain(routes.ExplainIn(frame_id=frame.frame_id, question="what do you see?")))
    assert response.status_code == 200
    # The bytes went straight to the model; nothing was staged on disk a second time.
    assert seen["image_b64"]
    assert seen["image_url"] == ""


def test_explain_on_an_expired_frame_asks_for_a_new_one():
    response = run(routes.explain(routes.ExplainIn(frame_id="deadbeef", question="?")))
    assert response.status_code == 404
    assert "expired" in response.body.decode()


def test_capability_answers_even_when_nothing_here_can_take_a_picture():
    # A 404 would collapse "too old to know what you are asking", "switched off" and "ready"
    # into one shrug. Each has a different sentence and a different fix.
    cap = routes._capability()
    assert cap["ok"] is True
    assert cap["available"] is False
    assert cap["reason"] == "disabled"
    assert cap["device"] == "Home PC"
