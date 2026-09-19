"""Backend voice session (MB2) — server-side STT/LLM/TTS orchestration so mobile
and web stay thin clients. Additive and flag-gated (`VOICE_BACKEND_ENABLED`).

``transcribe_router`` is deliberately *not* behind that flag: it is one-shot
speech-to-text for audio the client already recorded, which is what lets the web
client transcribe the microphone the user actually selected instead of whichever
input the browser's own recognizer happens to open. See `transcribe.py`.
"""

from .routes import router  # noqa: F401
from .transcribe import router as transcribe_router  # noqa: F401
