"""Web search for chat: find current pages, read them, and hand the model numbered sources.

The pattern the large assistants use (search-augmented, grounded answers), sized for local
models that cannot call tools:

1. **Plan** — a follow-up such as "and what about yesterday?" means nothing to a search engine,
   so it is rewritten into one standalone query from the conversation (a short model call,
   with a deterministic fallback). A first message is searched as typed.
2. **Search** — HomePilot's web-search MCP server (``hp.web.search`` on :9105, SearXNG by
   default, Tavily optional). Results are de-duplicated by URL and capped per domain, so five
   sources are five sites rather than one site five times.
3. **Read** — the top pages are fetched in parallel, with a size and time limit, refusing any
   address that is private, loopback or link-local at every redirect. Only the passages that
   match the question are kept, so a long page does not crowd out the rest.
4. **Ground** — the model receives the sources as a numbered list with instructions to cite
   them as [1], [2], never to invent a source, and to say when they do not answer. The chat
   reply carries the same list, so the UI shows "Searched the web · N sources" and links every
   [n] to its page.

When search is unavailable the model is told so, and told not to make up current events —
the answer the user gets says it could not check, instead of confidently reciting old news.
Searches leave this computer (through SearXNG to the engines it queries): the switch is per
chat, off by default, and the UI says when it is on.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import httpx

#: Results asked of the search engine, kept after de-duplication, and pages actually read.
SEARCH_LIMIT = 10
KEEP_SOURCES = 6
READ_PAGES = 3
READ_ATTEMPTS = 6
PER_DOMAIN = 2
#: Reading budget: per page, and the excerpt each read page contributes to the prompt.
PAGE_TIMEOUT_S = 6.0
PAGE_MAX_BYTES = 1_500_000
EXCERPT_CHARS = 1600
SNIPPET_CHARS = 320
#: The query rewrite is a nicety; it never holds the answer up for long.
PLAN_TIMEOUT_S = 8.0
USER_AGENT = "Mozilla/5.0 (compatible; HomePilot/1.0; +https://github.com/ruslanmv/HomePilot)"

_FRESH = re.compile(
    r"\b(today|tonight|yesterday|tomorrow|this (week|month|morning|evening)|latest|newest|recent(ly)?|"
    r"current(ly)?|right now|breaking|news|headlines?|now|update[sd]?|score|results?|price|stock|weather|"
    r"forecast|live|20\d\d)\b",
    re.I,
)
_STOP = set(
    "a an and are as at be by can could did do does for from had has have how i in is it its me my "
    "of on or our please should so tell than that the their them then there these they this to was "
    "we were what when where which who why will with would you your about give show find search "
    "look up know".split()
)
_ELLIPTIC = re.compile(r"^(and|but|so|what about|how about|also|then|why|is it|are they)\b|\b(it|that|this|they|them|those|these|he|she|him|her)\b", re.I)


# ── types ────────────────────────────────────────────────────────────────────


@dataclass
class Source:
    n: int
    title: str
    url: str
    domain: str
    snippet: str = ""
    excerpt: str = ""
    published: str = ""

    def public(self) -> Dict[str, Any]:
        return {"n": self.n, "title": self.title, "url": self.url, "domain": self.domain,
                "snippet": self.snippet, "published": self.published or None, "read": bool(self.excerpt)}


@dataclass
class WebContext:
    #: ok · no_results · unavailable
    status: str
    query: str
    sources: List[Source] = field(default_factory=list)
    error: str = ""
    took_ms: int = 0

    def public(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": self.status, "query": self.query, "took_ms": self.took_ms,
                               "sources": [s.public() for s in self.sources]}
        if self.status == "unavailable":
            out["message"] = ("Web search isn't available right now, so this answer is from the "
                              "model's own knowledge and may be out of date.")
            out["hint"] = self.error or "Start SearXNG with `make start-searxng`."
        return out


# ── configuration ────────────────────────────────────────────────────────────


def server_url() -> str:
    """The web-search MCP server's JSON-RPC endpoint."""
    explicit = os.getenv("HOMEPILOT_WEB_SEARCH_URL", "").strip()
    if explicit:
        return explicit
    port = os.getenv("WEB_SEARCH_PORT", "9105").strip() or "9105"
    return f"http://127.0.0.1:{port}/rpc"


