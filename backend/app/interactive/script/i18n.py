"""
Multilingual variant generator.

``generate_language_variants`` takes a filled BranchGraph and a
list of target languages, and returns a list of dicts suitable
for persisting into ``ix_node_variants`` via the repo.

Phase 1 implementation: passthrough — same narration/subtitles in
every target language with an ``[untranslated:<lang>]`` prefix.
This keeps the pipeline testable without an LLM/translator in the
loop. Phase 2 swaps in a real translator behind the same
signature.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..branching.graph import BranchGraph


def generate_language_variants(
    graph: BranchGraph, *, target_languages: List[str],
) -> List[Dict[str, Any]]:
    """Produce variant rows (as dicts) for every (node, language)
    pair where language is NOT already the authoring language
    ('en' by convention). No side effects — the caller persists.
    """
    out: List[Dict[str, Any]] = []
    for lang in target_languages:
        lang = (lang or "").strip()
        if not lang or lang == "en":
            continue
        for node in graph.nodes:
            narration = (node.narration or "").strip()
            if not narration:
                continue
            out.append({
                "node_id": node.id,
                "language": lang,
                "narration": f"[untranslated:{lang}] {narration}",
                "subtitles": f"[untranslated:{lang}] {narration}",
                "audio_asset_id": "",
                "video_asset_id": "",
            })
    return out
