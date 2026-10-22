# expert/providers.py
# All new LLM provider adapters for the Expert module.
# Pattern mirrors backend/app/llm.py — returns OpenAI-compatible dicts.
# Streaming variants yield raw SSE chunks for the /expert/stream endpoint.
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import heapq
import itertools
import json
import logging
import os
import random
import time
from collections import deque
from typing import Any, AsyncIterator, Deque, Dict, List, Optional, Tuple

import httpx

from .config import (
    GROK_API_KEY, GROK_BASE_URL, GROK_MODEL,
    GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODEL,
    GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL,
    EXPERT_OLLAMA_URL, EXPERT_LOCAL_MODEL, EXPERT_LOCAL_FAST_MODEL,
    EXPERT_MAX_TOKENS, EXPERT_TEMPERATURE,
    EXPERT_PROVIDER_MAX_INFLIGHT, EXPERT_PROVIDER_MIN_INTERVAL_S, EXPERT_PROVIDER_MAX_INTERVAL_S,
    EXPERT_PROVIDER_RETRIES, EXPERT_PROVIDER_WAIT_S, EXPERT_PROVIDER_BACKGROUND_WAIT_S,
    EXPERT_PROVIDER_WINDOW_S,
)

logger = logging.getLogger("expert.providers")

_TIMEOUT = httpx.Timeout(timeout=120.0, connect=15.0)
_STREAM_TIMEOUT = httpx.Timeout(timeout=300.0, connect=15.0)


# ─────────────────────────────────────────────────────────────────────────────
# Pacing and retries — one gateway is never flooded, and a rate limit is waited out
# ─────────────────────────────────────────────────────────────────────────────

# Who is waiting: 0 = a person in the chat, 1 = background work (a Deep research job). When the
# endpoint is scarce, interactive requests are served first and may wait less long.
INTERACTIVE, BACKGROUND = 0, 1
_PRIORITY: contextvars.ContextVar[int] = contextvars.ContextVar("expert_request_priority", default=INTERACTIVE)


def mark_background() -> None:
    """Make the current task's model calls background work (call at the start of a job's task;
    a task's context is its own, so the setting never leaks into a chat request)."""
    _PRIORITY.set(BACKGROUND)


class _PriorityGate:
    """A semaphore whose waiters are served by priority, then first come first served — the
    request queue in front of one endpoint. Cancellation-safe: a waiter that goes away leaves
    the queue, and a slot granted to a request that was cancelled passes to the next one."""

    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, int(capacity))
        self.inflight = 0
        self._waiters: List[Tuple[int, int, "asyncio.Future[None]"]] = []
        self._seq = itertools.count()

    def waiting(self) -> int:
        return sum(1 for _, _, fut in self._waiters if not fut.done())

    async def acquire(self, priority: int) -> None:
        if self.inflight < self.capacity and not self.waiting():
            self.inflight += 1
            return
        fut: "asyncio.Future[None]" = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._seq), fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release()                      # granted, then cancelled: hand the slot on
            raise

    def release(self) -> None:
        while self._waiters:
            _, _, fut = heapq.heappop(self._waiters)
            if not fut.done():
                fut.set_result(None)                # the slot passes straight to the next waiter
                return
        self.inflight = max(0, self.inflight - 1)


