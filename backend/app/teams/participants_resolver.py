# backend/app/teams/participants_resolver.py
"""
Participant resolver — makes ANY persona meeting-capable automatically.

For each persona project, constructs a normalized participant dict:
  - persona_id, display_name, role_tags (inferred if missing)

The meeting orchestrator works with these dicts so that personas
remain unchanged — the meeting layer adds participation behavior.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .. import projects


# ── Role tag inference ─────────────────────────────────────────────────────

_ROLE_PATTERNS: Dict[str, List[str]] = {
    "secretary": ["secretary", "assistant", "calendar", "minutes", "scheduler", "admin"],
    "analyst": ["data", "analyst", "metrics", "kpi", "analytics", "statistician"],
    "engineer": ["engineer", "devops", "api", "backend", "infra", "developer", "software"],
    "creative": ["creative", "design", "brand", "copy", "artist", "writer", "ux"],
    "research": ["research", "paper", "study", "evidence", "scientist", "academic"],
    "product": ["product", "roadmap", "requirements", "pm", "manager", "owner"],
    "legal": ["legal", "compliance", "lawyer", "attorney", "regulation"],
    "finance": ["finance", "budget", "accounting", "cfo", "treasurer"],
    "support": ["support", "customer", "helpdesk", "service", "success"],
}


def infer_role_tags(project: Dict[str, Any]) -> List[str]:
    """
    Infer role tags from persona name + description + system prompt.
    Returns at most 2 tags.  Stable and additive — no LLM call.
    """
    persona_agent = project.get("persona_agent") or {}
    text = " ".join([
        str(project.get("name", "")),
        str(project.get("description", "")),
        str(persona_agent.get("system_prompt", "")),
        str(project.get("instructions", "")),
        str(persona_agent.get("persona_class", "")),
    ]).lower()

    tags: List[str] = []
    for role, keywords in _ROLE_PATTERNS.items():
        if any(kw in text for kw in keywords):
            tags.append(role)
            if len(tags) >= 2:
                break
    return tags


# ── Resolver ───────────────────────────────────────────────────────────────


def resolve_participants(participant_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Convert a list of project IDs into normalized participant dicts.

    Each dict has:
      - persona_id: str
      - display_name: str
      - role_tags: List[str]

    If a project is missing, it is silently skipped.
    """
    out: List[Dict[str, Any]] = []
    for pid in participant_ids:
        proj = projects.get_project_by_id(pid)
        if not proj:
            continue
        out.append({
            "persona_id": pid,
            "display_name": proj.get("name", pid),
            "role_tags": proj.get("role_tags") or infer_role_tags(proj),
        })
    return out
