"""
FitLab feeds: the LLM registry (chat + vision) and the media registry (image + video).

Where a feed comes from, in order:
  1. Network — only when the user presses "Fetch suggestions" (``refresh=True``).
     FITLAB_REGISTRY_URL / FITLAB_MEDIA_URL first, then FitLab's ``registry-latest``
     branch, then ``master`` — the same order as the ``fitlab`` CLI.
  2. The last good copy fetched on this machine (any age).
  3. The snapshot bundled with this HomePilot release (data/), refreshed weekly by
     scripts/update_fitlab_snapshot.py, so every release ships current suggestions.

Nothing is sent: a fetch is one GET per URL until one answers. The ETag of the last
copy goes with it, so an unchanged feed answers 304 and nothing is downloaded — cheap
enough for the UI's optional automatic daily check. Only https:// (or file:// for an
air-gapped mirror) is accepted, responses are capped in size and time, and a document
is used only if it parses and has the shape this module reads — otherwise the previous
copy stands.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .. import config

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOTS = {"llm": DATA_DIR / "fitlab_registry.snapshot.json", "media": DATA_DIR / "fitlab_media.snapshot.json"}

_RAW = "https://raw.githubusercontent.com/ruslanmv/fitlab/{ref}/data/{name}"
_NAMES = {"llm": "registry.json", "media": "media_registry.json"}
MAX_BYTES = 12 * 1024 * 1024
TIMEOUT_S = 8.0

_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("FITLAB_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def network_allowed() -> bool:
    return os.getenv("FITLAB_OFFLINE", "").strip().lower() not in ("1", "true", "yes", "on")


def cache_dir() -> Path:
    override = os.getenv("FITLAB_CACHE_DIR", "").strip()
    return Path(override) if override else Path(config.SQLITE_PATH).parent / "cache" / "fitlab"


def urls(kind: str) -> List[str]:
    """Candidate URLs for one feed, freshest first."""
    out: List[str] = []
    if kind == "llm":
        custom = os.getenv("FITLAB_REGISTRY_URL", "").strip()
    else:
        custom = os.getenv("FITLAB_MEDIA_URL", "").strip()
        reg = os.getenv("FITLAB_REGISTRY_URL", "").strip()
        if not custom and reg.endswith("/registry.json"):
            custom = reg[: -len("registry.json")] + "media_registry.json"   # a mirror publishes both
    if custom:
        out.append(custom)
    out += [_RAW.format(ref=ref, name=_NAMES[kind]) for ref in ("registry-latest", "master")]
    return out


# ── shape checks ─────────────────────────────────────────────────────────────


def valid(kind: str, doc: Any) -> bool:
    """Only the shape this module reads — enough to never crash on a bad document."""
    if not isinstance(doc, dict) or not str(doc.get("schema_version", "")).startswith("1"):
        return False
    models = doc.get("models")
    if not isinstance(models, dict) or not models:
        return False
    if kind == "media":
        scoring = doc.get("scoring") or {}
        return isinstance(scoring.get("weights"), dict) and isinstance(scoring.get("fit_score"), dict)
    return isinstance(doc.get("generated_at"), str)


# ── fetch ────────────────────────────────────────────────────────────────────


NOT_MODIFIED = object()


def _read_url(url: str, etag: Optional[str] = None) -> Any:
    """The JSON at ``url`` — or NOT_MODIFIED when ``etag`` still matches. Sets ``_read_url.etag``."""
    _read_url.etag = None
    if url.startswith("file://"):
        path = Path(url[len("file://"):])
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("document too large")
        return json.loads(path.read_text(encoding="utf-8"))
    if not url.startswith("https://"):
        raise ValueError("only https:// or file:// URLs are accepted")
    headers = {"Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as r:
            if r.status_code == 304:
                return NOT_MODIFIED
            r.raise_for_status()
            _read_url.etag = r.headers.get("etag")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise ValueError("document too large")
    return json.loads(bytes(buf))


def fetch(kind: str, known: Optional[dict] = None) -> Tuple[Any, Optional[str], Optional[str], List[str]]:
    """Try each URL; return (document | NOT_MODIFIED | None, url, etag, errors).

    ``known`` is the cached copy's meta ({url, etag}); its ETag is sent to that URL only.
    """
    errors: List[str] = []
    known = known or {}
    for url in urls(kind):
        try:
            doc = _read_url(url, known.get("etag") if url == known.get("url") else None)
        except Exception as e:  # network, 404, too large, not JSON
            errors.append(f"{url}: {type(e).__name__}: {str(e)[:120]}")
            continue
        if doc is NOT_MODIFIED:
            return NOT_MODIFIED, url, known.get("etag"), errors
        if valid(kind, doc):
            return doc, url, getattr(_read_url, "etag", None), errors
        errors.append(f"{url}: not a FitLab {kind} document")
    return None, None, None, errors


# ── cache + snapshot ─────────────────────────────────────────────────────────


def _cache_paths(kind: str) -> Tuple[Path, Path]:
    d = cache_dir()
    return d / f"{kind}.json", d / f"{kind}.meta.json"


def _write_json(target: Path, payload: Any) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(target)


def _write_cache(kind: str, doc: dict, url: str, etag: Optional[str]) -> float:
    path, meta = _cache_paths(kind)
    now = time.time()
    _write_json(path, doc)
    _write_json(meta, {"url": url, "etag": etag, "fetched_at": now, "checked_at": now})
    return now


def _touch_cache(kind: str, info: dict) -> float:
    """A 304: the cached copy is current as of now."""
    now = time.time()
    _write_json(_cache_paths(kind)[1], {**info, "checked_at": now})
    return now


def _read_cache(kind: str) -> Tuple[Optional[dict], Optional[dict]]:
    path, meta = _cache_paths(kind)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        info = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    except Exception:
        return None, None
    return (doc, info) if valid(kind, doc) else (None, None)


def _read_snapshot(kind: str) -> Optional[dict]:
    try:
        doc = json.loads(SNAPSHOTS[kind].read_text(encoding="utf-8"))
    except Exception:
        return None
    return doc if valid(kind, doc) else None


@dataclass
class Feed:
    kind: str
    doc: Optional[dict]
    source: str  # live | cache | bundled | none
    fetched_at: Optional[float] = None
    url: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    checked_at: Optional[float] = None   # last time FitLab confirmed this copy is current
    changed: Optional[bool] = None       # on a live fetch: did the document change?

    def info(self) -> Dict[str, Any]:
        d = self.doc or {}
        return {
            "source": self.source,
            "generated_at": d.get("generated_at"),
            "ranking_version": d.get("ranking_version") or d.get("media_ranking_version"),
            "fetched_at": self.fetched_at,
            "checked_at": self.checked_at,
            "url": self.url,
        }


def load(kind: str, refresh: bool = False) -> Feed:
    """The best available copy of one feed. Network only when ``refresh`` and allowed."""
    errors: List[str] = []
    if refresh:
        if network_allowed():
            with _lock:
                cached, info = _read_cache(kind)
                doc, url, etag, errors = fetch(kind, info if cached is not None else None)
                if doc is NOT_MODIFIED and cached is not None:
                    checked = _touch_cache(kind, info or {})
                    return Feed(kind, cached, "live", (info or {}).get("fetched_at"), url, errors,
                                checked_at=checked, changed=False)
                if doc is not None and doc is not NOT_MODIFIED:
                    changed = cached is None or json.dumps(cached, sort_keys=True) != json.dumps(doc, sort_keys=True)
                    fetched_at = _write_cache(kind, doc, url or "", etag)
                    return Feed(kind, doc, "live", fetched_at, url, errors, checked_at=fetched_at, changed=changed)
        else:
            errors.append("network disabled (FITLAB_OFFLINE)")
    doc, info = _read_cache(kind)
    if doc is not None:
        info = info or {}
        return Feed(kind, doc, "cache", info.get("fetched_at"), info.get("url"), errors,
                    checked_at=info.get("checked_at") or info.get("fetched_at"))
    snap = _read_snapshot(kind)
    if snap is not None:
        return Feed(kind, snap, "bundled", None, None, errors)
    return Feed(kind, None, "none", None, None, errors)
