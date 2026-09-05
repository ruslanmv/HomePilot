"""Audio on the wire, and getting it into a shape the speech provider accepts (batch MS3).

Two facts drive this whole module.

**Raw PCM16 is not a WAV.** ``WhisperLocalSTTProvider.transcribe`` writes the bytes it is
given to a ``.{fmt}`` temp file and hands the path to faster-whisper. Send it headerless PCM
named ``.wav`` and the decoder reads the first 44 bytes of *speech* as a header — the failure
is a garbled transcript rather than an exception, which is the worst kind. So the header is
added here, server-side, where the sample rate and channel count are known.

**A stereo frame is two speakers, not one.** MS4's mixer keeps system audio and microphone on
separate gain nodes so they arrive as two channels rather than one sum. Channel 0 is the
system — the other people in the call — and channel 1 is this machine's microphone. That
convention is fixed here because both sides need it and only one of them can define it:

    channel 0 → ``them``      channel 1 → ``me``

Mixing them to mono would be simpler and would throw away the only speaker signal there is.

Pure functions over bytes: no sockets, no provider, no config. The route decides what to do
with a frame; this decides what a frame *is*.
"""

from __future__ import annotations

import array
import base64
import binascii
import io
import sys
import wave
from typing import List, NamedTuple, Optional, Tuple

#: The largest decoded audio frame accepted. MS4 cuts utterances at 8 s, which at 16 kHz
#: stereo PCM16 is 512 KB, so this is roughly 8× the worst legitimate frame — comfortably
#: past anything the recorder produces, and far short of a client streaming a file into a
#: transcription endpoint that would happily chew on it.
MAX_FRAME_BYTES = 4 * 1024 * 1024

#: Sample rate assumed when a frame does not say. MS4 resamples to 16 kHz, which is what
#: Whisper works at internally anyway.
DEFAULT_RATE = 16_000

#: The two channels of a 2-channel frame, in order. Fixed, and documented at the top.
CHANNEL_SPEAKERS = ("them", "me")

_FORMATS = ("wav", "pcm16")


class AudioFrameError(ValueError):
    """A frame that cannot be turned into audio, with a stable code for the error frame."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class Track(NamedTuple):
    """One speaker's audio, already WAV-framed and ready for a provider."""

    speaker: Optional[str]
    wav: bytes


def decode_b64(message) -> bytes:
    """Pull the audio bytes out of a frame.

    ``data_b64`` is the field, chosen in decision D6 so a meeting frame and a voice frame are
    the same shape and one contract gets debugged instead of two. ``pcm16_b64`` is accepted
    as well because the design document spells it that way, and a client written from the
    document should work rather than fail with an empty-audio error that says nothing about
    the field name.
    """
    raw = message.get("data_b64")
    if raw is None:
        raw = message.get("pcm16_b64")
    if not raw:
        raise AudioFrameError("audio_missing", "an audio frame needs data_b64")
    try:
        audio = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AudioFrameError("audio_undecodable", f"data_b64 is not base64: {exc}") from None
    if not audio:
        raise AudioFrameError("audio_missing", "an audio frame needs data_b64")
    if len(audio) > MAX_FRAME_BYTES:
        raise AudioFrameError(
            "audio_too_large",
            f"frame is {len(audio)} bytes; the limit is {MAX_FRAME_BYTES}",
        )
    return audio


def frame_format(message) -> str:
    """``wav`` or ``pcm16``. A frame using the ``pcm16_b64`` field has said which already."""
    fmt = (message.get("format") or "").strip().lower()
    if not fmt:
        fmt = "pcm16" if message.get("pcm16_b64") else "wav"
    if fmt not in _FORMATS:
        raise AudioFrameError("audio_format", f"unsupported format {fmt!r}; use wav or pcm16")
    return fmt


