"""
PromptLibrary — tiny, audit-friendly prompt loader for the
interactive AI workflows (autoplan, autogen, rule, QA).

Design goals:

* Prompts live on disk in YAML so operators + reviewers can diff
  wording, grep for forbidden phrases, and A/B revisions without
  patching Python.
* One YAML file per prompt, keyed by a stable ``prompt_id`` string
  (e.g. ``autoplan.classify_mode``). The id is what Python calls
  ``render()`` with — renaming a file without updating callers
  fails loudly at load time.
* Prompts are small and focused. A 1.5B Qwen or 8B Llama must be
  able to answer each one in a single short completion. If a
  prompt balloons past ~400 tokens it's the wrong shape — split.
* Rendering is plain ``str.format_map`` with a ``_SafeDict`` that
  leaves unknown keys as literal ``{key}`` — no Jinja, no code
  execution, no surprise imports. Variables are spelled out in
  the YAML under ``variables:`` and callers must provide every
  one; unused variables are ignored.
* Validation + retries live in the YAML, not the calling code.
  The workflow runner (REV-2) reads ``policy()`` and handles
  retry / fallback uniformly; this keeps planner code boring and
  makes ops changes a one-line YAML edit.

The library is purely additive — nothing else imports from it
today. REV-3 onward swap the legacy planner over to this loader.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml


# ── Errors ─────────────────────────────────────────────────────

class PromptLibraryError(Exception):
    """Base error for every load/render problem.

    We deliberately keep a single class (no subclassing) so callers
    can ``except PromptLibraryError`` once and still surface the
    exact message — no guesswork about which flavour fired.
    """


# ── Data shapes ────────────────────────────────────────────────

@dataclass(frozen=True)
class PromptPolicy:
    """Retry + validation knobs declared alongside the prompt.

    The workflow runner consumes these; ``PromptLibrary`` itself
    never dispatches. Keeping policy as data (not code) means a
    reviewer can eyeball every guardrail in one place.
    """

    retries: int = 1
    timeout_s: float = 20.0
    response_format: Optional[str] = None       # "json" | None
    output_schema: Optional[str] = None         # symbolic id, not a JSONSchema
    allowed_values: List[str] = field(default_factory=list)
    max_chars: int = 0                          # 0 → unbounded
    model_hints: Dict[str, Any] = field(default_factory=dict)
    fallback: Optional[str] = None              # symbolic: 'abort' | 'retry' | default value


@dataclass(frozen=True)
class RenderedPrompt:
    """The pair the LLM client needs: ``system`` + ``user`` strings.

    Anything downstream (provider adapter, response_format, etc.)
    comes from ``PromptPolicy``; this object only carries the two
    message bodies so call sites can trivially build the OpenAI
    ``messages`` array.
    """

    prompt_id: str
    version: str
    system: str
    user: str

    def to_messages(self) -> List[Dict[str, str]]:
        """OpenAI-style messages array."""
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


# ── Safe formatter ─────────────────────────────────────────────

class _SafeDict(dict):
    """``str.format_map`` helper that keeps unknown ``{keys}``
    as literal text instead of raising ``KeyError``.

    Prompts sometimes contain curly braces in example JSON — we
    don't want the renderer to confuse those with substitution
    variables. Anything the caller doesn't supply passes through
    untouched; any variable the caller *does* supply is
    substituted exactly once.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


# ── Library ────────────────────────────────────────────────────

