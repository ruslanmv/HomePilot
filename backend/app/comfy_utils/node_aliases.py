"""
Node alias maps for ComfyUI workflow portability.

ComfyUI custom node ecosystems are not standardized; different InstantID and
face-restore packs register different class names.  These alias maps let us
keep one "canonical" workflow while adapting at runtime to the installed node
pack.

Non-destructive:
  - If the canonical name already exists in ComfyUI, nothing changes.
  - If not, we try known alternatives.
  - The returned dict records every replacement made (for logging/debugging).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple


# ---------------------------------------------------------------------------
# Alias tables — canonical name → ordered list of known alternatives
# ---------------------------------------------------------------------------

NODE_ALIAS_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    # --- InstantID / InsightFace face analysis ---
    "InstantIDFaceAnalysis": (
        "InstantIDFaceAnalysis",
        "InstantIDFaceEmbedder",
        "InstantIDFaceEmbed",
        "InsightFaceAnalyzer",
        "InsightFaceFaceAnalysis",
        "FaceAnalysis",
    ),
    # --- InsightFace loader (some packs use this instead) ---
    "InsightFaceLoader": (
        "InsightFaceLoader",
        "InstantIDInsightFaceLoader",
        "FaceAnalysisLoader",
        "InsightFaceModelLoader",
    ),
    # --- InstantID model loader ---
    "InstantIDModelLoader": (
        "InstantIDModelLoader",
        "InstantIDLoader",
        "InstantIDIPAdapterLoader",
    ),
    # --- InstantID apply ---
    "ApplyInstantID": (
        "ApplyInstantID",
        "InstantIDApply",
        "InstantIDConditioning",
    ),
    # --- InstantID apply SDXL variant ---
    "ApplyInstantIDAdvanced": (
        "ApplyInstantIDAdvanced",
        "InstantIDApplySDXL",
        "ApplyInstantIDSDXL",
        "InstantIDConditioningSDXL",
    ),
    # --- GFPGAN / Face restore ---
    "FaceRestoreModelLoader": (
        "FaceRestoreModelLoader",
        "GFPGANLoader",
        "GFPGANModelLoader",
        "FaceRestorationModelLoader",
    ),
    "FaceRestoreWithModel": (
        "FaceRestoreWithModel",
        "GFPGAN",
        "ApplyGFPGAN",
        "FaceRestore",
    ),
}


def remap_workflow_nodes(
    workflow: Dict[str, Any],
    available_nodes: Iterable[str],
) -> Dict[str, str]:
    """
    Rewrite ``class_type`` values **in place** using the alias table.

    For each node in the workflow whose ``class_type`` is not in
    *available_nodes*, search the alias table for a match that IS available
    and replace.

    Returns:
        ``{old_name: new_name}`` for every replacement made (empty if none).
    """
    available = set(available_nodes)
    replacements: Dict[str, str] = {}

    for _node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue

        ct = node.get("class_type")
        if not ct or ct in available:
            continue

        candidates = NODE_ALIAS_CANDIDATES.get(ct)
        if not candidates:
            continue

        for alt in candidates:
            if alt in available:
                node["class_type"] = alt
                replacements[ct] = alt
                break

    return replacements


def find_missing_class_types(
    workflow: Dict[str, Any],
    available_nodes: Iterable[str],
) -> Tuple[str, ...]:
    """
    Return a sorted, de-duplicated tuple of ``class_type`` names that are
    present in *workflow* but absent from *available_nodes*.

    Should be called **after** :func:`remap_workflow_nodes` for an accurate
    picture of what is truly missing.
    """
    available = set(available_nodes)
    missing: list[str] = []

    for _node_id, node in workflow.items():
        if isinstance(node, dict):
            ct = node.get("class_type")
            if ct and ct not in available:
                missing.append(ct)

    return tuple(sorted(set(missing)))