class _EndpointPacer:
    """Adaptive client-side throttling, per base URL (the pattern behind the AWS SDKs'
    "adaptive" retry mode and Google SRE's client-side throttling):

    * a **queue** in front of every endpoint: at most ``max_inflight`` requests at a time, the
      rest wait in line — interactive requests ahead of background work — and a gap between
      request starts;
    * the gap starts at ``min_interval`` and **doubles on every rate limit** (up to
      ``max_interval``), and every other caller to that endpoint waits out the cooldown too —
      so one 429 slows the whole app down instead of each request hammering on its own;
    * every success **shrinks the gap back** by 15 %, so a quiet endpoint is fast again soon.

    Heavy's agents and Deep research's sub-agents then reach a shared gateway as a steady
    trickle that adapts to its real limit, instead of a burst that trips it."""

    def __init__(self, max_inflight: int, min_interval: float, max_interval: float, window: float = 60.0) -> None:
        self.max_inflight = max(1, int(max_inflight))
        self.min_interval = max(0.0, float(min_interval))
        self.max_interval = max(self.min_interval, float(max_interval))
        self.window = max(0.01, float(window))
        self._slots: Dict[str, _PriorityGate] = {}
        self._next_start: Dict[str, float] = {}
        self._interval: Dict[str, float] = {}
        # The meter, per endpoint: request starts (reserved, oldest first), successes and rate
        # limits in the rolling window, and the learned cap — requests per window the endpoint
        # takes before it says "rate limit" — with when it was last lowered or raised.
        self._starts: Dict[str, Deque[float]] = {}
        self._ok: Dict[str, Deque[float]] = {}
        self._limited: Dict[str, Deque[float]] = {}
        self._cap: Dict[str, int] = {}
        self._cap_since: Dict[str, float] = {}
        # Token bucket at the learned rate (cap per window): tokens left, and when last counted.
        # It goes negative as requests reserve future slots, so starts are spread evenly.
        self._tokens: Dict[str, float] = {}
        self._refill_at: Dict[str, float] = {}
        self._totals: Dict[str, Dict[str, int]] = {}
        self._urls: Dict[str, str] = {}

    def reset(self, *, min_interval: Optional[float] = None, max_interval: Optional[float] = None,
              window: Optional[float] = None) -> None:
        """Forget every endpoint's state (tests; a settings change)."""
        if min_interval is not None:
            self.min_interval = max(0.0, float(min_interval))
        if max_interval is not None:
            self.max_interval = max(self.min_interval, float(max_interval))
        if window is not None:
            self.window = max(0.01, float(window))
        for store in (self._slots, self._next_start, self._interval, self._starts, self._ok, self._limited,
                      self._cap, self._cap_since, self._tokens, self._refill_at, self._totals, self._urls):
            store.clear()

    # ── the meter ────────────────────────────────────────────────────────────
    def _trim(self, q: Deque[float], now: float) -> Deque[float]:
        while q and q[0] < now - self.window:
            q.popleft()
        return q

    def _count(self, key: str, what: str) -> None:
        totals = self._totals.setdefault(key, {"requests": 0, "ok": 0, "rate_limited": 0})
        totals[what] = totals.get(what, 0) + 1

    def cap(self, base_url: str) -> Optional[int]:
        return self._cap.get(self._key(base_url))

    def usage(self) -> List[Dict[str, Any]]:
        """Per endpoint: what is in flight and in line, the gap and cooldown, the learned cap,
        and the rolling window's requests, successes and rate limits (``GET /v1/expert/usage``)."""
        now = time.monotonic()
        out: List[Dict[str, Any]] = []
        for key, url in self._urls.items():
            gate = self._slots.get(key)
            limited = self._trim(self._limited.setdefault(key, deque()), now)
            out.append({
                "endpoint": url,
                "in_flight": gate.inflight if gate else 0,
                "queued": gate.waiting() if gate else 0,
                "interval_s": round(self._interval.get(key, self.min_interval), 2),
                "cooldown_s": round(max(0.0, self._next_start.get(key, 0.0) - now), 1),
                "window_s": self.window,
                "cap_per_window": self._cap.get(key),
                "tokens": round(self._tokens[key], 2) if key in self._tokens else None,
                "requests_in_window": len(self._trim(self._starts.setdefault(key, deque()), now)),
                "ok_in_window": len(self._trim(self._ok.setdefault(key, deque()), now)),
                "rate_limited_in_window": len(limited),
                "last_rate_limit_s_ago": round(now - limited[-1], 1) if limited else None,
                "totals": dict(self._totals.get(key, {})),
            })
        return out

    @staticmethod
    def _key(base_url: str) -> str:
        # Keyed by event loop too: a semaphore belongs to the loop it first waited in.
        return f"{id(asyncio.get_running_loop())}|{(base_url or '').rstrip('/').lower()}"

    def interval(self, base_url: str) -> float:
        return self._interval.get(self._key(base_url), self.min_interval)

    def _gate(self, key: str) -> _PriorityGate:
        gate = self._slots.get(key)
        if gate is None:
            gate = self._slots[key] = _PriorityGate(self.max_inflight)
        return gate

    def expected_wait(self, base_url: str) -> float:
        """Roughly how long a request sent now waits before it starts: the cooldown, plus one
        gap per request already in line. Used to tell the reader before a long wait."""
        key = self._key(base_url)
        gate = self._gate(key)
        cooldown = max(0.0, self._next_start.get(key, 0.0) - time.monotonic())
        queued = gate.waiting() + (1 if gate.inflight >= gate.capacity else 0)
        return cooldown + queued * self._interval.get(key, self.min_interval)

    def _bucket(self, key: str, cap: int, now: float) -> float:
        """Tokens in the bucket now (refilled at ``cap`` per window since last counted)."""
        rate = cap / self.window
        tokens = self._tokens.get(key, float(cap))
        tokens = min(float(cap), tokens + (now - self._refill_at.get(key, now)) * rate)
        self._refill_at[key] = now
        return tokens

    def _reserve(self, key: str) -> float:
        """This request's start time: after the cooldown and the gap, and — once a cap has been
        learned — when the token bucket has a token for it. Starts are then spread evenly at the
        learned rate (one every window/cap seconds) instead of a burst and a long stall."""
        now = time.monotonic()
        start_at = max(now, self._next_start.get(key, 0.0))
        starts = self._starts.setdefault(key, deque())
        cap = self._cap.get(key)
        if cap:
            tokens = self._bucket(key, cap, now) - 1.0
            self._tokens[key] = tokens
            if tokens < 0:
                start_at = max(start_at, now + (-tokens) * self.window / cap)
        starts.append(start_at)
        while starts and starts[0] < now - 2 * self.window:
            starts.popleft()
        self._next_start[key] = start_at + self._interval.get(key, self.min_interval)
        return start_at

    @contextlib.asynccontextmanager
    async def slot(self, base_url: str) -> AsyncIterator[None]:
        key = self._key(base_url)
        self._urls.setdefault(key, (base_url or "").rstrip("/"))
        gate = self._gate(key)
        await gate.acquire(_PRIORITY.get())
        try:
            # Reserve this request's start time before sleeping, so two waiting callers can never
            # read the same free moment and start together.
            start_at = self._reserve(key)
            self._count(key, "requests")
            now = time.monotonic()
            if start_at > now:
                await asyncio.sleep(start_at - now)
            yield
        finally:
            gate.release()

    def penalize(self, base_url: str, retry_after: Optional[float] = None) -> float:
        """A rate limit: double the gap, hold every caller until the cooldown ends, and learn the
        cap from the successes this window took — the endpoint's limit is at most that. With no
        success in the window there is nothing to learn from (the limit may be shared with other
        clients): an existing cap is lowered by one, and otherwise backoff alone handles it.
        The bucket is emptied, so the next start waits one learned interval."""
        key = self._key(base_url)
        now = time.monotonic()
        self._count(key, "rate_limited")
        self._trim(self._limited.setdefault(key, deque()), now).append(now)
        ok = len(self._trim(self._ok.setdefault(key, deque()), now))
        previous = self._cap.get(key)
        if ok >= 1:
            self._cap[key] = max(1, min(ok, previous - 1)) if previous else ok
        elif previous:
            self._cap[key] = max(1, previous - 1)
        if key in self._cap:
            self._cap_since[key] = now
            self._tokens[key] = min(0.0, self._bucket(key, self._cap[key], now))
            if self._cap[key] != previous:
                logger.info("endpoint %s: learned a limit of about %d requests per %.0fs", self._urls.get(key, key),
                            self._cap[key], self.window)
        current = self._interval.get(key, self.min_interval)
        grown = min(self.max_interval, max(current * 2, 2.0, self.min_interval))
        self._interval[key] = grown
        cooldown = min(self.max_interval, max(grown, retry_after or 0.0))
        self._next_start[key] = max(self._next_start.get(key, 0.0), now + cooldown)
        return grown

    def reward(self, base_url: str) -> None:
        """A success: count it, shrink the gap back toward ``min_interval``, and after a quiet
        stretch (three windows without a rate limit) raise the learned cap by one — additive
        increase, so a limit that was lifted is found again."""
        key = self._key(base_url)
        now = time.monotonic()
        self._count(key, "ok")
        self._trim(self._ok.setdefault(key, deque()), now).append(now)
        cap = self._cap.get(key)
        if cap is not None and now - self._cap_since.get(key, now) > 3 * self.window:
            if cap >= 120:
                self._cap.pop(key, None)            # far above any limit seen: stop capping
                self._cap_since.pop(key, None)
            else:
                self._cap[key] = cap + 1
                self._cap_since[key] = now
        current = self._interval.get(key)
        if current is not None:
            relaxed = max(self.min_interval, current * 0.85)
            if relaxed <= self.min_interval:
                self._interval.pop(key, None)
            else:
                self._interval[key] = relaxed