class PromptLibrary:
    """On-disk prompt loader with lazy caching.

    Usage::

        lib = PromptLibrary()          # defaults to ./prompts/
        rp = lib.render("autoplan.classify_mode", idea="...")
        policy = lib.policy("autoplan.classify_mode")

    The library is thread-safe enough for FastAPI (pure reads
    after the first hit, no mutation of shared state), but it's
    *not* reload-safe — operators edit YAML, restart the process.
    Hot reload can come later if it ever matters.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root: Path = Path(root) if root else Path(__file__).parent
        self._index: Optional[Dict[str, str]] = None
        self._cache: Dict[str, Dict[str, Any]] = {}

    # ── Index / lookup ────────────────────────────────────

    def _load_index(self) -> Dict[str, str]:
        """Read ``library.yaml`` → ``{prompt_id: relative_path}``."""
        if self._index is not None:
            return self._index
        index_path = self._root / "library.yaml"
        if not index_path.exists():
            raise PromptLibraryError(
                f"Prompt library index missing: {index_path}",
            )
        try:
            raw = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise PromptLibraryError(f"Invalid YAML in {index_path}: {exc}") from exc
        prompts = raw.get("prompts") if isinstance(raw, dict) else None
        if not isinstance(prompts, dict) or not prompts:
            raise PromptLibraryError(
                f"{index_path} must define a non-empty 'prompts:' map",
            )
        index: Dict[str, str] = {}
        for pid, rel in prompts.items():
            if not isinstance(pid, str) or not isinstance(rel, str):
                raise PromptLibraryError(
                    f"library.yaml entries must be str→str (got {pid!r}: {rel!r})",
                )
            index[pid] = rel
        self._index = index
        return index

    def _load_prompt(self, prompt_id: str) -> Dict[str, Any]:
        """Read + cache one prompt YAML."""
        if prompt_id in self._cache:
            return self._cache[prompt_id]
        index = self._load_index()
        rel = index.get(prompt_id)
        if rel is None:
            raise PromptLibraryError(
                f"Unknown prompt id: {prompt_id!r}. "
                f"Known: {sorted(index.keys())}",
            )
        path = self._root / rel
        if not path.exists():
            raise PromptLibraryError(f"Prompt file missing: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise PromptLibraryError(f"Invalid YAML in {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise PromptLibraryError(
                f"{path} must be a YAML mapping (got {type(data).__name__})",
            )
        for required in ("id", "version", "system", "user_template"):
            if required not in data or not isinstance(data[required], str):
                raise PromptLibraryError(
                    f"{path}: missing or non-string field {required!r}",
                )
        if data["id"] != prompt_id:
            raise PromptLibraryError(
                f"{path}: id field {data['id']!r} does not match "
                f"library.yaml key {prompt_id!r}",
            )
        self._cache[prompt_id] = data
        return data

    # ── Public API ────────────────────────────────────────

    def ids(self) -> List[str]:
        """Every prompt id the library can render."""
        return sorted(self._load_index().keys())

    def render(self, prompt_id: str, **variables: Any) -> RenderedPrompt:
        """Substitute ``variables`` into the template and return
        the ``RenderedPrompt``.

        Required variables are declared under ``variables:`` in the
        YAML. Missing any of them raises ``PromptLibraryError`` —
        better to fail loudly than ship a prompt with a literal
        ``{idea}`` to the LLM.
        """
        data = self._load_prompt(prompt_id)
        declared = data.get("variables") or []
        if not isinstance(declared, list):
            raise PromptLibraryError(
                f"{prompt_id}: 'variables' must be a list of strings",
            )
        missing = [v for v in declared if v not in variables]
        if missing:
            raise PromptLibraryError(
                f"{prompt_id}: missing required variables: {missing}",
            )
        safe = _SafeDict({k: _coerce(v) for k, v in variables.items()})
        return RenderedPrompt(
            prompt_id=prompt_id,
            version=str(data.get("version", "0")),
            system=str(data["system"]).format_map(safe),
            user=str(data["user_template"]).format_map(safe),
        )

    def policy(self, prompt_id: str) -> PromptPolicy:
        """Parse the YAML policy fields into a ``PromptPolicy``.

        Unknown fields are ignored so we can grow the schema
        without breaking already-loaded caches.

        ``INTERACTIVE_LLM_TIMEOUT_MULTIPLIER`` is applied at read
        time so ops on slow hardware can triple every timeout
        without editing YAML (e.g. set ``=3.0`` while a large
        chat model warms up). Read live on each call so changes
        take effect without a restart.
        """
        data = self._load_prompt(prompt_id)
        raw_policy = data.get("policy") or {}
        if not isinstance(raw_policy, dict):
            raise PromptLibraryError(
                f"{prompt_id}: 'policy' must be a mapping",
            )
        validation = data.get("validation") or {}
        if not isinstance(validation, dict):
            raise PromptLibraryError(
                f"{prompt_id}: 'validation' must be a mapping",
            )
        allowed = validation.get("allowed_values")
        if allowed is not None and (
            not isinstance(allowed, list)
            or not all(isinstance(v, str) for v in allowed)
        ):
            raise PromptLibraryError(
                f"{prompt_id}: validation.allowed_values must be list[str]",
            )
        hints = data.get("model_hints") or {}
        if not isinstance(hints, dict):
            raise PromptLibraryError(
                f"{prompt_id}: 'model_hints' must be a mapping",
            )
        fallback = data.get("fallback")
        if fallback is not None and not isinstance(fallback, str):
            raise PromptLibraryError(
                f"{prompt_id}: 'fallback' must be a string",
            )

        base_timeout = float(raw_policy.get("timeout_s", 20.0))
        multiplier = _timeout_multiplier_env()
        return PromptPolicy(
            retries=int(raw_policy.get("retries", 1)),
            timeout_s=max(1.0, base_timeout * multiplier),
            response_format=_nstr(raw_policy.get("response_format")),
            output_schema=_nstr(validation.get("schema")),
            allowed_values=list(allowed or []),
            max_chars=int(validation.get("max_chars", 0) or 0),
            model_hints=dict(hints),
            fallback=fallback,
        )


# ── Helpers ────────────────────────────────────────────────────

def _coerce(value: Any) -> Any:
    """Render list-of-strings as a bulleted block; otherwise str()."""
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {v}" for v in value)
    return value


def _nstr(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)


def _timeout_multiplier_env() -> float:
    """Read ``INTERACTIVE_LLM_TIMEOUT_MULTIPLIER`` live on each
    call. Lets operators on slow hardware triple every prompt's
    deadline without editing the YAML library. Defaults to 1.0;
    clamped to [0.1, 10.0] to prevent runaway values.

    Zero / negative / non-numeric values are ignored (fall back
    to 1.0) so a malformed env entry never disables timeouts
    entirely.
    """
    raw = os.getenv("INTERACTIVE_LLM_TIMEOUT_MULTIPLIER", "").strip()
    if not raw:
        return 1.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if value <= 0:
        return 1.0
    return max(0.1, min(10.0, value))


# ── Module-level convenience ───────────────────────────────────

_DEFAULT: Optional[PromptLibrary] = None


def default_library() -> PromptLibrary:
    """Process-wide default ``PromptLibrary`` rooted at this
    package's directory.

    Cached so the index only deserialises once; tests can still
    instantiate their own ``PromptLibrary(root=...)`` for
    isolation.
    """
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = PromptLibrary()
    return _DEFAULT


__all__ = [
    "PromptLibrary",
    "PromptLibraryError",
    "PromptPolicy",
    "RenderedPrompt",
    "default_library",
]
