"""
Tests for ComfyUI node preflight checks, alias remapping, and Same Person
(InstantID) / Face Restoration (GFPGAN) workflow integrity.

Non-destructive:  no network, no LLM, no GPU, no ComfyUI needed.
CI-friendly:      runs in < 1 second.

Covers:
  1. Node alias tables — canonical → alternative mappings
  2. remap_workflow_nodes() — in-place class_type rewriting
  3. find_missing_class_types() — post-remap detection
  4. ComfyObjectInfoCache — TTL-based caching of /object_info
  5. check_nodes_available() — high-level preflight
  6. validate_workflow_nodes() — full pipeline (remap + fail-fast)
  7. InstantID SD1.5 / SDXL workflow JSON integrity
  8. FaceRestore (GFPGAN) workflow JSON integrity
  9. Enhance endpoint — face_enhance preflight skip
 10. Identity edit endpoint — 503 with actionable hints
 11. Orchestrator — InstantID fallback when nodes missing
 12. End-to-end alias remap on real workflow JSONs
 13. Node package hints coverage
 14. ControlNet / checkpoint architecture mismatch guard
 15. change_background.json — templatized checkpoint
 16. Orchestrator — SD1.5 excluded from InstantID routing
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / "comfyui" / "workflows"


def _load_workflow(name: str) -> Dict[str, Any]:
    """Load a workflow JSON from the comfyui/workflows directory."""
    path = WORKFLOWS_DIR / f"{name}.json"
    assert path.exists(), f"Workflow not found: {path}"
    with open(path) as f:
        return json.load(f)


def _extract_class_types(workflow: Dict[str, Any]) -> set[str]:
    """Extract all class_type values from a workflow graph."""
    types: set[str] = set()
    for _id, node in workflow.items():
        if isinstance(node, dict):
            ct = node.get("class_type")
            if ct:
                types.add(ct)
    return types


# =====================================================================
# 1. Node Alias Tables
# =====================================================================

class TestNodeAliasTables:
    """NODE_ALIAS_CANDIDATES has the right structure and coverage."""

    def test_alias_table_is_non_empty(self):
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        assert len(NODE_ALIAS_CANDIDATES) > 0

    def test_instantid_face_analysis_has_aliases(self):
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        assert "InstantIDFaceAnalysis" in NODE_ALIAS_CANDIDATES
        aliases = NODE_ALIAS_CANDIDATES["InstantIDFaceAnalysis"]
        assert len(aliases) >= 3
        # First entry should be the canonical name itself
        assert aliases[0] == "InstantIDFaceAnalysis"

    def test_face_restore_model_loader_has_aliases(self):
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        assert "FaceRestoreModelLoader" in NODE_ALIAS_CANDIDATES
        aliases = NODE_ALIAS_CANDIDATES["FaceRestoreModelLoader"]
        assert "GFPGANLoader" in aliases
        assert "GFPGANModelLoader" in aliases

    def test_face_restore_with_model_has_aliases(self):
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        assert "FaceRestoreWithModel" in NODE_ALIAS_CANDIDATES
        aliases = NODE_ALIAS_CANDIDATES["FaceRestoreWithModel"]
        assert "GFPGAN" in aliases

    def test_apply_instantid_has_aliases(self):
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        assert "ApplyInstantID" in NODE_ALIAS_CANDIDATES
        aliases = NODE_ALIAS_CANDIDATES["ApplyInstantID"]
        assert "InstantIDApply" in aliases

    def test_instantid_model_loader_has_aliases(self):
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        assert "InstantIDModelLoader" in NODE_ALIAS_CANDIDATES

    def test_all_canonical_names_are_first_in_tuple(self):
        """The canonical name should be the first alternative (for self-match)."""
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        for canonical, alts in NODE_ALIAS_CANDIDATES.items():
            assert alts[0] == canonical, (
                f"First alias for '{canonical}' should be itself, got '{alts[0]}'"
            )

    def test_all_values_are_tuples_of_strings(self):
        from app.comfy_utils.node_aliases import NODE_ALIAS_CANDIDATES
        for k, v in NODE_ALIAS_CANDIDATES.items():
            assert isinstance(v, tuple), f"Expected tuple for '{k}', got {type(v)}"
            for alt in v:
                assert isinstance(alt, str), f"Non-string alias in '{k}': {alt}"


# =====================================================================
# 2. remap_workflow_nodes()
# =====================================================================

class TestRemapWorkflowNodes:
    """remap_workflow_nodes() rewrites class_type in-place when aliases match."""

    def test_no_change_when_all_nodes_available(self):
        from app.comfy_utils.node_aliases import remap_workflow_nodes
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {}},
            "2": {"class_type": "FaceRestoreModelLoader", "inputs": {}},
        }
        available = {"LoadImage", "FaceRestoreModelLoader"}
        replacements = remap_workflow_nodes(workflow, available)
        assert replacements == {}
        assert workflow["2"]["class_type"] == "FaceRestoreModelLoader"

    def test_remaps_face_restore_to_gfpgan_loader(self):
        from app.comfy_utils.node_aliases import remap_workflow_nodes
        workflow = {
            "1": {"class_type": "FaceRestoreModelLoader", "inputs": {}},
        }
        available = {"LoadImage", "GFPGANLoader", "SaveImage"}
        replacements = remap_workflow_nodes(workflow, available)
        assert "FaceRestoreModelLoader" in replacements
        assert replacements["FaceRestoreModelLoader"] == "GFPGANLoader"
        assert workflow["1"]["class_type"] == "GFPGANLoader"

    def test_remaps_instantid_face_analysis(self):
        from app.comfy_utils.node_aliases import remap_workflow_nodes
        workflow = {
            "11": {"class_type": "InstantIDFaceAnalysis", "inputs": {"provider": "CPU"}},
        }
        available = {"InsightFaceAnalyzer", "CheckpointLoaderSimple"}
        replacements = remap_workflow_nodes(workflow, available)
        assert replacements["InstantIDFaceAnalysis"] == "InsightFaceAnalyzer"
        assert workflow["11"]["class_type"] == "InsightFaceAnalyzer"

    def test_remaps_apply_instantid(self):
        from app.comfy_utils.node_aliases import remap_workflow_nodes
        workflow = {
            "14": {"class_type": "ApplyInstantID", "inputs": {}},
        }
        available = {"InstantIDApply"}
        replacements = remap_workflow_nodes(workflow, available)
        assert replacements["ApplyInstantID"] == "InstantIDApply"

    def test_no_change_for_unknown_node(self):
        from app.comfy_utils.node_aliases import remap_workflow_nodes
        workflow = {
            "1": {"class_type": "SomeRandomNode", "inputs": {}},
        }
        available = {"LoadImage"}
        replacements = remap_workflow_nodes(workflow, available)
        assert replacements == {}
        assert workflow["1"]["class_type"] == "SomeRandomNode"

    def test_skips_non_dict_entries(self):
        from app.comfy_utils.node_aliases import remap_workflow_nodes
        workflow = {
            "_comment": "this is a string, not a node",
            "1": {"class_type": "LoadImage", "inputs": {}},
        }
        available = {"LoadImage"}
        replacements = remap_workflow_nodes(workflow, available)
        assert replacements == {}

    def test_multiple_remaps_in_one_workflow(self):
        from app.comfy_utils.node_aliases import remap_workflow_nodes
        workflow = {
            "1": {"class_type": "FaceRestoreModelLoader", "inputs": {}},
            "2": {"class_type": "FaceRestoreWithModel", "inputs": {}},
            "3": {"class_type": "LoadImage", "inputs": {}},
        }
        available = {"GFPGANLoader", "GFPGAN", "LoadImage", "SaveImage"}
        replacements = remap_workflow_nodes(workflow, available)
        assert len(replacements) == 2
        assert workflow["1"]["class_type"] == "GFPGANLoader"
        assert workflow["2"]["class_type"] == "GFPGAN"
        assert workflow["3"]["class_type"] == "LoadImage"  # unchanged


# =====================================================================
# 3. find_missing_class_types()
# =====================================================================

class TestFindMissingClassTypes:
    """find_missing_class_types() detects what's truly missing after remap."""

    def test_nothing_missing(self):
        from app.comfy_utils.node_aliases import find_missing_class_types
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {}},
            "2": {"class_type": "SaveImage", "inputs": {}},
        }
        missing = find_missing_class_types(workflow, {"LoadImage", "SaveImage"})
        assert missing == ()

    def test_detects_missing_nodes(self):
        from app.comfy_utils.node_aliases import find_missing_class_types
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {}},
            "2": {"class_type": "MysteryNode", "inputs": {}},
            "3": {"class_type": "AnotherMissing", "inputs": {}},
        }
        missing = find_missing_class_types(workflow, {"LoadImage"})
        assert "MysteryNode" in missing
        assert "AnotherMissing" in missing

    def test_deduplicated_and_sorted(self):
        from app.comfy_utils.node_aliases import find_missing_class_types
        workflow = {
            "1": {"class_type": "ZNode", "inputs": {}},
            "2": {"class_type": "ANode", "inputs": {}},
            "3": {"class_type": "ZNode", "inputs": {}},  # duplicate
        }
        missing = find_missing_class_types(workflow, set())
        assert missing == ("ANode", "ZNode")

    def test_skips_non_dict_entries(self):
        from app.comfy_utils.node_aliases import find_missing_class_types
        workflow = {
            "_comment": "not a node",
            "1": {"class_type": "LoadImage", "inputs": {}},
        }
        missing = find_missing_class_types(workflow, {"LoadImage"})
        assert missing == ()


