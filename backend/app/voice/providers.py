"""Voice I/O providers (MB2).

Swappable STT (speech → text) and TTS (text → audio) behind small interfaces so
the *quality tier* is a server-side choice, never a client change:

  - Free today:  Piper TTS (local, reused engine) with a Null fallback; STT is a
    Null placeholder (real Whisper lands as a follow-up provider).
  - Premium later: a neural cloud STT/TTS provider implementing the same ABCs,
    selected by entitlement — no client or protocol change.

Additive and dependency-light: nothing here imports heavy models at import time;
providers degrade to None/"" when their engine isn't configured.
"""

from __future__ import annotations

import abc
import asyncio
import os
import shutil
import subprocess
import tempfile


class TTSProvider(abc.ABC):
    """text → audio bytes (or None when unavailable)."""

    name: str = "base"
    audio_format: str = "wav"

    @abc.abstractmethod
    async def synth(self, text: str) -> bytes | None: ...


class STTProvider(abc.ABC):
    """audio bytes → transcript text."""

    name: str = "base"

    @property
    def available(self) -> bool:
        return False

    @abc.abstractmethod
    async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str: ...


# ── Free / default providers ───────────────────────────────────────────────

class NullTTSProvider(TTSProvider):
    name = "null"

    async def synth(self, text: str) -> bytes | None:  # noqa: ARG002
        return None


class PiperTTSProvider(TTSProvider):
    """Local Piper TTS (the engine HomePilot already uses for story/persona
    speech). Active only when a voice model is configured; otherwise inert."""

    name = "piper"

    def __init__(self) -> None:
        self.binary = os.getenv("PIPER_BINARY", "piper")
        self.voice_model = os.getenv("PIPER_VOICE_MODEL", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.voice_model) and shutil.which(self.binary) is not None

    async def synth(self, text: str) -> bytes | None:
        if not text.strip() or not self.configured:
            return None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = tmp.name
        try:
            subprocess.run(
                [self.binary, "--model", self.voice_model, "--output_file", out],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
                timeout=30,
            )
            with open(out, "rb") as fh:
                return fh.read()
        except Exception:
            return None
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass


class KokoroTTSProvider(TTSProvider):
    """Kokoro-82M local TTS (Apache-2.0) - the same model that already
    narrates the ruslanmv.com essays, exposed as an in-app provider so
    short-form variants of an essay stay in the same voice as the full
    narration (essay-to-video pipeline, Batch 2).

    Active only when the ``kokoro`` package is installed. Env:
    ``KOKORO_VOICE_ID`` (default ``af_heart``) - pin this to the voice used
    by the existing essay narration; ``KOKORO_LANG_CODE`` (default ``a``,
    American English). Piper remains the default provider for every other
    project type - see get_tts_provider(), which is unchanged."""

    name = "kokoro"

    def __init__(self) -> None:
        self.voice = os.getenv("KOKORO_VOICE_ID", "af_heart").strip() or "af_heart"
        self.lang_code = os.getenv("KOKORO_LANG_CODE", "a").strip() or "a"
        self._pipeline = None

    @property
    def configured(self) -> bool:
        try:
            import kokoro  # noqa: F401
            return True
        except Exception:
            return False

    def _synth_sync(self, text: str) -> bytes | None:
        import io
        import wave as wave_mod

        import numpy as np
        from kokoro import KPipeline

        if self._pipeline is None:
            self._pipeline = KPipeline(lang_code=self.lang_code)

        chunks: list = []
        for _, _, audio in self._pipeline(text, voice=self.voice):
            chunks.append(np.asarray(audio))
        if not chunks:
            return None

        samples = np.concatenate(chunks)
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        buf = io.BytesIO()
        with wave_mod.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)  # Kokoro's native sample rate
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    async def synth(self, text: str) -> bytes | None:
        if not text.strip() or not self.configured:
            return None
        try:
            return await asyncio.to_thread(self._synth_sync, text)
        except Exception:
            return None


