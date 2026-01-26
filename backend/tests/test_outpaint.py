"""
Tests for the /v1/outpaint endpoint.

These are simple health check tests to verify:
1. Endpoint exists and responds
2. Input validation works
3. Error handling for missing parameters
4. Direction selection works correctly
"""

import pytest
from unittest.mock import patch, MagicMock


class TestOutpaintEndpoint:
    """Test suite for the outpaint API endpoint."""

    def test_outpaint_endpoint_exists(self, client):
        """Test that the /v1/outpaint endpoint exists."""
        # Send a POST request without body - should get 422 (validation error)
        # rather than 404 (not found)
        response = client.post("/v1/outpaint")
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_outpaint_requires_image_url(self, client):
        """Test that image_url is required."""
        response = client.post("/v1/outpaint", json={
            "direction": "right",
            "extend_pixels": 256
        })
        assert response.status_code == 422
        assert "image_url" in response.text.lower() or "field required" in response.text.lower()

    def test_outpaint_validates_direction(self, client):
        """Test that direction is validated."""
        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "direction": "invalid_direction"
        })
        assert response.status_code == 422

    def test_outpaint_validates_extend_pixels_min(self, client):
        """Test that extend_pixels minimum (64) is enforced."""
        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "extend_pixels": 32  # Below minimum
        })
        assert response.status_code == 422

    def test_outpaint_validates_extend_pixels_max(self, client):
        """Test that extend_pixels maximum (1024) is enforced."""
        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "extend_pixels": 2000  # Above maximum
        })
        assert response.status_code == 422

    def test_outpaint_accepts_valid_request(self, client, mock_outbound, monkeypatch):
        """Test that valid outpaint request is accepted."""
        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            assert name == "outpaint"
            assert "extend_left" in variables
            assert "extend_right" in variables
            assert "extend_top" in variables
            assert "extend_bottom" in variables
            return {
                "media": {
                    "images": ["http://localhost:8000/files/outpaint_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.outpaint._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.outpaint.run_workflow", mock_run_workflow)

        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "direction": "right",
            "extend_pixels": 256
        })

        assert response.status_code == 200
        data = response.json()
        assert "media" in data
        assert "direction_used" in data
        assert data["direction_used"] == "right"
        assert data["original_size"] == [512, 512]
        assert data["new_size"] == [768, 512]  # 512 + 256 = 768

    def test_outpaint_direction_all(self, client, mock_outbound, monkeypatch):
        """Test that 'all' direction extends all sides."""
        captured_vars = {}

        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            captured_vars.update(variables)
            return {
                "media": {
                    "images": ["http://localhost:8000/files/outpaint_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.outpaint._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.outpaint.run_workflow", mock_run_workflow)

        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "direction": "all",
            "extend_pixels": 128
        })

        assert response.status_code == 200
        assert captured_vars.get("extend_left") == 128
        assert captured_vars.get("extend_right") == 128
        assert captured_vars.get("extend_top") == 128
        assert captured_vars.get("extend_bottom") == 128

        data = response.json()
        assert data["new_size"] == [768, 768]  # 512 + 128 + 128 = 768

    def test_outpaint_direction_horizontal(self, client, mock_outbound, monkeypatch):
        """Test that 'horizontal' direction extends left and right."""
        captured_vars = {}

        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            captured_vars.update(variables)
            return {
                "media": {
                    "images": ["http://localhost:8000/files/outpaint_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.outpaint._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.outpaint.run_workflow", mock_run_workflow)

        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "direction": "horizontal",
            "extend_pixels": 256
        })

        assert response.status_code == 200
        assert captured_vars.get("extend_left") == 256
        assert captured_vars.get("extend_right") == 256
        assert captured_vars.get("extend_top") == 0
        assert captured_vars.get("extend_bottom") == 0

    def test_outpaint_direction_vertical(self, client, mock_outbound, monkeypatch):
        """Test that 'vertical' direction extends up and down."""
        captured_vars = {}

        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            captured_vars.update(variables)
            return {
                "media": {
                    "images": ["http://localhost:8000/files/outpaint_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.outpaint._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.outpaint.run_workflow", mock_run_workflow)

        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "direction": "vertical",
            "extend_pixels": 256
        })

        assert response.status_code == 200
        assert captured_vars.get("extend_left") == 0
        assert captured_vars.get("extend_right") == 0
        assert captured_vars.get("extend_top") == 256
        assert captured_vars.get("extend_bottom") == 256

    def test_outpaint_respects_max_size_guardrail(self, client, mock_outbound, monkeypatch):
        """Test that output size is limited to 4096px max edge."""
        def mock_get_image_size(url):
            return (3000, 3000)

        monkeypatch.setattr("app.outpaint._get_image_size", mock_get_image_size)

        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "direction": "all",
            "extend_pixels": 1024  # Would result in 5048x5048
        })

        assert response.status_code == 400
        assert "too large" in response.text.lower() or "max" in response.text.lower()

    def test_outpaint_accepts_prompt(self, client, mock_outbound, monkeypatch):
        """Test that optional prompt is passed to workflow."""
        captured_vars = {}

        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            captured_vars.update(variables)
            return {
                "media": {
                    "images": ["http://localhost:8000/files/outpaint_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.outpaint._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.outpaint.run_workflow", mock_run_workflow)

        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png",
            "direction": "right",
            "extend_pixels": 256,
            "prompt": "beautiful sunset sky"
        })

        assert response.status_code == 200
        assert "sunset" in captured_vars.get("prompt", "").lower()

    def test_outpaint_default_direction(self, client, mock_outbound, monkeypatch):
        """Test that default direction (all) is used if not specified."""
        captured_vars = {}

        def mock_get_image_size(url):
            return (512, 512)

        def mock_run_workflow(name, variables):
            captured_vars.update(variables)
            return {
                "media": {
                    "images": ["http://localhost:8000/files/outpaint_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.outpaint._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.outpaint.run_workflow", mock_run_workflow)

        response = client.post("/v1/outpaint", json={
            "image_url": "http://localhost:8000/files/test.png"
            # No direction specified - should default to "all"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["direction_used"] == "all"
        # Default extend_pixels is 256, so all sides should be 256
        assert captured_vars.get("extend_left") == 256
        assert captured_vars.get("extend_right") == 256


class TestOutpaintWorkflows:
    """Test the outpaint workflow file exists."""

    def test_outpaint_workflow_exists(self):
        """Test that outpaint.json workflow file exists."""
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "outpaint.json"

        assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    def test_outpaint_workflow_has_required_nodes(self):
        """Test that outpaint workflow has required ComfyUI nodes."""
        import json
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "outpaint.json"

        with open(workflow_path) as f:
            workflow = json.load(f)

        node_types = {node.get("class_type") for node in workflow.values() if isinstance(node, dict)}

        assert "LoadImage" in node_types, "Missing LoadImage node"
        assert "SaveImage" in node_types, "Missing SaveImage node"
        assert "KSampler" in node_types, "Missing KSampler node"
        assert "ImagePadForOutpaint" in node_types, "Missing ImagePadForOutpaint node"
