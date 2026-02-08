"""Tool scope and allow-list enforcement for the runtime.

This module defines:
  - ToolScope: encodes what an agent is allowed to use
  - allowed_tool_ids(): computes the allowed set from catalog + scope
  - pick_tool_for_capability(): resolves a capability ID to a tool ID

Additive: does not modify the existing policy.py (which handles
capability-level allowlists and profile defaults).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .catalog_types import AgenticCatalog


@dataclass(frozen=True)
class ToolScope:
    """Encodes what tools an agent is permitted to invoke.

    tool_source values:
      - None / ""   => fallback (legacy behavior, no enforcement)
      - "all"       => any enabled tool
      - "none"      => no tools allowed
      - "server:<id>" => only tools in that virtual server
    """
    tool_source: Optional[str] = None


def allowed_tool_ids(
    catalog: AgenticCatalog,
    scope: ToolScope,
) -> Tuple[Set[str], str]:
    """Return (allowed_tool_ids, mode).

    mode can be:
      - "fallback"  (no tool_source provided; keep legacy behavior)
      - "none"
      - "all"
      - "server"
    """
    if not scope.tool_source:
        return set(), "fallback"

    src = scope.tool_source.strip().lower()
    if src == "none":
        return set(), "none"

    enabled_tool_ids = {
        t.id for t in catalog.tools
        if (t.enabled is None or t.enabled is True)
    }

    if src == "all":
        return enabled_tool_ids, "all"

    if src.startswith("server:"):
        sid = src.split("server:", 1)[1].strip()
        server = next((s for s in catalog.servers if s.id == sid), None)
        if not server:
            return set(), "server"
        allow = {tid for tid in server.tool_ids if tid in enabled_tool_ids}
        return allow, "server"

    # Unknown tool_source -> fallback (safe default)
    return set(), "fallback"


def pick_tool_for_capability(
    capability_id: str,
    catalog: AgenticCatalog,
    allow: Set[str],
) -> Optional[str]:
    """Resolve capability -> tool_id.

    Strategy:
      1. Explicit mapping from catalog.capability_sources (best)
      2. Heuristic: first allowed tool whose name contains cap tokens
    """
    cap = (capability_id or "").strip()
    if not cap:
        return None

    # 1) Explicit mapping
    mapped = catalog.capability_sources.get(cap) or []
    for tid in mapped:
        if tid in allow:
            return tid

    # 2) Heuristic fallback
    cap_tokens = [x for x in cap.lower().replace("-", "_").split("_") if x]
    for t in catalog.tools:
        if t.id not in allow:
            continue
        name = t.name.lower()
        if all(tok in name for tok in cap_tokens[:2]):
            return t.id

    return None