class ChatterboxTTSProvider(TTSProvider):
    """Chatterbox local TTS - opt-in alternative for punchier, more
    expressive short-form delivery when Kokoro's documentary tone reads as
    too dry (essay-to-video pipeline, Batch 2). Gated behind
    ``CHATTERBOX_ENABLED=true`` on top of the package being installed,
    because the model download is heavy."""

    name = "chatterbox"

    def __init__(self) -> None:
        self.enabled = os.getenv("CHATTERBOX_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        self._model = None

    @property
    def configured(self) -> bool:
        if not self.enabled:
            return False
        try:
            import chatterbox  # noqa: F401
            return True
        except Exception:
            return False

    def _synth_sync(self, text: str) -> bytes | None:
        import io

        import torchaudio
        from chatterbox.tts import ChatterboxTTS

        if self._model is None:
            self._model = ChatterboxTTS.from_pretrained(
                device=os.getenv("CHATTERBOX_DEVICE", "cpu").strip() or "cpu")
        wav = self._model.generate(text)
        buf = io.BytesIO()
        torchaudio.save(buf, wav, self._model.sr, format="wav")
        return buf.getvalue()

    async def synth(self, text: str) -> bytes | None:
        if not text.strip() or not self.configured:
            return None
        try:
            return await asyncio.to_thread(self._synth_sync, text)
        except Exception:
            return None


class CloudNeuralTTSProvider(TTSProvider):
    """Premium, low-latency neural voice via an OpenAI-compatible ``/audio/speech``
    endpoint (OpenAI TTS, ElevenLabs-compatible gateways, …). Configured by env:
    ``TTS_BASE_URL`` (required), ``TTS_API_KEY``, ``TTS_MODEL`` (default ``tts-1``),
    ``TTS_VOICE`` (default ``alloy``). Selected only for entitled (premium) users —
    see ``get_tts_provider``."""

    name = "cloud-neural"
    audio_format = "mp3"

    def __init__(self) -> None:
        self.base_url = os.getenv("TTS_BASE_URL", "").strip().rstrip("/")
        self.api_key = os.getenv("TTS_API_KEY", "").strip()
        self.model = os.getenv("TTS_MODEL", "tts-1").strip()
        self.voice = os.getenv("TTS_VOICE", "alloy").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def synth(self, text: str) -> bytes | None:
        if not text.strip() or not self.configured:
            return None
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": self.audio_format,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{self.base_url}/audio/speech", headers=headers, json=payload)
            r.raise_for_status()
            return r.content


class NullSTTProvider(STTProvider):
    name = "null"

    async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str:  # noqa: ARG002
        raise NotImplementedError("speech-to-text provider not configured")


class OpenAICompatSTTProvider(STTProvider):
    """Speech-to-text via an OpenAI-compatible ``/audio/transcriptions`` endpoint
    (OpenAI Whisper API, a local whisper.cpp server, Groq, …). Configured by env:
    ``STT_BASE_URL`` (required), ``STT_API_KEY`` (optional), ``STT_MODEL``
    (default ``whisper-1``). This is also the premium/low-latency STT path."""

    name = "openai-compat"

    def __init__(self) -> None:
        self.base_url = os.getenv("STT_BASE_URL", "").strip().rstrip("/")
        self.api_key = os.getenv("STT_API_KEY", "").strip()
        self.model = os.getenv("STT_MODEL", "whisper-1").strip()

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str:
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        files = {"file": (f"audio.{fmt}", audio, f"audio/{fmt}")}
        data = {"model": self.model}
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{self.base_url}/audio/transcriptions", headers=headers, files=files, data=data
            )
            r.raise_for_status()
            return (r.json().get("text") or "").strip()


class WhisperLocalSTTProvider(STTProvider):
    """Local faster-whisper STT. Active only when ``WHISPER_MODEL`` is set (e.g.
    ``base``, ``small``) and the ``faster_whisper`` package is installed."""

    name = "whisper-local"

    def __init__(self) -> None:
        self.model_name = os.getenv("WHISPER_MODEL", "").strip()
        self._model = None

    @property
    def available(self) -> bool:
        if not self.model_name:
            return False
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str:
        from faster_whisper import WhisperModel

        if self._model is None:
            self._model = WhisperModel(self.model_name)
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tmp:
            tmp.write(audio)
            path = tmp.name

        def _run() -> str:
            segments, _ = self._model.transcribe(path)  # type: ignore[union-attr]
            return " ".join(seg.text for seg in segments).strip()

        try:
            return await asyncio.to_thread(_run)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


# ── Selectors (entitlement-aware later) ─────────────────────────────────────

def get_tts_provider(premium: bool = False) -> TTSProvider:
    """Premium (entitled) sessions get neural voice when it's configured; everyone
    else gets local Piper, falling back to silent text-only. Quality is purely a
    server choice — the client never changes."""
    if premium:
        neural = CloudNeuralTTSProvider()
        if neural.configured:
            return neural
    piper = PiperTTSProvider()
    return piper if piper.configured else NullTTSProvider()


def get_tts_provider_by_name(name: str) -> TTSProvider:
    """Explicit provider selection for flows that pin a voice - the essay
    pipeline pins Kokoro so every variant of an essay matches the source
    narration. Unknown/unconfigured names fall back exactly like
    get_tts_provider() (which stays the default path everywhere else)."""
    n = (name or "").strip().lower()
    if n == "kokoro":
        kokoro = KokoroTTSProvider()
        if kokoro.configured:
            return kokoro
    elif n == "chatterbox":
        chatterbox = ChatterboxTTSProvider()
        if chatterbox.configured:
            return chatterbox
    elif n == "cloud-neural":
        neural = CloudNeuralTTSProvider()
        if neural.configured:
            return neural
    piper = PiperTTSProvider()
    return piper if piper.configured else NullTTSProvider()


def get_stt_provider() -> STTProvider:
    cloud = OpenAICompatSTTProvider()
    if cloud.available:
        return cloud
    local = WhisperLocalSTTProvider()
    if local.available:
        return local
    return NullSTTProvider()
