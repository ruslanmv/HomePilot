"""
Local LLM runtime discovery and model resolution.

Design: docs/design/LOCAL_MODEL_RESOLUTION.md.

Problem this solves: every feature used to hard-code *one* Ollama URL
(``localhost:11434``) and *one* model name, so a machine whose Ollama lives one
hop away (Windows host seen from WSL, Docker host seen from a container) or
whose installed models differ from the configured name failed with
"no models found" although models were there.

This module is the single place that answers two questions:

1. **Which local runtimes are reachable, and what do they hold?**
   ``discover()`` probes a fixed, small candidate list in parallel (the
   configured URL, loopback, the WSL/Docker host gateway) and caches the
   answer for a short time. It never scans a network.
2. **Which model should a given role use right now?** ``resolve(role,
   configured)`` returns the configured model when it is installed, otherwise
   the best installed model for the role, otherwise an explicit "none" with a
   remedy (pull / start / connect / WSL bridge) the UI can act on.

``choose_model`` is a pure function so the selection rules are unit-testable
without any network. ``PullManager`` runs ``ollama pull`` through the HTTP API
with progress, so the UI can offer a download instead of printing a shell
command.

Everything here talks only to Ollama-compatible ``/api/*`` endpoints and
tolerates the test suite's ``DummyAsyncClient`` stub (it uses ``get`` only on
the discovery path).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx

from .config import OLLAMA_BASE_URL, OLLAMA_MODEL

log = logging.getLogger("homepilot.models")

Role = Literal["chat", "fast", "vision", "embed"]
ROLES: Tuple[str, ...] = ("chat", "fast", "vision", "embed")

# 3 s: Ollama answers /api/tags in tens of milliseconds, but not while it loads a model or the
# machine is short of memory (ComfyUI loading a checkpoint) — 1.5 s reported it missing then.
# The candidates are probed in parallel, so a down Ollama still costs one timeout, not several.
PROBE_TIMEOUT_S = float(os.getenv("MODEL_DISCOVERY_TIMEOUT_S", "3"))
CACHE_TTL_S = float(os.getenv("MODEL_DISCOVERY_TTL_S", "30"))
# "Nothing answered" is remembered briefly, so a hiccup clears itself on the next look instead
# of holding the "Ollama unavailable" banner for the full cache lifetime.
NEGATIVE_TTL_S = float(os.getenv("MODEL_DISCOVERY_NEGATIVE_TTL_S", "5"))

# ── Model classification (single source of truth; llm.py re-exports) ──────────
VISION_ONLY_HINTS = (
    "moondream", "llava", "bakllava", "minicpm-v", "-vl", "vision", "llama3.2-vision",
)
EMBED_HINTS = (
    "embed", "nomic-embed", "mxbai-embed", "all-minilm", "bge-", "bge:",
)
# Preferred general text-chat models, best first.
CHAT_MODEL_PRIORITY = (
    "llama3.2:3b", "llama3.2", "llama3.1", "llama3:8b", "qwen3", "qwen2.5",
    "mistral-nemo", "gemma2", "mistral:7b", "phi4", "deepseek-r1",
)
# Small models first for latency-sensitive paths (Game Mode fast path, prompt
# refinement, routines). Falls back to the chat list.
FAST_MODEL_PRIORITY = (
    "llama3.2:1b", "llama3.2:3b", "qwen2.5:0.5b", "qwen2.5:1.5b", "qwen2.5:3b",
    "gemma2:2b", "phi4-mini", "phi3", "llama3.2",
)
VISION_MODEL_PRIORITY = (
    "moondream", "gemma3:4b", "gemma3", "llava:7b", "llava", "minicpm-v",
    "llama3.2-vision",
)
EMBED_MODEL_PRIORITY = ("nomic-embed-text", "mxbai-embed-large", "all-minilm", "bge-m3")

# Offered by the UI when a runtime is reachable but holds nothing usable for a
# role. Sizes are the published download sizes, rounded.
SUGGESTED_MODELS: List[Dict[str, Any]] = [
    {"name": "llama3.2:3b", "size_gb": 2.0, "roles": ["chat", "fast"],
     "why": "Small, fast general chat. The model `make download-chat` installs."},
    {"name": "qwen2.5:7b", "size_gb": 4.7, "roles": ["chat"],
     "why": "Stronger answers and tool use; comfortable on an 8 GB GPU."},
    {"name": "deepseek-r1:8b", "size_gb": 4.9, "roles": ["chat"],
     "why": "Reasoning model that thinks before answering; slower per turn."},
    {"name": "moondream", "size_gb": 1.7, "roles": ["vision"],
     "why": "Tiny vision model for questions about images."},
    {"name": "nomic-embed-text", "size_gb": 0.3, "roles": ["embed"],
     "why": "Embeddings for memory and retrieval."},
]

_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*(?:/[A-Za-z0-9._\-]+)*(?::[A-Za-z0-9._\-]+)?$")


def is_valid_model_name(name: str) -> bool:
    """Ollama tag syntax only (``family[:tag]`` or ``namespace/model[:tag]``).
    Rejects anything that could smuggle a path or a URL into a pull request."""
    return bool(name) and len(name) <= 128 and bool(_MODEL_NAME_RE.match(name))


def is_text_chat_model(name: str) -> bool:
    """True when a model id can serve a plain text turn (not vision-only, not an
    embedding model)."""
    n = (name or "").lower()
    if not n:
        return False
    if any(h in n for h in EMBED_HINTS):
        return False
    if any(h in n for h in VISION_ONLY_HINTS):
        return False
    return True


def is_vision_model(name: str, capabilities: Optional[List[str]] = None) -> bool:
    n = (name or "").lower()
    if capabilities and "vision" in [c.lower() for c in capabilities]:
        return True
    return any(h in n for h in VISION_ONLY_HINTS) or "gemma3" in n


def is_embed_model(name: str, capabilities: Optional[List[str]] = None) -> bool:
    n = (name or "").lower()
    if capabilities and [c for c in capabilities if c.lower() == "embedding"]:
        return True
    return any(h in n for h in EMBED_HINTS)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    name: str
    family: str = ""
    parameter_size: str = ""
    size_bytes: int = 0
    modified_at: str = ""
    capabilities: List[str] = field(default_factory=list)
    loaded: bool = False  # currently resident in memory (``/api/ps``)

    def fits(self, role: str) -> bool:
        if role in ("chat", "fast"):
            return is_text_chat_model(self.name) and not is_embed_model(self.name, self.capabilities)
        if role == "vision":
            return is_vision_model(self.name, self.capabilities)
        if role == "embed":
            return is_embed_model(self.name, self.capabilities)
        return True


@dataclass
class Runtime:
    url: str
    label: str = "configured"      # configured | loopback | wsl-host | docker-host | explicit
    reachable: bool = False
    models: List[ModelInfo] = field(default_factory=list)
    models_known: bool = True      # False: answered, but not with an Ollama tag list
    error: str = ""
    latency_ms: int = 0

    @property
    def model_names(self) -> List[str]:
        return [m.name for m in self.models]


@dataclass
class Resolution:
    role: str
    configured: str
    model: str
    runtime_url: str
    source: str                    # configured | fallback | none
    reason: str
    installed: List[str] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)
    remedy: Optional[Dict[str, Any]] = None
    configured_installed: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


class NoLocalModelError(RuntimeError):
    """Raised by LLM adapters when no model can serve the request. Carries the
    full resolution so routes can answer with a structured, actionable body."""

    code = "no_local_model"

    def __init__(self, resolution: Resolution):
        self.resolution = resolution
        super().__init__(resolution.reason)

    def payload(self) -> Dict[str, Any]:
        r = self.resolution
        return {
            "code": self.code,
            "role": r.role,
            "message": r.reason,
            "runtime_url": r.runtime_url,
            "installed": r.installed,
            "remedy": r.remedy,
        }


# ── Environment detection (no subprocesses) ───────────────────────────────────

def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    return "microsoft" in _read_text("/proc/version").lower()


def is_docker() -> bool:
    return os.path.exists("/.dockerenv") or "docker" in _read_text("/proc/1/cgroup")


_WSL_MODE: Dict[str, str] = {}


def wsl_networking_mode() -> str:
    """``mirrored`` or ``nat`` (WSL 2), ``""`` outside WSL or when it cannot be told. In
    mirrored mode WSL shares Windows' loopback, so Ollama on Windows' 127.0.0.1 is reachable as
    127.0.0.1 here and the "enable mirrored networking" advice does not apply."""
    if "mode" in _WSL_MODE:
        return _WSL_MODE["mode"]
    mode = ""
    if is_wsl():
        try:
            out = subprocess.run(["wslinfo", "--networking-mode"], capture_output=True, text=True, timeout=2)
            mode = (out.stdout or "").strip().lower()
        except (OSError, subprocess.SubprocessError):
            mode = ""
        if mode not in ("mirrored", "nat"):
            # Mirrored mode puts the host's loopback alias 10.255.255.254 on lo.
            mode = "mirrored" if "10.255.255.254" in _read_text("/proc/net/fib_trie") else "nat"
    _WSL_MODE["mode"] = mode
    return mode


def _default_gateway_from_proc() -> str:
    """Default route gateway from ``/proc/net/route`` (little-endian hex)."""
    text = _read_text("/proc/net/route")
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "00000000":
            try:
                raw = int(parts[2], 16)
                return ".".join(str((raw >> (8 * i)) & 0xFF) for i in range(4))
            except ValueError:
                continue
    return ""


def _nameserver_from_resolv() -> str:
    for line in _read_text("/etc/resolv.conf").splitlines():
        line = line.strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) >= 2 and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[1]):
                return parts[1]
    return ""


def wsl_host_ips() -> List[str]:
    """Addresses at which the Windows host is reachable from WSL (NAT mode)."""
    out: List[str] = []
    for ip in (_default_gateway_from_proc(), _nameserver_from_resolv()):
        if ip and ip not in out and not ip.startswith("127."):
            out.append(ip)
    return out


def candidate_urls(explicit: Optional[str] = None) -> List[Tuple[str, str]]:
    """Ordered ``(label, url)`` candidates. ``explicit`` restricts the search to
    one URL (the user typed a Chat Base URL in Settings)."""
    if explicit:
        return [("explicit", explicit.rstrip("/"))]
    if os.getenv("OLLAMA_DISCOVERY", "auto").strip().lower() in ("off", "0", "false", "configured"):
        # Only the configured URL: for tests (deterministic, never a real Ollama)
        # and for deployments that must not probe other hosts.
        return [("configured", OLLAMA_BASE_URL.rstrip("/"))]
    out: List[Tuple[str, str]] = []
    seen = set()

    def add(label: str, url: str) -> None:
        u = (url or "").strip().rstrip("/")
        if not u or u in seen:
            return
        seen.add(u)
        out.append((label, u))

    add("configured", OLLAMA_BASE_URL)
    add("loopback", "http://127.0.0.1:11434")
    add("loopback", "http://localhost:11434")
    if is_wsl() and wsl_networking_mode() != "mirrored":
        # NAT mode only: with mirrored networking Windows' Ollama is 127.0.0.1 here, and the
        # gateway / nameserver addresses are the LAN router, which never runs Ollama.
        for ip in wsl_host_ips():
            add("wsl-host", f"http://{ip}:11434")
    if is_docker():
        add("docker-host", "http://host.docker.internal:11434")
        add("docker-host", "http://172.17.0.1:11434")
    extra = os.getenv("OLLAMA_EXTRA_URLS", "")
    for u in extra.split(","):
        add("configured", u)
    return out


# ── Probing ───────────────────────────────────────────────────────────────────

def _parse_tags(data: Any) -> Tuple[List[ModelInfo], bool]:
    """``(models, known)``. ``known`` is False when the body is not an Ollama
    tag list at all (a proxy or a stub answered), so callers can tell "zero
    models" from "no idea"."""
    models: List[ModelInfo] = []
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        return models, False
    for m in data.get("models", []) or []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or m.get("model") or "").strip()
        if not name:
            continue
        details = m.get("details") or {}
        caps = m.get("capabilities") or []
        models.append(ModelInfo(
            name=name,
            family=str(details.get("family") or ""),
            parameter_size=str(details.get("parameter_size") or ""),
            size_bytes=int(m.get("size") or 0),
            modified_at=str(m.get("modified_at") or ""),
            capabilities=[str(c) for c in caps if isinstance(c, str)],
        ))
    return models, True