_PACER = _EndpointPacer(EXPERT_PROVIDER_MAX_INFLIGHT, EXPERT_PROVIDER_MIN_INTERVAL_S, EXPERT_PROVIDER_MAX_INTERVAL_S,
                        EXPERT_PROVIDER_WINDOW_S)


def endpoint_usage() -> List[Dict[str, Any]]:
    """The usage meter, for ``GET /v1/expert/usage``."""
    return _PACER.usage()


class _Transient(RuntimeError):
    """A failure worth a short wait and another try — before any token has been produced, so
    nothing is repeated to the reader. Past the retries it reaches the user as it is."""

    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _RateLimited(_Transient):
    """HTTP 429, or a body that says "rate limit" (Open WebUI says it with a 400)."""


class _Overloaded(_Transient):
    """HTTP 502/503/504: a gateway shedding load (503 + Retry-After is backpressure, not an
    error) or a replica mid-restart. One or two tries later it is usually gone."""


def _retry_after(headers: Any) -> Optional[float]:
    try:
        value = float((headers or {}).get("retry-after") or 0)
    except (TypeError, ValueError):
        return None
    return value if 0 < value <= 30 else None


def _backoff_s(attempt: int, retry_after: Optional[float]) -> float:
    """Exponential backoff with jitter: about 2 s, 4 s, 8 s, 16 s (capped at 20 s), each ±25 %
    so callers that failed together do not retry together. A Retry-After header is a floor."""
    base = min(20.0, 2.0 * (2 ** attempt))
    if retry_after:
        base = max(base, retry_after)
    return base * random.uniform(0.75, 1.25)


def _wait_budget() -> float:
    """How long a request may wait in line and retry before it gives up: a person waits less
    than a background job."""
    return EXPERT_PROVIDER_BACKGROUND_WAIT_S if _PRIORITY.get() == BACKGROUND else EXPERT_PROVIDER_WAIT_S


def _gave_up(err: "_Transient", waited: float, model: str) -> RuntimeError:
    """The error a reader sees once the wait budget is spent: what happened, and what to do."""
    name = (model or "the selected model").split("/")[-1]
    if isinstance(err, _RateLimited):
        text = (f"The model provider for {name} is busy right now (rate limited). HomePilot waited "
                f"{waited:.0f} s in line; please try again in a minute.")
    else:
        text = (f"The model provider for {name} is overloaded or restarting. HomePilot waited "
                f"{waited:.0f} s; please try again in a minute.")
    out = type(err)(text, retry_after=err.retry_after)
    out.__cause__ = err
    return out


