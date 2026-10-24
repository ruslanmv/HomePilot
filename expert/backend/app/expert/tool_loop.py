"""The per-turn tool loop: offer tools, run the calls the model makes, then answer.

The shape ChatGPT and Claude use for one turn: the model may call tools for a few rounds
(bounded by ``EXPERT_TOOL_MAX_ROUNDS``), each result goes back as a ``tool`` message, and
the last round is forced to answer without tools. The streaming form emits events so the UI
can show "Searching the web…" chips, the numbered sources, and tokens as they arrive; the
non-streaming form goes through ``dispatch`` (the seam the sync pipelines and their tests
already use). Models or endpoints that refuse the ``tools`` field are remembered and answer
without them.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from .config import (
    EXPERT_MAX_TOKENS,
    EXPERT_TEMPERATURE,
    EXPERT_TOOLS_ENABLED,
    EXPERT_TOOL_MAX_CALLS_PER_ROUND,
    EXPERT_TOOL_MAX_ROUNDS,
    EXPERT_TOOL_RESULT_MAX_CHARS,
)
from .config import EXPERT_CAPABILITY_NEGATIVE_TTL_S, EXPERT_CAPABILITY_TTL_S
from .providers import ToolsUnsupported, local_tool_crash_exception
from .router import ProviderName, dispatch, extract_dispatch_meta, stream_provider_events
from . import state_store
from . import target as target_mod
from . import tools as tools_mod

logger = logging.getLogger("expert.tool_loop")


def _refused_tools(exc: BaseException, *, offered: bool, provider: str, model: Optional[str]) -> bool:
    """A tools-field refusal, or the local runner crash (exit status 4 / a bare ``"4"``) on a
    request that offered tools. One retry without tools; any other error stays an error."""
    if isinstance(exc, ToolsUnsupported):
        return True
    if offered and local_tool_crash_exception(exc):
        logger.warning(
            "local tool runner crash; one retry without tools provider=%s model=%s tools=1 error_type=%s error=%s",
            provider, model, type(exc).__name__, exc,
        )
        return True
    return False

# What is known about a model's tool calling, by connection key (see capability_key): True when
# a call came back, False when the tools field was rejected. Learned facts survive a restart in
# the state store (an hour for a refusal, a month for a success); this dict is the warm copy.
# Bump the version when what a stored fact means changes (v2: facts learned against a gateway
# that failed every tool-bearing request no longer apply).
_TOOL_FACTS: Dict[str, bool] = {}
TOOL_SCHEMA_VERSION = "v2"

DispatchFn = Callable[..., Awaitable[Dict[str, Any]]]


def capability_key(target: Optional["target_mod.ChatTarget"], provider: str, model: Optional[str]) -> str:
    """One key per endpoint + model + tool schema version: what a learned fact applies to."""
    if target is not None:
        return f"{target.provider}|{target.base_url}|{target.model or model or ''}|{TOOL_SCHEMA_VERSION}"
    return f"{provider}||{model or ''}|{TOOL_SCHEMA_VERSION}"


def tools_known(key: str) -> Optional[bool]:
    """True / False when a fact is known for ``key``, None when it has to be tried."""
    if key in _TOOL_FACTS:
        return _TOOL_FACTS[key]
    stored = state_store.kv_get(f"tools:{key}")
    if stored is not None and isinstance(stored.get("ok"), bool):
        _TOOL_FACTS[key] = stored["ok"]
        return stored["ok"]
    return None


def remember_tools(key: str, ok: bool, *, source: str = "observed") -> None:
    _TOOL_FACTS[key] = ok
    ttl = EXPERT_CAPABILITY_TTL_S * 4 if ok else EXPERT_CAPABILITY_NEGATIVE_TTL_S
    state_store.kv_set(f"tools:{key}", {"ok": ok, "source": source, "at": time.time()}, ttl_s=ttl)


def forget_tools(key: Optional[str] = None) -> None:
    """Drop learned facts (tests; a settings change)."""
    if key is None:
        for k in list(_TOOL_FACTS):
            state_store.kv_delete(f"tools:{k}")
        _TOOL_FACTS.clear()
    else:
        _TOOL_FACTS.pop(key, None)
        state_store.kv_delete(f"tools:{key}")

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.S)
_LEAKED_TAG = re.compile(r"^\s*(?:</think>\s*|>\s*\n+)")


def strip_think(text: str) -> str:
    """Text without a reasoning model's ``<think>…</think>`` block, or the tag fragment some
    runtimes leak at the start of an answer (``</think>``, or a lone ``>`` before the text)."""
    return _LEAKED_TAG.sub("", _THINK_BLOCK.sub("", text or ""))


class ThinkFilter:
    """:func:`strip_think` for a token stream: holds back a possible partial tag, drops
    everything inside a think block, and never emits the leaked fragment at the start."""

    _TAGS = ("<think>", "</think>")

    def __init__(self) -> None:
        self.buf = ""
        self.inside = False
        self.emitted = False

    def _pending_tag(self) -> int:
        """Length of a tail of the buffer that may be the start of a tag."""
        for n in range(min(8, len(self.buf)), 0, -1):
            tail = self.buf[-n:]
            if any(tag.startswith(tail) for tag in self._TAGS):
                return n
        return 0

    def feed(self, delta: str) -> str:
        self.buf += delta
        out = ""
        while self.buf:
            if self.inside:
                end = self.buf.find("</think>")
                if end < 0:
                    self.buf = self.buf[-8:]          # thinking is dropped; a split tag may be pending
                    break
                self.buf = self.buf[end + len("</think>"):].lstrip()
                self.inside = False
                continue
            start = self.buf.find("<think>")
            if start >= 0:
                out += self.buf[:start]
                self.buf = self.buf[start + len("<think>"):]
                self.inside = True
                continue
            keep = self._pending_tag()
            out += self.buf[: len(self.buf) - keep]
            self.buf = self.buf[len(self.buf) - keep:]
            break
        if out and not self.emitted:
            out = _LEAKED_TAG.sub("", out)
            if out.strip():
                self.emitted = True
        return out

    def flush(self) -> str:
        out = "" if self.inside else self.buf
        self.buf = ""
        if out and not self.emitted:
            out = _LEAKED_TAG.sub("", out)
        return out


def _model_key(provider: str, model: Optional[str]) -> str:
    return capability_key(target_mod.current(), provider, model)


def _with_system_note(messages: List[Dict[str, Any]], note: str) -> List[Dict[str, Any]]:
    """``messages`` with ``note`` appended to the system prompt (one added when there is none)."""
    if messages and messages[0].get("role") == "system":
        first = dict(messages[0])
        first["content"] = f"{first.get('content') or ''}\n\n{note}"
        return [first, *messages[1:]]
    return [{"role": "system", "content": note}, *messages]


def _with_tools_note(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _with_system_note(messages, tools_mod.TOOLS_NOTE)


# Once there are numbered results in the conversation. The one-line mention in TOOLS_NOTE is
# not enough for smaller models; said on its own, right before the answer, it is followed.
CITE_NOTE = (
    "The results you were given are numbered. Cite each fact you take from them as [n] at the "
    "end of its sentence, using the number shown in the result; an answer may cite several."
)


def _round_messages(convo: List[Dict[str, Any]], *, offer: bool, book: "SourceBook") -> List[Dict[str, Any]]:
    """What the model sees this round: the tools note while tools are offered, and the
    citation note as soon as there is something to cite."""
    out = _with_tools_note(convo) if offer else convo
    if book.items:
        out = _with_system_note(out, CITE_NOTE)
    return out


def _parse_args(call: Dict[str, Any]) -> Dict[str, Any]:
    raw = (call.get("function") or {}).get("arguments") or "{}"
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        args = {"input": raw}
    return args if isinstance(args, dict) else {"input": args}


def _no_tools_note(model: Optional[str]) -> str:
    return f"{model or 'This model'} cannot call tools, so it answered from its own knowledge."


ForcedTools = List[Tuple[str, Dict[str, Any]]]


def _unavailable_note(forced: ForcedTools) -> str:
    names = ", ".join(n.replace("_", " ") for n, _ in forced) or "the tool"
    return f"{names} is not available right now, so the answer is from the model's own knowledge."


def without_tool_roles(convo: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The conversation for a model that cannot take tool messages: results already gathered
    (a forced web search, say) become plain user turns, and the tool-call stubs go."""
    out: List[Dict[str, Any]] = []
    for m in convo:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            if m.get("content"):
                out.append({"role": "assistant", "content": m["content"]})
            continue
        if role == "tool":
            label = str(m.get("name") or "tool").replace("_", " ")
            out.append({"role": "user", "content": f"Results from {label}:\n{m.get('content') or ''}"})
            continue
        out.append(m)
    return out