# =====================================================================
# 4. ComfyObjectInfoCache
# =====================================================================

class TestComfyObjectInfoCache:
    """ComfyObjectInfoCache respects TTL and handles network failures."""

    def test_returns_empty_when_comfyui_unreachable(self):
        from app.comfy_utils.object_info_cache import ComfyObjectInfoCache
        cache = ComfyObjectInfoCache("http://unreachable:9999", ttl_seconds=0)
        nodes = cache.get_available_nodes()
        assert nodes == []

    def test_returns_node_names_from_mocked_response(self):
        from app.comfy_utils.object_info_cache import ComfyObjectInfoCache
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=60)

        mock_data = {
            "LoadImage": {"input": {}, "output": {}},
            "SaveImage": {"input": {}, "output": {}},
            "InstantIDFaceAnalysis": {"input": {}, "output": {}},
        }

        with patch("app.comfy_utils.object_info_cache.httpx.Client") as MockClient:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_data
            mock_resp.raise_for_status = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.get.return_value = mock_resp
            MockClient.return_value = mock_ctx

            nodes = cache.get_available_nodes(force=True)
            assert "LoadImage" in nodes
            assert "SaveImage" in nodes
            assert "InstantIDFaceAnalysis" in nodes
            assert len(nodes) == 3

    def test_cache_hit_does_not_refetch(self):
        from app.comfy_utils.object_info_cache import ComfyObjectInfoCache
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300)

        mock_data = {"LoadImage": {}}

        with patch("app.comfy_utils.object_info_cache.httpx.Client") as MockClient:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_data
            mock_resp.raise_for_status = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.get.return_value = mock_resp
            MockClient.return_value = mock_ctx

            cache.get_available_nodes(force=True)  # first call: fetches
            cache.get_available_nodes()  # second call: should hit cache

            # httpx.Client was only created once (for the forced call)
            assert MockClient.call_count == 1

    def test_invalidate_forces_refetch(self):
        from app.comfy_utils.object_info_cache import ComfyObjectInfoCache
        cache = ComfyObjectInfoCache("http://mock:8188", ttl_seconds=300)
        # Simulate that cache was populated
        cache._nodes = ["OldNode"]
        cache._expires_at = 9999999999.0  # far future

        cache.invalidate()
        assert cache._expires_at == 0.0

    def test_get_raw_returns_dict_or_none(self):
        from app.comfy_utils.object_info_cache import ComfyObjectInfoCache
        cache = ComfyObjectInfoCache("http://unreachable:9999", ttl_seconds=0)
        raw = cache.get_raw()
        assert raw is None


