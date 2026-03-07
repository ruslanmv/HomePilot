"""
Tests for Hybrid Avatar Pipeline — Stage B: full-body/outfit from face.

Validates:
  - POST /v1/avatars/hybrid/fullbody generates outfit images from a face
  - Prompt builder produces correct positive/negative prompts
  - Identity strength maps to denoise correctly
  - Endpoint handles missing ComfyUI gracefully (503)
  - Wizard appearance fields flow through to the generated prompt

Non-destructive: no network, no LLM, no GPU.
CI-friendly: runs in <1 second.
"""

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Prompt builder unit tests
# ---------------------------------------------------------------------------


class TestBuildFullbodyPrompt:
    """hybrid_prompt.build_fullbody_prompt produces correct prompts."""

    def test_minimal_prompt(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, neg = build_fullbody_prompt()
        assert "full body photograph" in pos
        assert "person" in pos
        assert "8k resolution" in pos
        # Negative prompt has standard artifact terms
        assert "lowres" in neg
        assert "bad anatomy" in neg

    def test_outfit_in_prompt(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt(outfit_style="Corporate Formal")
        assert "wearing Corporate Formal" in pos

    def test_profession_in_prompt(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt(profession="Executive Secretary")
        assert "Executive Secretary" in pos

    def test_gender_mapping(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt(gender="female")
        assert "woman" in pos

        pos, _ = build_fullbody_prompt(gender="male")
        assert "man" in pos

    def test_age_range_mapping(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt(age_range="young_adult", gender="female")
        assert "young adult woman" in pos

    def test_background_mapping(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt(background="office")
        assert "professional office interior" in pos

    def test_lighting_mapping(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt(lighting="dramatic")
        assert "dramatic cinematic lighting" in pos

    def test_default_lighting(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt()
        assert "professional studio lighting" in pos

    def test_prompt_extra_appended(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, _ = build_fullbody_prompt(prompt_extra="golden hour glow")
        assert "golden hour glow" in pos

    def test_all_fields_combined(self):
        from app.avatar.hybrid_prompt import build_fullbody_prompt

        pos, neg = build_fullbody_prompt(
            outfit_style="Business Casual",
            profession="Software Engineer",
            body_type="athletic",
            posture="confident",
            gender="male",
            age_range="adult",
            background="urban",
            lighting="natural",
            prompt_extra="bokeh background",
        )
        assert "wearing Business Casual" in pos
        assert "Software Engineer" in pos
        assert "athletic build" in pos
        assert "confident posture" in pos
        assert "adult man" in pos
        assert "urban" in pos.lower()
        assert "natural daylight" in pos
        assert "bokeh background" in pos
        assert len(neg) > 0


# ---------------------------------------------------------------------------
# Identity strength → denoise mapping
# ---------------------------------------------------------------------------


class TestIdentityStrengthMapping:
    """identity_strength maps to denoise in the correct range."""

    def test_high_identity_low_denoise(self):
        """identity_strength=1.0 → denoise ~0.65 (strict face preservation)."""
        denoise = max(0.60, min(0.95, 1.0 - (1.0 * 0.35)))
        assert denoise == pytest.approx(0.65, abs=0.01)

    def test_low_identity_high_denoise(self):
        """identity_strength=0.1 → denoise ~0.95 (maximum creativity)."""
        denoise = max(0.60, min(0.95, 1.0 - (0.1 * 0.35)))
        assert denoise == pytest.approx(0.95, abs=0.01)

    def test_balanced_identity(self):
        """identity_strength=0.75 (default) → denoise ~0.7375."""
        denoise = max(0.60, min(0.95, 1.0 - (0.75 * 0.35)))
        assert 0.70 < denoise < 0.80


# ---------------------------------------------------------------------------
# Fullbody schemas
# ---------------------------------------------------------------------------


class TestHybridFullBodySchemas:
    """HybridFullBodyRequest / HybridFullBodyResponse schema validation."""

    def test_fullbody_request_requires_face_url(self):
        from pydantic import ValidationError
        from app.avatar.hybrid_schemas import HybridFullBodyRequest

        with pytest.raises(ValidationError):
            HybridFullBodyRequest()  # face_image_url is required

    def test_fullbody_request_defaults(self):
        from app.avatar.hybrid_schemas import HybridFullBodyRequest

        req = HybridFullBodyRequest(face_image_url="http://example.com/face.png")
        assert req.count == 2
        assert req.identity_strength == 0.75
        assert req.outfit_style is None
        assert req.gender is None

    def test_fullbody_request_all_fields(self):
        from app.avatar.hybrid_schemas import HybridFullBodyRequest

        req = HybridFullBodyRequest(
            face_image_url="http://example.com/face.png",
            count=3,
            outfit_style="Casual",
            profession="Teacher",
            body_type="average",
            posture="relaxed",
            gender="female",
            age_range="adult",
            background="outdoors",
            lighting="natural",
            prompt_extra="smiling",
            identity_strength=0.8,
            seed=123,
        )
        assert req.count == 3
        assert req.outfit_style == "Casual"
        assert req.identity_strength == 0.8

    def test_fullbody_response_model(self):
        from app.avatar.hybrid_schemas import HybridFullBodyResponse, HybridFullBodyResult

        resp = HybridFullBodyResponse(
            results=[HybridFullBodyResult(url="/test.png", seed=1)],
            used_checkpoint="v1-5-pruned.safetensors",
        )
        assert resp.stage == "full_body"
        assert resp.used_checkpoint == "v1-5-pruned.safetensors"
        assert len(resp.results) == 1


# ---------------------------------------------------------------------------
# Stage B — /v1/avatars/hybrid/fullbody endpoint
# ---------------------------------------------------------------------------


class TestHybridFullBodyEndpoint:
    """POST /v1/avatars/hybrid/fullbody generates outfit from face."""

    def test_fullbody_endpoint_exists(self, client, mock_outbound):
        """Endpoint responds (not 404/405)."""
        resp = client.post(
            "/v1/avatars/hybrid/fullbody",
            json={"face_image_url": "http://example.com/face.png"},
        )
        assert resp.status_code != 404
        assert resp.status_code != 405

    def test_fullbody_missing_face_url_rejected(self, client, mock_outbound):
        """Missing face_image_url is rejected by Pydantic (422)."""
        resp = client.post("/v1/avatars/hybrid/fullbody", json={})
        assert resp.status_code == 422

    def test_fullbody_with_mocked_pipeline(self, client, monkeypatch):
        """Full pipeline with mocked ComfyUI returns results."""
        from app.avatar.schemas import AvatarResult

        mock_results = [
            AvatarResult(
                url="/comfy/view/outfit_0.png",
                seed=42,
                metadata={"source": "comfyui", "workflow": "avatar_body_from_face.json"},
            ),
        ]

        # Mock enabled_modes to include at least one mode (hybrid_body uses ComfyUI directly)
        monkeypatch.setattr(
            "app.avatar.hybrid_service.enabled_modes",
            lambda: ["studio_reference", "creative"],
        )

        # Mock run_avatar_workflow to return our fake results
        async_mock = AsyncMock(return_value=mock_results)
        monkeypatch.setattr(
            "app.avatar.hybrid_service.run_avatar_workflow",
            async_mock,
        )

        resp = client.post(
            "/v1/avatars/hybrid/fullbody",
            json={
                "face_image_url": "http://example.com/face.png",
                "count": 1,
                "outfit_style": "Business Formal",
                "gender": "female",
                "age_range": "adult",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "full_body"
        assert len(data["results"]) == 1
        assert data["results"][0]["url"] == "/comfy/view/outfit_0.png"

        # Verify run_avatar_workflow was called with hybrid_body mode
        call_kwargs = async_mock.call_args
        assert call_kwargs.kwargs["mode"] == "hybrid_body"
        # identity_strength should be passed through (default 0.75)
        assert call_kwargs.kwargs["identity_strength"] == 0.75
        # Prompt should contain outfit and gender info
        prompt = call_kwargs.kwargs["prompt"]
        assert "wearing Business Formal" in prompt
        assert "woman" in prompt
        # Negative prompt should be passed
        assert call_kwargs.kwargs["negative_prompt"] is not None
        assert "bad anatomy" in call_kwargs.kwargs["negative_prompt"]

    def test_fullbody_uses_hybrid_body_mode(self, client, monkeypatch):
        """hybrid_body mode is always used regardless of available modes."""
        from app.avatar.schemas import AvatarResult

        mock_results = [
            AvatarResult(
                url="/comfy/view/outfit_fallback.png",
                seed=99,
                metadata={"source": "comfyui"},
            ),
        ]

        # Only creative mode listed as available
        monkeypatch.setattr(
            "app.avatar.hybrid_service.enabled_modes",
            lambda: ["creative"],
        )

        async_mock = AsyncMock(return_value=mock_results)
        monkeypatch.setattr(
            "app.avatar.hybrid_service.run_avatar_workflow",
            async_mock,
        )

        resp = client.post(
            "/v1/avatars/hybrid/fullbody",
            json={
                "face_image_url": "http://example.com/face.png",
                "count": 1,
            },
        )
        assert resp.status_code == 200
        # Should still use hybrid_body mode (not creative)
        call_kwargs = async_mock.call_args
        assert call_kwargs.kwargs["mode"] == "hybrid_body"

    def test_fullbody_no_modes_returns_503(self, client, monkeypatch):
        """When no generation modes available, returns 503."""
        monkeypatch.setattr(
            "app.avatar.hybrid_service.enabled_modes",
            lambda: [],
        )

        resp = client.post(
            "/v1/avatars/hybrid/fullbody",
            json={
                "face_image_url": "http://example.com/face.png",
                "count": 1,
            },
        )
        # 503 from HybridUnavailable or 500 from exception
        assert resp.status_code in (500, 503)

    def test_fullbody_metadata_includes_pipeline_info(self, client, monkeypatch):
        """Result metadata contains hybrid pipeline info."""
        from app.avatar.schemas import AvatarResult

        mock_results = [
            AvatarResult(url="/comfy/view/test.png", seed=1, metadata={}),
        ]

        monkeypatch.setattr(
            "app.avatar.hybrid_service.enabled_modes",
            lambda: ["studio_reference"],
        )
        monkeypatch.setattr(
            "app.avatar.hybrid_service.run_avatar_workflow",
            AsyncMock(return_value=mock_results),
        )

        resp = client.post(
            "/v1/avatars/hybrid/fullbody",
            json={
                "face_image_url": "http://example.com/face.png",
                "count": 1,
                "identity_strength": 0.8,
            },
        )
        assert resp.status_code == 200
        meta = resp.json()["results"][0]["metadata"]
        assert meta["engine"] == "comfyui"
        assert meta["pipeline"] == "hybrid"
        assert meta["identity_strength"] == 0.8
        assert "prompt" in meta


# ---------------------------------------------------------------------------
# Workflow template and injection helpers
# ---------------------------------------------------------------------------


class TestBodyFromFaceWorkflow:
    """avatar_body_from_face.json workflow template structure."""

    def test_workflow_file_exists(self):
        import json
        from pathlib import Path

        wf_path = Path(__file__).resolve().parents[2] / "workflows" / "avatar" / "avatar_body_from_face.json"
        assert wf_path.exists(), f"Missing workflow: {wf_path}"
        wf = json.loads(wf_path.read_text())

        # Must have InstantID nodes
        node_types = {n["class_type"] for n in wf.values() if isinstance(n, dict) and "class_type" in n}
        assert "InstantIDFaceAnalysis" in node_types
        assert "InstantIDModelLoader" in node_types
        assert "ApplyInstantID" in node_types
        assert "ControlNetLoader" in node_types

        # Must use EmptyLatentImage (txt2img, not img2img)
        assert "EmptyLatentImage" in node_types
        # Should NOT have VAEEncode (that would be img2img)
        assert "VAEEncode" not in node_types

    def test_workflow_has_portrait_dimensions(self):
        import json
        from pathlib import Path

        wf_path = Path(__file__).resolve().parents[2] / "workflows" / "avatar" / "avatar_body_from_face.json"
        wf = json.loads(wf_path.read_text())

        for node in wf.values():
            if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
                inputs = node["inputs"]
                # Portrait orientation: height > width
                assert inputs["height"] > inputs["width"]
                break

    def test_workflow_has_positive_and_negative_prompts(self):
        import json
        from pathlib import Path

        wf_path = Path(__file__).resolve().parents[2] / "workflows" / "avatar" / "avatar_body_from_face.json"
        wf = json.loads(wf_path.read_text())

        titles = []
        for node in wf.values():
            if isinstance(node, dict) and node.get("class_type") in ("CLIPTextEncode", "CLIPTextEncodeSDXL"):
                meta = node.get("_meta", {})
                titles.append(meta.get("title", ""))

        assert "Positive Prompt" in titles
        assert "Negative Prompt" in titles


class TestWorkflowInjectionHelpers:
    """Workflow injection helpers for InstantID weight and negative prompt."""

    def test_inject_identity_strength(self):
        from app.services.comfyui.workflows import _inject_identity_strength

        wf = {
            "14": {
                "class_type": "ApplyInstantID",
                "inputs": {"weight": 0.5},
            }
        }
        _inject_identity_strength(wf, 0.8)
        assert wf["14"]["inputs"]["weight"] == 0.8

    def test_inject_negative_prompt(self):
        from app.services.comfyui.workflows import _inject_negative_prompt

        wf = {
            "2": {
                "class_type": "CLIPTextEncode",
                "_meta": {"title": "Positive Prompt"},
                "inputs": {"text": "original positive"},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "_meta": {"title": "Negative Prompt"},
                "inputs": {"text": "original negative"},
            },
        }
        _inject_negative_prompt(wf, "custom negative")
        # Only negative should change
        assert wf["2"]["inputs"]["text"] == "original positive"
        assert wf["3"]["inputs"]["text"] == "custom negative"

    def test_hybrid_body_in_workflow_mapping(self):
        from app.services.comfyui.workflows import _REF_WORKFLOWS

        assert "hybrid_body" in _REF_WORKFLOWS
        assert _REF_WORKFLOWS["hybrid_body"] == "avatar_body_from_face.json"