def _next_retry(err: "_Transient", attempt: int, started: float, base_url: str, model: str) -> float:
    """The delay before the next try, or raise when the budget (time or tries) is spent."""
    delay = _backoff_s(attempt, err.retry_after)
    waited = time.monotonic() - started
    if attempt >= EXPERT_PROVIDER_RETRIES or waited + delay > _wait_budget():
        logger.warning("%s for %s: giving up after %.0fs and %d tries: %s", base_url, model, waited, attempt + 1, err)
        raise _gave_up(err, waited, model)
    logger.info("%s for %s: %s; retry %d in %.1fs (waited %.0fs of %.0fs)", base_url, model,
                type(err).__name__.strip("_").lower(), attempt + 1, delay, waited, _wait_budget())
    return delay


def _wait_event(text: str, seconds: float, attempt: int = 0) -> Dict[str, Any]:
    return {"wait": {"text": text, "retry_in": round(max(0.0, seconds), 1), "attempt": attempt}}

# If the configured EXPERT_LOCAL_MODEL / EXPERT_LOCAL_FAST_MODEL isn't pulled,
# fall back to whatever Ollama has locally. Set to "false" to disable and get
# a hard error instead — useful in production where the deployed model must
# match exactly.
_LOCAL_AUTO_FALLBACK = os.getenv("EXPERT_LOCAL_AUTO_FALLBACK", "true").lower() != "false"

# Where Ollama may live besides EXPERT_OLLAMA_URL: loopback, and the Windows /
# Docker host when this service runs inside WSL or a container. The first URL
# that answers /api/tags with models wins and is remembered for a short time
# (same rules as HomePilot's backend/app/model_resolver.py; this service is
# deliberately isolated, so the 40 lines are copied rather than imported).
_OLLAMA_CACHE: Dict[str, Any] = {"url": "", "ts": 0.0, "models": []}
_OLLAMA_CACHE_TTL_S = 30.0


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def _host_gateway_ips() -> List[str]:
    out: List[str] = []
    for line in _read_text("/proc/net/route").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "00000000":
            try:
                raw = int(parts[2], 16)
                out.append(".".join(str((raw >> (8 * i)) & 0xFF) for i in range(4)))
            except ValueError:
                pass
    for line in _read_text("/etc/resolv.conf").splitlines():
        p = line.split()
        if len(p) >= 2 and p[0] == "nameserver" and p[1].count(".") == 3 and p[1] not in out:
            out.append(p[1])
    return [ip for ip in out if not ip.startswith("127.")]


def _ollama_candidates() -> List[str]:
    urls = [EXPERT_OLLAMA_URL, "http://127.0.0.1:11434", "http://localhost:11434"]
    in_wsl = bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in _read_text("/proc/version").lower()
    if in_wsl:
        urls += [f"http://{ip}:11434" for ip in _host_gateway_ips()]
    if os.path.exists("/.dockerenv"):
        urls += ["http://host.docker.internal:11434", "http://172.17.0.1:11434"]
    seen: List[str] = []
    for u in urls:
        u = (u or "").rstrip("/")
        if u and u not in seen:
            seen.append(u)
    return seen


def _ollama_base() -> str:
    """Runtime URL the last successful probe found (EXPERT_OLLAMA_URL until then)."""
    return _OLLAMA_CACHE["url"] or EXPERT_OLLAMA_URL


async def _ollama_pulled_models() -> List[str]:
    """Model tags of the first reachable Ollama among ``_ollama_candidates()``
    that has models. Remembers which URL answered so chat_local/stream_local
    talk to the same runtime. Empty when nothing answers."""
    import time as _time
    now = _time.monotonic()
    if _OLLAMA_CACHE["url"] and _OLLAMA_CACHE["models"] and now - _OLLAMA_CACHE["ts"] < _OLLAMA_CACHE_TTL_S:
        return list(_OLLAMA_CACHE["models"])
    best_url, best_models = "", []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            for url in _ollama_candidates():
                try:
                    r = await client.get(f"{url}/api/tags")
                    r.raise_for_status()
                    data = r.json()
                except Exception:
                    continue
                models = [m.get("name") or m.get("model") for m in data.get("models", []) if isinstance(m, dict)]
                if models:
                    best_url, best_models = url, models
                    break
                if not best_url:
                    best_url = url
    except Exception:
        pass
    if best_url:
        _OLLAMA_CACHE.update(url=best_url, ts=now, models=best_models)
    return best_models