def _forced_calls(forced: Optional[ForcedTools], registry: tools_mod.ToolRegistry) -> List[Dict[str, Any]]:
    """Calls the operator asks for before the model's first word (the chat's "Search the
    web" switch), in the shape the model's own calls take; unknown tools are skipped."""
    calls: List[Dict[str, Any]] = []
    for i, (name, args) in enumerate(forced or [], 1):
        if registry.spec(name) is None:
            continue
        calls.append({"id": f"forced_{i}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args or {}, ensure_ascii=False)}})
    return calls


class SourceBook:
    """Numbered, de-duplicated sources across a turn: the model cites [n], the UI links n."""

    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []
        self._by_url: Dict[str, Dict[str, Any]] = {}

    def add(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Register new sources; returns only the ones not seen before."""
        new: List[Dict[str, Any]] = []
        for s in sources or []:
            url = s.get("url")
            if not url or url in self._by_url:
                continue
            item = {**{k: v for k, v in s.items() if k != "n"}, "n": len(self.items) + 1}
            self.items.append(item)
            self._by_url[url] = item
            new.append(item)
        return new

    def numbered(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self._by_url[s["url"]] for s in sources or [] if s.get("url") in self._by_url]


def result_text(outcome: tools_mod.ToolOutcome, numbered: List[Dict[str, Any]]) -> str:
    """What the model reads back: numbered sources for web-like results, else the tool's text."""
    if not outcome.ok:
        return f"Tool error: {outcome.error or 'failed'}"[:EXPERT_TOOL_RESULT_MAX_CHARS]
    if numbered:
        parts = []
        for s in numbered:
            block = f"[{s['n']}] {s.get('title') or s['url']}\n{s['url']}"
            if s.get("snippet"):
                block += f"\n{s['snippet']}"
            parts.append(block)
        text = "\n\n".join(parts)
    else:
        text = outcome.text
    return (text or "(no result)")[:EXPERT_TOOL_RESULT_MAX_CHARS]


def _summary(outcome: tools_mod.ToolOutcome, numbered: List[Dict[str, Any]]) -> str:
    if not outcome.ok:
        return (outcome.error or "failed")[:120]
    if numbered:
        return f"{len(numbered)} result{'s' if len(numbered) != 1 else ''}"
    return (outcome.text or "").strip().replace("\n", " ")[:120]


async def _execute_calls(
    calls: List[Dict[str, Any]],
    *,
    registry: tools_mod.ToolRegistry,
    book: SourceBook,
    trace: List[Dict[str, Any]],
    convo: List[Dict[str, Any]],
) -> AsyncIterator[Dict[str, Any]]:
    """Run one round's tool calls: events out, results appended to ``convo`` as tool messages."""
    for call in calls[:EXPERT_TOOL_MAX_CALLS_PER_ROUND]:
        name = str((call.get("function") or {}).get("name") or "")
        args = _parse_args(call)
        spec = registry.spec(name)
        label = tools_mod.label_for(spec.native if spec else name, args)
        yield {"type": "tool_start", "id": call.get("id"), "name": name, "label": label, "arguments": args}
        outcome = await registry.call(name, args)
        new = book.add(outcome.sources)
        numbered = book.numbered(outcome.sources)
        trace.append({
            "id": call.get("id"), "name": name, "label": label, "arguments": args,
            "ok": outcome.ok, "elapsed_ms": outcome.elapsed_ms,
            "sources": [s["n"] for s in numbered], "error": outcome.error,
        })
        yield {
            "type": "tool_end", "id": call.get("id"), "name": name, "label": label,
            "ok": outcome.ok, "summary": _summary(outcome, numbered), "elapsed_ms": outcome.elapsed_ms,
        }
        if new:
            yield {"type": "sources", "sources": list(book.items)}
        convo.append({"role": "tool", "tool_call_id": call.get("id"), "name": name, "content": result_text(outcome, numbered)})
    for call in calls[EXPERT_TOOL_MAX_CALLS_PER_ROUND:]:
        name = str((call.get("function") or {}).get("name") or "")
        convo.append({"role": "tool", "tool_call_id": call.get("id"), "name": name,
                      "content": "Skipped: too many tool calls in one round; answer with what you have."})


async def stream_with_tools(
    messages: List[Dict[str, Any]],
    provider: ProviderName,
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    registry: Optional[tools_mod.ToolRegistry] = None,
    max_rounds: Optional[int] = None,
    enabled: Optional[bool] = None,
    stream: Optional[Callable[..., AsyncIterator[Dict[str, Any]]]] = None,
    forced: Optional[ForcedTools] = None,
    assist: Optional[ForcedTools] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Run one turn with tools, streaming. Events:
    ``token`` {content} · ``reset`` (the text so far was a preamble, not the answer) ·
    ``tool_start`` {id, name, label, arguments} · ``tool_end`` {id, name, label, ok, summary, elapsed_ms} ·
    ``sources`` {sources} · ``notice`` {text} ·
    ``done`` {content, tool_trace, sources, notices, rounds, fallback_applied}.
    ``stream`` is the provider event stream to use (``stream_provider_events`` by default —
    pipelines pass their own module's name so the usual seam, and its fakes in tests, apply).
    ``forced`` tools run first, before the model is asked anything. ``assist`` tools run
    instead, only for a model that cannot call tools itself: HomePilot does the search and
    hands the model the results (the research modes stay grounded on such models).
    """
    stream = stream or stream_provider_events
    registry = registry or tools_mod.registry()
    use_tools = EXPERT_TOOLS_ENABLED if enabled is None else enabled
    max_rounds = EXPERT_TOOL_MAX_ROUNDS if max_rounds is None else max_rounds
    tools = (await registry.openai_tools()) if use_tools else []
    key = _model_key(provider, model)
    book = SourceBook()
    trace: List[Dict[str, Any]] = []
    notices: List[str] = []
    convo = list(messages)
    answer: List[str] = []
    rounds = 0
    fallback_applied = False

    first = _forced_calls(forced, registry) if tools else []
    if not first and assist and tools and tools_known(key) is False:
        first = _forced_calls(assist, registry)
    if first:
        rounds += 1
        convo.append({"role": "assistant", "content": "", "tool_calls": first})
        async for ev in _execute_calls(first, registry=registry, book=book, trace=trace, convo=convo):
            yield ev
    elif forced:
        notices.append(_unavailable_note(forced))
        yield {"type": "notice", "text": notices[-1]}

    if tools_known(key) is False:
        convo = without_tool_roles(convo)

    while True:
        offer = bool(tools) and rounds < max_rounds and tools_known(key) is not False
        round_text: List[str] = []
        calls: List[Dict[str, Any]] = []
        thinking = ThinkFilter()
        try:
            async for ev in stream(
                _round_messages(convo, offer=offer, book=book), provider,
                tools=tools if offer else None, model=model, temperature=temperature, max_tokens=max_tokens,
            ):
                if "delta" in ev:
                    clean = thinking.feed(ev["delta"])
                    if clean:
                        round_text.append(clean)
                        yield {"type": "token", "content": clean}
                elif ev.get("tool_calls") and offer:
                    calls = list(ev["tool_calls"])
                elif ev.get("wait"):
                    # In line, or waiting out a rate limit: transient, shown in place of a pause.
                    yield {"type": "wait", **ev["wait"]}
                elif ev.get("notice"):
                    fallback_applied = fallback_applied or bool(ev.get("fallback"))
                    if ev["notice"] not in notices:
                        notices.append(ev["notice"])
                        yield {"type": "notice", "text": ev["notice"]}
        except Exception as exc:
            if not _refused_tools(exc, offered=offer, provider=provider, model=model):
                raise
            # A capability fact, not news for the reader: logged and remembered, the answer
            # simply continues without tools (the UI stays clean; the trace is unchanged).
            remember_tools(key, False)
            logger.info("tools: %s rejected the tools field; answering without tools from now on (%s)", key, _no_tools_note(model))
            if round_text:
                yield {"type": "reset"}
            if assist and not first and tools:
                # The model cannot search; HomePilot searches for it before asking again.
                first = _forced_calls(assist, registry)
                if first:
                    rounds += 1
                    convo.append({"role": "assistant", "content": "", "tool_calls": first})
                    async for ev in _execute_calls(first, registry=registry, book=book, trace=trace, convo=convo):
                        yield ev
            convo = without_tool_roles(convo)
            continue
        tail = thinking.flush()
        if tail:
            round_text.append(tail)
            yield {"type": "token", "content": tail}
        if not calls:
            answer = round_text
            break

        if tools_known(key) is not True:
            remember_tools(key, True)
        rounds += 1
        if round_text:
            yield {"type": "reset"}      # whatever came before the calls is not the answer
        convo.append({"role": "assistant", "content": "".join(round_text), "tool_calls": calls})
        async for ev in _execute_calls(calls, registry=registry, book=book, trace=trace, convo=convo):
            yield ev

    yield {
        "type": "done", "content": "".join(answer), "tool_trace": trace,
        "sources": list(book.items), "notices": notices, "rounds": rounds,
        "fallback_applied": fallback_applied,
    }


async def run_with_tools(
    messages: List[Dict[str, Any]],
    provider: ProviderName,
    *,
    model: Optional[str] = None,
    temperature: float = EXPERT_TEMPERATURE,
    max_tokens: int = EXPERT_MAX_TOKENS,
    registry: Optional[tools_mod.ToolRegistry] = None,
    max_rounds: Optional[int] = None,
    enabled: Optional[bool] = None,
    call: Optional[DispatchFn] = None,
    forced: Optional[ForcedTools] = None,
    assist: Optional[ForcedTools] = None,
) -> Dict[str, Any]:
    """The non-streaming turn, through ``call`` (``dispatch`` by default — callers pass their
    own module's ``dispatch`` so the usual seam, and its fakes in tests, still apply).
    Returns the ``done`` payload of :func:`stream_with_tools` plus ``provider`` and ``model``."""
    call = call or dispatch
    registry = registry or tools_mod.registry()
    use_tools = EXPERT_TOOLS_ENABLED if enabled is None else enabled
    max_rounds = EXPERT_TOOL_MAX_ROUNDS if max_rounds is None else max_rounds
    tools = (await registry.openai_tools()) if use_tools else []
    key = _model_key(provider, model)
    book = SourceBook()
    trace: List[Dict[str, Any]] = []
    notices: List[str] = []
    convo = list(messages)
    rounds = 0
    fallback_applied = False
    content = ""
    raw: Dict[str, Any] = {}

    first = _forced_calls(forced, registry) if tools else []
    if not first and assist and tools and tools_known(key) is False:
        first = _forced_calls(assist, registry)
    if first:
        rounds += 1
        convo.append({"role": "assistant", "content": "", "tool_calls": first})
        async for _ in _execute_calls(first, registry=registry, book=book, trace=trace, convo=convo):
            pass
    elif forced:
        notices.append(_unavailable_note(forced))

    if tools_known(key) is False:
        convo = without_tool_roles(convo)

    while True:
        offer = bool(tools) and rounds < max_rounds and tools_known(key) is not False
        try:
            raw = await call(
                _round_messages(convo, offer=offer, book=book), provider,
                model=model, temperature=temperature, max_tokens=max_tokens, tools=tools if offer else None,
            )
        except Exception as exc:
            if not _refused_tools(exc, offered=offer, provider=provider, model=model):
                raise
            remember_tools(key, False)
            logger.info("tools: %s rejected the tools field; answering without tools from now on", key)
            if assist and not first and tools:
                first = _forced_calls(assist, registry)
                if first:
                    rounds += 1
                    convo.append({"role": "assistant", "content": "", "tool_calls": first})
                    async for _ in _execute_calls(first, registry=registry, book=book, trace=trace, convo=convo):
                        pass
            convo = without_tool_roles(convo)
            continue
        raw = raw if isinstance(raw, dict) else {}
        meta = extract_dispatch_meta(raw)
        fallback_applied = fallback_applied or bool(meta.get("fallback_applied"))
        if isinstance(meta.get("notice"), str) and meta["notice"] and meta["notice"] not in notices:
            notices.append(meta["notice"])
        message = ((raw.get("choices") or [{}])[0] or {}).get("message") or {}
        calls = list(message.get("tool_calls") or []) if offer else []
        if not calls:
            content = strip_think(message.get("content") or "")
            break
        if tools_known(key) is not True:
            remember_tools(key, True)
        rounds += 1
        convo.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
        async for _ in _execute_calls(calls, registry=registry, book=book, trace=trace, convo=convo):
            pass

    return {
        "content": content, "tool_trace": trace, "sources": list(book.items), "notices": notices,
        "rounds": rounds, "fallback_applied": fallback_applied,
        "provider": raw.get("provider", provider), "model": raw.get("model", model),
    }
