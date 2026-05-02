"""
Individual QA checks over a manifest dict.

Each check is a small pure function that returns a list of
``QAIssue`` dicts. Adding a new check = appending a callable to
``all_checks()``. No global state.

Checks defined here:

  C1 graph_has_entry_node     There must be at least one scene/node we can start from.
  C2 graph_no_dangling_edges  Every edge points at a real node.
  C3 nodes_have_narration     Non-ending nodes ought to have narration text.
  C4 every_action_reachable   Every action's required_level must be
                              attainable given the experience's xp_award totals.
  C5 every_node_has_outbound  Non-ending nodes have ≥1 outbound edge (dead-end check).
  C6 personalization_rules_valid  Each rule's condition + action keys
                                  pass validate_rule.
  C7 mature_content_consent   experience_mode='mature_gated' must require consent.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from ..personalize.rules import validate_rule


QAIssue = Dict[str, Any]
QACheck = Callable[[Dict[str, Any]], List[QAIssue]]


def _issue(code: str, severity: str, detail: str, **extra: Any) -> QAIssue:
    out: QAIssue = {"code": code, "severity": severity, "detail": detail}
    if extra:
        out.update(extra)
    return out


# ─────────────────────────────────────────────────────────────────
# Individual checks
# ─────────────────────────────────────────────────────────────────

def graph_has_entry_node(manifest: Dict[str, Any]) -> List[QAIssue]:
    nodes = manifest.get("nodes") or []
    if not nodes:
        return [_issue("no_nodes", "error", "experience has no nodes")]
    scenes = [n for n in nodes if n.get("kind") == "scene"]
    if not scenes:
        return [_issue("no_entry_scene", "error", "no node of kind='scene' to use as entry")]
    return []


def graph_no_dangling_edges(manifest: Dict[str, Any]) -> List[QAIssue]:
    nodes = {n["id"] for n in (manifest.get("nodes") or [])}
    out: List[QAIssue] = []
    for e in manifest.get("edges") or []:
        if e.get("from_node_id") not in nodes:
            out.append(_issue(
                "edge_dangling_from", "error",
                f"edge {e.get('id')} references missing from_node {e.get('from_node_id')}",
                edge_id=e.get("id"),
            ))
        if e.get("to_node_id") not in nodes:
            out.append(_issue(
                "edge_dangling_to", "error",
                f"edge {e.get('id')} references missing to_node {e.get('to_node_id')}",
                edge_id=e.get("id"),
            ))
    return out


def nodes_have_narration(manifest: Dict[str, Any]) -> List[QAIssue]:
    out: List[QAIssue] = []
    for n in manifest.get("nodes") or []:
        if n.get("kind") == "ending":
            continue
        if not (n.get("narration") or "").strip():
            out.append(_issue(
                "narration_empty", "warning",
                f"node {n.get('id')} has no narration",
                node_id=n.get("id"),
            ))
    return out


def every_action_reachable(manifest: Dict[str, Any]) -> List[QAIssue]:
    """Sum of xp_award across all actions must be ≥ each action's
    required_level when the scheme is xp_level. Otherwise the
    catalog has actions a viewer can never unlock through normal
    play (a soft warning, not an error — sometimes the level comes
    from external progression)."""
    actions = manifest.get("actions") or []
    total_xp = sum(int(a.get("xp_award") or 0) for a in actions if a.get("required_scheme") == "xp_level")
    out: List[QAIssue] = []
    for a in actions:
        if a.get("required_scheme") != "xp_level":
            continue
        # required_level is a coarse proxy — level 5 needs ~_xp_threshold(5) XP.
        # Use a simple linear approximation 15 * (level-1)^1.5 ≈ 15 * (level-1) * 1.5
        lvl = int(a.get("required_level") or 1)
        threshold = max(0, int(15 * (lvl - 1) ** 1.5))
        if threshold > total_xp:
            out.append(_issue(
                "action_unreachable", "warning",
                f"action {a.get('id')} requires level {lvl} (~{threshold} XP) "
                f"but max attainable in this experience is ~{total_xp} XP",
                action_id=a.get("id"),
            ))
    return out


def every_node_has_outbound(manifest: Dict[str, Any]) -> List[QAIssue]:
    out: List[QAIssue] = []
    edges = manifest.get("edges") or []
    by_from = {}
    for e in edges:
        by_from.setdefault(e.get("from_node_id"), []).append(e)
    for n in manifest.get("nodes") or []:
        if n.get("kind") == "ending":
            continue
        if not by_from.get(n.get("id")):
            out.append(_issue(
                "node_dead_end", "warning",
                f"non-ending node {n.get('id')} has no outbound edges",
                node_id=n.get("id"),
            ))
    return out


def personalization_rules_valid(manifest: Dict[str, Any]) -> List[QAIssue]:
    out: List[QAIssue] = []
    for r in manifest.get("rules") or []:
        problems = validate_rule(r.get("condition") or {}, r.get("action") or {})
        for p in problems:
            out.append(_issue(
                "rule_invalid", "error",
                f"rule {r.get('id')} ({r.get('name')}): {p}",
                rule_id=r.get("id"),
            ))
    return out


def mature_content_consent(manifest: Dict[str, Any]) -> List[QAIssue]:
    exp = manifest.get("experience") or {}
    if exp.get("experience_mode") != "mature_gated":
        return []
    profile_id = (exp.get("policy_profile_id") or "").lower()
    if "mature" not in profile_id:
        return [_issue(
            "mature_profile_mismatch", "error",
            "mature_gated mode must use a mature-* policy profile",
            profile_id=profile_id,
        )]
    return []


def all_checks() -> List[QACheck]:
    """Return the registry of checks in execution order."""
    return [
        graph_has_entry_node,
        graph_no_dangling_edges,
        nodes_have_narration,
        every_action_reachable,
        every_node_has_outbound,
        personalization_rules_valid,
        mature_content_consent,
    ]
