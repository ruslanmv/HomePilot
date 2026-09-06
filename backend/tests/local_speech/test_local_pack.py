"""A model that is already on this machine (batch LS3).

The plan's acceptance, verbatim: *networking blocked, pack present, an 8-second WAV in →
transcript **with timestamps** out, and **zero** outbound sockets. That proves local rather than
documenting it.*

The last clause is the point. A feature can work offline today and start phoning home the first
time somebody swaps a model name back in for a directory, and nothing about the transcript would
look different. So the acceptance test runs the whole load-and-transcribe path inside
:func:`netguard.no_outbound`, which fails an outbound `connect` **or a DNS lookup** at the moment
it happens — a lookup being what a download does first, and therefore the most informative thing
to catch.

The engine is injected. Not as a testing shortcut: it is what lets this run on a machine with no
pack and no faster-whisper and still prove the claim about HomePilot's own code, which is the
only half of the claim HomePilot controls.
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import wave
from pathlib import Path

import pytest

from app.local_speech import manifest, models, netguard
from app.local_speech.provider import HomePilotLocalSTTProvider


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def eight_second_wav(path: Path, seconds: float = 8.0, rate: int = 16000) -> bytes:
    """A real WAV, so the engine under test is handed a file and not a promise."""
    frames = int(seconds * rate)
    samples = bytearray()
    for index in range(frames):
        # A quiet warble. Nothing here transcribes it; what matters is that it is a valid file
        # of the stated length, which is what a duration assertion rests on.
        value = int(3000 * ((index // 400) % 2 - 0.5) * 2)
        samples += struct.pack("<h", value)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(samples))
    return path.read_bytes()


def make_pack(root: Path, pack_id: str = "whisper-small", *, complete: bool = True) -> Path:
    directory = root / pack_id
    directory.mkdir(parents=True, exist_ok=True)
    names = list(manifest.REQUIRED) if complete else list(manifest.REQUIRED)[:-1]
    for name in names:
        (directory / name).write_bytes(b"pack-" + name.encode())
    return directory


class FakeSegment:
    def __init__(self, text, start, end):
        self.text, self.start, self.end = text, start, end


class FakeEngine:
    """Stands in for `WhisperModel`. Reads the file it is given, like the real one."""

    def __init__(self, directory, device="auto", compute_type="default", **kwargs):
        self.model_path = directory
        self.kwargs = kwargs
        # What a real engine reports back, which is the point of reading it rather than echoing.
        self.device = "cpu" if device == "auto" else device
        self.compute_type = "int8" if compute_type == "default" else compute_type
        self.seen = []

    def transcribe(self, path, **kwargs):
        self.seen.append((path, kwargs))
        with wave.open(path, "rb") as handle:
            duration = handle.getnframes() / float(handle.getframerate())
        segments = [
            FakeSegment(" Good morning everyone.", 0.0, duration / 3),
            FakeSegment(" Let's start with the roadmap.", duration / 3, 2 * duration / 3),
            FakeSegment(" Any objections?", 2 * duration / 3, duration),
        ]
        return iter(segments), {"duration": duration}


def provider(tmp_path, **kwargs):
    make_pack(tmp_path)
    return HomePilotLocalSTTProvider(
        environ={"HOMEPILOT_SPEECH_DIR": str(tmp_path)},
        engine_factory=kwargs.pop("engine_factory", FakeEngine),
        **kwargs,
    )


# ── the acceptance ──────────────────────────────────────────────────────────


def test_a_pack_on_disk_transcribes_with_timestamps_and_touches_no_network(tmp_path):
    audio = eight_second_wav(tmp_path / "meeting.wav")
    stt = provider(tmp_path)

    with netguard.no_outbound() as attempts:
        spans = run(stt.transcribe_segments(audio, fmt="wav"))

    assert attempts.clean, attempts.outbound
    assert len(spans) == 3
    assert spans[0]["text"].startswith("Good morning")

    # Timestamps, measured: monotonic, inside the clip, and covering it. And in the shape every
    # existing MeetingSense consumer already reads — `t0`/`t1`, not a type of this provider's own.
    assert spans[0]["t0"] == 0.0
    assert all(span["t1"] > span["t0"] for span in spans)
    assert all(later["t0"] >= earlier["t1"] - 1e-6 for earlier, later in zip(spans, spans[1:]))
    assert 7.9 <= spans[-1]["t1"] <= 8.1
    assert set(spans[0]) == {"t0", "t1", "text", "conf"}


def test_the_plain_transcript_path_is_equally_offline(tmp_path):
    audio = eight_second_wav(tmp_path / "meeting.wav")
    stt = provider(tmp_path)
    with netguard.no_outbound() as attempts:
        text = run(stt.transcribe(audio, fmt="wav"))
    assert attempts.clean
    assert "roadmap" in text


def test_the_guard_would_have_caught_a_download(tmp_path):
    """The acceptance is only worth anything if the guard can fail.

    A test that asserts "no sockets" with a guard that never fires proves nothing at all, so
    this drives the guard with the exact thing a model download does first.
    """
    class DownloadingEngine(FakeEngine):
        def __init__(self, directory, **kwargs):
            socket.getaddrinfo("huggingface.co", 443)
            super().__init__(directory, **kwargs)

    stt = provider(tmp_path, engine_factory=DownloadingEngine)
    with netguard.no_outbound() as attempts:
        loaded = stt.load()

    assert loaded is None, "a rung that dials out must not silently succeed"
    assert not attempts.clean
    assert "huggingface.co" in str(attempts.outbound)


def test_loopback_is_not_the_internet(tmp_path):
    # Ollama on this machine, a worker over a Unix socket: local, and not what the guard is for.
    with netguard.no_outbound() as attempts:
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", 9), timeout=0.05)
    assert attempts.clean


# ── a directory, never a name ───────────────────────────────────────────────


def test_the_engine_is_handed_a_directory_that_exists(tmp_path):
    stt = provider(tmp_path)
    engine = stt.load()
    assert engine is not None
    # The whole batch in one assertion: anything that is not an existing path is a name, and a
    # name handed to faster-whisper is a download.
    assert Path(engine.model_path).is_dir()


def test_and_it_is_told_not_to_look_anywhere_else(tmp_path):
    stt = provider(tmp_path)
    engine = stt.load()
    assert engine.kwargs.get("local_files_only") is True


def test_an_engine_that_predates_that_argument_still_only_gets_a_directory(tmp_path):
    class OldEngine(FakeEngine):
        def __init__(self, directory, device="auto", compute_type="default"):
            super().__init__(directory, device=device, compute_type=compute_type)

    stt = provider(tmp_path, engine_factory=OldEngine)
    engine = stt.load()
    assert engine is not None
    assert Path(engine.model_path).is_dir()


def test_no_pack_is_a_sentence_rather_than_a_crash(tmp_path):
    stt = HomePilotLocalSTTProvider(environ={"HOMEPILOT_SPEECH_DIR": str(tmp_path / "empty")},
                                    engine_factory=FakeEngine)
    assert stt.available is False
    assert stt.load() is None
    assert stt.load_error == "pack-not-installed"
    assert run(stt.transcribe(b"", fmt="wav")) == ""


def test_an_explicit_directory_wins_over_the_root(tmp_path):
    # An operator with packs on a shared volume should not have to move them.
    elsewhere = make_pack(tmp_path / "volume", "whisper-base")
    resolved = models.resolve({"HOMEPILOT_SPEECH_PACK": str(elsewhere),
                               "HOMEPILOT_SPEECH_DIR": str(tmp_path)})
    assert resolved.ok
    assert resolved.directory == elsewhere
    assert resolved.pack.id == "whisper-base"


def test_the_best_installed_pack_is_preferred_not_the_best_pack(tmp_path):
    # Ranking among what is *installed* is never a claim that anything should be downloaded.
    make_pack(tmp_path, "whisper-base")
    make_pack(tmp_path, "whisper-small")
    resolved = models.resolve({"HOMEPILOT_SPEECH_DIR": str(tmp_path)})
    assert resolved.pack.id == "whisper-small"
    assert "whisper-large-v3-turbo" not in [item.pack.id for item in models.installed({"HOMEPILOT_SPEECH_DIR": str(tmp_path)})]


def test_a_named_preference_is_honoured(tmp_path):
    make_pack(tmp_path, "whisper-base")
    make_pack(tmp_path, "whisper-small")
    resolved = models.resolve({"HOMEPILOT_SPEECH_DIR": str(tmp_path),
                               "HOMEPILOT_SPEECH_PACK_ID": "whisper-base"})
    assert resolved.pack.id == "whisper-base"


# ── the pack is the pack ────────────────────────────────────────────────────


def test_an_incomplete_pack_is_incomplete_not_missing(tmp_path):
    # The fix is different: one is a finished download, the other is a broken one.
    make_pack(tmp_path, "whisper-small", complete=False)
    resolved = models.resolve({"HOMEPILOT_SPEECH_DIR": str(tmp_path)})
    assert resolved.reason == "incomplete"
    assert resolved.ok is False


def test_a_pack_with_no_digests_is_unverified_not_verified(tmp_path):
    # A build nobody has hashed must never masquerade as one that passed.
    directory = make_pack(tmp_path)
    report = manifest.verify(directory, manifest.PACKS_BY_ID["whisper-small"])
    assert report.unverified is True
    assert report.verified is False
    assert report.usable is True


def test_a_pack_whose_digest_is_wrong_is_never_loaded(tmp_path):
    directory = make_pack(tmp_path)
    pinned = manifest.Pack(
        id="whisper-small", label="x", source_model="y", source_revision="z", license="MIT",
        size_mb=1, digests={"model.bin": "0" * 64},
    )
    report = manifest.verify(directory, pinned)
    assert report.mismatched == ["model.bin"]
    assert report.usable is False
    assert report.reason() == "corrupt"


def test_a_matching_digest_verifies(tmp_path):
    directory = make_pack(tmp_path)
    digest = manifest.sha256(directory / "model.bin")
    pinned = manifest.Pack(
        id="whisper-small", label="x", source_model="y", source_revision="z", license="MIT",
        size_mb=1, digests={"model.bin": digest},
    )
    report = manifest.verify(directory, pinned)
    assert report.verified is True
    assert report.reason() == "ok"


def test_every_pack_carries_its_provenance_and_its_licence():
    # A pack whose provenance is "whisper, probably" is one nobody can reproduce or audit.
    for pack in manifest.PACKS:
        assert pack.source_model and "/" in pack.source_model
        assert pack.license
        assert pack.size_mb > 0


def test_the_size_comes_from_the_manifest_so_the_ui_cannot_hard_code_it():
    # Conversion and quantisation change the footprint; any figure typed into the interface is
    # wrong the first time the pack is rebuilt (LS4).
    assert {pack.id: pack.size_mb for pack in manifest.PACKS}


# ── what it reports ─────────────────────────────────────────────────────────


def test_the_device_is_read_back_rather_than_echoed(tmp_path):
    # `auto` falling back to CPU silently is the failure LS5's acceptance is built around, and it
    # is invisible unless the answer comes from the engine.
    stt = provider(tmp_path)
    assert stt.status()["device"] is None, "not loaded is not the same as loaded on CPU"
    stt.load()
    assert stt.requested_device == "auto"
    assert stt.status()["device"] == "cpu"


def test_warming_is_idempotent_and_visible(tmp_path):
    stt = provider(tmp_path)
    assert stt.warm is False
    assert stt.warm_up() is True
    assert stt.warm_up() is True
    assert stt.warm is True


def test_meetingsense_never_learns_what_is_underneath(tmp_path):
    from app.voice.providers import STTProvider

    stt = provider(tmp_path)
    assert isinstance(stt, STTProvider)
    # The seam: everything MeetingSense needs is on the base class.
    for attribute in ("transcribe", "transcribe_segments", "available", "supports_segments"):
        assert hasattr(STTProvider, attribute)


def test_meetingsense_is_told_the_second_vad_is_off_for_this_path(tmp_path):
    # MeetingSense has already decided where each utterance begins and ends; a second VAD can
    # trim audio at exactly those boundaries, which is how a final line loses its first word.
    audio = eight_second_wav(tmp_path / "m.wav")
    stt = provider(tmp_path)
    run(stt.transcribe_segments(audio, fmt="wav"))
    _path, kwargs = stt._engine.seen[-1]
    assert kwargs["vad_filter"] is False
    assert kwargs["word_timestamps"] is True


def test_the_status_payload_is_json(tmp_path):
    stt = provider(tmp_path)
    json.dumps(stt.status())
