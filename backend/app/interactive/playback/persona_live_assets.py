"""Authoritative Play-image resolver for Persona Live sessions.

The Persona Live runtime historically had two parallel image sources:

- ``persona_portrait_url`` and ``persona_avatar_url`` on the experience
  (set at session creation from ``audience_profile``),
- per-action edit-recipe outputs that arrive later via ``/pending``.

The frontend used a first-hit-wins fallback and ad-hoc cache keys, which
could race — Play would pin the persona portrait and never swap to the
live edit-recipe output. This module exposes *one* resolver that
normalizes the priority order so both the ``/persona-live/session`` and
``/play/sessions`` routes can agree on which image to display.

Design
------
- Pure function, zero I/O: caller passes in the candidate URLs and we
  pick the best one. Easy to unit-test, cheap to call per-request.
- Priority matches user intent: the most recent live-render wins,
  falling back to the static persona portrait only when no live render
  has completed yet.
- Never returns a placeholder — callers decide what to render when the
  resolver returns ``""``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class PlayImageCandidate:
    """One possible source for the Play image, with priority metadata.

    ``priority`` is lower-is-better so callers can add new sources
    without rewriting the resolver.
    """
    url: str
    source: str      # "live_recipe" | "scene_asset" | "portrait" | "avatar"
    priority: int


# Default priority ladder. Lower = preferred.
PRIORITY_LIVE_RECIPE: int = 0
PRIORITY_SCENE_ASSET: int = 1
PRIORITY_PORTRAIT: int = 2
PRIORITY_AVATAR: int = 3


def _clean(url: Optional[str]) -> str:
    return str(url or "").strip()


def resolve_play_image_url(
    *,
    live_recipe_url: Optional[str] = None,
    scene_asset_url: Optional[str] = None,
    persona_portrait_url: Optional[str] = None,
    persona_avatar_url: Optional[str] = None,
    extra_candidates: Optional[Iterable[PlayImageCandidate]] = None,
) -> str:
    """Return the authoritative Play image URL for the current turn.

    Priority (highest → lowest):
      1. live_recipe_url       — most recent Persona Live action render
      2. scene_asset_url       — graph scene pre-render (Standard mode)
      3. persona_portrait_url  — locked portrait anchor
      4. persona_avatar_url    — generic avatar fallback

    Returns ``""`` when nothing is available. Callers decide whether to
    show a placeholder, loader, or empty frame in that case.
    """
    candidates: list[PlayImageCandidate] = [
        PlayImageCandidate(_clean(live_recipe_url), "live_recipe", PRIORITY_LIVE_RECIPE),
        PlayImageCandidate(_clean(scene_asset_url), "scene_asset", PRIORITY_SCENE_ASSET),
        PlayImageCandidate(_clean(persona_portrait_url), "portrait", PRIORITY_PORTRAIT),
        PlayImageCandidate(_clean(persona_avatar_url), "avatar", PRIORITY_AVATAR),
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)

    # Sort stably by priority; filter out empty URLs.
    live = sorted((c for c in candidates if c.url), key=lambda c: c.priority)
    return live[0].url if live else ""


def describe_source(
    *,
    live_recipe_url: Optional[str] = None,
    scene_asset_url: Optional[str] = None,
    persona_portrait_url: Optional[str] = None,
    persona_avatar_url: Optional[str] = None,
) -> str:
    """Debug helper: return the tag of the source that *would* win.

    Intended for temporary UI badges / structured logs while debugging
    mismatches like the "Play shows persona portrait, not scene asset"
    case. Not used by production code paths.
    """
    url = resolve_play_image_url(
        live_recipe_url=live_recipe_url,
        scene_asset_url=scene_asset_url,
        persona_portrait_url=persona_portrait_url,
        persona_avatar_url=persona_avatar_url,
    )
    if not url:
        return "none"
    if url == _clean(live_recipe_url):
        return "live_recipe"
    if url == _clean(scene_asset_url):
        return "scene_asset"
    if url == _clean(persona_portrait_url):
        return "portrait"
    if url == _clean(persona_avatar_url):
        return "avatar"
    return "extra"


__all__ = [
    "PlayImageCandidate",
    "PRIORITY_LIVE_RECIPE",
    "PRIORITY_SCENE_ASSET",
    "PRIORITY_PORTRAIT",
    "PRIORITY_AVATAR",
    "resolve_play_image_url",
    "describe_source",
]