async def probe(url: str, label: str = "explicit") -> Runtime:
    """One runtime: ``GET /api/tags`` (required) + ``GET /api/ps`` (best effort,
    marks models that are already loaded)."""
    rt = Runtime(url=url.rstrip("/"), label=label)
    timeout = httpx.Timeout(PROBE_TIMEOUT_S, connect=PROBE_TIMEOUT_S)
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{rt.url}/api/tags")
            rt.latency_ms = int((time.perf_counter() - started) * 1000)
            if r.status_code != 200:
                rt.error = f"HTTP {r.status_code}"
                return rt
            rt.reachable = True
            rt.models, rt.models_known = _parse_tags(r.json())
            try:
                ps = await client.get(f"{rt.url}/api/ps")
                if ps.status_code == 200:
                    data = ps.json()
                    loaded = {
                        str(m.get("name") or m.get("model") or "")
                        for m in (data.get("models", []) if isinstance(data, dict) else [])
                        if isinstance(m, dict)
                    }
                    for m in rt.models:
                        m.loaded = m.name in loaded
            except Exception:  # noqa: BLE001 — /api/ps is optional
                pass
    except Exception as exc:  # noqa: BLE001 — a probe never raises
        rt.error = f"{type(exc).__name__}"
    return rt


# ── Discovery cache ───────────────────────────────────────────────────────────

