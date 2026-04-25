"""
Persona asset-library pre-render pack.

Why this exists
---------------
Persona Live Play used to live-render every reaction (blush / smirk /
closer pose / outfit change) through ``render_adapter.render_scene_
async`` on every click. On a busy GPU that's a 5-15 s wait per action
— the "compliment her → blush" click lands, the player stares at the
same frame, then eventually sees the reaction. Immersion collapses.

This module is the pre-render pack:

* Declares a **standardized visual state set** (idles, expressions,
  poses, cameras, outfits, environments) every persona should ship
  with so common reactions can be served instantly from cache.
* Provides a **planner** that turns the manifest into a list of
  ``AssetSpec`` rows the caller can iterate and render.
* Provides **storage helpers** that read/write the library inside
  ``project.persona_appearance.asset_library`` — the existing
  ``projects.update_project`` deep-merge path already preserves that
  dict, so we add no new schema and can't stomp anything.
* Provides **intent lookup** (``asset_id_for_intent``) so the action
  endpoint can resolve ``compliment`` → ``expr_blush`` → stored URL
  without touching the renderer in the fast path.

Strictly additive: the action endpoint's existing live-render path
keeps working when the library is empty / the env flag is off. The
pack is the cache, not a replacement.

Priority tiers
--------------
* Tier 1 (MUST) — idles + all expressions + default outfit + medium
  camera. Covers the common loop; the lookup layer expects all of
  these to be present.
* Tier 2 (SHOULD) — pose variations + close-up camera + 1-2 extra
  outfits.
* Tier 3 (MAY) — additional outfits, environments, special poses.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence


log = logging.getLogger(__name__)


# ── Public types ────────────────────────────────────────────────────────────

AssetKind = str  # "idle" | "expression" | "pose" | "outfit" | "camera" | "environment"
Tier = int       # 1 | 2 | 3


@dataclass(frozen=True)
class AssetSpec:
    """One pre-render row in the standardized pack.

    ``asset_id``   — namespaced id ("expr_blush", "pose_lean_forward").
                     Stored in the library dict as the key; retrieval is
                     O(1) from ``asset_id_for_intent``.
    ``tier``       — 1 / 2 / 3. Build passes take a max-tier arg.
    ``kind``       — high-level bucket used by UI / debugging.
    ``edit_hint``  — routes to the matching edit recipe
                     ("expression" / "pose" / "outfit" / "bg").
    ``reaction_intent`` — the key ``ACTION_RECIPES`` uses (smirk / blush /
                     closer_pose / outfit_change / …). Lets us reuse the
                     existing recipe router without a second code path.
    ``prompt_fragment`` — appended to the render-time prompt so the
                     workflow produces the right visual state.
    ``explicit_only`` — when True, this spec is only planned / rendered
                     when the persona has ``allow_explicit=True``. Hard
                     fail-closed: the filter never includes it for a
                     persona whose safety profile forbids explicit
                     content, so Spicy Mode off + non-allow_explicit
                     personas never see these rows at any tier.
    """
    asset_id: str
    tier: Tier
    kind: AssetKind
    edit_hint: str
    reaction_intent: str
    prompt_fragment: str
    description: str = ""
    explicit_only: bool = False


@dataclass(frozen=True)
class AssetRecord:
    """One row persisted under ``persona_appearance.asset_library``.

    ``asset_id`` is the SPEC id from the manifest (``"expr_blush"``,
    ``"idle_neutral"``, …) — it's how the dict is keyed, used by the
    runtime-lookup helpers to find a row by intent.

    ``registry_asset_id`` is the asset registry's id (e.g.
    ``"a_f3dbc3ea0ca345d3966c"``) returned by ``register_asset``.
    This is the id the **editor preview** + the **Phase-4 scene link**
    pass to ``/v1/interactive/assets/{id}/url``. Storing it here means
    we can attach the registry id to a scene's ``asset_ids`` list
    instead of the raw ComfyUI ``http://...`` URL — the editor's
    resolve endpoint expects a registry id, and giving it a URL gets
    silently 404'd because URL chars confuse the path parser.

    ``asset_url`` is a denormalised copy of the URL the registry
    resolves the id to. Useful for the runtime fast-path lookup that
    avoids the registry hop, and as a fallback when the registry row
    is gone but the URL is still reachable.
    """
    asset_id: str
    asset_url: str
    kind: AssetKind
    tier: Tier
    reaction_intent: str
    registry_asset_id: str = ""
    generated_at: float = 0.0
    source: str = ""  # "library_build" | "live_render_promoted"


# ── Standardized manifest (v1 spec) ─────────────────────────────────────────
#
# Keep this table tight: every entry is either (a) directly targeted by a
# runtime intent in ``_INTENT_CATALOG`` or (b) a visible visual state
# useful for progression UX. Adding rows here is cheap — don't bloat.

ASSET_MANIFEST: tuple[AssetSpec, ...] = (
    # ── Tier 1 — MUST pre-generate ─────────────────────────────────────
    AssetSpec(
        asset_id="idle_neutral",
        tier=1, kind="idle", edit_hint="expression", reaction_intent="tease",
        prompt_fragment="neutral expression, soft eyes, relaxed stance, direct gaze",
        description="Default idle — fallback state when no intent has fired.",
    ),
    AssetSpec(
        asset_id="idle_soft_smile",
        tier=1, kind="idle", edit_hint="expression", reaction_intent="tease",
        prompt_fragment="gentle smile, calm eyes, relaxed shoulders, warm vibe",
        description="Secondary idle — ambient warmth between actions.",
    ),
    AssetSpec(
        asset_id="expr_blush",
        tier=1, kind="expression", edit_hint="expression", reaction_intent="blush",
        prompt_fragment="shy blush, lips parted, averted glance, flustered vibe",
        description="Reaction to compliment / ask_personal.",
    ),
    AssetSpec(
        asset_id="expr_smirk",
        tier=1, kind="expression", edit_hint="expression", reaction_intent="smirk",
        prompt_fragment="playful smirk, confident gaze, slight eyebrow raise",
        description="Reaction to say_playful.",
    ),
    AssetSpec(
        asset_id="expr_smile",
        tier=1, kind="expression", edit_hint="expression", reaction_intent="tease",
        prompt_fragment="warm genuine smile, relaxed eyes, open body language",
        description="Reaction to stay_quiet, ask_about_her.",
    ),
    AssetSpec(
        asset_id="expr_neutral_attentive",
        tier=1, kind="expression", edit_hint="expression", reaction_intent="tease",
        prompt_fragment="attentive neutral expression, head slightly tilted, listening",
        description="Reaction to ask_about_her.",
    ),
    AssetSpec(
        asset_id="expr_curious",
        tier=1, kind="expression", edit_hint="expression", reaction_intent="tease",
        prompt_fragment="curious expression, raised eyebrow, engaged gaze, half smile",
        description="Reaction to ask_personal.",
    ),
    AssetSpec(
        asset_id="outfit_casual",
        tier=1, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="oversized hoodie and jeans, casual look, everyday fashion",
        description="Default outfit — paired with every expression.",
    ),
    AssetSpec(
        asset_id="cam_medium",
        tier=1, kind="camera", edit_hint="composition", reaction_intent="turn_around",
        prompt_fragment="medium shot, waist up, standard framing",
        description="Default camera framing — paired with every pose.",
    ),

    # ── Tier 2 — SHOULD pre-generate ───────────────────────────────────
    AssetSpec(
        asset_id="pose_lean_forward",
        tier=2, kind="pose", edit_hint="pose", reaction_intent="closer_pose",
        prompt_fragment="leaning forward slightly, elbows on knees, engaged posture",
        description="Reaction to get_closer intent.",
    ),
    AssetSpec(
        asset_id="pose_relaxed",
        tier=2, kind="pose", edit_hint="pose", reaction_intent="closer_pose",
        prompt_fragment="relaxed seated pose, one hand on lap, comfortable stance",
        description="Trust / comfort ladder mid-progression.",
    ),
    AssetSpec(
        asset_id="cam_close_up",
        tier=2, kind="camera", edit_hint="composition", reaction_intent="closer_pose",
        prompt_fragment="close-up shot, face and shoulders, soft background blur",
        description="Intimate framing reaction to get_closer.",
    ),
    AssetSpec(
        asset_id="cam_wide",
        tier=2, kind="camera", edit_hint="composition", reaction_intent="zoom_out",
        prompt_fragment="wide shot, full body, ambient environment visible",
        description="Reaction to step_back intent.",
    ),
    AssetSpec(
        asset_id="outfit_fitness",
        tier=2, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="fitted athleisure, sports bra and leggings, fitness look",
        description="Outfit variety — tier 2 unlock.",
    ),
    AssetSpec(
        asset_id="outfit_sleepwear",
        tier=2, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="oversized button-up shirt over shorts, cozy sleepwear",
        description="Outfit variety — intimate setting.",
    ),

    # ── Tier 2 outfit × expression composites ──────────────────────────
    #
    # The v1 spec calls out "outfits × expressions" as the dimension
    # that produces the felt sense of variety — players notice when
    # the same character reacts in a NEW outfit. Two composites cover
    # the highest-impact cases: fitness + smile (reaction to a
    # compliment in athleisure) and sleepwear + blush (reaction in an
    # intimate setting). Same plain-img2img pipeline, just denser
    # prompt fragments combining outfit + expression cues.
    AssetSpec(
        asset_id="outfit_fitness_expr_smile",
        tier=2, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="fitted athleisure, sports bra and leggings, fitness look, "
                        "warm genuine smile, relaxed eyes, open body language",
        description="Composite: fitness outfit + warm smile (compliment in athleisure).",
    ),
    AssetSpec(
        asset_id="outfit_sleepwear_expr_blush",
        tier=2, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="oversized button-up shirt over shorts, cozy sleepwear, "
                        "shy blush, lips parted, averted glance, flustered vibe",
        description="Composite: sleepwear + blush (intimate setting reaction).",
    ),

    # ── Tier 3 — MAY pre-generate ──────────────────────────────────────
    AssetSpec(
        asset_id="outfit_dress",
        tier=3, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="evening dress, elegant, modest neckline",
        description="Formal outfit variety.",
    ),
    AssetSpec(
        asset_id="env_room",
        tier=3, kind="environment", edit_hint="bg", reaction_intent="move_to_beach",
        prompt_fragment="warm-lit bedroom, soft bedding, dim practical light",
        description="Default environment.",
    ),
    AssetSpec(
        asset_id="env_couch",
        tier=3, kind="environment", edit_hint="bg", reaction_intent="move_to_beach",
        prompt_fragment="cozy living room, warm lamp light, soft sofa",
        description="Relaxed environment.",
    ),
    AssetSpec(
        asset_id="env_outdoor",
        tier=3, kind="environment", edit_hint="bg", reaction_intent="move_to_beach",
        prompt_fragment="sunset beach, warm golden light, ocean waves",
        description="Outdoor escape environment.",
    ),

    # ── NSFW pack (explicit_only=True) ─────────────────────────────────
    #
    # Gated behind ``persona.allow_explicit`` AND a Mature (gated)
    # experience mode. Vocabulary mirrors the explicit rows in
    # ``persona_live_prompts.EXPRESSION_LADDER / POSE_LADDER /
    # OUTFIT_LADDER`` so the build pack produces the same "fan-service
    # tasteful erotic art" style the system prompt already asks for at
    # the explicit tier. ``BASE_NEGATIVE`` (minor-safety floor) applies
    # automatically via the shared render adapter — we don't need a
    # separate guard here.

    # Tier 1 NSFW — the fan-service core reactions. These are what the
    # "compliment her → breathless" / "lean in → heated gaze" loop
    # needs served instantly to feel alive on an explicit-tier persona.
    AssetSpec(
        asset_id="expr_heated",
        tier=1, kind="expression", edit_hint="expression", reaction_intent="blush",
        prompt_fragment="heated gaze, flushed cheeks, lips parted, sensual mood, "
                        "boudoir photography style, fan service, tasteful erotic art",
        description="Mature expression reaction — warm, charged, clothed.",
        explicit_only=True,
    ),
    AssetSpec(
        asset_id="expr_breathless",
        tier=1, kind="expression", edit_hint="expression", reaction_intent="ahegao",
        prompt_fragment="breathless expression, half-lidded eyes, soft biting lip, "
                        "sensual mood, boudoir photography style, tasteful erotic art",
        description="Mature expression for lean_in / level-5 intents.",
        explicit_only=True,
    ),

    # Tier 2 NSFW — poses + outfits that carry the most visible tier
    # uplift on a click ("suggest outfit" → instant lingerie reveal).
    AssetSpec(
        asset_id="pose_reclining",
        tier=2, kind="pose", edit_hint="pose", reaction_intent="closer_pose",
        prompt_fragment="reclining on bed, one knee raised, relaxed pose, "
                        "tasteful framing, boudoir photography style",
        description="Mature pose — intimate bedroom framing.",
        explicit_only=True,
    ),
    AssetSpec(
        asset_id="pose_closer_intimate",
        tier=2, kind="pose", edit_hint="pose", reaction_intent="closer_pose",
        prompt_fragment="closer intimate pose, partner-implied framing, "
                        "tasteful crop, boudoir photography style",
        description="Mature close-framing pose for high-trust turns.",
        explicit_only=True,
    ),
    AssetSpec(
        asset_id="outfit_lingerie",
        tier=2, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="lingerie-style outfit, tasteful boudoir framing, "
                        "soft rim light, sensual mood, tasteful erotic art",
        description="Mature outfit — tasteful boudoir / lingerie.",
        explicit_only=True,
    ),
    AssetSpec(
        asset_id="outfit_silk_robe",
        tier=2, kind="outfit", edit_hint="outfit", reaction_intent="outfit_change",
        prompt_fragment="silk robe loosely tied, tasteful boudoir framing, "
                        "soft window light, silk sheets, sensual mood",
        description="Mature outfit — silk robe / boudoir loungewear.",
        explicit_only=True,
    ),

    # Tier 3 NSFW — environments that complete the boudoir set.
    AssetSpec(
        asset_id="env_boudoir",
        tier=3, kind="environment", edit_hint="bg", reaction_intent="move_to_beach",
        prompt_fragment="boudoir set, soft window light, silk sheets, "
                        "dramatic contrast, tasteful erotic art",
        description="Mature environment — boudoir set.",
        explicit_only=True,
    ),
    AssetSpec(
        asset_id="env_bedroom_intimate",
        tier=3, kind="environment", edit_hint="bg", reaction_intent="move_to_beach",
        prompt_fragment="warm-lit intimate bedroom, low dim lighting, "
                        "soft bedding, sensual mood",
        description="Mature environment — intimate bedroom.",
        explicit_only=True,
    ),
)


# ── Intent → library asset mapping ──────────────────────────────────────────
#
# Maps the player-facing intent ids from ``routes/persona_live._INTENT_CATALOG``
# to the library asset that should be served. Any intent not in this table
# falls through to the live-render path (which is the current behaviour —
# nothing regresses when the library is empty).

INTENT_TO_ASSET_ID: Dict[str, str] = {
    # Level 1
    "say_playful":     "expr_smirk",
    "compliment":      "expr_blush",
    "ask_about_her":   "expr_smile",
    "stay_quiet":      "expr_neutral_attentive",
    # Level 2
    "get_closer":      "pose_lean_forward",
    "ask_personal":    "expr_curious",
    # Level 3
    "change_view":     "cam_wide",
    "step_back":       "cam_wide",
    # Level 4
    "suggest_outfit":  "outfit_fitness",  # variety; rotates further when cached
    "change_location": "env_couch",
}

# Explicit-only intent overrides. Used when the persona has
# allow_explicit=True AND Spicy Mode is on — these level-4 / level-5
# intents prefer a NSFW library row over the SFW fallback above.
# Every asset_id here must be tagged ``explicit_only=True`` in the
# manifest; if the library doesn't have it yet (build pass hasn't run
# at that tier, or the persona disallows explicit), the lookup falls
# through to the SFW entry and then to live render.
INTENT_TO_ASSET_ID_EXPLICIT: Dict[str, str] = {
    # Level 4 mature variety — when the persona allows, suggest the
    # lingerie outfit / boudoir environment instead of the SFW default.
    "suggest_outfit":  "outfit_lingerie",
    "change_location": "env_boudoir",
    # Level 5 — "Lean into the moment" / "Playful dare". Previously
    # fell through to live render always; now resolvable when the
    # library is built at tier 2 for explicit personas.
    "lean_in":         "expr_breathless",
    "playful_dare":    "pose_closer_intimate",
    # Level 2 intimacy can also prefer the mature close-framing pose
    # once the library has it.
    "get_closer":      "pose_closer_intimate",
    "ask_personal":    "expr_heated",
}


def asset_id_for_intent(intent_id: str, *, allow_explicit: bool = False) -> str:
    """Resolve player intent → pre-rendered library asset id.

    When ``allow_explicit=True``, the lookup prefers the NSFW override
    row if one exists for this intent; otherwise falls back to the SFW
    default. Returns empty string when the intent has no library
    mapping at all — the caller should fall through to live render.
    """
    key = (intent_id or "").strip().lower()
    if allow_explicit:
        explicit_id = INTENT_TO_ASSET_ID_EXPLICIT.get(key)
        if explicit_id:
            return explicit_id
    return INTENT_TO_ASSET_ID.get(key, "")


# ── Planning ────────────────────────────────────────────────────────────────

def plan_library(
    max_tier: Tier = 1, *, allow_explicit: bool = False,
) -> List[AssetSpec]:
    """Filter the manifest to the requested tier ceiling.

    ``max_tier=1`` → idles + all expressions + default outfit + medium cam
    ``max_tier=2`` → adds poses + close-up / wide cam + extra outfits
    ``max_tier=3`` → full manifest including environments + formal outfit

    ``allow_explicit`` opts the persona into the NSFW rows
    (``explicit_only=True`` in the manifest). Fail-closed: when False,
    explicit rows are dropped at every tier. Callers must resolve this
    flag from the persona's ``safety.allow_explicit`` — the library
    never decides on its own.
    """
    t = max(1, min(int(max_tier or 1), 3))
    out: List[AssetSpec] = []
    for spec in ASSET_MANIFEST:
        if spec.tier > t:
            continue
        if spec.explicit_only and not allow_explicit:
            continue
        out.append(spec)
    return out


def pending_specs(
    *, max_tier: Tier,
    already_built: Dict[str, Any] | None = None,
    allow_explicit: bool = False,
) -> List[AssetSpec]:
    """Subtract the already-built asset ids from the planned set.

    ``already_built`` is the dict stored at
    ``persona_appearance.asset_library`` — keys are asset ids.
    ``allow_explicit`` gates the NSFW rows the same way
    ``plan_library`` does.
    """
    built = set((already_built or {}).keys())
    return [
        spec for spec in plan_library(max_tier, allow_explicit=allow_explicit)
        if spec.asset_id not in built
    ]


# ── Storage helpers ─────────────────────────────────────────────────────────
#
# The library lives at ``project.persona_appearance.asset_library`` because
# ``projects.update_project`` already deep-merges persona_appearance. That
# keeps this module additive — no new schema to register, no migrations, and
# an older server will ignore the field gracefully.

def load_library(persona_project_id: str) -> Dict[str, Dict[str, Any]]:
    """Return the library dict for a persona project (``{}`` if none)."""
    try:
        from app import projects
    except Exception:
        return {}
    data = projects.get_project_by_id(persona_project_id) or {}
    if not isinstance(data, dict):
        return {}
    appearance = data.get("persona_appearance") if isinstance(data.get("persona_appearance"), dict) else {}
    library = appearance.get("asset_library") if isinstance(appearance.get("asset_library"), dict) else {}
    return dict(library)


def save_asset_record(
    persona_project_id: str, record: AssetRecord,
) -> bool:
    """Merge one AssetRecord into the persona's asset_library dict.

    Uses projects.update_project which deep-merges persona_appearance,
    so concurrent writes to other appearance fields (outfits / sets /
    selected_filename) can't step on the library.
    """
    try:
        from app import projects
    except Exception:
        return False

    existing = load_library(persona_project_id)
    existing[record.asset_id] = {
        "asset_id": record.asset_id,
        "asset_url": record.asset_url,
        "kind": record.kind,
        "tier": record.tier,
        "reaction_intent": record.reaction_intent,
        "registry_asset_id": record.registry_asset_id,
        "generated_at": record.generated_at,
        "source": record.source,
    }
    patched = projects.update_project(persona_project_id, {
        "persona_appearance": {"asset_library": existing},
    })
    return patched is not None


def resolve_asset_url_for_intent(
    persona_project_id: str,
    intent_id: str,
    *,
    allow_explicit: bool = False,
) -> str:
    """Fast-path lookup: intent → library asset url (``""`` if missing).

    When ``allow_explicit=True``, prefers the NSFW variant (if the
    library has it); falls back to the SFW variant; falls back to
    empty (→ live render). Never raises, never blocks — the whole
    point is instant feedback.

    Callers (e.g. the action endpoint) should treat an empty return as
    "fall through to live render".
    """
    library = load_library(persona_project_id)
    if not isinstance(library, dict) or not library:
        return ""

    # Try the explicit override first when the persona allows.
    if allow_explicit:
        explicit_id = INTENT_TO_ASSET_ID_EXPLICIT.get(
            (intent_id or "").strip().lower()
        )
        if explicit_id:
            row = library.get(explicit_id)
            if isinstance(row, dict):
                url = str(row.get("asset_url") or "")
                if url:
                    return url
            # Fall through to SFW if the NSFW row isn't built yet.

    sfw_id = INTENT_TO_ASSET_ID.get((intent_id or "").strip().lower())
    if not sfw_id:
        return ""
    row = library.get(sfw_id)
    if not isinstance(row, dict):
        return ""
    return str(row.get("asset_url") or "")


# ── Build pass ──────────────────────────────────────────────────────────────

# Operator kill-switch: set ``PERSONA_LIVE_LIBRARY_LOOKUP=false`` to
# force every action click back through the live-render path. Default
# is ON because the wizard's Phase 3 builds the library automatically
# now and the fast path is thoroughly tested — keeping the toggle off
# by default just means generated images sit unused on disk and the
# player ends up live-rendering things it has cached. Flip it OFF
# only as a safety valve when a library is suspected of being stale
# or corrupted.
_LIBRARY_LOOKUP_ENABLED_ENV = "PERSONA_LIVE_LIBRARY_LOOKUP"


def lookup_enabled() -> bool:
    """Global kill-switch for the runtime library-first lookup.

    Default ON — the wizard's Phase 3 pre-renders the library on
    every persona_live experience create, and the action endpoint
    serves cached images instantly when the player's intent has a
    matching row. Set ``PERSONA_LIVE_LIBRARY_LOOKUP=false`` to bypass
    the cache entirely (every click fires a fresh SDXL render — slow
    but useful when verifying renders pass-by-pass).

    Lookup misses always fall through to live render, so flipping
    the switch is reversible without losing any data.
    """
    return os.getenv(_LIBRARY_LOOKUP_ENABLED_ENV, "true").lower() != "false"


@dataclass(frozen=True)
class RenderResult:
    """Outcome of rendering one asset spec.

    Returned by the ``RenderFn`` callback the caller hands to
    ``build_library``. Carries both the registry id and the URL so
    we can persist both — the registry id powers the editor preview
    + Phase-4 scene-link path; the URL powers the runtime fast-path
    lookup. ``url=""`` is the failure sentinel (treat as no asset).
    """
    asset_id: str
    url: str


RenderFn = Callable[[AssetSpec], Awaitable[Optional["RenderResult"]]]
"""Callback signature: given an AssetSpec, submit a render, return a
``RenderResult`` (or empty / ``None`` on failure). For backwards
compatibility ``build_library`` also accepts callbacks that return
plain strings (treated as a URL with no registry id), but new code
should return RenderResult so the editor preview path keeps working.
Separating the callback from the planner keeps this module decoupled
from render_adapter, which keeps the tests fast (mock the callback,
assert the planner + storage
behaviour without spinning up ComfyUI)."""


@dataclass
class BuildStats:
    total: int = 0
    rendered: int = 0
    skipped: int = 0
    failed: int = 0
    failures: List[Dict[str, str]] = field(default_factory=list)


async def build_library(
    persona_project_id: str,
    *,
    render_fn: RenderFn,
    max_tier: Tier = 1,
    allow_explicit: bool = False,
    on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> BuildStats:
    """Render and persist every missing asset in the requested tier.

    ``allow_explicit`` gates whether the NSFW rows from the manifest
    are included — must be True AND the persona's safety profile must
    allow explicit content (the route enforces this upstream before
    calling us). Passing True on a persona whose profile forbids
    explicit content is a caller bug; fail-closed is the responsibility
    of the route layer.

    Idempotent: if the library already has a row for an asset_id, that
    row is left untouched. Per-asset failures are non-fatal — they're
    counted and logged, and the rest of the pass continues. Returns a
    ``BuildStats`` the caller can forward to the UI.
    """
    import time

    existing = load_library(persona_project_id)
    specs = pending_specs(
        max_tier=max_tier,
        already_built=existing,
        allow_explicit=allow_explicit,
    )

    stats = BuildStats(
        total=len(plan_library(max_tier, allow_explicit=allow_explicit)),
        skipped=len(existing),
    )
    if on_progress:
        on_progress("build_started", {
            "total": stats.total,
            "to_render": len(specs),
            "already_built": stats.skipped,
        })

    for idx, spec in enumerate(specs, start=1):
        if on_progress:
            on_progress("rendering_asset", {
                "index": idx, "total": len(specs),
                "asset_id": spec.asset_id, "kind": spec.kind,
            })

        try:
            rendered = await render_fn(spec)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "persona_library_render_error asset=%s: %s",
                spec.asset_id, str(exc)[:200],
            )
            stats.failed += 1
            stats.failures.append({
                "asset_id": spec.asset_id,
                "reason": f"{exc.__class__.__name__}: {str(exc)[:120]}",
            })
            if on_progress:
                on_progress("asset_failed", {
                    "asset_id": spec.asset_id,
                    "reason": stats.failures[-1]["reason"],
                })
            continue

        # Backwards-compat shim: callbacks may still return a bare URL
        # string. New callers return ``RenderResult`` so we can persist
        # both the registry asset_id and the URL.
        if isinstance(rendered, RenderResult):
            registry_asset_id = rendered.asset_id
            asset_url = rendered.url
        else:
            registry_asset_id = ""
            asset_url = str(rendered or "")

        if not asset_url:
            stats.failed += 1
            stats.failures.append({
                "asset_id": spec.asset_id,
                "reason": "render_returned_empty",
            })
            if on_progress:
                on_progress("asset_failed", {
                    "asset_id": spec.asset_id,
                    "reason": "render_returned_empty",
                })
            continue

        record = AssetRecord(
            asset_id=spec.asset_id,
            asset_url=asset_url,
            kind=spec.kind,
            tier=spec.tier,
            reaction_intent=spec.reaction_intent,
            registry_asset_id=registry_asset_id,
            generated_at=time.time(),
            source="library_build",
        )
        if save_asset_record(persona_project_id, record):
            stats.rendered += 1
            if on_progress:
                on_progress("asset_rendered", {
                    "asset_id": spec.asset_id,
                    "asset_url": asset_url,
                    "kind": spec.kind,
                })
        else:
            stats.failed += 1
            stats.failures.append({
                "asset_id": spec.asset_id,
                "reason": "save_failed",
            })
            if on_progress:
                on_progress("asset_failed", {
                    "asset_id": spec.asset_id,
                    "reason": "save_failed",
                })

    if on_progress:
        on_progress("build_done", {
            "rendered": stats.rendered,
            "skipped": stats.skipped,
            "failed": stats.failed,
        })
    return stats


__all__ = [
    "ASSET_MANIFEST",
    "AssetKind",
    "AssetRecord",
    "AssetSpec",
    "BuildStats",
    "INTENT_TO_ASSET_ID",
    "RenderFn",
    "Tier",
    "asset_id_for_intent",
    "build_library",
    "load_library",
    "lookup_enabled",
    "pending_specs",
    "plan_library",
    "resolve_asset_url_for_intent",
    "save_asset_record",
]