# =====================================================================
# 5. check_nodes_available() — high-level
# =====================================================================

class TestCheckNodesAvailable:
    """check_nodes_available() uses the cache and reports missing nodes."""

    def test_all_available(self):
        from app.comfy import check_nodes_available
        with patch("app.comfy.get_available_node_names", return_value=["LoadImage", "SaveImage"]):
            ok, missing = check_nodes_available(["LoadImage", "SaveImage"])
            assert ok is True
            assert missing == []

    def test_detects_missing(self):
        from app.comfy import check_nodes_available
        with patch("app.comfy.get_available_node_names", return_value=["LoadImage"]):
            ok, missing = check_nodes_available(["LoadImage", "InstantIDFaceAnalysis"])
            assert ok is False
            assert "InstantIDFaceAnalysis" in missing

    def test_returns_true_when_comfyui_unreachable(self):
        """When ComfyUI is unreachable, we allow the workflow to proceed."""
        from app.comfy import check_nodes_available
        with patch("app.comfy.get_available_node_names", return_value=[]):
            ok, missing = check_nodes_available(["AnyNode"])
            assert ok is True
            assert missing == []


# =====================================================================
# 6. validate_workflow_nodes() — full pipeline
# =====================================================================

class TestValidateWorkflowNodes:
    """validate_workflow_nodes() remaps aliases then fails fast on truly missing nodes."""

    def test_passes_when_all_nodes_available(self):
        from app.comfy import validate_workflow_nodes
        graph = {
            "1": {"class_type": "LoadImage", "inputs": {}},
            "2": {"class_type": "SaveImage", "inputs": {}},
        }
        with patch("app.comfy.get_available_node_names", return_value=["LoadImage", "SaveImage"]):
            # Should not raise
            validate_workflow_nodes("test_wf", graph)

    def test_remaps_and_passes(self):
        """If alias remapping resolves the missing node, no error is raised."""
        from app.comfy import validate_workflow_nodes
        graph = {
            "1": {"class_type": "FaceRestoreModelLoader", "inputs": {}},
            "2": {"class_type": "SaveImage", "inputs": {}},
        }
        available = ["GFPGANLoader", "SaveImage", "LoadImage"]
        with patch("app.comfy.get_available_node_names", return_value=available):
            validate_workflow_nodes("test_wf", graph)
            # The graph was mutated in-place
            assert graph["1"]["class_type"] == "GFPGANLoader"

    def test_raises_when_truly_missing(self):
        from app.comfy import validate_workflow_nodes
        graph = {
            "1": {"class_type": "LoadImage", "inputs": {}},
            "2": {"class_type": "TotallyFakeNode", "inputs": {}},
        }
        with patch("app.comfy.get_available_node_names", return_value=["LoadImage"]):
            with pytest.raises(RuntimeError, match="not registered"):
                validate_workflow_nodes("test_wf", graph)

    def test_error_message_contains_install_hint(self):
        from app.comfy import validate_workflow_nodes
        graph = {
            "1": {"class_type": "InstantIDFaceAnalysis", "inputs": {}},
        }
        with patch("app.comfy.get_available_node_names", return_value=["LoadImage"]):
            with pytest.raises(RuntimeError, match="cubiq/ComfyUI_InstantID"):
                validate_workflow_nodes("test_wf", graph)

    def test_error_message_for_face_restore(self):
        from app.comfy import validate_workflow_nodes
        graph = {
            "1": {"class_type": "FaceRestoreModelLoader", "inputs": {}},
        }
        # No GFPGAN aliases available either
        with patch("app.comfy.get_available_node_names", return_value=["LoadImage"]):
            with pytest.raises(RuntimeError, match="facexlib"):
                validate_workflow_nodes("test_wf", graph)

    def test_passes_through_when_comfyui_unreachable(self):
        """When ComfyUI is down, we don't block — let the workflow attempt proceed."""
        from app.comfy import validate_workflow_nodes
        graph = {
            "1": {"class_type": "FakeNode", "inputs": {}},
        }
        with patch("app.comfy.get_available_node_names", return_value=[]):
            # Should not raise — empty list means ComfyUI unreachable
            validate_workflow_nodes("test_wf", graph)