async def _resolve_local_model(requested: str) -> str:
    """Return ``requested`` if Ollama has it pulled, otherwise either fall back
    to the first available model or raise a clear error describing how to pull
    it. Behavior controlled by ``EXPERT_LOCAL_AUTO_FALLBACK``."""
    pulled = await _ollama_pulled_models()
    if not pulled:
        probed = ", ".join(_ollama_candidates())
        raise RuntimeError(
            f"No Ollama with models answered (tried {probed}). Open Settings → Models in "
            f"HomePilot to download one, or run `ollama pull {requested}`. If Ollama runs on "
            f"Windows and this service runs in WSL, enable WSL mirrored networking."
        )
    if requested in pulled:
        return requested
    if not _LOCAL_AUTO_FALLBACK:
        raise RuntimeError(
            f"Expert local model '{requested}' is not pulled. "
            f"Available: {pulled}. Run `ollama pull {requested}` to fix."
        )
    # Prefer an exact stem match (handles ':latest' vs ':Q4_K_M' variants).
    stem = requested.split(":")[0]
    for m in pulled:
        if m and m.split(":")[0] == stem:
            return m
    return pulled[0]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _openai_wrap(
    content: str, model: str, provider: str, tool_calls: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Wrap a plain text response into OpenAI-like schema for orchestrator consistency.
    ``tool_calls`` (OpenAI shape, see :func:`_normalize_tool_calls`) ride on the message."""
    message: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message}],
        "model": model,
        "provider": provider,
    }


def _extract_content(data: Dict[str, Any]) -> str:
    """Extract text content from OpenAI-style response dict."""
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Tool calling — one wire shape inside Expert (OpenAI's), translated per provider
# ─────────────────────────────────────────────────────────────────────────────

class ToolsUnsupported(RuntimeError):
    """The model or endpoint rejected the ``tools`` field; the caller retries without tools."""


def _rate_limited(status: int, body: str) -> bool:
    text = (body or "").lower()
    return status == 429 or "rate limit" in text or "rate_limit" in text or "too many requests" in text


def _tools_rejected(status: int, body: str) -> bool:
    """Ollama answers 400 "<model> does not support tools"; OllaBridge says ``tools_unsupported``;
    other gateways say similar things. Never a rate limit, whatever its status."""
    text = (body or "").lower()
    if _rate_limited(status, text):
        return False
    if "tools_unsupported" in text:
        return True
    return status in (400, 422) and ("tool" in text or "function" in text)


def _legacy_tools_failure(status: int, body: str) -> bool:
    """OllaBridge before October 2026 sent a tool-bearing request for a provider model to local
    Ollama: HTTP 500 wrapping "404 Not Found … /api/chat". Read as "no tools here"."""
    text = (body or "").lower()
    return status >= 500 and "/api/chat" in text and "404" in text


def _wrapped_local_refusal(status: int, body: str) -> bool:
    """An OllaBridge 500 wrapping local Ollama's 400 ("Client error '400 Bad Request' for url …
    /api/chat"): on a tool-bearing request, Ollama's "this model does not support tools"."""
    text = (body or "").lower()
    return status >= 500 and "/api/chat" in text and "400" in text


def _message_in(data: Any) -> str:
    """The human message in an error body, however it is nested: OpenAI's ``error.message``,
    FastAPI's ``detail`` (a string, or OllaBridge's ``detail.error.message``), or ``message``."""
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, dict):
        return ""
    for key in ("error", "detail", "message"):
        found = _message_in(data.get(key))
        if found:
            return found
    return ""


def _detail_text(body: str) -> str:
    """The message inside an error body (see :func:`_message_in`), else the body."""
    try:
        data = json.loads(body or "")
    except (json.JSONDecodeError, TypeError):
        return (body or "").strip()
    return _message_in(data) or (body or "").strip()


def _openai_compat_error(status: int, detail: str, headers: Any, *, base_url: str, model: str, tools: bool) -> Exception:
    """The exception for an error answer from ``{base_url}/chat/completions``: a rate limit to
    wait out, a refusal of the tools field to remember, or the endpoint's own explanation."""
    who = f"{model or 'The selected model'} at {base_url}"
    text = (detail or "").strip()
    if _rate_limited(status, text):
        return _RateLimited(
            f"{who} is being rate limited by its provider (HTTP {status}"
            + (f": {text[:160]}" if text else "") + "). Try again in a moment.",
            retry_after=_retry_after(headers),
        )
    if tools and (_tools_rejected(status, text) or _legacy_tools_failure(status, text)
                  or _wrapped_local_refusal(status, text)):
        return ToolsUnsupported(
            f"{who} rejected the tools field (HTTP {status}" + (f": {text[:160]}" if text else "") + ")"
        )
    if _legacy_tools_failure(status, text):
        # An older OllaBridge reports a provider failure (most often its rate limit) as a 500
        # from local Ollama; for a request without tools it is worth waiting for, not fatal.
        return _RateLimited(
            f"{who} could not reach its provider (HTTP {status}; an older OllaBridge reports a "
            "provider's rate limit this way). Try again in a moment.",
            retry_after=_retry_after(headers),
        )
    if status in (502, 503, 504):
        return _Overloaded(
            f"{who} is overloaded or restarting (HTTP {status}"
            + (f": {text[:160]}" if text else "") + "). Try again in a moment.",
            retry_after=_retry_after(headers),
        )
    return RuntimeError(f"{who} answered HTTP {status}" + (f": {text[:240]}" if text else ""))


def _normalize_tool_calls(raw: Any) -> List[Dict[str, Any]]:
    """Tool calls as OpenAI emits them: ``{id, type, function: {name, arguments: <json str>}}``.
    Ollama sends ``arguments`` as an object and no id; both are normalized here."""
    out: List[Dict[str, Any]] = []
    for i, call in enumerate(raw or []):
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args or {}, ensure_ascii=False)
        out.append({
            "id": str(call.get("id") or f"call_{i + 1}"),
            "type": "function",
            "function": {"name": str(fn.get("name") or ""), "arguments": args or "{}"},
        })
    return out


