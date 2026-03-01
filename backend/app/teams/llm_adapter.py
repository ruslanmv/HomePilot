# backend/app/teams/llm_adapter.py
"""
Teams LLM adapter — routes persona LLM calls through the same provider
infrastructure as the main chat, respecting user Enterprise Settings.

Features:
  - Reads DEFAULT_PROVIDER from config (not hardcoded "openai_compat")
  - Accepts runtime overrides for provider, model, base_url from /react body
  - Concurrency semaphore limits parallel Ollama/LLM calls (configurable)
  - Logs target provider/model/base_url for every call (debug-level)
  - Returns clean error messages instead of raw httpx.ConnectError
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from ..config import (
    DEFAULT_PROVIDER,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    LLM_BASE_URL,
    TEAMS_MAX_CONCURRENT_LLM,
)
from ..llm import chat as llm_chat, strip_think_tags, _is_reasoning_text, recover_from_reasoning

logger = logging.getLogger("homepilot.teams.llm_adapter")

# ── Concurrency limiter ──────────────────────────────────────────────────
# Prevents overwhelming a single Ollama instance with parallel requests.
# Default: 1 (sequential). Configurable via TEAMS_MAX_CONCURRENT_LLM env var
# or the frontend "Teams Concurrent LLM Calls" setting.
_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore(max_concurrent: Optional[int] = None) -> asyncio.Semaphore:
    """Lazily create (or recreate) the global semaphore."""
    global _semaphore
    limit = max_concurrent or TEAMS_MAX_CONCURRENT_LLM
    if _semaphore is None or _semaphore._value != limit:  # type: ignore[attr-defined]
        _semaphore = asyncio.Semaphore(limit)
    return _semaphore


def _resolve_provider_settings(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple:
    """Resolve provider, model, and base_url from overrides + config defaults.

    Priority: explicit override > config env var > sensible default.
    """
    prov = provider or DEFAULT_PROVIDER

    if prov == "ollama":
        mdl = model or OLLAMA_MODEL or "llama3:8b"
        url = base_url or OLLAMA_BASE_URL
    elif prov == "openai_compat":
        mdl = model or LLM_MODEL
        url = base_url or LLM_BASE_URL
    else:
        # openai, claude, watsonx — use whatever was passed
        mdl = model or LLM_MODEL
        url = base_url  # let llm.py use its own defaults

    return prov, mdl, url


class LLMConnectionError(Exception):
    """Raised when the LLM provider is unreachable."""
    def __init__(self, provider: str, base_url: str, detail: str = ""):
        self.provider = provider
        self.base_url = base_url
        self.detail = detail
        super().__init__(
            f"LLM provider unreachable: {provider} at {base_url}. "
            f"{detail} "
            "Check that the service is running and the URL is correct."
        )


async def llm_text(
    messages: List[Dict[str, Any]],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 800,
    max_concurrent: Optional[int] = None,
) -> str:
    """
    Call the configured LLM and return the assistant reply as a string.

    This is the ``llm_fn`` that meeting_engine / orchestrator expects:
        async callable(messages) -> str

    Args:
        messages: OpenAI-style message list
        provider: Override provider (e.g. "ollama", "openai_compat")
        model: Override model (e.g. "llama3:8b")
        base_url: Override base URL (e.g. "http://localhost:11434")
        temperature: Sampling temperature
        max_tokens: Max tokens in response
        max_concurrent: Override concurrent call limit (None = use config)
    """
    prov, mdl, url = _resolve_provider_settings(
        provider=provider, model=model, base_url=base_url,
    )

    logger.info(
        "Teams LLM call → provider=%s, model=%s, base_url=%s, max_tokens=%d",
        prov, mdl, url or "(default)", max_tokens,
    )

    sem = _get_semaphore(max_concurrent)

    async with sem:
        try:
            kwargs: Dict[str, Any] = {
                "provider": prov,
                "model": mdl,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if url:
                kwargs["base_url"] = url

            resp = await llm_chat(messages, **kwargs)
        except Exception as exc:
            exc_str = str(exc).lower()
            if "connect" in exc_str or "connection" in exc_str or "refused" in exc_str:
                raise LLMConnectionError(
                    provider=prov,
                    base_url=url or "(default)",
                    detail=str(exc),
                ) from exc
            raise

    try:
        content = (resp["choices"][0]["message"]["content"] or "").strip()
        # Layer 1: Strip paired reasoning blocks (matches orchestrator.py:1981)
        content = strip_think_tags(content)
        # Layer 2: Remove orphaned closing tags from malformed/truncated output
        content = re.sub(
            r"</(?:think|thinking|reasoning|reflection)>\s*",
            "", content, flags=re.IGNORECASE,
        ).strip()
        # Layer 3: Detect leaked reasoning / meta-commentary and recover
        # This catches "But the user is the host, so maybe…" style leaks
        # that slip through tag-based stripping.
        if content and _is_reasoning_text(content):
            recovered = recover_from_reasoning(content)
            if recovered:
                logger.info("Teams LLM: recovered spoken text from reasoning leak")
                content = recovered
            else:
                logger.warning(
                    "Teams LLM: reasoning leak detected, no recoverable text. "
                    "Returning empty to trigger retry. Leaked: %.120s",
                    content,
                )
                content = ""
        # Layer 4: Strip speaker-label prefixes the model may emit
        # e.g. "Partner: Hello there" → "Hello there"
        content = _strip_speaker_label(content)
        # Layer 5: Strip multi-speaker scripts (model writing both sides)
        content = _strip_multi_speaker_script(content)
        # Layer 6: Collapse repeated sentences / paragraphs
        content = _collapse_repetitions(content)
        return content
    except Exception:
        logger.warning("Unexpected LLM response shape: %s", resp)
        return ""


# ── Speaker label stripping ──────────────────────────────────────────────

_SPEAKER_LABEL_RE = re.compile(
    r"^[A-Z][A-Za-z\s]{0,30}:\s+",  # "Partner: " or "Girlfriend: "
)

# Internal label pattern: matches "Name:" at the start of a line mid-text
_INTERNAL_LABEL_RE = re.compile(
    r"^\s*[A-Z][A-Za-z\s]{0,30}:\s+",
    re.MULTILINE,
)


def _strip_speaker_label(text: str) -> str:
    """Remove a leading speaker label if the LLM emitted one.

    Models sometimes prefix output with the persona's own name or another
    participant's name followed by a colon (e.g. "Partner: I think...").
    The UI already labels speakers, so this is redundant and confusing.
    """
    if not text:
        return text
    m = _SPEAKER_LABEL_RE.match(text)
    if m:
        stripped = text[m.end():]
        return stripped if stripped else text
    return text


def _strip_multi_speaker_script(text: str) -> str:
    """If the model produced a multi-speaker script, keep only the first block.

    Detects patterns like:
        Some text here.
        Partner: More text.
        Girlfriend: Even more.

    Keeps only the text before the first internal speaker label.
    """
    if not text:
        return text
    lines = text.split("\n")
    kept: list[str] = []
    for i, line in enumerate(lines):
        if i > 0 and _INTERNAL_LABEL_RE.match(line):
            # Found an internal speaker label — stop here
            logger.info("Multi-speaker script detected, truncating at line %d", i)
            break
        kept.append(line)
    result = "\n".join(kept).strip()
    return result if result else text


def _collapse_repetitions(text: str) -> str:
    """Remove repeated sentences and paragraphs from LLM output.

    Catches the common failure mode where the model loops and repeats
    the same sentence or paragraph multiple times.
    """
    if not text or len(text) < 50:
        return text

    # Split into sentences and remove consecutive duplicates
    # Use a pattern that splits on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) < 2:
        return text

    deduped: list[str] = []
    seen_normalized: set[str] = set()

    for sent in sentences:
        # Normalize for comparison: lowercase, strip punctuation
        norm = re.sub(r'[^\w\s]', '', sent.lower()).strip()
        if len(norm) < 10:
            # Too short to meaningfully compare — keep it
            deduped.append(sent)
            continue
        if norm in seen_normalized:
            logger.debug("Collapsed repeated sentence: %.60s...", sent)
            continue
        seen_normalized.add(norm)
        deduped.append(sent)

    result = " ".join(deduped).strip()
    if len(result) < len(text) * 0.5 and result:
        logger.info(
            "Repetition scrubber: %.0f%% reduction (%d→%d chars)",
            (1 - len(result) / len(text)) * 100, len(text), len(result),
        )
    return result if result else text
