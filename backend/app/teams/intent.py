# backend/app/teams/intent.py
"""
SpeakIntent — deterministic scoring for meeting participation.

Computes whether a persona should speak based on:
  - Name mention in human message
  - Question / decision context
  - Role-relevance triggers (keyword matching)
  - Authority boost (role expertise matches intent type)
  - Cooldown penalties (recently spoke)
  - Redundancy penalties (topic already covered)
  - Dominance suppression (persona spoke too much recently)

This module runs without any LLM call — pure rules.
Any persona that joins a meeting automatically gets this behavior.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SpeakIntent:
    """Result of intent computation for one persona."""

    persona_id: str
    wants_to_speak: bool
    confidence: float  # 0.0 .. 1.0
    reason: str
    intent_type: str  # "idea" | "risk" | "clarify" | "summary" | "action"
    urgency: float  # 0.0 .. 1.0
    topic_tags: List[str] = field(default_factory=list)


# ── Role trigger keywords ─────────────────────────────────────────────────

ROLE_TRIGGERS: Dict[str, List[str]] = {
    "secretary": [
        "agenda", "minutes", "action", "deadline", "schedule",
        "follow up", "recap", "meeting", "notes",
    ],
    "analyst": [
        "metric", "kpi", "numbers", "data", "conversion",
        "funnel", "growth", "cohort", "analysis", "report",
    ],
    "engineer": [
        "deploy", "bug", "api", "integration", "latency",
        "infra", "security", "code", "technical", "backend",
    ],
    "creative": [
        "design", "brand", "copy", "story", "visual",
        "campaign", "creative", "mockup", "prototype",
    ],
    "research": [
        "evidence", "study", "source", "hypothesis",
        "experiment", "research", "paper", "survey",
    ],
    "product": [
        "roadmap", "scope", "user", "feature", "requirements",
        "sprint", "backlog", "priority", "milestone",
    ],
    "legal": [
        "compliance", "contract", "regulation", "liability",
        "privacy", "gdpr", "terms", "legal",
    ],
    "finance": [
        "budget", "cost", "revenue", "forecast", "margin",
        "expense", "roi", "investment", "pricing",
    ],
    "support": [
        "ticket", "customer", "feedback", "churn", "retention",
        "satisfaction", "support", "escalation",
    ],
}


# ── Helpers ────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _last_messages(room: Dict[str, Any], k: int = 6) -> List[Dict[str, Any]]:
    msgs = room.get("messages") or []
    return msgs[-k:]


def _extract_keywords(text: str) -> List[str]:
    """Simple keyword extraction (stable, no external deps)."""
    words = re.findall(r"[a-zA-Z]{4,}", _normalize(text))
    seen: set = set()
    out: List[str] = []
    for w in words:
        if w not in seen:
            out.append(w)
            seen.add(w)
    return out[:12]


def _cooldown_penalty(room: Dict[str, Any], persona_id: str) -> float:
    """Penalize if persona spoke recently."""
    cd = (room.get("cooldowns") or {}).get(persona_id, 0)
    return 0.35 if cd and cd > 0 else 0.0


def _redundancy_penalty(
    room: Dict[str, Any], persona_id: str, tags: List[str],
) -> float:
    """Penalize if recent assistant messages already cover same topics."""
    recent = _last_messages(room, k=5)
    recent_text = " ".join(
        _normalize(m.get("content", ""))
        for m in recent
        if m.get("role") == "assistant"
    )
    overlap = sum(1 for t in tags if t in recent_text)
    if not tags:
        return 0.0
    ratio = overlap / max(1, len(tags))
    return min(0.25, 0.25 * ratio)


def _dominance_penalty(
    room: Dict[str, Any], persona_id: str, lookback: int = 10,
) -> float:
    """Penalize personas who dominated recent conversation (>40% of messages).

    If a persona has spoken more than 40% of the last `lookback` assistant
    messages, add +0.15 to the speak threshold — they must have stronger
    relevance to intervene again.
    """
    msgs = (room.get("messages") or [])[-lookback:]
    assistant_msgs = [m for m in msgs if m.get("role") == "assistant"]
    if len(assistant_msgs) < 3:
        return 0.0
    persona_count = sum(1 for m in assistant_msgs if m.get("sender_id") == persona_id)
    ratio = persona_count / len(assistant_msgs)
    if ratio > 0.4:
        return 0.15
    return 0.0


# ── Authority: role-expertise alignment with intent type ──────────────────

AUTHORITY_MAP: Dict[str, List[str]] = {
    "risk": ["legal", "engineer", "analyst"],
    "action": ["product", "secretary"],
    "clarify": ["research", "analyst"],
    "summary": ["secretary", "analyst"],
    "idea": ["creative", "product", "research"],
}


def _authority_boost(role_tags: List[str], intent_type: str) -> float:
    """Boost confidence for personas whose role matches the intent type.

    E.g. a legal persona gets +0.10 when the topic is risk/compliance,
    an engineer gets +0.10 for technical risks, etc.
    """
    matching_roles = AUTHORITY_MAP.get(intent_type, [])
    if any(rt in matching_roles for rt in (role_tags or [])):
        return 0.10
    return 0.0


# ── Main intent computation ────────────────────────────────────────────────


def compute_intent(
    room: Dict[str, Any],
    persona_id: str,
    display_name: str,
    role_tags: List[str],
    last_human_message: str,
) -> SpeakIntent:
    """
    Deterministic intent computation (no LLM call).

    Returns a SpeakIntent that the orchestrator uses to decide who speaks.
    Works for any persona with zero custom configuration.
    """
    text = _normalize(last_human_message)
    score = 0.15  # baseline "present in meeting"
    reason_parts: List[str] = []

    # ── Name mention in human message ─────────────────────────────
    name_lower = _normalize(display_name)
    if name_lower and name_lower in text:
        score += 0.35
        reason_parts.append("mentioned by name")

    # ── Name mention in recent persona messages (inter-persona) ───
    # If another persona just spoke and mentioned this persona by name,
    # this persona should want to respond.
    recent_persona_msgs = [
        m for m in _last_messages(room, k=4)
        if m.get("role") == "assistant" and m.get("sender_id") != persona_id
    ]
    for m in recent_persona_msgs:
        m_text = _normalize(m.get("content", ""))
        if name_lower and name_lower in m_text:
            score += 0.30
            sender = m.get("sender_name", "someone")
            reason_parts.append(f"addressed by {sender}")
            break  # one boost is enough

    # ── Question or decision request ──────────────────────────────
    question_words = ["should we", "what do", "decide", "choose", "priority", "opinion", "think"]
    if "?" in last_human_message or any(w in text for w in question_words):
        score += 0.15
        reason_parts.append("question/decision")

    # ── Brainstorming triggers ────────────────────────────────────
    brainstorm_words = ["brainstorm", "ideas", "creative", "options", "suggest", "propose", "explore"]
    if any(w in text for w in brainstorm_words):
        score += 0.15
        reason_parts.append("brainstorm prompt")

    # ── Role-relevance triggers ───────────────────────────────────
    role_hit = 0.0
    for rt in role_tags or []:
        for kw in ROLE_TRIGGERS.get(rt, []):
            if kw in text:
                role_hit = max(role_hit, 0.30)
    if role_hit > 0:
        score += role_hit
        reason_parts.append("role relevance")

    # ── Topic tags ────────────────────────────────────────────────
    tags = _extract_keywords(last_human_message)

    # ── Intent type classification (computed early for authority boost) ─
    intent_type = "idea"
    if any(w in text for w in ["risk", "blocker", "problem", "issue", "concern"]):
        intent_type = "risk"
    elif "?" in last_human_message:
        intent_type = "clarify"
    elif any(w in text for w in ["summary", "recap", "wrap"]):
        intent_type = "summary"
    elif any(w in text for w in ["action", "next steps", "assign", "task"]):
        intent_type = "action"

    # ── Authority boost (role matches intent type) ─────────────────
    auth = _authority_boost(role_tags, intent_type)
    if auth > 0:
        score += auth
        reason_parts.append("authority match")

    # ── Penalties ─────────────────────────────────────────────────
    score -= _cooldown_penalty(room, persona_id)
    score -= _redundancy_penalty(room, persona_id, tags)

    # ── Dominance suppression ─────────────────────────────────────
    policy = room.get("policy") or {}
    lookback = int(policy.get("dominance_lookback", 10))
    dom = _dominance_penalty(room, persona_id, lookback)
    if dom > 0:
        score -= dom
        reason_parts.append("dominance penalty")

    # ── Clamp ─────────────────────────────────────────────────────
    score = max(0.0, min(1.0, score))

    # ── Threshold check ───────────────────────────────────────────
    threshold = float(policy.get("speak_threshold", 0.45))
    wants = score >= threshold

    # ── Urgency ───────────────────────────────────────────────────
    urgency = 0.4
    if intent_type == "risk":
        urgency = 0.8
    if any(w in text for w in ["urgent", "today", "asap", "critical", "immediately"]):
        urgency = 0.9

    return SpeakIntent(
        persona_id=persona_id,
        wants_to_speak=wants,
        confidence=round(score, 3),
        reason=", ".join(reason_parts) if reason_parts else "listening",
        intent_type=intent_type,
        urgency=round(urgency, 2),
        topic_tags=tags,
    )


# ── Cooldown management ───────────────────────────────────────────────────


def tick_cooldowns(room: Dict[str, Any]) -> None:
    """Decrement all cooldowns by 1 (called at the start of each step)."""
    cds = room.setdefault("cooldowns", {})
    for k in list(cds.keys()):
        v = cds[k]
        if isinstance(v, (int, float)) and v > 0:
            cds[k] = max(0, v - 1)


def set_cooldown(room: Dict[str, Any], persona_id: str, turns: int) -> None:
    """Set cooldown for a persona after they spoke."""
    cds = room.setdefault("cooldowns", {})
    cds[persona_id] = max(turns, int(cds.get(persona_id, 0)))