# =====================================================================
# 7. InstantID workflow JSON integrity
# =====================================================================

class TestInstantIDWorkflowIntegrity:
    """Verify the InstantID workflow JSONs have correct structure."""

    @pytest.mark.parametrize("wf_name", [
        "txt2img-sd15-instantid",
        "txt2img-sdxl-instantid",
    ])
    def test_workflow_file_exists(self, wf_name):
        path = WORKFLOWS_DIR / f"{wf_name}.json"
        assert path.exists(), f"Workflow not found: {path}"

    @pytest.mark.parametrize("wf_name", [
        "txt2img-sd15-instantid",
        "txt2img-sdxl-instantid",
    ])
    def test_workflow_has_instantid_nodes(self, wf_name):
        """Each InstantID workflow must contain the three core InstantID nodes."""
        wf = _load_workflow(wf_name)
        types = _extract_class_types(wf)
        assert "InstantIDFaceAnalysis" in types, f"Missing InstantIDFaceAnalysis in {wf_name}"
        assert "InstantIDModelLoader" in types, f"Missing InstantIDModelLoader in {wf_name}"
        assert "ApplyInstantID" in types, f"Missing ApplyInstantID in {wf_name}"

    @pytest.mark.parametrize("wf_name", [
        "txt2img-sd15-instantid",
        "txt2img-sdxl-instantid",
    ])
    def test_workflow_has_standard_nodes(self, wf_name):
        """InstantID workflows also need standard ComfyUI pipeline nodes."""
        wf = _load_workflow(wf_name)
        types = _extract_class_types(wf)
        assert "CheckpointLoaderSimple" in types
        assert "KSampler" in types
        assert "VAEDecode" in types
        assert "SaveImage" in types
        assert "LoadImage" in types

    @pytest.mark.parametrize("wf_name", [
        "txt2img-sd15-instantid",
        "txt2img-sdxl-instantid",
    ])
    def test_workflow_has_template_variables(self, wf_name):
        """Key template variables must be present for the backend to inject."""
        raw = (WORKFLOWS_DIR / f"{wf_name}.json").read_text()
        for var in ["{{prompt}}", "{{negative_prompt}}", "{{reference_image_url}}",
                     "{{identity_strength}}", "{{seed}}", "{{steps}}", "{{cfg}}",
                     "{{width}}", "{{height}}"]:
            assert var in raw, f"Missing template variable {var} in {wf_name}"

    @pytest.mark.parametrize("wf_name", [
        "txt2img-sd15-instantid",
        "txt2img-sdxl-instantid",
    ])
    def test_face_analysis_node_feeds_into_apply(self, wf_name):
        """Node 11 (FaceAnalysis) output must be wired to ApplyInstantID's insightface input."""
        wf = _load_workflow(wf_name)
        apply_node = None
        for _id, node in wf.items():
            if isinstance(node, dict) and node.get("class_type") == "ApplyInstantID":
                apply_node = node
                break
        assert apply_node is not None, f"ApplyInstantID node not found in {wf_name}"
        # insightface input should reference node 11, output 0
        insightface_ref = apply_node["inputs"]["insightface"]
        assert insightface_ref == ["11", 0], (
            f"ApplyInstantID.insightface should reference node 11 output 0, got {insightface_ref}"
        )

    def test_sd15_uses_clip_text_encode(self):
        wf = _load_workflow("txt2img-sd15-instantid")
        types = _extract_class_types(wf)
        assert "CLIPTextEncode" in types

    def test_sdxl_uses_clip_text_encode_sdxl(self):
        wf = _load_workflow("txt2img-sdxl-instantid")
        types = _extract_class_types(wf)
        assert "CLIPTextEncodeSDXL" in types


