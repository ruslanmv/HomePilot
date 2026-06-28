"""Backend voice session (MB2) — server-side STT/LLM/TTS orchestration so mobile
and web stay thin clients. Additive and flag-gated (`VOICE_BACKEND_ENABLED`)."""

from .routes import router  # noqa: F401