def provider_name() -> str:
    return (os.getenv("WEB_SEARCH_PROVIDER", "searxng").strip().lower() or "searxng")


def searxng_url() -> str:
    """Same default as the web-search server (agentic/integrations/mcp/web_search/config.py)."""
    return os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8899").strip().rstrip("/") or "http://127.0.0.1:8899"


# ── the date every standard chat is told ─────────────────────────────────────


def current_time_context(timezone: Optional[str] = None, now: Optional[datetime] = None) -> str:
    """Today's date and time for the system prompt, in the user's time zone when the browser
    sent one. Without it a model answers "which day is today?" from its training data."""
    moment = (now or datetime.now()).astimezone()
    zone_label = ""
    if timezone:
        try:
            from zoneinfo import ZoneInfo  # noqa: PLC0415

            moment = moment.astimezone(ZoneInfo(timezone))
            zone_label = timezone
        except Exception:  # noqa: BLE001 — an unknown zone name falls back to the server's
            zone_label = ""
    if not zone_label:
        zone_label = moment.tzname() or ""
    stamp = moment.strftime("%A, %B %d, %Y, %H:%M").replace(" 0", " ")
    zone = f" ({zone_label})" if zone_label else ""
    return (
        f"Current date and time: {stamp}{zone}. Use it for anything that depends on today's date. "
        "Your own knowledge stops at your training cutoff: for news, prices, scores or anything else "
        "that may have changed since, say you cannot check live information unless web results are "
        "provided below, and never invent recent events."
    )


# ── search ───────────────────────────────────────────────────────────────────


class SearchUnavailable(RuntimeError):
    pass


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _parse_text_results(text: str) -> List[Dict[str, str]]:
    """The server's prose, for an older server without ``structuredContent``."""
    out: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for line in (text or "").splitlines():
        head = re.match(r"^\s*\d+\.\s+\*\*(.+?)\*\*\s*$", line)
        if head:
            if current.get("url"):
                out.append(current)
            current = {"title": head.group(1).strip(), "url": "", "snippet": ""}
            continue
        url = re.match(r"^\s*-\s*URL:\s*(\S+)", line)
        if url and current:
            current["url"] = url.group(1).strip()
            continue
        snip = re.match(r"^\s*-\s*(.+)$", line)
        if snip and current and current.get("url") and not current.get("snippet"):
            current["snippet"] = snip.group(1).strip()
    if current.get("url"):
        out.append(current)
    return out