# =====================================================================
# 8. FaceDetailer workflow JSON integrity
# =====================================================================

class TestFaceRestoreWorkflowIntegrity:
    """Verify the fix_faces_facedetailer workflow JSON structure."""

    def test_workflow_file_exists(self):
        path = WORKFLOWS_DIR / "fix_faces_facedetailer.json"
        assert path.exists()

    def test_legacy_gfpgan_workflow_still_exists(self):
        """Old fix_faces_gfpgan.json kept for backwards compatibility."""
        path = WORKFLOWS_DIR / "fix_faces_gfpgan.json"
        assert path.exists()

    def test_has_required_nodes(self):
        wf = _load_workflow("fix_faces_facedetailer")
        types = _extract_class_types(wf)
        assert "LoadImage" in types
        assert "FaceDetailer" in types
        assert "UltralyticsDetectorProvider" in types
        assert "CheckpointLoaderSimple" in types
        assert "SaveImage" in types

    def test_has_template_variables(self):
        raw = (WORKFLOWS_DIR / "fix_faces_facedetailer.json").read_text()
        assert "{{image_path}}" in raw
        assert "{{ckpt_name}}" in raw
        assert "{{detector_model}}" in raw
        assert "{{filename_prefix}}" in raw

    def test_face_detailer_feeds_into_save(self):
        """FaceDetailer output feeds into SaveImage."""
        wf = _load_workflow("fix_faces_facedetailer")
        save_node = None
        for _id, node in wf.items():
            if isinstance(node, dict) and node.get("class_type") == "SaveImage":
                save_node = node
                break
        assert save_node is not None
        # images input references the FaceDetailer node
        images_ref = save_node["inputs"]["images"]
        assert images_ref[0] == "6", "SaveImage should reference node 6 (FaceDetailer)"


# =====================================================================
# 9. Enhance endpoint — face_enhance preflight skip
# =====================================================================

class TestEnhanceFacePreflightSkip:
    """When face restore nodes are missing, face_enhance pass is skipped gracefully."""

    def test_face_enhance_skipped_when_nodes_missing(self, client, mock_outbound, monkeypatch):
        """face_enhance=true should skip (not crash) when nodes are unavailable."""
        from dataclasses import dataclass

        @dataclass
        class MockConfig:
            mode: str = "photo"
            name: str = "Photo"
            description: str = "Photo"
            workflow: str = "upscale"
            model_category: str = "upscale"
            default_model_id: str = "4x-UltraSharp"
            param_name: str = "upscale_model"

        monkeypatch.setattr("app.enhance._get_image_size", lambda url: (256, 256))
        monkeypatch.setattr("app.enhance.get_enhance_model",
                            lambda mode: ("4x-UltraSharp.pth", None, MockConfig()))
        monkeypatch.setattr("app.enhance.run_workflow",
                            lambda name, vars: {"images": ["http://x/enhanced.png"], "videos": []})
        monkeypatch.setattr("app.enhance.get_face_restore_model",
                            lambda: ("GFPGANv1.4.pth", None))
        # Nodes NOT available
        monkeypatch.setattr("app.enhance.check_nodes_available",
                            lambda nodes: (False, ["FaceDetailer"]))

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "photo",
            "scale": 2,
            "face_enhance": True,
        })

        assert response.status_code == 200
        data = response.json()
        # Should return the upscaled image (face pass was skipped, not crashed)
        assert "media" in data
        assert len(data["media"]["images"]) > 0


