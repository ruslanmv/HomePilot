"""
Tests for the /v1/background endpoint.

These are simple health check tests to verify:
1. Endpoint exists and responds
2. Input validation works
3. Error handling for missing parameters
4. Action selection works correctly
"""

import pytest
import io
from unittest.mock import patch, MagicMock

# Minimal valid PNG bytes (1x1 red pixel)
MINIMAL_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0'
    b'\x00\x00\x00\x03\x00\x01\x00\x18\xdd\x8d\xb9\x00\x00\x00\x00IEND\xaeB`\x82'
)


class TestBackgroundEndpoint:
    """Test suite for the background API endpoint."""

    def test_background_endpoint_exists(self, client):
        """Test that the /v1/background endpoint exists."""
        # Send a POST request without body - should get 422 (validation error)
        # rather than 404 (not found)
        response = client.post("/v1/background")
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_background_requires_image_url(self, client):
        """Test that image_url is required."""
        response = client.post("/v1/background", json={
            "action": "remove"
        })
        assert response.status_code == 422
        assert "image_url" in response.text.lower() or "field required" in response.text.lower()

    def test_background_validates_action(self, client):
        """Test that action is validated."""
        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "invalid_action"
        })
        assert response.status_code == 422

    def test_background_validates_blur_strength(self, client):
        """Test that blur_strength is validated (5-50 range)."""
        # Too low
        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "blur",
            "blur_strength": 2
        })
        assert response.status_code == 422

        # Too high
        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "blur",
            "blur_strength": 100
        })
        assert response.status_code == 422

    def test_background_blur_accepts_valid_request(self, client, mock_outbound, monkeypatch):
        """Test that valid blur request is accepted."""
        def mock_get_image_and_size(url):
            return MINIMAL_PNG, (100, 100)

        def mock_apply_blur(img_bytes, blur_strength):
            return img_bytes, False

        def mock_save_image(data, prefix="bg", ext="png"):
            return "/files/test_blur.png"

        monkeypatch.setattr("app.background._get_image_and_size", mock_get_image_and_size)
        monkeypatch.setattr("app.background._apply_blur_to_background", mock_apply_blur)
        monkeypatch.setattr("app.background._save_image_to_uploads", mock_save_image)

        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "blur",
            "blur_strength": 15
        })

        assert response.status_code == 200
        data = response.json()
        assert "media" in data
        assert "action_used" in data
        assert data["action_used"] == "blur"

    def test_background_remove_accepts_valid_request(self, client, mock_outbound, monkeypatch):
        """Test that valid remove request is accepted."""
        def mock_get_image_and_size(url):
            return MINIMAL_PNG, (100, 100)

        def mock_remove_background_pil(img_bytes):
            # Return fake result
            return img_bytes, True

        def mock_save_image(data, prefix="bg", ext="png"):
            return "/files/test_nobg.png"

        monkeypatch.setattr("app.background._get_image_and_size", mock_get_image_and_size)
        monkeypatch.setattr("app.background._remove_background_pil", mock_remove_background_pil)
        monkeypatch.setattr("app.background._save_image_to_uploads", mock_save_image)

        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "remove"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["action_used"] == "remove"
        assert data["has_alpha"] == True

    def test_background_replace_requires_prompt(self, client, mock_outbound, monkeypatch):
        """Test that replace action requires a prompt."""
        def mock_get_image_and_size(url):
            return MINIMAL_PNG, (100, 100)

        monkeypatch.setattr("app.background._get_image_and_size", mock_get_image_and_size)

        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "replace"
            # No prompt provided
        })

        assert response.status_code == 400
        assert "prompt" in response.text.lower()

    def test_background_replace_accepts_valid_request(self, client, mock_outbound, monkeypatch):
        """Test that valid replace request is accepted."""
        def mock_get_image_and_size(url):
            return MINIMAL_PNG, (100, 100)

        def mock_run_workflow(name, variables):
            assert name == "change_background"
            assert "prompt" in variables
            return {
                "media": {
                    "images": ["http://localhost:8000/files/newbg_test.png"],
                    "videos": []
                }
            }

        monkeypatch.setattr("app.background._get_image_and_size", mock_get_image_and_size)
        monkeypatch.setattr("app.background.run_workflow", mock_run_workflow)

        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "replace",
            "prompt": "a beautiful sunset beach"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["action_used"] == "replace"
        assert data["has_alpha"] == False

    def test_background_respects_max_size_guardrail(self, client, mock_outbound, monkeypatch):
        """Test that image size is limited to 4096px max edge."""
        def mock_get_image_and_size(url):
            return MINIMAL_PNG, (5000, 5000)  # Too large

        monkeypatch.setattr("app.background._get_image_and_size", mock_get_image_and_size)

        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png",
            "action": "blur"
        })

        assert response.status_code == 400
        assert "too large" in response.text.lower() or "max" in response.text.lower()

    def test_background_default_action(self, client, mock_outbound, monkeypatch):
        """Test that default action (remove) is used if not specified."""
        captured_action = {}

        def mock_get_image_and_size(url):
            return MINIMAL_PNG, (100, 100)

        def mock_remove_background_pil(img_bytes):
            captured_action["called"] = True
            return img_bytes, True

        def mock_save_image(data, prefix="bg", ext="png"):
            return "/files/test_nobg.png"

        monkeypatch.setattr("app.background._get_image_and_size", mock_get_image_and_size)
        monkeypatch.setattr("app.background._remove_background_pil", mock_remove_background_pil)
        monkeypatch.setattr("app.background._save_image_to_uploads", mock_save_image)

        response = client.post("/v1/background", json={
            "image_url": "http://localhost:8000/files/test.png"
            # No action specified - should default to "remove"
        })

        assert response.status_code == 200
        assert captured_action.get("called") == True
        data = response.json()
        assert data["action_used"] == "remove"


class TestBackgroundWorkflows:
    """Test the background workflow files exist."""

    def test_remove_background_workflow_exists(self):
        """Test that remove_background.json workflow file exists."""
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "remove_background.json"

        assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    def test_change_background_workflow_exists(self):
        """Test that change_background.json workflow file exists."""
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent
        workflow_path = repo_root / "comfyui" / "workflows" / "change_background.json"

        assert workflow_path.exists(), f"Workflow not found at {workflow_path}"

    def test_workflows_have_required_nodes(self):
        """Test that background workflows have required ComfyUI nodes."""
        import json
        from pathlib import Path

        current_file = Path(__file__).resolve()
        repo_root = current_file.parent.parent.parent

        # Check remove_background workflow
        workflow_path = repo_root / "comfyui" / "workflows" / "remove_background.json"
        with open(workflow_path) as f:
            workflow = json.load(f)
        node_types = {node.get("class_type") for node in workflow.values() if isinstance(node, dict)}
        assert "LoadImage" in node_types, "Missing LoadImage node in remove_background"
        assert "SaveImage" in node_types, "Missing SaveImage node in remove_background"

        # Check change_background workflow
        workflow_path = repo_root / "comfyui" / "workflows" / "change_background.json"
        with open(workflow_path) as f:
            workflow = json.load(f)
        node_types = {node.get("class_type") for node in workflow.values() if isinstance(node, dict)}
        assert "LoadImage" in node_types, "Missing LoadImage node in change_background"
        assert "SaveImage" in node_types, "Missing SaveImage node in change_background"
        assert "KSampler" in node_types, "Missing KSampler node in change_background"
