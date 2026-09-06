"""The seam MeetingSense talks to (batch LS3).

``HomePilotLocalSTTProvider`` is a :class:`~app.voice.providers.STTProvider`, and that is the
whole of what MeetingSense may know about it. Not CTranslate2, not Metal, not Vulkan, not
whatever replaces them in 2028. A meeting feature that has learned the name of its inference
runtime is a meeting feature that has to be rewritten when the runtime changes.

Two things distinguish it from LS1's :class:`WhisperLocalSTTProvider`, which stays exactly where
it is and keeps working:

* **it loads a directory, never a name.** :mod:`models` resolves a pinned pack; a name would be a
  download, and a download at the moment a meeting starts is the failure this batch exists to
  remove;
* **it reports the device it actually got.** ``device="auto"`` falls back to CPU silently when
  CUDA is present but unusable, and an install running ten times slower than its budget while the
  interface says GPU is worse than one that says CPU.

The engine is injectable. That is not a testing convenience bolted on — it is what lets the
acceptance test run the whole load-and-transcribe path inside :func:`netguard.no_outbound` and
prove there were no outbound sockets, on a machine with no pack and no faster-whisper installed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..voice.providers import STTProvider, Span
from . import models as _models
from .hardware import Hardware, detect

#: Device to request. ``auto`` is faster-whisper's own default and stays the default here.
DEVICE_ENV = "HOMEPILOT_SPEECH_DEVICE"
#: Compute type. ``default`` lets CTranslate2 choose per device.
COMPUTE_ENV = "HOMEPILOT_SPEECH_COMPUTE"


class HomePilotLocalSTTProvider(STTProvider):
    """Local transcription from a pinned pack, with timings."""

    name = "homepilot-local"

    def __init__(
        self,
        *,
        environ=None,
        engine_factory: Optional[Callable[..., Any]] = None,
        hardware: Optional[Hardware] = None,
    ) -> None:
        self.environ = environ if environ is not None else os.environ
        self._engine_factory = engine_factory
        self._engine = None
        self._hardware = hardware
        self.resolved = _models.resolve(self.environ)
        self.requested_device = (self.environ.get(DEVICE_ENV) or "auto").strip() or "auto"
        self.compute_type = (self.environ.get(COMPUTE_ENV) or "default").strip() or "default"
        #: What the engine actually loaded on. ``None`` until it has. "Not loaded yet" and
        #: "loaded on CPU" are different answers and are never collapsed.
        self.device: Optional[str] = None
        self.compute: Optional[str] = None
        self.load_error: str = ""

    # ── what it can say about itself ────────────────────────────────────────

    @property
    def available(self) -> bool:
        """A usable pack is on disk. Says nothing about whether it has been loaded yet."""
        return bool(self.resolved.ok)

    @property
    def supports_segments(self) -> bool:
        return True

    @property
    def supports_word_timestamps(self) -> bool:
        return True

    @property
    def warm(self) -> bool:
        return self._engine is not None

    def hardware(self) -> Hardware:
        if self._hardware is None:
            self._hardware = detect()
        return self._hardware

    def status(self) -> Dict[str, Any]:
        """Everything a status endpoint needs, with the failure modes kept apart (LS7)."""
        return {
            "local": True,
            "available": self.available,
            "engine": "faster-whisper",
            "warm": self.warm,
            "requested_device": self.requested_device,
            "device": self.device,
            "compute": self.compute,
            "supports_segments": self.supports_segments,
            "supports_word_timestamps": self.supports_word_timestamps,
            "pack": self.resolved.as_dict(),
            "load_error": self.load_error,
        }

    # ── loading ─────────────────────────────────────────────────────────────

    def _factory(self):
        if self._engine_factory is not None:
            return self._engine_factory
        from faster_whisper import WhisperModel  # noqa: PLC0415 — optional dependency

        return WhisperModel

    def load(self):
        """Load the pack. Returns the engine, or ``None`` with :attr:`load_error` set.

        Never raises: a meeting that cannot transcribe should say so, not 500.
        """
        if self._engine is not None:
            return self._engine
        if not self.resolved.ok or not self.resolved.directory:
            self.load_error = f"pack-{self.resolved.reason}"
            return None
        try:
            factory = self._factory()
        except Exception as exc:
            self.load_error = f"engine-unavailable: {type(exc).__name__}"
            return None

        # A **directory**. This is the line the batch is about: anything that is not an existing
        # path is a name, and a name is a download.
        directory = str(self.resolved.directory)
        try:
            engine = factory(
                directory,
                device=self.requested_device,
                compute_type=self.compute_type,
                local_files_only=True,
            )
        except TypeError:
            # An engine that does not take `local_files_only` still gets a directory, which is
            # what makes the download impossible in the first place.
            try:
                engine = factory(directory, device=self.requested_device, compute_type=self.compute_type)
            except Exception as exc:
                self.load_error = f"load-failed: {type(exc).__name__}: {exc}"
                return None
        except Exception as exc:
            self.load_error = f"load-failed: {type(exc).__name__}: {exc}"
            return None

        self._engine = engine
        # Read back rather than echo. The whole point is to catch the silent CPU fallback.
        self.device = str(getattr(engine, "device", None) or self.requested_device)
        self.compute = str(getattr(engine, "compute_type", None) or self.compute_type)
        self.load_error = ""
        return engine

    def warm_up(self) -> bool:
        """Load ahead of the first spoken word (LS6). Idempotent and safe to call anywhere."""
        return self.load() is not None

    # ── transcribing ────────────────────────────────────────────────────────

    def _write_temp(self, audio: bytes, fmt: str) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=f".{fmt or 'wav'}", delete=False)
        try:
            handle.write(audio or b"")
        finally:
            handle.close()
        return Path(handle.name)

    def _run(self, audio: bytes, *, fmt: str, word_timestamps: bool, vad: bool):
        engine = self.load()
        if engine is None:
            return [], None
        path = self._write_temp(audio, fmt)
        try:
            segments, info = engine.transcribe(
                str(path),
                word_timestamps=word_timestamps,
                # MeetingSense has already decided where each utterance begins and ends. A second
                # VAD can trim audio at exactly those boundaries, which is how a final line loses
                # its first word — so it is off for this path and available for the
                # upload-and-transcribe-later one (LS6).
                vad_filter=vad,
            )
            return list(segments), info
        except Exception as exc:
            self.load_error = f"transcribe-failed: {type(exc).__name__}: {exc}"
            return [], None
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str:
        segments, _info = self._run(audio, fmt=fmt, word_timestamps=False, vad=False)
        return " ".join(str(getattr(segment, "text", "") or "").strip() for segment in segments).strip()

    async def transcribe_segments(
        self, audio: bytes, *, fmt: str = "wav", duration_s: Optional[float] = None
    ) -> List[Span]:
        """Timed spans, measured by the model rather than guessed from the clip length."""
        segments, _info = self._run(audio, fmt=fmt, word_timestamps=True, vad=False)
        spans: List[Span] = []
        for segment in segments:
            text = str(getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            # The repo's `Span` is `Dict[str, Any]` with `t0`/`t1`/`text`/`conf`, and every
            # existing consumer reads those keys. A provider that invented its own shape here
            # would be a provider MeetingSense had to special-case — which is the one thing this
            # seam exists to prevent.
            spans.append({
                "t0": float(getattr(segment, "start", 0.0) or 0.0),
                "t1": float(getattr(segment, "end", 0.0) or 0.0),
                "text": text,
                "conf": getattr(segment, "avg_logprob", None),
            })
        return spans