_cache: Dict[str, Any] = {"ts": 0.0, "runtimes": []}
_url_cache: Dict[str, Tuple[float, Runtime]] = {}
_lock: Optional[asyncio.Lock] = None
_lock_loop: Any = None


def _get_lock() -> asyncio.Lock:
    """One lock per event loop: a Lock first used on one loop cannot be reused
    on another (tests and scripts create several loops per process)."""
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


def invalidate(reason: str = "") -> None:
    _cache["ts"] = 0.0
    _cache["runtimes"] = []
    _url_cache.clear()
    if reason:
        log.info("model discovery cache invalidated: %s", reason)


def _fresh(ts: float, runtimes: List[Runtime], now: float) -> bool:
    """A cached probe result still holds: ``CACHE_TTL_S`` when something answered,
    ``NEGATIVE_TTL_S`` when nothing did (a hiccup must not stick)."""
    ttl = CACHE_TTL_S if any(r.reachable for r in runtimes) else NEGATIVE_TTL_S
    return now - ts < ttl


async def discover(force: bool = False) -> List[Runtime]:
    """All candidate runtimes with their probe results, cached (see :func:`_fresh`)."""
    now = time.monotonic()
    if not force and _cache["runtimes"] and _fresh(_cache["ts"], _cache["runtimes"], now):
        return list(_cache["runtimes"])
    async with _get_lock():
        now = time.monotonic()
        if not force and _cache["runtimes"] and _fresh(_cache["ts"], _cache["runtimes"], now):
            return list(_cache["runtimes"])
        cands = candidate_urls()
        results = await asyncio.gather(*(probe(u, label) for label, u in cands))
        runtimes = list(results)
        _cache["ts"] = time.monotonic()
        _cache["runtimes"] = runtimes
        reachable = [r for r in runtimes if r.reachable]
        log.info(
            "model discovery: %d candidates, %d reachable%s",
            len(runtimes), len(reachable),
            "" if not reachable else " — " + ", ".join(f"{r.url} ({len(r.models)} models)" for r in reachable),
        )
        return list(runtimes)


