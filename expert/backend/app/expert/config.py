# expert/config.py
# All Expert module env vars — purely additive, no conflict with existing config.py
from __future__ import annotations

import os

# ── xAI Grok ────────────────────────────────────────────────────────────────
GROK_API_KEY: str = os.getenv("GROK_API_KEY", "").strip()
GROK_BASE_URL: str = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").rstrip("/")
GROK_MODEL: str = os.getenv("GROK_MODEL", "grok-3").strip()

# ── Groq (ultra-fast open-model inference, free tier available) ──────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

# ── Google Gemini ────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_BASE_URL: str = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai"
).rstrip("/")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

# ── Local Ollama (free, on-premises) ─────────────────────────────────────────
# Reuses existing OLLAMA_BASE_URL from main config if not overridden
EXPERT_OLLAMA_URL: str = os.getenv(
    "EXPERT_OLLAMA_URL",
    os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
).rstrip("/")
# Default chosen so out-of-the-box Expert runs on a 12 GB consumer GPU.
# Operators with larger VRAM (or a cloud deploy) can point this at
# ``deepseek-r1:32b`` or similar for top-tier reasoning quality.
# If the configured model isn't pulled, chat_local falls back to any
# installed model via EXPERT_LOCAL_AUTO_FALLBACK — Expert never hard-fails
# on "model not found" as long as Ollama has at least one model.
EXPERT_LOCAL_MODEL: str = os.getenv("EXPERT_LOCAL_MODEL", "deepseek-r1:latest").strip()
EXPERT_LOCAL_FAST_MODEL: str = os.getenv("EXPERT_LOCAL_FAST_MODEL", "llama3.2:3b").strip()

# ── Routing thresholds ────────────────────────────────────────────────────────
# Complexity scores (0-10) that determine which tier to use
EXPERT_LOCAL_THRESHOLD: int = int(os.getenv("EXPERT_LOCAL_THRESHOLD", "3"))   # ≤3 → local fast
EXPERT_GROQ_THRESHOLD: int = int(os.getenv("EXPERT_GROQ_THRESHOLD", "6"))    # ≤6 → Groq 70B
# >6 → Grok / Gemini / best available cloud

# ── Expert system identity ────────────────────────────────────────────────────
EXPERT_SYSTEM_PROMPT: str = os.getenv(
    "EXPERT_SYSTEM_PROMPT",
    "You are Expert, an advanced AI assistant integrated into HomePilot. "
    "You are precise, helpful, and honest. You think step-by-step for complex "
    "problems and give concise answers for simple ones. You never fabricate facts."
)

# ── Streaming ────────────────────────────────────────────────────────────────
EXPERT_STREAM_CHUNK_SIZE: int = int(os.getenv("EXPERT_STREAM_CHUNK_SIZE", "64"))
EXPERT_MAX_TOKENS: int = int(os.getenv("EXPERT_MAX_TOKENS", "2048"))
EXPERT_TEMPERATURE: float = float(os.getenv("EXPERT_TEMPERATURE", "0.7"))
EXPERT_PROVIDER_TIMEOUT_S: float = float(os.getenv("EXPERT_PROVIDER_TIMEOUT_S", "45"))


def available_expert_providers() -> list[str]:
    """Return which expert providers are configured (have API keys or local URL)."""
    providers = []
    # Local is always available if Ollama is reachable (no key needed)
    providers.append("local")
    if GROQ_API_KEY:
        providers.append("groq")
    if GROK_API_KEY:
        providers.append("grok")
    if GEMINI_API_KEY:
        providers.append("gemini")
    # Claude / OpenAI reuse existing HomePilot keys — check them
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        providers.append("claude")
    if os.getenv("OPENAI_API_KEY", "").strip():
        providers.append("openai")
    return providers
