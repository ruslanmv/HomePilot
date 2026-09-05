"""Nothing reaches disk, and nothing reaches a log (spec v1.1 §6.13, batch B15).

``frames.retention: 0`` is easy to write in a config and hard to mean. This file is the
part that means it: a real insight request runs against a stubbed model while the
filesystem and every log stream in the process are watched, and the assertions are that
neither of them saw the frame or the answer.

The observation is deliberately broad rather than targeted. Checking that *this module*
does not call ``open`` would prove nothing about the module it calls; instead ``open``,
``Path.write_bytes``, ``Path.write_text`` and ``os.replace`` are patched process-wide for
the duration of the request, so a write from anywhere below fails the test. Logging is
captured at the root with propagation on, for the same reason.

What is *not* claimed: that the model provider stores nothing. A hosted API is somebody
else's disk and this cannot speak for it — which is why §6.2's default is a local model and
why the config names one explicitly rather than defaulting to a service.
"""

from __future__ import annotations

import asyncio
import base64
import builtins
import logging
import os
import struct
from pathlib import Path

import pytest

from app.avatar_director.config import AvatarDirectorConfig, VisionConfig
from app.avatar_director.vision import VisionService

#: A recognisable needle. If any of these bytes reach a file or a log line, the test says so.
NEEDLE = b"NEXUS_SECRET_PIXELS_DO_NOT_PERSIST"
ANSWER = "A spreadsheet with the client's revenue in it."


def frame() -> bytes:
    """A JPEG header with the needle stuffed into a comment segment, so the payload is
    both a valid frame and something a grep can find."""
    comment = b"\xff\xfe" + struct.pack(">H", len(NEEDLE) + 2) + NEEDLE
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 288, 512) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + comment + sof0 + b"\xff\xd9"


class Watcher:
    """Every write the process attempts, and every log line it emits, while armed."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.records: list[str] = []

    def arm(self, monkeypatch, caplog) -> None:
        real_open = builtins.open

        def watched_open(file, mode="r", *args, **kwargs):
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                self.writes.append(f"open({file!r}, {mode!r})")
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", watched_open)
        monkeypatch.setattr(Path, "write_bytes", lambda self, data: self_record(self, "write_bytes"))
        monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: self_record(self, "write_text"))
        monkeypatch.setattr(os, "replace", lambda src, dst: self.writes.append(f"os.replace({src!r})"))

        def self_record(path, what):
            self.writes.append(f"{what}({path!r})")
            return 0

        caplog.set_level(logging.DEBUG)
        self.caplog = caplog

    @property
    def logged(self) -> str:
        return "\n".join(record.getMessage() for record in self.caplog.records)


def service(answer: str = ANSWER, *, fail=None) -> VisionService:
    async def analyze(**kwargs):
        if fail is not None:
            raise fail
        return {"ok": True, "analysis_text": answer}

    return VisionService(
        AvatarDirectorConfig(enabled=True, vision=VisionConfig(model="moondream", max_image_px=768)),
        analyze=analyze,
    )


def run_insight(svc, raw=None, prompt="what is this?"):
    return asyncio.run(svc.insight(base64.b64encode(raw or frame()).decode("ascii"), prompt))


# ── the retention proof ──────────────────────────────────────────────────────


def test_a_complete_insight_writes_no_file(monkeypatch, caplog):
    watcher = Watcher()
    watcher.arm(monkeypatch, caplog)

    result = run_insight(service())

    assert result["text"] == ANSWER
    assert watcher.writes == [], f"something wrote to disk: {watcher.writes}"


def test_and_logs_neither_the_frame_nor_the_answer(monkeypatch, caplog):
    watcher = Watcher()
    watcher.arm(monkeypatch, caplog)

    run_insight(service())

    logged = watcher.logged
    assert NEEDLE.decode("ascii") not in logged
    assert ANSWER not in logged
    assert "image_b64" not in logged
    # A base64 blob in a log line is the same leak wearing a hat.
    assert not any(len(line) > 400 for line in logged.split("\n"))


def test_the_service_holds_nothing_once_the_answer_is_returned(monkeypatch, caplog):
    watcher = Watcher()
    watcher.arm(monkeypatch, caplog)

    svc = service()
    run_insight(svc)

    held = repr(vars(svc)) + repr(vars(svc.stats))
    assert NEEDLE.decode("ascii") not in held
    assert ANSWER not in held
    # The only things kept are counters.
    assert svc.stats.asks == 1


def test_ten_asks_leave_ten_times_nothing(monkeypatch, caplog):
    # A per-request leak is obvious; a cache that fills up over a session is not.
    watcher = Watcher()
    watcher.arm(monkeypatch, caplog)

    svc = service()
    for _ in range(10):
        run_insight(svc)

    assert watcher.writes == []
    assert svc.stats.asks == 10
    assert NEEDLE.decode("ascii") not in repr(vars(svc))


def test_a_failing_model_leaks_nothing_on_the_error_path(monkeypatch, caplog):
    # The error path is where a frame usually ends up in a log, attached to a traceback
    # someone added while debugging.
    watcher = Watcher()
    watcher.arm(monkeypatch, caplog)

    with pytest.raises(Exception):
        run_insight(service(fail=RuntimeError(f"model choked on {NEEDLE.decode('ascii')}")))

    assert watcher.writes == []
    # The exception's own text is the model's, and it is the caller's to handle; what must
    # not happen is this module logging it.
    assert NEEDLE.decode("ascii") not in watcher.logged


def test_an_oversize_frame_is_refused_without_touching_anything(monkeypatch, caplog):
    watcher = Watcher()
    watcher.arm(monkeypatch, caplog)

    big = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 4000, 3000) + b"\x08\x02" * 4
    with pytest.raises(Exception):
        run_insight(service(), raw=big)

    assert watcher.writes == []


# ── the shape that makes it true ─────────────────────────────────────────────


def test_the_module_has_nowhere_to_put_a_frame():
    """The structural half. Retention is 0 because there is no store, not because a policy
    says so — and a later batch that adds one has to get past this test to do it."""
    source = Path(__file__).resolve().parents[2] / "app" / "avatar_director" / "vision.py"
    body = source.read_text(encoding="utf-8").split('"""', 2)[2]

    for forbidden in ("open(", "Path(", "write_bytes", "write_text", "tempfile", "NamedTemporary", "upload_path"):
        assert forbidden not in body, f"vision.py names {forbidden}"


def test_the_config_default_is_zero_and_is_the_one_shipped(monkeypatch):
    for name in ("AVATAR_FRAMES_RETENTION", "AVATAR_VISION_MAX_IMAGE_PX"):
        monkeypatch.delenv(name, raising=False)
    from app.avatar_director import load_config

    cfg = load_config()
    assert cfg.frames.retention == 0
    assert cfg.vision.max_image_px == 768


def test_a_retention_typo_cannot_widen_it(monkeypatch):
    # "lots" must not become "keep everything". The config falls back to the safe value.
    monkeypatch.setenv("AVATAR_FRAMES_RETENTION", "lots")
    from app.avatar_director import load_config

    assert load_config().frames.retention == 0