async def discover_url(url: str, force: bool = False) -> Runtime:
    """Probe one explicit URL (Settings override), cached per URL."""
    key = url.rstrip("/")
    now = time.monotonic()
    hit = _url_cache.get(key)
    if hit and not force and _fresh(hit[0], [hit[1]], now):
        return hit[1]
    rt = await probe(key, "explicit")
    _url_cache[key] = (time.monotonic(), rt)
    return rt


def pick_runtime(runtimes: List[Runtime]) -> Optional[Runtime]:
    """Configured URL wins when it answers; otherwise the first runtime that
    answers with at least one model; otherwise the first that answers."""
    reachable = [r for r in runtimes if r.reachable]
    if not reachable:
        return None
    for r in reachable:
        if r.label == "configured" and r.models:
            return r
    for r in reachable:
        if r.models:
            return r
    return reachable[0]


def ollama_root(url: str) -> str:
    """The Ollama root a URL points at: Ollama serves its own API (``/api/tags``) and the
    OpenAI-compatible one (``/v1``) from the same root, so ``http://host:11434/v1`` — what an
    OpenAI-style "Base URL" field holds — means ``http://host:11434``."""
    u = (url or "").strip().rstrip("/")
    for suffix in ("/v1", "/api"):
        if u.lower().endswith(suffix):
            u = u[: -len(suffix)]
    return u


