"""
Tests for the /v1/upscale endpoint.

These are simple health check tests to verify:
1. Endpoint exists and responds
2. Input validation works
3. Error handling for missing parameters
"""

import pytest
from unittest.mock import patch, MagicMock


class TestUpscaleEndpoint:
    """Test suite for the upscale API endpoint."""

    def test_upscale_endpoint_exists(self, client):
        """Test that the /v1/upscale endpoint exists."""
        # Send a POST request without body - should get 422 (validation error)
        # rather than 404 (not found)
        response = client.post("/v1/upscale")
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_upscale_requires_image_url(self, client):
        """Test that image_url is required."""
        response = client.post("/v1/upscale", json={
            "scale": 2,
            "model": "4x-UltraSharp.pth"
        })
        assert response.status_code == 422
        assert "image_url" in response.text.lower() or "field required" in response.text.lower()

    def test_upscale_validates_scale(self, client):
        """Test that scale is validated (1-4 range)."""
        # Scale too high
        response = client.post("/v1/upscale", json={
            "image_url": "http://localhost:8000/files/test.png",
            "scale": 10  # Invalid: max is 4
        })
        assert response.status_code == 422

    def test_upscale_accepts_valid_request(self, client, mock_outbound, monkeypatch):
        """Test that valid request is accepted (mocked workflow)."""
        # Mock the image size detection
        def mock_get_image_size(url):
            return (512, 512)

        # Mock run_workflow to avoid actual ComfyUI call
        # run_workflow returns {"images": [...], "videos": [...]} directly
        def mock_run_workflow(name, variables):
            assert name == "upscale"
            assert "image_path" in variables
            assert "upscale_model" in variables
            return {
                "images": ["http://localhost:8000/files/upscaled_test.png"],
                "videos": []
            }

        monkeypatch.setattr("app.upscale._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.upscale.run_workflow", mock_run_workflow)

        response = client.post("/v1/upscale", json={
            "image_url": "http://localhost:8000/files/test.png",
            "scale": 2,
            "model": "4x-UltraSharp.pth"
        })

        assert response.status_code == 200
        data = response.json()
        assert "media" in data
        assert "images" in data["media"]
        assert len(data["media"]["images"]) > 0

    def test_upscale_respects_max_size_guardrail(self, client, mock_outbound, monkeypatch):
        """Test that output size is limited to 4096px max edge."""
        # Mock the image size detection to return a large image
        def mock_get_image_size(url):
            return (2048, 2048)  # 2048 * 4 = 8192 > 4096

        monkeypatch.setattr("app.upscale._get_image_size", mock_get_image_size)

        response = client.post("/v1/upscale", json={
            "image_url": "http://localhost:8000/files/test.png",
            "scale": 4,  # Would result in 8192x8192
            "model": "4x-UltraSharp.pth"
        })

        assert response.status_code == 400
        assert "too large" in response.text.lower() or "max edge" in response.text.lower()

    def test_upscale_default_model(self, client, mock_outbound, monkeypatch):
        """Test that default model is used if not specified."""
        captured_vars = {}

        def mock_get_image_size(url):
            return (256, 256)

        # Mock the model detection to return a valid model
        def mock_get_upscale_model():
            return ("4x-UltraSharp.pth", None)

        def mock_run_workflow(name, variables):
            captured_vars.update(variables)
            # run_workflow returns {"images": [...], "videos": [...]} directly
            return {"images": ["http://localhost:8000/files/upscaled.png"], "videos": []}

        monkeypatch.setattr("app.upscale._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.upscale.get_upscale_model", mock_get_upscale_model)
        monkeypatch.setattr("app.upscale.run_workflow", mock_run_workflow)

        response = client.post("/v1/upscale", json={
            "image_url": "http://localhost:8000/files/test.png",
            "scale": 2
            # No model specified - should use default from get_upscale_model
        })

        assert response.status_code == 200
        assert captured_vars.get("upscale_model") == "4x-UltraSharp.pth"


class TestUpscaleWorkflow:
    """Test the upscale workflow file exists."""

    def test_workflow_file_exists(self):
        """Test that upscale.json workflow file exists."""
        import os
        from pathlib import Path

        # Find the workflow file
        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent  # HomePilot root
        workflow_path = repo_root / "comfyui" / "workflows" / "upscale.json"

        assert workflow_path.exists(), f"Upscale workflow not found at {workflow_path}"

    def test_workflow_has_required_nodes(self):
        """Test that upscale workflow has required ComfyUI nodes."""
        import json
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "upscale.json"

        with open(workflow_path) as f:
            workflow = json.load(f)

        # Check for required node types
        node_types = {node.get("class_type") for node in workflow.values() if isinstance(node, dict)}

        assert "LoadImage" in node_types, "Missing LoadImage node"
        assert "UpscaleModelLoader" in node_types, "Missing UpscaleModelLoader node"
        assert "ImageUpscaleWithModel" in node_types, "Missing ImageUpscaleWithModel node"
        assert "SaveImage" in node_types, "Missing SaveImage node"