def _openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Messages for an OpenAI-compatible endpoint: role/content, plus the tool-call fields."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": str(m.get("tool_call_id") or ""), "content": str(m.get("content") or "")})
        elif role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": _normalize_tool_calls(m["tool_calls"])})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _ollama_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Messages for Ollama's /api/chat: tool results carry ``tool_name`` and arguments are objects."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append({"role": "tool", "content": str(m.get("content") or ""), "tool_name": str(m.get("name") or "")})
        elif role == "assistant" and m.get("tool_calls"):
            calls = []
            for c in _normalize_tool_calls(m["tool_calls"]):
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {"input": c["function"]["arguments"]}
                calls.append({"function": {"name": c["function"]["name"], "arguments": args if isinstance(args, dict) else {"input": args}}})
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _params_b(text: Any) -> Optional[float]:
    """'8.2B' → 8.2, '70B' → 70, '355M' → 0.355; None when the text says nothing."""
    s = str(text or "").strip().upper()
    if not s:
        return None
    try:
        if s.endswith("B"):
            return float(s[:-1])
        if s.endswith("M"):
            return float(s[:-1]) / 1000.0
        return float(s)
    except ValueError:
        return None


async def ollama_models_detail(base_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """``[{name, params_b, family, size_gb}]`` from ``/api/tags`` of ``base_url`` or the default
    Ollama. Empty when nothing answers."""
    urls = [base_url.rstrip("/")] if base_url else _ollama_candidates()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
            for url in urls:
                try:
                    r = await client.get(f"{url}/api/tags")
                    r.raise_for_status()
                    data = r.json()
                except Exception:
                    continue
                out = []
                for m in data.get("models", []) or []:
                    if not isinstance(m, dict):
                        continue
                    details = m.get("details") or {}
                    out.append({
                        "name": m.get("name") or m.get("model") or "",
                        "params_b": _params_b(details.get("parameter_size")),
                        "family": str(details.get("family") or ""),
                        "size_gb": round(float(m.get("size") or 0) / 1e9, 1),
                    })
                if out:
                    return out
    except Exception:
        pass
    return []


async def openai_compat_models(base_url: str, api_key: str = "") -> List[str]:
    """Model ids an OpenAI-compatible endpoint lists at ``GET {base_url}/models``."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
            r = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    items = data.get("data") if isinstance(data, dict) else data
    names: List[str] = []
    for item in items or []:
        name = item.get("id") or item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name:
            names.append(name)
    return names


# ─────────────────────────────────────────────────────────────────────────────
# xAI Grok  (OpenAI-compatible — reuses same wire format)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_grok(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """xAI Grok via OpenAI-compatible /v1/chat/completions."""
    if not GROK_API_KEY:
        raise RuntimeError("GROK_API_KEY not set — cannot use Grok provider.")
    mdl = model or GROK_MODEL
    url = f"{GROK_BASE_URL}/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {GROK_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json()
    data["provider"] = "grok"
    return data


async def stream_grok(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """Stream tokens from Grok, yielding SSE-ready delta strings."""
    if not GROK_API_KEY:
        raise RuntimeError("GROK_API_KEY not set.")
    mdl = model or GROK_MODEL
    url = f"{GROK_BASE_URL}/chat/completions"
    payload = {
        "model": mdl, "messages": messages, "stream": True,
        "temperature": float(temperature), "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream(
            "POST", url, json=payload,
            headers={"Authorization": f"Bearer {GROK_API_KEY}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


# ─────────────────────────────────────────────────────────────────────────────
# Groq  (ultra-fast, free tier, open models: Llama 3.3 70B, Mixtral, etc.)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_groq(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """Groq inference API — OpenAI-compatible, blazing fast."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set — cannot use Groq provider.")
    mdl = model or GROQ_MODEL
    url = f"{GROQ_BASE_URL}/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json()
    data["provider"] = "groq"
    return data


