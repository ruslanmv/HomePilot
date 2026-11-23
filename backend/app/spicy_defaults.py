"""
Spicy (adult) mode's local model defaults.

Why this exists
---------------
Turning Spicy mode on used to change only the prompts. The models stayed whatever was selected,
so an explicit request went to a model that either could not draw it (SDXL base, Flux, the SVD
video default) or, for edits, to an img2img pass on the image checkpoint. The catalog already
knew which local models are adult-capable (``nsfw: true``), but nothing chose one.

``model_catalog_data.json`` now carries a ``spicy_defaults`` block: per capability, the local
models Spicy mode should use, best first. This module reads it and answers one question —
"which of those is installed?" — so the orchestrator can fill in a model when the request
names none (image, video) or when the capability has no picker at all (edit).

Rules it keeps
--------------
- **A model the person picked always wins.** Defaults fill gaps; they never replace a choice.
- **Only installed models are returned.** Suggesting a 38 GB download mid-request helps nobody;
  when none is installed the caller keeps its old behaviour.
- **Local only.** Every id here is a local Ollama or ComfyUI model; nothing in this module can
  send a request off the machine.
- **Fail soft.** A missing or malformed catalog block means "no default", never an exception
  in the middle of a generation.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path

_CATALOG_PATH = Path(__file__).parent / "model_catalog_data.json"

CAPABILITIES = ("chat", "multimodal", "image", "edit", "video")

# The Qwen editor is selected by name as well as by default, so a request that names it (from
# the image picker or a ``--ckpt`` flag) goes to its own workflow instead of img2img.
QWEN_EDIT_MARKER = "qwen-image-edit"


@lru_cache(maxsize=1)
def _defaults() -> dict[str, list[str]]:
    try:
        with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
            block = json.load(f).get("spicy_defaults") or {}
    except (OSError, ValueError) as exc:
        print(f"[SPICY] Could not read spicy_defaults from the catalog: {exc}")
        return {}
    return {
        cap: [str(x) for x in block.get(cap, []) if isinstance(x, str) and x]
        for cap in CAPABILITIES
    }


def defaults_for(capability: str) -> list[str]:
    """The ordered Spicy defaults for one capability (may be empty)."""
    return list(_defaults().get(capability, []))


def pick_installed(capability: str, installed: Iterable[str]) -> str | None:
    """First Spicy default for ``capability`` that appears in ``installed``, else None."""
    have = {str(x) for x in installed or []}
    for model_id in defaults_for(capability):
        if model_id in have:
            return model_id
    return None


def _installed(capability: str) -> list[str]:
    from .providers import scan_installed_models

    try:
        return scan_installed_models(capability)
    except Exception as exc:  # noqa: BLE001 — a scan failure must not fail the request
        print(f"[SPICY] Could not scan installed {capability} models: {exc}")
        return []


def _is_empty(value: str | None) -> bool:
    return not value or str(value).strip().lower() in ("none", "null", "")


def resolve(
    capability: str,
    requested: str | None,
    nsfw_mode: bool | None,
    *,
    installed: Callable[[str], Iterable[str]] | None = None,
) -> str | None:
    """
    The model to use for ``capability``.

    ``requested`` when the person named one; otherwise, in Spicy mode, the first installed
    Spicy default; otherwise ``requested`` unchanged (so the caller's own default applies).
    ``installed`` is injectable for tests; it defaults to the filesystem scan.
    """
    if not _is_empty(requested):
        return requested
    if not nsfw_mode:
        return requested
    choice = pick_installed(capability, (installed or _installed)(capability))
    if choice:
        print(f"[SPICY] No {capability} model chosen; using the Spicy default {choice}")
    return choice or requested


def is_qwen_edit(model_id: str | None) -> bool:
    return QWEN_EDIT_MARKER in (model_id or "").lower()


def use_qwen_edit(
    *,
    has_mask: bool,
    named_model: str | None,
    nsfw_mode: bool | None,
    installed: Callable[[str], Iterable[str]] | None = None,
) -> bool:
    """
    Whether an edit should run on Qwen-Image-Edit instead of the img2img/inpaint workflows.

    - A masked edit keeps the inpaint workflows: they honour the mask, Qwen's editor does not.
    - Naming the Qwen editor selects it in any mode.
    - In Spicy mode it is the default editor when installed, unless another checkpoint was named
      explicitly for this edit (``--ckpt``).
    """
    if has_mask:
        return False
    if is_qwen_edit(named_model):
        return True
    if not nsfw_mode or not _is_empty(named_model):
        return False
    return pick_installed("edit", (installed or _installed)("edit")) is not None
