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
# "Expert" is the name of this pipeline (Fast / Think / Heavy), not a persona. The old
# prompt opened "You are Expert, an advanced AI assistant integrated into HomePilot", and
# models took it literally: a plain "hello" came back as "Hello! I am Expert, your HomePilot
# assistant. How can I help you today?". The assistant should sound like a capable colleague,
# not announce a product name.
EXPERT_SYSTEM_PROMPT: str = os.getenv(
    "EXPERT_SYSTEM_PROMPT",
    "You are a knowledgeable, professional assistant. Talk the way a thoughtful colleague "
    "would: natural, warm and direct.\n"
    "\n"
    "- Reply in the language the user writes in.\n"
    "- Fit the length to the request. A greeting or a quick question gets a short, friendly "
    "reply; a complex problem gets a clear, well-structured answer that reasons it through.\n"
    "- Do not introduce yourself, give yourself a name or describe what you are unless the "
    "user asks.\n"
    "- Skip filler and formula: no \"Great question!\", no \"As an AI…\", no stock sign-off "
    "at the end of every answer.\n"
    "- Be accurate. If something is uncertain or depends on information you do not have, say "
    "so briefly instead of guessing. Never invent facts, figures or sources.\n"
    "- Use Markdown (lists, headings, code blocks) only when it makes the answer easier to "
    "read."
)

# ── Streaming ────────────────────────────────────────────────────────────────
EXPERT_STREAM_CHUNK_SIZE: int = int(os.getenv("EXPERT_STREAM_CHUNK_SIZE", "64"))
EXPERT_MAX_TOKENS: int = int(os.getenv("EXPERT_MAX_TOKENS", "2048"))
EXPERT_TEMPERATURE: float = float(os.getenv("EXPERT_TEMPERATURE", "0.7"))
# Conversation window handed to every pipeline call — fast, think and heavy alike: the newest
# turns that fit both budgets. The chat sends its last 8 turns; API callers may send any number.
EXPERT_HISTORY_MAX_TURNS: int = int(os.getenv("EXPERT_HISTORY_MAX_TURNS", "12"))
EXPERT_HISTORY_MAX_CHARS: int = int(os.getenv("EXPERT_HISTORY_MAX_CHARS", "16000"))
# Compaction: turns older than the window are summarized into a running note instead of being
# dropped (compaction.py). One short model call per overflow, cached per session.
EXPERT_COMPACTION_ENABLED: bool = os.getenv("EXPERT_COMPACTION_ENABLED", "1").lower() in ("1", "true", "yes")
EXPERT_COMPACTION_MAX_TOKENS: int = int(os.getenv("EXPERT_COMPACTION_MAX_TOKENS", "400"))
EXPERT_COMPACTION_MAX_INPUT_CHARS: int = int(os.getenv("EXPERT_COMPACTION_MAX_INPUT_CHARS", "24000"))

# ── Tools (tools.py, tool_loop.py) ───────────────────────────────────────────
# The per-turn tool loop: the model may call a curated set of HomePilot's MCP tools (web search,
# page fetch, workspace and notes search) while answering, ChatGPT-style. Servers speak JSON-RPC
# tools/list + tools/call on /rpc — HomePilot's own agentic servers by default; Context Forge's
# /rpc speaks the same protocol and can be added for federated tools.
EXPERT_TOOLS_ENABLED: bool = os.getenv("EXPERT_TOOLS_ENABLED", "1").lower() in ("1", "true", "yes")
EXPERT_TOOL_SERVERS: str = os.getenv(
    "EXPERT_TOOL_SERVERS",
    "http://127.0.0.1:9105/rpc,http://127.0.0.1:9102/rpc,http://127.0.0.1:9101/rpc",
)
# Native tool names offered to the model (comma-separated; '*' for every tool the servers list).
EXPERT_TOOL_ALLOWLIST: str = os.getenv(
    "EXPERT_TOOL_ALLOWLIST",
    "hp.web.search,hp.web.fetch,hp.search_workspace,hp.get_document,hp.personal.search",
)
EXPERT_TOOL_MAX_ROUNDS: int = int(os.getenv("EXPERT_TOOL_MAX_ROUNDS", "4"))
EXPERT_TOOL_MAX_CALLS_PER_ROUND: int = int(os.getenv("EXPERT_TOOL_MAX_CALLS_PER_ROUND", "4"))
EXPERT_TOOL_TIMEOUT_S: float = float(os.getenv("EXPERT_TOOL_TIMEOUT_S", "45"))
EXPERT_TOOL_RESULT_MAX_CHARS: int = int(os.getenv("EXPERT_TOOL_RESULT_MAX_CHARS", "6000"))