def wrap_pcm16(pcm: bytes, *, rate: int = DEFAULT_RATE, channels: int = 1) -> bytes:
    """Put a RIFF header on raw little-endian PCM16.

    Rejects a byte count that is not a whole number of frames rather than dropping the odd
    trailing byte: a stream that is off by one byte is misaligned from that point on, and
    every sample after it is noise. Failing here says so; padding it would hide it.
    """
    width = 2 * max(1, channels)
    if len(pcm) % width:
        raise AudioFrameError(
            "audio_misaligned",
            f"{len(pcm)} bytes is not a whole number of {channels}-channel PCM16 frames",
        )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(max(1, channels))
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def read_wav(data: bytes) -> Tuple[bytes, int, int]:
    """Unpack a WAV into ``(pcm, rate, channels)``.

    Only needed to split a stereo WAV; a mono one is handed to the provider untouched,
    because re-encoding audio that is already in the right shape is a way to introduce a bug
    with no upside.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            if wf.getsampwidth() != 2:
                raise AudioFrameError(
                    "audio_format",
                    f"expected 16-bit samples, got {wf.getsampwidth() * 8}-bit",
                )
            return wf.readframes(wf.getnframes()), wf.getframerate(), wf.getnchannels()
    except AudioFrameError:
        raise
    except wave.Error as exc:
        raise AudioFrameError("audio_format", f"not a readable WAV: {exc}") from None


def deinterleave(pcm: bytes, channels: int) -> List[bytes]:
    """Split interleaved PCM16 into one byte string per channel.

    Goes through :mod:`array` rather than slicing bytes so the unit is a sample, not a byte —
    the off-by-one that splits a sample down the middle is not a bug that shows up as an
    exception, it shows up as static.
    """
    if channels <= 1:
        return [pcm]
    stride = 2 * channels
    if len(pcm) % stride:
        raise AudioFrameError(
            "audio_misaligned",
            f"{len(pcm)} bytes is not a whole number of {channels}-channel PCM16 frames",
        )
    samples = array.array("h")
    samples.frombytes(pcm)
    if sys.byteorder == "big":
        # The wire is little-endian; `array` is native. On a big-endian host the two differ,
        # and every sample would come out byte-reversed — silence-shaped noise.
        samples.byteswap()
    out = []
    for ch in range(channels):
        part = samples[ch::channels]
        if sys.byteorder == "big":
            part.byteswap()
        out.append(part.tobytes())
    return out


def tracks(message, *, declared_channels: int = 1, rate: int = DEFAULT_RATE) -> List[Track]:
    """Turn one wire frame into the WAV-framed tracks a provider can transcribe.

    Returns one track for mono audio (``speaker`` left to the caller, since a 1-channel
    recording cannot tell who is talking) and two for stereo, tagged by
    :data:`CHANNEL_SPEAKERS`.

    ``declared_channels`` comes from the ``start`` frame. A WAV carries its own channel count
    and that wins — the header is a fact, the declaration is a claim — but headerless PCM has
    only the claim to go on.
    """
    audio = decode_b64(message)
    fmt = frame_format(message)
    channels = int(message.get("channels") or declared_channels or 1)

    if fmt == "wav":
        pcm, wav_rate, wav_channels = read_wav(audio)
        if wav_channels <= 1:
            # Already exactly what the provider wants.
            return [Track(None, audio)]
        return [
            Track(_speaker(ch, wav_channels), wrap_pcm16(part, rate=wav_rate, channels=1))
            for ch, part in enumerate(deinterleave(pcm, wav_channels))
        ]

    if channels <= 1:
        return [Track(None, wrap_pcm16(audio, rate=rate, channels=1))]
    return [
        Track(_speaker(ch, channels), wrap_pcm16(part, rate=rate, channels=1))
        for ch, part in enumerate(deinterleave(audio, channels))
    ]


def _speaker(channel: int, channels: int) -> Optional[str]:
    """Name a channel, or leave it unnamed rather than guess.

    Two channels is the case the convention covers. Anything else — a 6-channel capture from
    a conference device, say — has no agreed mapping, and inventing one would put a confident
    ``me`` on audio nobody promised was the microphone.
    """
    if channels == len(CHANNEL_SPEAKERS) and channel < len(CHANNEL_SPEAKERS):
        return CHANNEL_SPEAKERS[channel]
    return None
