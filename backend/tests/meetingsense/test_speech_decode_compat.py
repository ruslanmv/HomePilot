"""faster-whisper must be able to decode a recording with the PyAV that is installed.

Regression: an unpinned resolve picked PyAV 19.0.1, whose ``av.open`` no longer accepts the
``metadata_errors`` argument faster-whisper 1.2.1 passes. Every live meeting then failed
with "open() got an unexpected keyword argument 'metadata_errors'" and produced no
transcript. This decodes a tiny WAV through faster-whisper's own decoder, so a future
version drift fails here instead of in a meeting.
"""
import io
import struct
import wave

import pytest


def _silent_wav(seconds: float = 0.2, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(int(seconds * rate))))
    return buf.getvalue()


def test_faster_whisper_decodes_audio_with_the_installed_pyav(tmp_path):
    audio = pytest.importorskip("faster_whisper.audio")
    path = tmp_path / "tiny.wav"
    path.write_bytes(_silent_wav())
    samples = audio.decode_audio(str(path), sampling_rate=16000)
    assert len(samples) == pytest.approx(3200, abs=200)


def test_pyav_matches_the_pin():
    av = pytest.importorskip("av")
    import pathlib
    import tomllib

    backend = pathlib.Path(__file__).resolve().parents[2]
    extra = tomllib.loads((backend / "pyproject.toml").read_text())["project"]["optional-dependencies"]["whisper"]
    pinned = next(dep.split("==", 1)[1] for dep in extra if dep.startswith("av=="))
    assert av.__version__ == pinned, f"installed PyAV {av.__version__}, pinned {pinned}: run make install"
