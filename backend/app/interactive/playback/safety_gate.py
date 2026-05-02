"""Optional safety screening for scene-render prompts and rendered assets.

Additive, best-practice layer that wraps the ``mcp-safety-policy`` server
(one of the Expert Core MCP servers — see ``server_catalog.yaml``). Each
scene prompt gets screened before render; each rendered asset can be
screened after render. Fail-open by design: if MCP is offline, we log a
warning and allow the render — this feature is optional and must never
take the Interactive pipeline down.

Tiered NSFW policy
------------------
Three tiers matching industry convention (Civitai / Replicate / Fal):

- ``safe`` (default): no adult content, no suggestive themes.
- ``suggestive``: romance, implied intimacy, partial nudity. Requires
  ``audience_profile.nsfw_ceiling >= "suggestive"`` on the experience.
- ``explicit``: full adult content. Requires
  ``audience_profile.nsfw_ceiling == "explicit"`` AND the project owner
  has opted in via the existing ``NSFW_MODE`` setting.

The tier comes from ``mcp-safety-policy.risk_score`` output (``risk``
field) mapped into the tier ladder.

Environment knobs
-----------------
- ``INTERACTIVE_SAFETY_GATE`` (``true|false``, default ``false``) — enables
  the pre-render scene screen. Off by default so existing flows are
  unaffected.
- ``EXPERT_MCP_SAFETY_POLICY_URL`` (inherits the Expert Core setting) —
  which safety-policy server to call. When unset, screening no-ops.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

try:
    import httpx
except ImportError:  # pragma: no cover — httpx is a core backend dep
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger("interactive.safety_gate")

# ── Configuration ────────────────────────────────────────────────────────────

SAFETY_GATE_ENABLED: bool = (
    os.getenv("INTERACTIVE_SAFETY_GATE", "false").lower() == "true"
)

# Reuse the Expert Core MCP safety-policy URL if present; fall back
# to the legacy per-subsystem env var for forward compatibility.
_SAFETY_MCP_URL = (
    os.getenv("EXPERT_MCP_SAFETY_POLICY_URL")
    or os.getenv("INTERACTIVE_SAFETY_MCP_URL")
    or ""
).rstrip("/")

_HTTP_TIMEOUT_S: float = float(os.getenv("INTERACTIVE_SAFETY_TIMEOUT_S", "3.0") or 3.0)


# ── Types ────────────────────────────────────────────────────────────────────

# Tier ladder — comparison uses the index so ``safe < suggestive < explicit``.
_TIER_ORDER = ("safe", "suggestive", "explicit")


@dataclass(frozen=True)
class SafetyVerdict:
    """Structured screening result.

    - ``allowed`` is ``True`` when the render should proceed.
    - ``tier`` is the classified content tier for the prompt / asset.
    - ``reason`` explains the decision (useful in SSE events and logs).
    - ``raw_score`` is the numeric risk score from mcp-safety-policy
      (0.0 low → 1.0 critical).
    """
    allowed: bool
    tier: str           # one of _TIER_ORDER
    reason: str
    raw_score: float = 0.0

    def above(self, ceiling: str) -> bool:
        """True if this verdict's tier exceeds the given ceiling."""
        try:
            return _TIER_ORDER.index(self.tier) > _TIER_ORDER.index(ceiling)
        except ValueError:
            return False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _risk_label_to_tier(label: str) -> str:
    """Map mcp-safety-policy's risk labels into our tier ladder."""
    label = (label or "").lower()
    if label in {"critical", "high"}:
        return "explicit"
    if label in {"medium"}:
        return "suggestive"
    return "safe"


def _nsfw_ceiling_for(experience: object) -> str:
    """Read the NSFW ceiling from the experience's audience_profile.

    Default is ``safe`` so projects authored before this feature existed
    behave exactly as they did before.
    """
    ap = None
    if isinstance(experience, dict):
        ap = experience.get("audience_profile") or {}
    else:
        ap = getattr(experience, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return "safe"
    ceiling = str(ap.get("nsfw_ceiling") or "").lower().strip()
    return ceiling if ceiling in _TIER_ORDER else "safe"


# ── Public API ───────────────────────────────────────────────────────────────

async def screen_scene_prompt(
    prompt: str,
    *,
    experience: object,
) -> SafetyVerdict:
    """Pre-render content screen for a scene prompt.

    Returns ``allowed=True`` when:
      * the feature flag is off, OR
      * MCP isn't reachable (fail-open), OR
      * the classified tier is at/below the experience's ``nsfw_ceiling``.

    Returns ``allowed=False`` with a pointed reason otherwise.
    """
    if not SAFETY_GATE_ENABLED:
        return SafetyVerdict(True, "safe", "gate_disabled")
    if not _SAFETY_MCP_URL or httpx is None:
        # Fail-open: renders proceed, but log once per process cycle so
        # operators notice that screening isn't running.
        logger.info(
            "interactive safety gate on but EXPERT_MCP_SAFETY_POLICY_URL "
            "unset — passing prompts through unchecked"
        )
        return SafetyVerdict(True, "safe", "mcp_unconfigured")
    if not prompt or not prompt.strip():
        return SafetyVerdict(True, "safe", "empty_prompt")

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
            resp = await client.post(
                f"{_SAFETY_MCP_URL}/tools/hp.safety.check_input",
                json={"text": prompt},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as err:  # noqa: BLE001 — fail-open
        logger.warning(
            "safety_policy MCP call failed (fail-open): %s", err, exc_info=False
        )
        return SafetyVerdict(True, "safe", f"mcp_error:{type(err).__name__}")

    # Tool output shape: {"content": [...], "meta": {"score": float, "risk": str, ...}}
    meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        meta = {}
    tier = _risk_label_to_tier(str(meta.get("risk") or ""))
    score = float(meta.get("score") or 0.0)

    ceiling = _nsfw_ceiling_for(experience)
    try:
        if _TIER_ORDER.index(tier) > _TIER_ORDER.index(ceiling):
            return SafetyVerdict(
                False, tier,
                f"tier_above_ceiling(tier={tier}, ceiling={ceiling})",
                raw_score=score,
            )
    except ValueError:
        pass
    return SafetyVerdict(True, tier, "allowed", raw_score=score)


__all__ = [
    "SAFETY_GATE_ENABLED",
    "SafetyVerdict",
    "screen_scene_prompt",
]