async def active_runtime(base_url: Optional[str] = None, force: bool = False) -> Tuple[Optional[Runtime], List[Runtime]]:
    """The Ollama to use. An explicit ``base_url`` wins when it is an Ollama (or answers like one,
    a proxy that lists no tags). When it does not answer as Ollama at all — an OpenAI-compatible
    gateway such as OllaBridge (404 on ``/api/tags``), or nothing — the usual places are searched
    instead of reporting Ollama missing while it runs on its own port."""
    if base_url:
        root = ollama_root(base_url)
        rt = await discover_url(root, force=force)
        if rt.reachable:
            return rt, [rt]
        if os.getenv("OLLAMA_DISCOVERY", "auto").strip().lower() in ("explicit", "strict"):
            return None, [rt]
        runtimes = [r for r in await discover(force=force) if r.url != rt.url]
        found = pick_runtime(runtimes)
        if found is not None:
            log.info("model discovery: %s is not an Ollama runtime (%s); using Ollama at %s",
                     base_url, rt.error or "no /api/tags", found.url)
        return found, [rt, *runtimes]
    runtimes = await discover(force=force)
    return pick_runtime(runtimes), runtimes


async def active_runtime_url(base_url: Optional[str] = None) -> str:
    """URL the LLM adapters should talk to: the reachable runtime, else the
    configured default (so error messages still name a URL)."""
    rt, _ = await active_runtime(base_url)
    return rt.url if rt else (base_url or OLLAMA_BASE_URL).rstrip("/")


# ── Selection rules (pure) ────────────────────────────────────────────────────

def _match_priority(names: List[str], priority) -> str:
    for preferred in priority:
        for n in names:
            nl = n.lower()
            if nl == preferred or nl.startswith(preferred + ":") or preferred in nl:
                return n
    return ""


def _stem(name: str) -> str:
    return (name or "").split(":", 1)[0].lower()


def _most_recent(models: List[ModelInfo]) -> str:
    if not models:
        return ""
    # ISO timestamps from one server share a format, so string order is time
    # order; empty strings sort last.
    return sorted(models, key=lambda m: m.modified_at or "", reverse=True)[0].name


def choose_model(role: str, configured: str, models: List[ModelInfo]) -> Tuple[str, str, str]:
    """Return ``(model, source, reason)`` with ``source`` in
    ``configured | fallback | none``. Order:

    1. the configured name when installed (exact, then same stem);
    2. a model that fits the role and is already loaded in memory;
    3. the role's priority list;
    4. the most recently modified model that fits the role;
    5. nothing.
    """
    cfg = (configured or "").strip()
    names = [m.name for m in models]
    if cfg and cfg.lower() != "auto":
        for n in names:
            if n == cfg or n.lower() == cfg.lower():
                return n, "configured", f"Using the configured model '{n}'."
        for n in names:
            if _stem(n) == _stem(cfg):
                return n, "configured", f"Configured model '{cfg}' resolved to the installed tag '{n}'."
    fitting = [m for m in models if m.fits(role)]
    if not fitting:
        return "", "none", _none_reason(role, cfg, names)
    prefix = f"Configured model '{cfg}' is not installed; " if cfg and cfg.lower() != "auto" else ""
    loaded = [m for m in fitting if m.loaded]
    if loaded:
        n = loaded[0].name
        return n, "fallback", prefix + f"using '{n}', which is already loaded in Ollama."
    priority = {
        "chat": CHAT_MODEL_PRIORITY,
        "fast": FAST_MODEL_PRIORITY + CHAT_MODEL_PRIORITY,
        "vision": VISION_MODEL_PRIORITY,
        "embed": EMBED_MODEL_PRIORITY,
    }.get(role, CHAT_MODEL_PRIORITY)
    picked = _match_priority([m.name for m in fitting], priority)
    if picked:
        return picked, "fallback", prefix + f"using the best installed {role} model '{picked}'."
    recent = _most_recent(fitting)
    return recent, "fallback", prefix + f"using the most recently installed {role} model '{recent}'."