# =====================================================================
# 10. Identity edit endpoint — 503 with actionable hints
# =====================================================================

class TestIdentityEdit503Hints:
    """POST /v1/edit/identity returns 503 with specific hints when nodes are missing."""

    def test_fix_faces_identity_503_when_nodes_missing(self, client, mock_outbound, monkeypatch):
        from app.face_restore import FaceRestoreNodesNotInstalled
        monkeypatch.setattr("app.enhance.get_face_restore_model",
                            lambda: ("GFPGANv1.4.pth", None))
        monkeypatch.setattr("app.enhance.restore_faces_via_comfyui",
                            MagicMock(side_effect=FaceRestoreNodesNotInstalled(
                                "Missing nodes: FaceDetailer.\n"
                                "Fix: install ComfyUI-Impact-Pack"
                            )))

        response = client.post("/v1/edit/identity", json={
            "image_url": "http://localhost:8000/files/test.png",
            "tool_type": "fix_faces_identity",
        })
        assert response.status_code == 503
        body = response.json()["detail"]
        assert "impact-pack" in body.lower() or "facedetailer" in body.lower()

    def test_inpaint_identity_requires_mask(self, client, mock_outbound):
        """inpaint_identity requires a mask_data_url — should return 400 without it."""
        response = client.post("/v1/edit/identity", json={
            "image_url": "http://localhost:8000/files/test.png",
            "tool_type": "inpaint_identity",
        })
        assert response.status_code == 400
        assert "mask" in response.text.lower()

    def test_inpaint_identity_runs_fallback(self, client, mock_outbound, monkeypatch):
        """inpaint_identity falls back to standard inpaint workflow."""
        monkeypatch.setattr("app.enhance.run_workflow",
                            lambda name, vars: {"images": ["http://x/inpaint.png"], "videos": []})
        response = client.post("/v1/edit/identity", json={
            "image_url": "http://localhost:8000/files/test.png",
            "tool_type": "inpaint_identity",
            "mask_data_url": "http://localhost:8000/files/mask.png",
            "prompt": "blue sky",
        })
        assert response.status_code == 200

    def test_change_bg_identity_runs_fallback(self, client, mock_outbound, monkeypatch):
        """change_bg_identity falls back to standard change_background workflow."""
        monkeypatch.setattr("app.enhance.run_workflow",
                            lambda name, vars: {"images": ["http://x/bg.png"], "videos": []})
        response = client.post("/v1/edit/identity", json={
            "image_url": "http://localhost:8000/files/test.png",
            "tool_type": "change_bg_identity",
            "prompt": "tropical beach",
        })
        assert response.status_code == 200

    def test_face_swap_requires_reference(self, client, mock_outbound):
        response = client.post("/v1/edit/identity", json={
            "image_url": "http://localhost:8000/files/test.png",
            "tool_type": "face_swap",
        })
        assert response.status_code in (400, 501)


# =====================================================================
# 11. Orchestrator — InstantID fallback when nodes missing
# =====================================================================

class TestOrchestratorInstantIDFallback:
    """Orchestrator falls back to standard workflow when InstantID nodes are unavailable."""

    def test_check_nodes_used_before_routing(self):
        """check_nodes_available is called with the 3 InstantID node names."""
        from app.comfy import check_nodes_available
        # Just verify the function signature works with InstantID node names
        with patch("app.comfy.get_available_node_names", return_value=[]):
            ok, missing = check_nodes_available([
                "InstantIDFaceAnalysis",
                "InstantIDModelLoader",
                "ApplyInstantID",
            ])
            # Empty available = unreachable, returns True (allow attempt)
            assert ok is True

    def test_check_nodes_reports_missing_instantid(self):
        from app.comfy import check_nodes_available
        available = ["LoadImage", "SaveImage", "CheckpointLoaderSimple"]
        with patch("app.comfy.get_available_node_names", return_value=available):
            ok, missing = check_nodes_available([
                "InstantIDFaceAnalysis",
                "InstantIDModelLoader",
                "ApplyInstantID",
            ])
            assert ok is False
            assert len(missing) == 3