async def stream_groq(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """Stream tokens from Groq."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set.")
    mdl = model or GROQ_MODEL
    url = f"{GROQ_BASE_URL}/chat/completions"
    payload = {
        "model": mdl, "messages": messages, "stream": True,
        "temperature": float(temperature), "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream(
            "POST", url, json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


# ─────────────────────────────────────────────────────────────────────────────
# Google Gemini  (via OpenAI-compatible endpoint — available since Gemini 1.5)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_gemini(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> Dict[str, Any]:
    """Google Gemini via its OpenAI-compatible REST endpoint."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set — cannot use Gemini provider.")
    mdl = model or GEMINI_MODEL
    url = f"{GEMINI_BASE_URL}/chat/completions"
    payload = {
        "model": mdl,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {GEMINI_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json()
    data["provider"] = "gemini"
    return data


async def stream_gemini(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
) -> AsyncIterator[str]:
    """Stream tokens from Gemini."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set.")
    mdl = model or GEMINI_MODEL
    url = f"{GEMINI_BASE_URL}/chat/completions"
    payload = {
        "model": mdl, "messages": messages, "stream": True,
        "temperature": float(temperature), "max_tokens": int(max_tokens),
    }
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream(
            "POST", url, json=payload,
            headers={"Authorization": f"Bearer {GEMINI_API_KEY}"},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible endpoint the user chose for chat (OllaBridge gateway, Cloud relay, vLLM…)
# ─────────────────────────────────────────────────────────────────────────────

async def chat_openai_compat(
    messages: List[Dict[str, Any]],
    *,
    base_url: str,
    model: str = "",
    api_key: str = "",
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    provider_label: str = "openai_compat",
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """``POST {base_url}/chat/completions`` — the same request HomePilot's ordinary chat sends
    (``app.llm.chat_openai_compat``), kept here because Expert is loaded as its own top-level
    package and cannot import the backend's modules relatively.

    Failures carry the endpoint's own explanation: a gateway that refuses a model says why in
    its body, and "HTTP 500" alone sends the user looking in the wrong place.
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: Dict[str, Any] = {
        "messages": _openai_messages(messages),
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    if model:
        payload["model"] = model
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    attempt = 0
    started = time.monotonic()
    while True:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client, _PACER.slot(base_url):
                r = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Could not reach {base_url} for {model or 'the selected model'} "
                f"({type(exc).__name__}). Is it running?"
            ) from exc
        if r.status_code < 400:
            _PACER.reward(base_url)
            break
        err = _openai_compat_error(
            r.status_code, _error_detail(r), r.headers, base_url=base_url, model=model, tools=bool(tools),
        )
        if not isinstance(err, _Transient):
            raise err
        if isinstance(err, _RateLimited):
            _PACER.penalize(base_url, err.retry_after)
        await asyncio.sleep(_next_retry(err, attempt, started, base_url, model))
        attempt += 1
    data = r.json()
    try:
        raw_calls = data["choices"][0]["message"].get("tool_calls")
    except (KeyError, IndexError, AttributeError):
        raw_calls = None
    return _openai_wrap(
        _extract_content(data), str(data.get("model") or model), provider_label,
        tool_calls=_normalize_tool_calls(raw_calls),
    )


def _error_detail(r: httpx.Response) -> str:
    try:
        return _message_in(r.json()) or (r.text or "").strip()
    except Exception:  # noqa: BLE001
        return (r.text or "").strip()


async def stream_openai_compat_events(
    messages: List[Dict[str, Any]],
    *,
    base_url: str,
    model: str = "",
    api_key: str = "",
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream ``{base_url}/chat/completions`` (:func:`_stream_openai_compat_once`) through the
    endpoint's queue, retried with backoff while the provider rate-limits or sheds load — only
    before the first token, so nothing is ever repeated to the reader. While it waits it says
    so: ``{"wait": {"text", "retry_in", "attempt"}}`` events, which the chat shows in place of
    a silent pause."""
    attempt = 0
    started = time.monotonic()
    ahead = _PACER.expected_wait(base_url)
    if ahead >= 2.0:
        yield _wait_event("Waiting in line for the model provider…", ahead)
    while True:
        try:
            async for event in _stream_openai_compat_once(
                messages, base_url=base_url, model=model, api_key=api_key,
                temperature=temperature, max_tokens=max_tokens, tools=tools,
            ):
                yield event
            _PACER.reward(base_url)
            return
        except _Transient as exc:
            if isinstance(exc, _RateLimited):
                _PACER.penalize(base_url, exc.retry_after)
            delay = _next_retry(exc, attempt, started, base_url, model)
            busy = "busy" if isinstance(exc, _RateLimited) else "overloaded"
            yield _wait_event(f"The model provider is {busy}; retrying in {delay:.0f} s…", delay, attempt + 1)
            await asyncio.sleep(delay)
            attempt += 1


async def _stream_openai_compat_once(
    messages: List[Dict[str, Any]],
    *,
    base_url: str,
    model: str = "",
    api_key: str = "",
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream ``{base_url}/chat/completions``: ``{"delta": text}`` as tokens arrive and, once
    the stream ends, ``{"tool_calls": [...]}`` when the model called tools (their argument
    fragments are assembled here, by index, the way OpenAI streams them)."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: Dict[str, Any] = {
        "messages": _openai_messages(messages),
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": True,
    }
    if model:
        payload["model"] = model
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    pending: Dict[int, Dict[str, str]] = {}
    try:
        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client, _PACER.slot(base_url):
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise _openai_compat_error(
                        resp.status_code, _detail_text(body), resp.headers,
                        base_url=base_url, model=model, tools=bool(tools),
                    )
                if "text/event-stream" not in (resp.headers.get("content-type") or "").lower():
                    # A gateway that ignores stream=true answers with one JSON completion (OllaBridge
                    # does): hand it over as a single delta rather than reading it as empty SSE.
                    raw_body = (await resp.aread()).decode("utf-8", "replace")
                    try:
                        data = json.loads(raw_body or "{}")
                    except json.JSONDecodeError:
                        data = {}
                    content = _extract_content(data) if isinstance(data, dict) else ""
                    if content:
                        yield {"delta": content}
                    try:
                        raw_calls = data["choices"][0]["message"].get("tool_calls")
                    except (KeyError, IndexError, AttributeError, TypeError):
                        raw_calls = None
                    calls = _normalize_tool_calls(raw_calls)
                    if calls:
                        yield {"tool_calls": calls}
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        yield {"delta": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index", len(pending)) or 0)
                        slot = pending.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = str(tc["id"])
                        fn = tc.get("function") or {}
                        if fn.get("name") and not slot["name"]:
                            slot["name"] = str(fn["name"])
                        if fn.get("arguments"):
                            slot["arguments"] += str(fn["arguments"])
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Could not reach {base_url} for {model or 'the selected model'} ({type(exc).__name__}). Is it running?"
        ) from exc
    if pending:
        yield {"tool_calls": _normalize_tool_calls([
            {"id": s["id"], "function": {"name": s["name"], "arguments": s["arguments"] or "{}"}}
            for _, s in sorted(pending.items())
        ])}


# ─────────────────────────────────────────────────────────────────────────────
# Local Ollama  (free, on-premises, no API key needed)
# ─────────────────────────────────────────────────────────────────────────────

def _ollama_failure(r: httpx.Response, mdl: str) -> RuntimeError:
    """Ollama's own reason for a 5xx, which is usually the useful part ("model requires more
    system memory", "llama runner process has terminated") and was hidden behind a bare
    ``500 Internal Server Error``."""
    reason = ""
    try:
        reason = str((r.json() or {}).get("error") or "")
    except Exception:  # noqa: BLE001
        reason = (r.text or "").strip()
    reason = reason[:240] or r.reason_phrase or "server error"
    return RuntimeError(f"Ollama could not run '{mdl}' (HTTP {r.status_code}): {reason}")


async def chat_local(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    fast: bool = False,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    base_url: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Ollama local inference — zero cost, fully sovereign.

    ``base_url`` is an Ollama the user chose for chat; its model is used as given, since the
    installed-model check below is about the default Ollama, not that one. ``tools`` (OpenAI
    shape) are offered to the model; a model without tool support raises ToolsUnsupported.
    """
    requested = model or (EXPERT_LOCAL_FAST_MODEL if fast else EXPERT_LOCAL_MODEL)
    mdl = requested if (base_url and model) else await _resolve_local_model(requested)
    url = f"{(base_url or _ollama_base()).rstrip('/')}/api/chat"
    payload: Dict[str, Any] = {
        "model": mdl,
        "messages": _ollama_messages(messages),
        "stream": False,
        "options": {
            "temperature": float(temperature),
            "num_predict": int(max_tokens),
        },
    }
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(url, json=payload)
        if r.status_code == 404:
            raise RuntimeError(
                f"Ollama rejected model '{mdl}' with 404. Run "
                f"`ollama pull {mdl}` and retry (or set EXPERT_LOCAL_MODEL)."
            )
        if r.status_code >= 500:
            raise _ollama_failure(r, mdl)
        if tools and _tools_rejected(r.status_code, r.text):
            raise ToolsUnsupported(f"{mdl} does not support tool calling.")
        r.raise_for_status()
        data = r.json()

    message = data.get("message", {}) or {}
    return _openai_wrap(message.get("content", ""), mdl, "local", tool_calls=_normalize_tool_calls(message.get("tool_calls")))


async def stream_local_events(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    fast: bool = False,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    base_url: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream Ollama: ``{"delta": text}`` per token and ``{"tool_calls": [...]}`` when the model
    calls tools. ``base_url`` and ``tools``: as in :func:`chat_local`."""
    requested = model or (EXPERT_LOCAL_FAST_MODEL if fast else EXPERT_LOCAL_MODEL)
    mdl = requested if (base_url and model) else await _resolve_local_model(requested)
    url = f"{(base_url or _ollama_base()).rstrip('/')}/api/chat"
    payload: Dict[str, Any] = {
        "model": mdl,
        "messages": _ollama_messages(messages),
        "stream": True,
        "options": {"temperature": float(temperature), "num_predict": int(max_tokens)},
    }
    if tools:
        payload["tools"] = tools
    calls: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Ollama rejected model '{mdl}' with 404. Run "
                    f"`ollama pull {mdl}` and retry (or set EXPERT_LOCAL_MODEL)."
                )
            if resp.status_code == 400 and tools:
                body = (await resp.aread()).decode("utf-8", "replace")
                if _tools_rejected(400, body):
                    raise ToolsUnsupported(f"{mdl} does not support tool calling.")
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = chunk.get("message", {}) or {}
                delta = message.get("content", "")
                if delta:
                    yield {"delta": delta}
                if message.get("tool_calls"):
                    calls.extend(_normalize_tool_calls(message["tool_calls"]))
                if chunk.get("done"):
                    break
    if calls:
        yield {"tool_calls": calls}


async def stream_local(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    fast: bool = False,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    base_url: Optional[str] = None,
) -> AsyncIterator[str]:
    """Stream tokens from Ollama. ``base_url``: as in :func:`chat_local`."""
    async for event in stream_local_events(
        messages, model=model, fast=fast, temperature=temperature, max_tokens=max_tokens, base_url=base_url,
    ):
        if "delta" in event:
            yield event["delta"]