# ── Heavy: escalate to the strongest model on the same connection (routes.py) ─
# Off by default: the model chosen in the chat is the model for every mode. Set to 1 to let
# Heavy move to a clearly stronger model of the same connection, with a notice.
EXPERT_HEAVY_ESCALATE: bool = os.getenv("EXPERT_HEAVY_ESCALATE", "0").lower() in ("1", "true", "yes")

# ── Effort profiles (policies.py): what each mode may spend, not what it must ─
# A mode sets the ceiling; the request's complexity decides how much of it is used. A greeting
# in Heavy is one generation; a hard question gets the full pipeline.
EXPERT_FAST_TEMPERATURE: float = float(os.getenv("EXPERT_FAST_TEMPERATURE", "0.7"))
EXPERT_FAST_MAX_TOKENS: int = int(os.getenv("EXPERT_FAST_MAX_TOKENS", "1024"))
EXPERT_FAST_TOOL_ROUNDS: int = int(os.getenv("EXPERT_FAST_TOOL_ROUNDS", "2"))
EXPERT_THINK_TEMPERATURE: float = float(os.getenv("EXPERT_THINK_TEMPERATURE", "0.4"))
EXPERT_THINK_MAX_TOKENS: int = int(os.getenv("EXPERT_THINK_MAX_TOKENS", "2048"))
EXPERT_THINK_TOOL_ROUNDS: int = int(os.getenv("EXPERT_THINK_TOOL_ROUNDS", "4"))
EXPERT_THINK_PLAN_MIN_COMPLEXITY: int = int(os.getenv("EXPERT_THINK_PLAN_MIN_COMPLEXITY", "4"))
EXPERT_HEAVY_TEMPERATURE: float = float(os.getenv("EXPERT_HEAVY_TEMPERATURE", "0.3"))
EXPERT_HEAVY_MAX_TOKENS: int = int(os.getenv("EXPERT_HEAVY_MAX_TOKENS", "3072"))
EXPERT_HEAVY_TOOL_ROUNDS: int = int(os.getenv("EXPERT_HEAVY_TOOL_ROUNDS", "4"))
EXPERT_HEAVY_RESEARCH_MIN_COMPLEXITY: int = int(os.getenv("EXPERT_HEAVY_RESEARCH_MIN_COMPLEXITY", "5"))
EXPERT_DEEP_TEMPERATURE: float = float(os.getenv("EXPERT_DEEP_TEMPERATURE", "0.3"))

# ── Durable state (state_store.py): capability facts, Deep research jobs ─────
# Default: <DATA_DIR or backend/data>/expert_state.sqlite.
EXPERT_STATE_DB: str = os.getenv("EXPERT_STATE_DB", "").strip()
EXPERT_CAPABILITY_TTL_S: float = float(os.getenv("EXPERT_CAPABILITY_TTL_S", str(7 * 24 * 3600)))
# A learned refusal ("this connection rejects the tools field") is re-checked sooner than a
# success: gateways get fixed, and re-learning costs one rejected request plus a retry.
EXPERT_CAPABILITY_NEGATIVE_TTL_S: float = float(os.getenv("EXPERT_CAPABILITY_NEGATIVE_TTL_S", "3600"))
# `: keep-alive` SSE comment after this many silent seconds on /stream (0 disables): a long model
# call or a slow tool no longer looks like a dead connection to proxies, browsers, or the reader.
EXPERT_SSE_HEARTBEAT_S: float = float(os.getenv("EXPERT_SSE_HEARTBEAT_S", "10"))

