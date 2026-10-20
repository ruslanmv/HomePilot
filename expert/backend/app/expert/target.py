# expert/target.py
"""The chat model the user picked, for the length of one Expert request.

Expert used to choose its own model: a request said ``provider: "auto"`` and Expert answered
from Ollama's default — even after the user had connected an OllaBridge gateway in Models and
picked ``openwebui/internal-gemma4-31b`` for chat. The reasoning modes (Fast, Think, Heavy)
therefore talked to a different model from the rest of the chat, and when Ollama was busy the
user saw ``500 Internal Server Error for url 'http://localhost:11434/api/chat'`` for a model
they never chose.

The client now sends the chat selection as ``target`` (provider, base URL, model, key). It is
held in a context variable rather than threaded through every pipeline step, so Fast, Think,
Heavy and their streaming forms all use it without each learning a new parameter — the steps
run inside the request's task, which carries the variable with it.

``local`` means "the user's chosen model" whenever a target is set. A target is never replaced
by a cloud provider behind the user's back: with one set, ``auto`` routes to it rather than to
Groq or Gemini on a complex question.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional

#: Providers answered through Ollama's own API; everything else is OpenAI-compatible.
OLLAMA_PROVIDERS = ("", "ollama")


@dataclass(frozen=True)
class ChatTarget:
    provider: str
    base_url: str
    model: str
    api_key: str = ""

    @property
    def is_ollama(self) -> bool:
        return self.provider in OLLAMA_PROVIDERS

    @property
    def label(self) -> str:
        """What a response reports as the provider that answered."""
        return "local" if self.is_ollama else self.provider

    def __repr__(self) -> str:  # never print the key
        return f"ChatTarget(provider={self.provider!r}, base_url={self.base_url!r}, model={self.model!r})"


_CURRENT: ContextVar[Optional[ChatTarget]] = ContextVar("expert_chat_target", default=None)


def from_request(raw: Any) -> Optional[ChatTarget]:
    """A target from the request's ``target`` field, or ``None`` when it names nothing.

    An Ollama target with no model and no URL is the same as no target: Expert's own defaults
    already mean "the local Ollama".
    """
    if raw is None:
        return None
    get = raw.get if isinstance(raw, dict) else (lambda k, d=None: getattr(raw, k, d))
    provider = str(get("provider", "") or "").strip().lower()
    base_url = str(get("base_url", "") or "").strip().rstrip("/")
    model = str(get("model", "") or "").strip()
    api_key = str(get("api_key", "") or "").strip()
    if provider in OLLAMA_PROVIDERS and not model and not base_url:
        return None
    if provider not in OLLAMA_PROVIDERS and not base_url:
        # An OpenAI-compatible provider with nowhere to send it cannot be honoured; Expert's
        # defaults are a better answer than an error about a URL the user never typed.
        return None
    return ChatTarget(provider=provider, base_url=base_url, model=model, api_key=api_key)


def current() -> Optional[ChatTarget]:
    return _CURRENT.get()


@contextmanager
def using(target: Optional[ChatTarget]) -> Iterator[Optional[ChatTarget]]:
    """Make ``target`` the chat target for everything awaited inside the block."""
    token = _CURRENT.set(target)
    try:
        yield target
    finally:
        _CURRENT.reset(token)