def _none_reason(role: str, cfg: str, names: List[str]) -> str:
    if not names:
        return f"Ollama is reachable but has no models installed."
    kind = {"vision": "vision", "embed": "embedding"}.get(role, "text chat")
    return (
        f"None of the installed models ({', '.join(names)}) can serve {kind}"
        + (f"; the configured model '{cfg}' is not installed either." if cfg else ".")
    )


# ── Remedies ──────────────────────────────────────────────────────────────────

def suggested_for(role: str, installed: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    inst = {n.lower() for n in (installed or [])}
    out = []
    for s in SUGGESTED_MODELS:
        if role in s["roles"]:
            out.append({**s, "installed": s["name"].lower() in inst or any(_stem(n) == _stem(s["name"]) for n in inst)})
    return out


def build_remedy(role: str, runtime: Optional[Runtime], runtimes: List[Runtime], installed: List[str]) -> Dict[str, Any]:
    suggested = suggested_for(role, installed)
    first = suggested[0]["name"] if suggested else "llama3.2:3b"
    if runtime is not None:
        return {
            "kind": "pull",
            "message": (
                f"Ollama at {runtime.url} has no model for {role}. Download one below, or run the command."
            ),
            "command": f"ollama pull {first}",
            "runtime_url": runtime.url,
            "suggested": suggested,
        }
    probed = [r.url for r in runtimes]
    wsl_hosts = [r for r in runtimes if r.label == "wsl-host"]
    if is_wsl() and wsl_networking_mode() == "mirrored":
        # WSL shares Windows' loopback: a Windows Ollama would have answered on 127.0.0.1, so
        # it is stopped, starting, or too busy to answer — not unreachable.
        return {
            "kind": "start",
            "message": (
                "Ollama did not answer. WSL uses mirrored networking, so an Ollama running on Windows "
                "is reachable here: it is probably stopped, still starting, or busy loading a model. "
                "Start the Ollama app on Windows (if `ollama serve` says the port is already in use, "
                "it is running), wait a few seconds, then press Check again."
            ),
            "command": "ollama serve",
            "probed": probed,
            "suggested": suggested,
        }
    if is_wsl() and wsl_hosts:
        return {
            "kind": "wsl_bridge",
            "message": (
                "No Ollama answered inside WSL, and the Windows host refused the connection. "
                "If Ollama runs on Windows it is listening on 127.0.0.1 only: enable WSL mirrored "
                "networking (add `networkingMode=mirrored` under [wsl2] in %USERPROFILE%\\.wslconfig, "
                "then `wsl --shutdown`), or set OLLAMA_HOST=0.0.0.0 on Windows and restart Ollama."
            ),
            "command": "ollama serve",
            "probed": probed,
            "suggested": suggested,
        }
    return {
        "kind": "start",
        "message": (
            "No Ollama runtime is reachable. Start it with `ollama serve`, or set OLLAMA_BASE_URL "
            "to where it runs."
        ),
        "command": "ollama serve",
        "probed": probed,
        "suggested": suggested,
    }


# ── Public resolution ─────────────────────────────────────────────────────────

async def resolve(role: str, configured: str = "", *, base_url: Optional[str] = None, force: bool = False) -> Resolution:
    """Effective model for ``role``. Never raises; ``source == "none"`` with a
    ``remedy`` when nothing can serve the role."""
    if role not in ROLES:
        role = "chat"
    cfg = (configured if configured is not None else "").strip()
    if not cfg and role in ("chat", "fast"):
        cfg = (OLLAMA_MODEL or "").strip()
    runtime, runtimes = await active_runtime(base_url, force=force)
    models = runtime.models if runtime else []
    installed = [m.name for m in models]
    if runtime is not None and not runtime.models_known and cfg and cfg.lower() != "auto":
        # The endpoint answered, but not with an Ollama tag list (a proxy or a
        # stub). Trust the configured name instead of refusing to chat.
        return Resolution(
            role=role, configured=cfg, model=cfg, runtime_url=runtime.url, source="configured",
            reason=f"Using the configured model '{cfg}' (the runtime did not list its models).",
        )
    cfg_installed: Optional[bool] = None
    if cfg and cfg.lower() != "auto":
        cfg_installed = any(n.lower() == cfg.lower() or _stem(n) == _stem(cfg) for n in installed)
    model, source, reason = choose_model(role, cfg, models)
    if runtime is None:
        model, source = "", "none"
        urls = ", ".join(r.url for r in runtimes) or (base_url or OLLAMA_BASE_URL)
        reason = f"No Ollama runtime is reachable (tried {urls})."
    elif base_url and runtime.url != ollama_root(base_url):
        reason = (f"{base_url} is not an Ollama runtime (an OpenAI-compatible gateway such as "
                  f"OllaBridge?); found Ollama at {runtime.url}. " + reason)
    res = Resolution(
        role=role,
        configured=cfg,
        model=model,
        runtime_url=runtime.url if runtime else "",
        source=source,
        reason=reason,
        installed=installed,
        alternatives=[n for n in installed if n != model and ModelInfo(name=n).fits(role)],
        configured_installed=cfg_installed,
    )
    if source == "none":
        res.remedy = build_remedy(role, runtime, runtimes, installed)
    return res


async def snapshot(configured_chat: str = "", configured_vision: str = "", base_url: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """Everything the UI needs in one call."""
    if force:
        invalidate("refresh requested")
    chat = await resolve("chat", configured_chat, base_url=base_url, force=force)
    vision = await resolve("vision", configured_vision, base_url=base_url)
    fast = await resolve("fast", "", base_url=base_url)
    _, runtimes = await active_runtime(base_url)
    return {
        "ok": True,
        "chat": chat.to_dict(),
        "vision": vision.to_dict(),
        "fast": fast.to_dict(),
        "runtimes": [
            {"url": r.url, "label": r.label, "reachable": r.reachable, "models": r.model_names,
             "error": r.error, "latency_ms": r.latency_ms}
            for r in runtimes
        ],
        "runtime_url": chat.runtime_url,
        "suggested": suggested_for("chat", chat.installed),
        "fingerprint": f"{chat.runtime_url}|{','.join(sorted(chat.installed))}",
        "environment": {"wsl": is_wsl(), "docker": is_docker()},
        "pulls": pull_manager.list_active(),
    }


# ── Pull manager ──────────────────────────────────────────────────────────────

@dataclass
class PullJob:
    name: str
    runtime_url: str
    status: str = "queued"         # queued | running | completed | error
    message: str = ""
    total: int = 0
    completed: int = 0
    pct: float = 0.0
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


class PullManager:
    """Runs ``POST /api/pull`` (streaming) in the background, one at a time,
    and keeps progress in memory for the UI to poll."""

    def __init__(self) -> None:
        self._jobs: Dict[str, PullJob] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._sem: Optional[asyncio.Semaphore] = None

    def _semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(1)
        return self._sem

    def get(self, name: str) -> Optional[PullJob]:
        return self._jobs.get(name)

    def list_active(self) -> List[Dict[str, Any]]:
        return [j.to_dict() for j in self._jobs.values() if j.status in ("queued", "running")]

    def start(self, name: str, runtime_url: str) -> PullJob:
        job = self._jobs.get(name)
        if job and job.status in ("queued", "running"):
            return job
        job = PullJob(name=name, runtime_url=runtime_url.rstrip("/"))
        self._jobs[name] = job
        self._tasks[name] = asyncio.get_running_loop().create_task(self._run(job), name=f"pull:{name}")
        return job

    async def _run(self, job: PullJob) -> None:
        async with self._semaphore():
            job.status = "running"
            job.message = "starting"
            timeout = httpx.Timeout(None, connect=10.0)
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", f"{job.runtime_url}/api/pull",
                        json={"model": job.name, "stream": True},
                    ) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                            raise RuntimeError(f"HTTP {resp.status_code}: {body}")
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                import json as _json
                                evt = _json.loads(line)
                            except Exception:  # noqa: BLE001
                                continue
                            if evt.get("error"):
                                raise RuntimeError(str(evt["error"]))
                            job.message = str(evt.get("status") or job.message)
                            total = int(evt.get("total") or 0)
                            done = int(evt.get("completed") or 0)
                            if total:
                                job.total, job.completed = total, done
                                job.pct = round(100.0 * done / total, 1)
                            if job.message == "success":
                                job.pct = 100.0
                job.status = "completed"
                job.message = "success"
                job.pct = 100.0
                invalidate(f"pulled {job.name}")
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.error = str(exc)[:300]
                log.warning("model pull failed for %s: %s", job.name, job.error)
            finally:
                job.finished_at = time.time()


pull_manager = PullManager()