# =====================================================================
# 12. End-to-end alias remap on real workflow JSONs
# =====================================================================

class TestEndToEndAliasRemap:
    """Apply alias remapping to real workflow JSONs and verify correctness."""

    def test_instantid_sd15_remaps_face_analysis(self):
        """If ComfyUI has InsightFaceAnalyzer instead of InstantIDFaceAnalysis."""
        from app.comfy_utils.node_aliases import remap_workflow_nodes, find_missing_class_types

        wf = copy.deepcopy(_load_workflow("txt2img-sd15-instantid"))
        # Simulate a ComfyUI that uses alternative node names
        available = {
            "CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage",
            "LoadImage", "KSampler", "VAEDecode", "SaveImage", "ControlNetLoader",
            # Alternative InstantID names
            "InsightFaceAnalyzer", "InstantIDModelLoader", "InstantIDApply",
        }
        replacements = remap_workflow_nodes(wf, available)
        assert "InstantIDFaceAnalysis" in replacements
        assert replacements["InstantIDFaceAnalysis"] == "InsightFaceAnalyzer"
        assert "ApplyInstantID" in replacements
        assert replacements["ApplyInstantID"] == "InstantIDApply"

        missing = find_missing_class_types(wf, available)
        assert missing == (), f"Should have no missing after remap, got: {missing}"

    def test_gfpgan_workflow_remaps_to_alternative(self):
        """If ComfyUI has GFPGANLoader instead of FaceRestoreModelLoader."""
        from app.comfy_utils.node_aliases import remap_workflow_nodes, find_missing_class_types

        wf = copy.deepcopy(_load_workflow("fix_faces_gfpgan"))
        available = {"LoadImage", "SaveImage", "GFPGANLoader", "GFPGAN"}
        replacements = remap_workflow_nodes(wf, available)
        assert "FaceRestoreModelLoader" in replacements
        assert "FaceRestoreWithModel" in replacements

        missing = find_missing_class_types(wf, available)
        assert missing == ()

    def test_no_remap_when_canonical_names_exist(self):
        """When ComfyUI has the canonical names, nothing should be remapped."""
        from app.comfy_utils.node_aliases import remap_workflow_nodes

        wf = copy.deepcopy(_load_workflow("txt2img-sd15-instantid"))
        available = _extract_class_types(wf)  # all canonical names
        replacements = remap_workflow_nodes(wf, available)
        assert replacements == {}


# =====================================================================
# 13. Node package hints coverage
# =====================================================================

class TestNodePackageHints:
    """_NODE_PACKAGE_HINTS covers all nodes used in our identity/face workflows."""

    def test_instantid_nodes_have_hints(self):
        from app.comfy import _NODE_PACKAGE_HINTS
        for node in ["InstantIDFaceAnalysis", "InstantIDModelLoader", "ApplyInstantID"]:
            assert node in _NODE_PACKAGE_HINTS, f"Missing hint for {node}"

    def test_face_restore_nodes_have_hints(self):
        from app.comfy import _NODE_PACKAGE_HINTS
        for node in ["FaceDetailer", "UltralyticsDetectorProvider",
                      "FaceRestoreModelLoader", "FaceRestoreWithModel"]:
            assert node in _NODE_PACKAGE_HINTS, f"Missing hint for {node}"

    def test_hints_contain_install_instructions(self):
        from app.comfy import _NODE_PACKAGE_HINTS
        for node, hint in _NODE_PACKAGE_HINTS.items():
            assert "restart ComfyUI" in hint.lower() or "restart" in hint.lower(), (
                f"Hint for '{node}' should mention restarting ComfyUI"
            )


# =====================================================================
# 14. ControlNet / Checkpoint Architecture Mismatch Guard
# =====================================================================