async def search(query: str, *, limit: int = SEARCH_LIMIT, recency_days: int = 0,
                 client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, str]]:
    """Results for ``query`` from the web-search server. Raises ``SearchUnavailable``."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "hp.web.search",
                       "arguments": {"query": query, "limit": limit, "recency_days": recency_days}}}
    own = client is None
    http = client or httpx.AsyncClient(timeout=25.0)
    try:
        resp = await http.post(server_url(), json=body)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise SearchUnavailable("The web-search server (port 9105) is not answering.") from exc
    finally:
        if own:
            await http.aclose()
    if "error" in data:
        raise SearchUnavailable(str((data.get("error") or {}).get("message") or "The search failed."))
    result = data.get("result") or {}
    structured = (result.get("structuredContent") or {}).get("results")
    if isinstance(structured, list):
        return [r for r in structured if isinstance(r, dict) and r.get("url")]
    text = " ".join(str(c.get("text") or "") for c in (result.get("content") or []) if isinstance(c, dict))
    if text.startswith("Web search failed"):
        raise SearchUnavailable(_explain(text))
    return _parse_text_results(text)


def _explain(text: str) -> str:
    low = text.lower()
    if "connect" in low or "8080" in low or "searxng" in low:
        return "SearXNG is not running. Start it with `make start-searxng`."
    if "tavily" in low:
        return "Tavily is not configured (set TAVILY_API_KEY)."
    return text[:200]


def select_sources(results: Sequence[Dict[str, Any]], keep: int = KEEP_SOURCES,
                   per_domain: int = PER_DOMAIN) -> List[Source]:
    """De-duplicate by URL and cap each domain, keeping the engine's order."""
    seen_urls: set = set()
    per: Dict[str, int] = {}
    out: List[Source] = []
    for r in results:
        url = str(r.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = url.split("#")[0].rstrip("/")
        if key in seen_urls:
            continue
        dom = _domain(url)
        if per.get(dom, 0) >= per_domain:
            continue
        seen_urls.add(key)
        per[dom] = per.get(dom, 0) + 1
        snippet = re.sub(r"\s+", " ", str(r.get("snippet") or r.get("content") or "")).strip()
        out.append(Source(n=len(out) + 1, title=str(r.get("title") or dom or url).strip()[:200], url=url,
                          domain=dom, snippet=snippet[:SNIPPET_CHARS], published=str(r.get("published") or "")))
        if len(out) >= keep:
            break
    return out


# ── reading pages ────────────────────────────────────────────────────────────


def _public_host(host: str) -> bool:
    """True when every address ``host`` resolves to is on the public internet."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            return False
    return True


class _TextExtractor(HTMLParser):
    """The readable text of a page: paragraphs, headings, list items and cells; nothing from
    scripts, styles, navigation, headers, footers, forms or asides."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe",
            "button", "select", "template"}
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "td", "th", "blockquote", "pre", "dd", "dt", "article",
             "section", "div", "br", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: List[str] = []
        self.buf: List[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.buf.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            self.parts.append(text)

    def paragraphs(self) -> List[str]:
        self._flush()
        return self.parts


def extract_paragraphs(html: str) -> List[str]:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — broken HTML still has text worth keeping
        pass
    return [p for p in parser.paragraphs() if len(p) >= 40]


def _terms(text: str) -> List[str]:
    return [w for w in re.findall(r"[\w'-]{3,}", (text or "").lower()) if w not in _STOP]


def best_passages(paragraphs: Sequence[str], query: str, budget: int = EXCERPT_CHARS) -> str:
    """The paragraphs that share most words with the query, in page order, within ``budget``.
    Falls back to the opening paragraphs when nothing matches."""
    terms = set(_terms(query))
    scored = []
    for i, p in enumerate(paragraphs):
        words = _terms(p)
        hits = sum(1 for w in words if w in terms)
        scored.append((hits / (1 + len(words) ** 0.5), i, p))
    chosen = sorted([s for s in scored if s[0] > 0], reverse=True) or [(0, i, p) for i, p in enumerate(paragraphs[:4])]
    picked: List[Tuple[int, str]] = []
    used = 0
    for _, i, p in chosen:
        text = p if len(p) <= 700 else p[:700].rsplit(" ", 1)[0] + "…"
        if used + len(text) > budget and picked:
            continue
        picked.append((i, text))
        used += len(text) + 1
        if used >= budget:
            break
    return "\n".join(t for _, t in sorted(picked))[:budget]


async def read_page(url: str, client: httpx.AsyncClient, *, max_redirects: int = 3) -> List[str]:
    """The readable paragraphs of ``url``, or [] — never raises."""
    current = url
    try:
        for _ in range(max_redirects + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https"):
                return []
            ok = await asyncio.to_thread(_public_host, parsed.hostname or "")
            if not ok:
                return []
            async with client.stream("GET", current, follow_redirects=False) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = urljoin(current, resp.headers["location"])
                    continue
                if resp.status_code >= 400:
                    return []
                ctype = resp.headers.get("content-type", "").lower()
                if "html" not in ctype and "text/plain" not in ctype:
                    return []
                chunks: List[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= PAGE_MAX_BYTES:
                        break
                raw = b"".join(chunks)
                text = raw.decode(resp.encoding or "utf-8", errors="replace")
                if "text/plain" in ctype:
                    return [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) >= 40]
                return extract_paragraphs(text)
    except Exception:  # noqa: BLE001 — a page that cannot be read is a source with its snippet only
        return []
    return []


async def read_sources(sources: List[Source], query: str, *, pages: int = READ_PAGES,
                       attempts: int = READ_ATTEMPTS, client: Optional[httpx.AsyncClient] = None) -> None:
    """Read up to ``attempts`` sources in parallel and attach the best passages of the first
    ``pages`` that could be read. Many large sites refuse automated readers, so trying a few
    more than needed — at the same time, so it costs no extra waiting — is what keeps three."""
    if not sources:
        return
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(PAGE_TIMEOUT_S), headers={"User-Agent": USER_AGENT})
    try:
        targets = sources[:max(pages, attempts)]
        results = await asyncio.gather(
            *[asyncio.wait_for(read_page(s.url, http), timeout=PAGE_TIMEOUT_S + 2) for s in targets],
            return_exceptions=True,
        )
        kept = 0
        for source, paragraphs in zip(targets, results):
            if kept >= pages:
                break
            if isinstance(paragraphs, list) and paragraphs:
                source.excerpt = best_passages(paragraphs, query)
                kept += 1
    finally:
        if own:
            await http.aclose()


# ── planning the query ───────────────────────────────────────────────────────


def wants_fresh(text: str) -> bool:
    return bool(_FRESH.search(text or ""))


def fallback_query(user_text: str, history: Sequence[Tuple[str, str]]) -> str:
    """No model: an elliptical follow-up borrows the previous question's words."""
    text = re.sub(r"\s+", " ", user_text or "").strip()
    prev = ""
    for role, content in reversed(list(history)):
        if role == "user" and content.strip() and content.strip() != text:
            prev = re.sub(r"\s+", " ", content).strip()
            break
    if prev and (len(text.split()) <= 5 or _ELLIPTIC.search(text)):
        text = f"{prev[:160]} {text}"
    return text[:300]


async def plan_query(user_text: str, history: Sequence[Tuple[str, str]], *,
                     chat: Optional[Any] = None) -> str:
    """One standalone search query. ``chat`` is an awaitable ``messages -> text`` (the same model
    as the conversation); a first message, or a model that is slow or says nothing useful, gets
    the deterministic fallback."""
    earlier = [(r, c) for r, c in history if r in ("user", "assistant") and (c or "").strip()]
    # The current message is usually the last history entry already.
    if earlier and earlier[-1][0] == "user" and earlier[-1][1].strip() == (user_text or "").strip():
        earlier = earlier[:-1]
    if not earlier or chat is None:
        return fallback_query(user_text, earlier)
    transcript = "\n".join(f"{r}: {c.strip()[:400]}" for r, c in earlier[-4:])
    prompt = [
        {"role": "system", "content": (
            "Rewrite the user's latest message as one web search query that makes sense on its own. "
            "Resolve words like 'it', 'that' or 'they' from the conversation. Reply with the query only: "
            "no quotes, no explanation, at most 14 words.")},
        {"role": "user", "content": f"Conversation:\n{transcript}\n\nLatest message: {user_text.strip()[:400]}"},
    ]
    try:
        raw = await asyncio.wait_for(chat(prompt), timeout=PLAN_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return fallback_query(user_text, earlier)
    line = re.sub(r"<think>[\s\S]*?</think>", "", str(raw or ""), flags=re.I).strip().splitlines()
    query = (line[0] if line else "").strip().strip('"\'').strip()
    if not query or len(query) > 200 or len(query.split()) > 24:
        return fallback_query(user_text, earlier)
    return query


# ── the whole step ───────────────────────────────────────────────────────────


async def gather(user_text: str, history: Sequence[Tuple[str, str]], *, chat: Optional[Any] = None) -> WebContext:
    """Plan, search, de-duplicate and read. Never raises: failures come back as a status."""
    started = time.perf_counter()
    query = await plan_query(user_text, history, chat=chat)
    try:
        results = await search(query, recency_days=3 if wants_fresh(user_text) or wants_fresh(query) else 0)
    except SearchUnavailable as exc:
        return WebContext(status="unavailable", query=query, error=str(exc),
                          took_ms=int((time.perf_counter() - started) * 1000))
    sources = select_sources(results)
    if not sources and wants_fresh(query):
        # A date filter that found nothing: the same search without it.
        try:
            sources = select_sources(await search(query, recency_days=0))
        except SearchUnavailable:
            sources = []
    if not sources:
        return WebContext(status="no_results", query=query, took_ms=int((time.perf_counter() - started) * 1000))
    await read_sources(sources, query)
    return WebContext(status="ok", query=query, sources=sources,
                      took_ms=int((time.perf_counter() - started) * 1000))


def system_block(ctx: WebContext) -> str:
    """What the model is told: the sources and how to use them — or that it could not search."""
    if ctx.status == "unavailable":
        return (
            "WEB SEARCH — UNAVAILABLE\n"
            "The user turned on web search for this chat, but it could not run right now. Start your "
            "answer by saying briefly that you could not search the web, then answer from what you know "
            "and make clear it may be out of date. Do not invent current events, headlines, numbers or "
            "sources."
        )
    if ctx.status != "ok":
        return (
            f"WEB SEARCH — NO RESULTS\nA web search for “{ctx.query}” found nothing usable. Say so briefly, "
            "then answer from what you know, making clear it may be out of date. Do not invent sources."
        )
    lines = [
        f"WEB SEARCH RESULTS — retrieved just now for the query “{ctx.query}”.",
        "Answer the user's latest message from these sources. Put the source number in square brackets "
        "right after each fact you take from one, like [1] or [2][3]. Use only these numbers and never "
        "invent a source, a URL or a quote. Prefer the most recent information and give dates when they "
        "matter. If the sources disagree, say so; if they do not answer the question, say that plainly "
        "instead of guessing. Do not add a list of sources at the end — it is shown separately.",
        "",
    ]
    for s in ctx.sources:
        when = f" · {s.published[:10]}" if s.published else ""
        lines.append(f"[{s.n}] {s.title} — {s.domain}{when}")
        body = s.excerpt or s.snippet
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


# ── status, for the chat settings ────────────────────────────────────────────


async def status() -> Dict[str, Any]:
    """Whether web search can run: the server answers and, for SearXNG, the engine is up."""
    provider = provider_name()
    out: Dict[str, Any] = {"provider": provider, "available": False, "server": False, "engine": None, "hint": ""}
    async with httpx.AsyncClient(timeout=3.0) as http:
        try:
            health = await http.get(server_url().rsplit("/rpc", 1)[0] + "/health")
            out["server"] = health.status_code == 200
        except Exception:  # noqa: BLE001
            out["server"] = False
        if provider == "searxng":
            try:
                ping = await http.get(f"{searxng_url()}/healthz")
                out["engine"] = ping.status_code == 200
            except Exception:  # noqa: BLE001
                out["engine"] = False
        else:
            out["engine"] = bool(os.getenv("TAVILY_API_KEY", "").strip()) if provider == "tavily" else None
    out["available"] = bool(out["server"]) and out["engine"] is not False
    if not out["server"]:
        out["hint"] = "The web-search server (port 9105) is not running. `make start` starts it."
    elif out["engine"] is False:
        out["hint"] = ("SearXNG is not running. Start it with `make start-searxng`." if provider == "searxng"
                       else "Set TAVILY_API_KEY for the Tavily provider.")
    return out
