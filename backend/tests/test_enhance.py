"""
Tests for the /v1/enhance endpoint.

These are simple health check tests to verify:
1. Endpoint exists and responds
2. Input validation works
3. Error handling for missing parameters
4. Mode selection works correctly
"""

import pytest
from unittest.mock import patch, MagicMock


class TestEnhanceEndpoint:
    """Test suite for the enhance API endpoint."""

    def test_enhance_endpoint_exists(self, client):
        """Test that the /v1/enhance endpoint exists."""
        # Send a POST request without body - should get 422 (validation error)
        # rather than 404 (not found)
        response = client.post("/v1/enhance")
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_enhance_requires_image_url(self, client):
        """Test that image_url is required."""
        response = client.post("/v1/enhance", json={
            "mode": "photo",
            "scale": 2
        })
        assert response.status_code == 422
        assert "image_url" in response.text.lower() or "field required" in response.text.lower()

    def test_enhance_validates_mode(self, client):
        """Test that mode is validated."""
        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "invalid_mode"
        })
        assert response.status_code == 422

    def test_enhance_validates_scale(self, client):
        """Test that scale is validated (1, 2, or 4)."""
        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "scale": 8  # Invalid: only 1, 2, 4 allowed
        })
        assert response.status_code == 422

    def test_enhance_accepts_valid_photo_request(self, client, mock_outbound, monkeypatch):
        """Test that valid photo enhancement request is accepted."""
        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            assert name == "enhance_realesrgan"
            assert "image_path" in variables
            assert "model_name" in variables
            return {
                "media": {
                    "images": ["http://localhost:8000/files/enhanced_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.run_workflow", mock_run_workflow)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "photo",
            "scale": 2
        })

        assert response.status_code == 200
        data = response.json()
        assert "media" in data
        assert "mode_used" in data
        assert data["mode_used"] == "photo"

    def test_enhance_accepts_valid_restore_request(self, client, mock_outbound, monkeypatch):
        """Test that valid restore request is accepted."""
        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            assert name == "restore_swinir"
            assert variables.get("model_name") == "SwinIR_4x.pth"
            return {
                "media": {
                    "images": ["http://localhost:8000/files/restored_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.run_workflow", mock_run_workflow)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "restore",
            "scale": 4
        })

        assert response.status_code == 200
        data = response.json()
        assert data["mode_used"] == "restore"
        assert data["model_used"] == "SwinIR_4x.pth"

    def test_enhance_accepts_valid_faces_request(self, client, mock_outbound, monkeypatch):
        """Test that valid faces request is accepted."""
        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            assert name == "fix_faces_gfpgan"
            assert variables.get("model_name") == "GFPGANv1.4.pth"
            return {
                "media": {
                    "images": ["http://localhost:8000/files/faces_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.run_workflow", mock_run_workflow)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "faces"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["mode_used"] == "faces"
        assert data["model_used"] == "GFPGANv1.4.pth"

    def test_enhance_respects_max_size_guardrail(self, client, mock_outbound, monkeypatch):
        """Test that output size is limited to 4096px max edge."""
        def mock_get_image_size(url):
            return (2048, 2048)

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "photo",
            "scale": 4  # Would result in 8192x8192
        })

        assert response.status_code == 400
        assert "too large" in response.text.lower() or "max edge" in response.text.lower()

    def test_enhance_default_mode(self, client, mock_outbound, monkeypatch):
        """Test that default mode (photo) is used if not specified."""
        captured_name = {}

        def mock_get_image_size(url):
            return (256, 256)

        def mock_run_workflow(name, variables):
            captured_name["workflow"] = name
            return {"media": {"images": ["http://localhost:8000/files/enhanced.png"], "videos": []}}

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.run_workflow", mock_run_workflow)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png"
            # No mode specified - should use default (photo)
        })

        assert response.status_code == 200
        assert captured_name.get("workflow") == "enhance_realesrgan"


class TestEnhanceWorkflows:
    """Test the enhance workflow files exist."""

    def test_enhance_realesrgan_workflow_exists(self):
        """Test that enhance_realesrgan.json workflow file exists."""
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "enhance_realesrgan.json"

        assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    def test_restore_swinir_workflow_exists(self):
        """Test that restore_swinir.json workflow file exists."""
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "restore_swinir.json"

        assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    def test_fix_faces_gfpgan_workflow_exists(self):
        """Test that fix_faces_gfpgan.json workflow file exists."""
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "fix_faces_gfpgan.json"

        assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    def test_workflows_have_required_nodes(self):
        """Test that enhance workflows have required ComfyUI nodes."""
        import json
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent

        workflows = [
            "enhance_realesrgan.json",
            "restore_swinir.json",
            "fix_faces_gfpgan.json"
        ]

        for workflow_name in workflows:
            workflow_path = repo_root / "comfyui" / "workflows" / workflow_name

            with open(workflow_path) as f:
                workflow = json.load(f)

            node_types = {node.get("class_type") for node in workflow.values() if isinstance(node, dict)}

            assert "LoadImage" in node_types, f"Missing LoadImage node in {workflow_name}"
            assert "UpscaleModelLoader" in node_types, f"Missing UpscaleModelLoader node in {workflow_name}"
            assert "SaveImage" in node_types, f"Missing SaveImage node in {workflow_name}"