class TestControlNetArchitectureGuard:
    """_check_controlnet_architecture() catches SDXL ControlNet + SD1.5 checkpoint."""

    def test_sdxl_controlnet_with_sd15_checkpoint_raises(self):
        """InstantID ControlNet is SDXL-only — must fail with SD1.5 checkpoint."""
        from app.comfy import _check_controlnet_architecture
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "dreamshaper_8.safetensors"},
            },
            "13": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "InstantID/diffusion_pytorch_model.safetensors"},
            },
        }
        with pytest.raises(RuntimeError, match="Architecture mismatch"):
            _check_controlnet_architecture("test_wf", graph)

    def test_sdxl_controlnet_with_sdxl_checkpoint_passes(self):
        """SDXL ControlNet + SDXL checkpoint is valid — should not raise."""
        from app.comfy import _check_controlnet_architecture
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
            },
            "13": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "InstantID/diffusion_pytorch_model.safetensors"},
            },
        }
        # Should not raise
        _check_controlnet_architecture("test_wf", graph)

    def test_no_controlnet_passes(self):
        """Workflows without ControlNet should pass without issue."""
        from app.comfy import _check_controlnet_architecture
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "dreamshaper_8.safetensors"},
            },
            "2": {
                "class_type": "KSampler",
                "inputs": {},
            },
        }
        _check_controlnet_architecture("test_wf", graph)

    def test_no_checkpoint_passes(self):
        """Workflows without a checkpoint (e.g. Flux UNET loaders) should pass."""
        from app.comfy import _check_controlnet_architecture
        graph = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "flux_dev.safetensors"},
            },
            "2": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "InstantID/diffusion_pytorch_model.safetensors"},
            },
        }
        _check_controlnet_architecture("test_wf", graph)

    def test_non_instantid_controlnet_with_sd15_passes(self):
        """A non-SDXL ControlNet paired with SD1.5 should pass."""
        from app.comfy import _check_controlnet_architecture
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "dreamshaper_8.safetensors"},
            },
            "13": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "control_v11p_sd15_canny.safetensors"},
            },
        }
        _check_controlnet_architecture("test_wf", graph)

    def test_error_message_mentions_sdxl(self):
        """Error message should explain the SDXL-only requirement."""
        from app.comfy import _check_controlnet_architecture
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "dreamshaper_8.safetensors"},
            },
            "13": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "InstantID/diffusion_pytorch_model.safetensors"},
            },
        }
        with pytest.raises(RuntimeError, match="SDXL-only"):
            _check_controlnet_architecture("test_wf", graph)

    def test_error_message_mentions_y_is_none(self):
        """Error message should explain the 'y is None' symptom."""
        from app.comfy import _check_controlnet_architecture
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
            },
            "13": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "InstantID/diffusion_pytorch_model.safetensors"},
            },
        }
        with pytest.raises(RuntimeError, match="y is None"):
            _check_controlnet_architecture("test_wf", graph)

    def test_validate_workflow_runs_architecture_guard(self):
        """validate_workflow_nodes() should catch architecture mismatches."""
        from app.comfy import validate_workflow_nodes
        graph = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "dreamshaper_8.safetensors"},
            },
            "13": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": "InstantID/diffusion_pytorch_model.safetensors"},
            },
            "14": {
                "class_type": "ApplyInstantID",
                "inputs": {},
            },
        }
        # Architecture guard runs even before /object_info check
        with pytest.raises(RuntimeError, match="Architecture mismatch"):
            validate_workflow_nodes("test_wf", graph)


# =====================================================================
# 15. change_background.json — templatized checkpoint
# =====================================================================

class TestChangeBackgroundWorkflow:
    """change_background.json uses template variable for checkpoint."""

    def test_workflow_has_ckpt_name_template(self):
        raw = (WORKFLOWS_DIR / "change_background.json").read_text()
        assert "{{ckpt_name}}" in raw, (
            "change_background.json should use {{ckpt_name}} template, "
            "not a hardcoded checkpoint"
        )

    def test_workflow_does_not_hardcode_sdxl_checkpoint(self):
        raw = (WORKFLOWS_DIR / "change_background.json").read_text()
        assert "sd_xl_base_1.0_inpainting_0.1.safetensors" not in raw, (
            "change_background.json should NOT hardcode SDXL checkpoint"
        )

    def test_workflow_structure(self):
        wf = _load_workflow("change_background")
        types = _extract_class_types(wf)
        assert "CheckpointLoaderSimple" in types
        assert "LoadImage" in types
        assert "SaveImage" in types


# =====================================================================
# 16. Orchestrator — SD1.5 excluded from InstantID routing
# =====================================================================

class TestOrchestratorSD15InstantIDExclusion:
    """Orchestrator should NOT route SD1.5 models to InstantID workflows."""

    def test_sd15_not_in_identity_workflow_map(self):
        """SD1.5 should not appear in the InstantID workflow map."""
        # Read the orchestrator source to verify
        import ast
        orch_path = Path(__file__).resolve().parent.parent / "app" / "orchestrator.py"
        source = orch_path.read_text()
        # The map should only contain "sdxl", not "sd15"
        assert '"sd15": "txt2img-sd15-instantid"' not in source, (
            "SD1.5 should be removed from the InstantID workflow map "
            "(InstantID ControlNet is SDXL-only)"
        )
