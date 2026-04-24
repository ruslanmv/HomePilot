"""
Persona Live prompt-vocabulary builder.

Why this exists
---------------
Persona Live used to hand the LLM a one-paragraph system prompt with
no visual vocabulary and no way to vary a scene along outfit / pose /
environment / expression / emotional-level axes. Result: scenes
collapsed onto "slight smile, neutral pose, soft background" every
turn and the Mature (gated) tier was indistinguishable from the SFW
default because the prompt never carried tier-aware style tokens.

This module owns the vocabulary and the tier-aware composition:

* ``EXPRESSION_LADDER`` — expression tokens ordered low → high intensity
* ``POSE_LADDER``       — pose tokens ordered reserved → closer framing
* ``OUTFIT_LADDER``     — outfit tokens ordered modest → themed
* ``ENVIRONMENT_LIB``   — tagged environment fragments
* ``EMOTIONAL_LADDER``  — body-language modifiers tied to trust level
* ``TIER_STYLE_TAGS``   — quality / style tokens per NSFW tier

Public entry points:
* ``compose_system_prompt(tier, allow_explicit)`` — returns the LLM
  system prompt, widened when the experience is Mature (gated) + the
  persona's safety profile allows explicit content.
* ``compose_image_prompt(*, base_subject, axis, tier, emotional_level)``
  — builds a single render prompt string from a named axis + ladder
  positions, so the render adapter stops emitting bland one-liners.

Both are pure functions with zero I/O — trivial to unit-test.

Gating rules (mirrored in the safety_gate module):
* tier == "safe"       → only SFW ladders are used
* tier == "suggestive" → SFW ladders + mildly-flirty modifiers
* tier == "explicit"   → full ladders AND requires ``allow_explicit``
                         on the persona. If the persona forbids, we
                         fall back to "suggestive" automatically.

Nothing in this module emits hardcore/extreme tokens; the vocabulary
stays firmly in "fan-service / tasteful erotic art" territory so the
downstream workflow still renders on SDXL checkpoints that Civitai
classifies as mature-but-not-adult-hardcore. The safety gate upstream
is still responsible for region + consent checks.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Literal, Optional, Tuple


# ── Public type aliases ─────────────────────────────────────────────────────

NsfwTier = Literal["safe", "suggestive", "explicit"]
PromptAxis = Literal["expression", "pose", "outfit", "environment"]


# ── Ladders (index ~ "intensity"; callers clamp against tier) ───────────────

# Emotional levels 0..4 — the fraction of (trust, intensity) the LLM
# receives maps onto this ladder. "reserved" scenes never use
# "intimate" body language even at high trust if the tier is safe.
EMOTIONAL_LADDER: Tuple[str, ...] = (
    "reserved body language, measured eye contact, polite distance",
    "warm body language, softened smile, relaxed shoulders",
    "playful body language, teasing eye contact, slight lean forward",
    "affectionate body language, knowing smile, close framing",
    "intimate body language, held gaze, comfortable closeness",
)


# Expression ladder — caption-friendly fragments, ordered roughly
# neutral → charged. Each tier clamps how far down the ladder we go.
EXPRESSION_LADDER: Tuple[Tuple[str, NsfwTier], ...] = (
    ("neutral expression, soft eyes",                          "safe"),
    ("gentle smile, calm eyes",                                "safe"),
    ("slight smirk, confident gaze",                           "safe"),
    ("playful tease, half-smile, slight eyebrow raise",        "suggestive"),
    ("shy blush, lips parted, averted glance",                 "suggestive"),
    ("sultry gaze, lips slightly parted, relaxed mouth",       "suggestive"),
    ("heated gaze, flushed cheeks, lips parted",               "explicit"),
    ("breathless expression, half-lidded eyes, soft biting lip","explicit"),
)


POSE_LADDER: Tuple[Tuple[str, NsfwTier], ...] = (
    ("upright sitting pose, hands relaxed in lap",             "safe"),
    ("standing three-quarter view, weight on one hip",         "safe"),
    ("looking over shoulder, head tilted, shoulder line visible","safe"),
    ("leaning forward slightly, elbows on knees, engaged pose","suggestive"),
    ("lying on couch, propped on elbow, relaxed pose",         "suggestive"),
    ("stretching overhead, arched back, relaxed smile",        "suggestive"),
    ("reclining on bed, one knee raised, relaxed pose, tasteful framing","explicit"),
    ("closer intimate pose, partner-implied framing, tasteful crop","explicit"),
)


OUTFIT_LADDER: Tuple[Tuple[str, NsfwTier], ...] = (
    ("oversized hoodie and jeans, casual",                     "safe"),
    ("fitted t-shirt and leggings, athleisure",                "safe"),
    ("sundress, light cardigan, casual summer",                "safe"),
    ("workout set, sports bra and leggings, fitness",          "suggestive"),
    ("oversized button-up shirt over shorts, cozy sleepwear",  "suggestive"),
    ("evening dress, elegant, modest neckline",                "safe"),
    ("swimsuit, tasteful beach fashion",                       "suggestive"),
    ("themed cosplay-lite outfit, stylised and tasteful",      "suggestive"),
    ("lingerie-style outfit, tasteful boudoir framing",        "explicit"),
    ("silk robe loosely tied, tasteful boudoir framing",       "explicit"),
)


ENVIRONMENT_LIB: Dict[str, Tuple[str, NsfwTier]] = {
    "bedroom":      ("warm-lit bedroom, soft bedding, dim practical light",     "safe"),
    "livingroom":   ("cozy living room, warm lamp light, soft sofa",            "safe"),
    "kitchen":      ("bright kitchen, morning light, marble counters",          "safe"),
    "beach":        ("sunset beach, warm golden light, ocean waves",            "safe"),
    "cafe":         ("quiet cafe, window light, warm wood interior",            "safe"),
    "nightcity":    ("rooftop night city view, neon reflections, soft bokeh",   "safe"),
    "vacation":     ("tropical resort balcony, warm breeze, palm fronds",       "safe"),
    "bathroom":     ("steamy bathroom, tiled walls, warm light, tasteful framing","suggestive"),
    "boudoir":      ("boudoir set, soft window light, silk sheets, tasteful",   "explicit"),
}


# Tier-wide style modifiers appended to every rendered prompt. These
# are the knobs that actually move a build from "safe pastel" to
# "fan-service tasteful erotic art" without dipping into banned tokens.
TIER_STYLE_TAGS: Dict[NsfwTier, str] = {
    "safe": (
        "cinematic lighting, soft shadows, portrait composition, "
        "high detail, natural skin texture, tasteful"
    ),
    "suggestive": (
        "cinematic lighting, soft rim light, portrait composition, "
        "high detail, natural skin, flattering angle, flirty mood, "
        "fan service, tasteful"
    ),
    "explicit": (
        "cinematic lighting, soft rim light, dramatic contrast, "
        "portrait composition, high detail, natural skin, flattering "
        "angle, sensual mood, boudoir photography style, fan service, "
        "tasteful erotic art, artstation-grade, identity locked"
    ),
}


# Negative prompt tokens — always applied, appended with more when
# running at "safe" (we don't want the checkpoint to drift suggestive
# on its own at low tiers).
#
# Quality + minor-safety tokens are ALWAYS in the base negative — the
# system prompt soft-bans minor-suggestive content as an LLM-side rule,
# but the diffusion model needs these tokens to enforce at the model
# level too. Keeping them at every tier (including "safe") makes the
# floor fail-closed even if the LLM hands the renderer a bad prompt.
BASE_NEGATIVE = (
    "lowres, blurry, bad anatomy, extra limbs, deformed hands, "
    "deformed face, text, watermark, jpeg artifacts, oversaturated, "
    "child, kid, minor, underage, underage looking, teen, teenager, "
    "loli, shota, young, youthful body, school uniform, schoolgirl"
)
SAFE_NEGATIVE_EXTRA = "nsfw, nudity, explicit, sexual, lingerie"


# ── Tier resolver ───────────────────────────────────────────────────────────

def effective_tier(
    requested: NsfwTier,
    *,
    allow_explicit: bool,
) -> NsfwTier:
    """Clamp ``requested`` against the persona's safety profile.

    * "explicit" requires ``allow_explicit`` on the persona. If the
      persona forbids it, we downgrade to "suggestive" (the Mature
      tier still earns flirty modifiers, but stays clothed / tasteful).
    * "suggestive" and "safe" pass through unchanged.
    * Unknown strings fall through to "safe" for fail-closed semantics.
    """
    req = (requested or "safe").lower()
    if req not in ("safe", "suggestive", "explicit"):
        return "safe"
    if req == "explicit" and not allow_explicit:
        return "suggestive"
    return req  # type: ignore[return-value]


# ── System-prompt composition ───────────────────────────────────────────────

def compose_system_prompt(
    *,
    tier: NsfwTier,
    allow_explicit: bool,
    persona_archetype: str = "",
    persona_style_hint: str = "",
) -> str:
    """Build the Persona Live system prompt, tier-aware.

    Returns a single string sent as the ``system`` message to the LLM.
    The prompt is deliberately compact — Persona Live is already
    constrained to emit strict JSON (dialogue, scene_prompt, edit_hint,
    scene_change) and the schema lives outside this function.
    """
    eff = effective_tier(tier, allow_explicit=allow_explicit)

    base = (
        "You are a roleplay assistant for an interactive persona chat. "
        "Reply naturally in-character using concise conversational language. "
        "You must output strict JSON with keys: dialogue, scene_prompt, edit_hint, scene_change. "
        "dialogue is 1-3 short sentences. "
        "scene_prompt must keep identity continuity and mention the same subject. "
        "edit_hint must be one of: expression, pose, outfit, bg. "
        "scene_change must be one of apartment, beach, supermarket, rainstreet, or empty string."
    )

    style_clause = ""
    if persona_archetype or persona_style_hint:
        parts = [p for p in (persona_archetype, persona_style_hint) if p]
        style_clause = (
            f" Persona is {' '.join(parts).strip()}. "
            "Keep the character's voice consistent across turns."
        )

    tier_clause = {
        "safe": (
            " Keep visuals strictly safe-for-work. No nudity, no overtly "
            "sexual body language, no suggestive clothing. scene_prompt "
            "should be a short caption describing framing, outfit, "
            "environment, and expression; use the vocabulary: "
            "casual / hoodie / sundress / athleisure / bedroom / cafe / "
            "beach / neutral smile / gentle gaze."
        ),
        "suggestive": (
            " Visuals may be flirty and fan-service-leaning but stay "
            "clothed. scene_prompt should vary along outfit, pose, "
            "environment, and expression — rotate variety instead of "
            "re-using the same beat. Suggested vocabulary: "
            "fitted athleisure / oversized shirt / swimsuit / "
            "cosplay-lite / playful tease / shy blush / sultry gaze / "
            "leaning forward / stretching / looking over shoulder / "
            "rooftop night city / cafe / boudoir-lite. Keep framing "
            "tasteful — no explicit nudity, no banned tokens."
        ),
        "explicit": (
            " This persona is tagged Mature (gated) with explicit "
            "consent. Visuals may lean into boudoir / tasteful erotic "
            "art style. scene_prompt should rotate across outfit, pose, "
            "environment, and expression for engagement variety. "
            "Suggested vocabulary: lingerie / silk robe / tasteful "
            "boudoir framing / reclining pose / heated gaze / breathless "
            "expression / intimate bedroom / warm rim light. Stay in "
            "'fan-service tasteful erotic art' territory — do NOT emit "
            "hardcore, graphic-anatomy, minor-suggestive, or non-consensual "
            "language; the render gate will reject those and the turn "
            "will fall back."
        ),
    }[eff]

    progression_clause = (
        " Track emotional progression: early turns use reserved body "
        "language, mid turns add playful / teasing modifiers, high-trust "
        "turns add warm / intimate modifiers. The same pose should feel "
        "different at different trust levels — adjust body language and "
        "expression rather than repeating the exact caption."
    )

    intent_clause = (
        " The viewer's action_id is a PLAYER INTENT (say_playful, "
        "compliment, ask_about_her, stay_quiet, get_closer, ask_personal, "
        "change_view, step_back, suggest_outfit, change_location, "
        "lean_in, playful_dare). Treat it as what the player just SAID "
        "or DID, not as a command for the character. Your dialogue is "
        "the persona's REACTION (in-character voice, 1-3 sentences). "
        "Your scene_prompt and edit_hint describe the visible REACTION "
        "(blush after a compliment, smirk after a tease, closer pose "
        "after get_closer, outfit_change after suggest_outfit, etc). "
        "Never repeat the action label back at the viewer."
    )

    return base + style_clause + tier_clause + progression_clause + intent_clause


# ── Image-prompt composition ────────────────────────────────────────────────

def _pick_ladder_entry(
    ladder: Iterable[Tuple[str, NsfwTier]],
    *,
    tier: NsfwTier,
    index: int,
) -> str:
    """Return the ladder entry at ``index`` whose tier ≤ ``tier``.

    Rows tagged stricter than the active tier are skipped; the result
    is the first eligible row at or beyond ``index``. Falls back to
    the last eligible row if ``index`` overshoots the filtered list.
    """
    order: List[str] = []
    allowed = _tiers_at_or_below(tier)
    for text, row_tier in ladder:
        if row_tier in allowed:
            order.append(text)
    if not order:
        return ""
    idx = max(0, min(index, len(order) - 1))
    return order[idx]


def _tiers_at_or_below(tier: NsfwTier) -> Tuple[NsfwTier, ...]:
    if tier == "explicit":
        return ("safe", "suggestive", "explicit")
    if tier == "suggestive":
        return ("safe", "suggestive")
    return ("safe",)


def compose_image_prompt(
    *,
    base_subject: str,
    axis: PromptAxis,
    tier: NsfwTier,
    allow_explicit: bool = False,
    emotional_level: int = 1,
    ladder_index: Optional[int] = None,
    environment_key: Optional[str] = None,
    extra_fragments: Optional[List[str]] = None,
) -> str:
    """Compose a single image prompt from the ladders.

    ``axis`` selects which ladder's entry is highlighted (the other
    axes contribute a single token from their safe tier). This gives
    the caller one knob to vary per turn while still painting a full
    scene every render. ``ladder_index`` defaults to ``emotional_level``
    when omitted, so "higher trust → richer prompt" is automatic.

    Returns the concatenated prompt with tier style tags appended.
    """
    eff = effective_tier(tier, allow_explicit=allow_explicit)
    ei = max(0, min(int(emotional_level or 0), len(EMOTIONAL_LADDER) - 1))
    li = int(ladder_index if ladder_index is not None else emotional_level)

    # Non-focus axes still ride the emotional_level so high-trust scenes
    # don't strand the character in a casual-hoodie + neutral-pose default
    # while only the focus axis evolves. The factor (×2) keeps the focus
    # axis ahead — at level 4 / focus=outfit, outfit hits index 4 from
    # ladder_index but pose + expression land at index 4×2/3 ≈ 2-3, which
    # is "lying on couch" + "playful tease" in the ladders. That's the
    # fan-service density the user asked for: visible variety per turn.
    bg_idx = max(0, min(ei * 2, 8))

    expr = _pick_ladder_entry(EXPRESSION_LADDER, tier=eff, index=li if axis == "expression" else bg_idx)
    pose = _pick_ladder_entry(POSE_LADDER,       tier=eff, index=li if axis == "pose"       else bg_idx)
    outfit = _pick_ladder_entry(OUTFIT_LADDER,   tier=eff, index=li if axis == "outfit"     else bg_idx)

    env_entry = ""
    if environment_key and environment_key in ENVIRONMENT_LIB:
        env_text, env_tier = ENVIRONMENT_LIB[environment_key]
        if env_tier in _tiers_at_or_below(eff):
            env_entry = env_text

    emotional = EMOTIONAL_LADDER[ei]
    style_tail = TIER_STYLE_TAGS[eff]
    extras = ", ".join([s.strip() for s in (extra_fragments or []) if s and s.strip()])

    pieces = [
        base_subject.strip() or "persona portrait",
        outfit,
        pose,
        expr,
        emotional,
        env_entry,
        extras,
        style_tail,
    ]
    return ", ".join([p for p in pieces if p])


def negative_prompt_for(tier: NsfwTier, *, allow_explicit: bool) -> str:
    """Negative prompt token list, tightened at "safe" so the
    checkpoint doesn't drift suggestive on its own."""
    eff = effective_tier(tier, allow_explicit=allow_explicit)
    if eff == "safe":
        return f"{BASE_NEGATIVE}, {SAFE_NEGATIVE_EXTRA}"
    return BASE_NEGATIVE