# ── Adaptive pacing and retries for OpenAI-compatible endpoints (providers.py) ─
# One gateway is never flooded: at most MAX_INFLIGHT requests at a time, and a gap between
# request starts, per base URL. The gap starts at MIN_INTERVAL_S, doubles on every rate limit
# (up to MAX_INTERVAL_S, and every caller waits out the cooldown) and shrinks back 15 % per
# success — Heavy's agents and Deep research's sub-agents adapt to the gateway's real limit.
# Requests beyond MAX_INFLIGHT wait in a queue, a person's ahead of background work (Deep
# research). A 429, a body that says "rate limit", or a 502/503/504 is retried with exponential
# backoff and jitter (about 2 s, 4 s, 8 s, 16 s, 20 s…; Retry-After is a floor), always before
# the first token, for up to WAIT_S seconds in a chat turn and BACKGROUND_WAIT_S in a background
# job (RETRIES caps the tries). Meanwhile the chat shows "The model provider is busy; retrying…".
EXPERT_PROVIDER_MAX_INFLIGHT: int = int(os.getenv("EXPERT_PROVIDER_MAX_INFLIGHT", "2"))
EXPERT_PROVIDER_MIN_INTERVAL_S: float = float(os.getenv("EXPERT_PROVIDER_MIN_INTERVAL_S", "1.0"))
EXPERT_PROVIDER_MAX_INTERVAL_S: float = float(os.getenv("EXPERT_PROVIDER_MAX_INTERVAL_S", "15"))
EXPERT_PROVIDER_RETRIES: int = int(os.getenv("EXPERT_PROVIDER_RETRIES", "8"))
EXPERT_PROVIDER_WAIT_S: float = float(os.getenv("EXPERT_PROVIDER_WAIT_S", "90"))
EXPERT_PROVIDER_BACKGROUND_WAIT_S: float = float(os.getenv("EXPERT_PROVIDER_BACKGROUND_WAIT_S", "300"))
# The usage meter's rolling window. On a rate limit the endpoint's cap is learned as the
# successes this window took; new requests then wait their turn to stay under it, and the cap
# grows by one after three quiet windows (GET /v1/expert/usage shows it all).
EXPERT_PROVIDER_WINDOW_S: float = float(os.getenv("EXPERT_PROVIDER_WINDOW_S", "60"))

# ── Deep research (deep.py, capability.py) ───────────────────────────────────
# auto: offered when the connection has a high-end model (capability.py); always / off override.
EXPERT_DEEP_RESEARCH: str = os.getenv("EXPERT_DEEP_RESEARCH", "auto").strip().lower() or "auto"
EXPERT_DEEP_MIN_PARAMS_B: float = float(os.getenv("EXPERT_DEEP_MIN_PARAMS_B", "20"))
EXPERT_DEEP_TIME_BUDGET_S: float = float(os.getenv("EXPERT_DEEP_TIME_BUDGET_S", "300"))
EXPERT_DEEP_MAX_ITEMS: int = int(os.getenv("EXPERT_DEEP_MAX_ITEMS", "5"))
EXPERT_DEEP_ROUNDS_PER_ITEM: int = int(os.getenv("EXPERT_DEEP_ROUNDS_PER_ITEM", "3"))
EXPERT_DEEP_JOB_TTL_S: float = float(os.getenv("EXPERT_DEEP_JOB_TTL_S", "3600"))
# 120s accommodates CPU-only Ollama setups with mid-size thinking models
# (e.g. deepseek-r1 / phi4) where a single analysis pass can easily exceed
# 45s. Think mode chains three such calls, so keeping the per-call timeout
# tight caused ``[expert chat] TimeoutError → 502`` on local dev boxes even
# when the model was making progress. Override via env for prod deploys
# where faster providers enforce a shorter SLA.
EXPERT_PROVIDER_TIMEOUT_S: float = float(os.getenv("EXPERT_PROVIDER_TIMEOUT_S", "120"))


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
