"""
Build a self-contained manifest dict for an experience.

Manifest shape (versioned via ``manifest_version``):

  {
    "manifest_version": 1,
    "experience": {... pydantic dump of Experience ...},
    "nodes": [ {... node dump ...}, ... ],
    "edges": [ {... edge dump ...}, ... ],
    "actions": [ {... action dump ...}, ... ],
    "rules": [ {... rule dump ...}, ... ],
    "stats": { "node_count": N, "edge_count": M, "action_count": K, ... },
  }

Everything is pydantic-serializable so the manifest survives a
JSON round-trip without losing fields. Assets (images, voice
clips) are referenced by id — the publishing channel is
responsible for resolving those ids to URLs in its own way (CDN,
S3, signed URL, …).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .. import repo
from ..models import Experience


_MANIFEST_VERSION = 1


def build_manifest(experience: Experience) -> Dict[str, Any]:
    """Assemble a full snapshot dict from the live DB rows."""
    nodes = [n.model_dump() for n in repo.list_nodes(experience.id)]
    edges = [e.model_dump() for e in repo.list_edges(experience.id)]
    actions = [a.model_dump() for a in repo.list_actions(experience.id)]
    rules = [r.model_dump() for r in repo.list_rules(experience.id)]
    return {
        "manifest_version": _MANIFEST_VERSION,
        "experience": experience.model_dump(),
        "nodes": nodes,
        "edges": edges,
        "actions": actions,
        "rules": rules,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "action_count": len(actions),
            "rule_count": len(rules),
        },
    }