# ── Progression library ─────────────────────────────────────────────────────
#
# Dense suggested-action library per emotional level. Used by
# _default_levels in persona_live.py and by the wizard to preview the
# unlock ladder. Kept here so the vocabulary lives in exactly one
# place.

PROGRESSION_LIBRARY: Dict[int, Dict[str, List[str]]] = {
    1: {
        "description": "Baseline — identity + familiarity. Neutral poses, clean backgrounds.",
        "expressions":  ["neutral", "gentle_smile", "soft_gaze"],
        "poses":        ["upright_sit", "three_quarter_stand"],
        "outfits":      ["casual_hoodie", "sundress", "fitted_tshirt"],
        "environments": ["livingroom", "cafe"],
    },
    2: {
        "description": "Early unlocks — expression variety + playful modifiers.",
        "expressions":  ["playful_tease", "smirk", "shy_blush"],
        "poses":        ["lean_forward", "over_shoulder"],
        "outfits":      ["athleisure", "sundress"],
        "environments": ["livingroom", "kitchen", "cafe"],
    },
    3: {
        "description": "Mid progression — dynamic poses, outfit variety.",
        "expressions":  ["smirk", "sultry_gaze"],
        "poses":        ["lying_couch_elbow", "stretching", "turn_around"],
        "outfits":      ["cozy_sleepwear", "swimsuit", "cosplay_lite"],
        "environments": ["bedroom", "beach", "vacation"],
    },
    4: {
        "description": "High progression — intimate framing, evening / boudoir environments.",
        "expressions":  ["sultry_gaze", "heated_gaze"],
        "poses":        ["lying_couch_elbow", "reclining", "closer_pose"],
        "outfits":      ["evening_dress", "silk_robe", "cosplay_lite"],
        "environments": ["bedroom", "nightcity", "boudoir"],
    },
    5: {
        "description": "Mature gated — boudoir-style, tasteful erotic art. Requires allow_explicit.",
        "expressions":  ["heated_gaze", "breathless"],
        "poses":        ["reclining", "closer_intimate"],
        "outfits":      ["lingerie_tasteful", "silk_robe"],
        "environments": ["bedroom", "boudoir"],
    },
}


__all__ = [
    "BASE_NEGATIVE",
    "EMOTIONAL_LADDER",
    "ENVIRONMENT_LIB",
    "EXPRESSION_LADDER",
    "NsfwTier",
    "OUTFIT_LADDER",
    "POSE_LADDER",
    "PROGRESSION_LIBRARY",
    "PromptAxis",
    "SAFE_NEGATIVE_EXTRA",
    "TIER_STYLE_TAGS",
    "compose_image_prompt",
    "compose_system_prompt",
    "effective_tier",
    "negative_prompt_for",
]
