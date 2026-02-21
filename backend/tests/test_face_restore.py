"""
Tests for the face restoration service (face_restore.py).

Architecture: ComfyUI-only.  The backend never imports torch/gfpgan/ML libs.
All face restoration runs through ComfyUI's fix_faces_facedetailer workflow
(FaceDetailer node from Impact-Pack).

These tests verify:
1. ComfyUI health check logic
2. Node readiness check (Impact-Pack installed?)
3. restore_faces_via_comfyui() happy path and error paths
4. Enhance endpoint integration (faces mode uses ComfyUI)
5. Clear error messages when ComfyUI is down or nodes missing
"""

import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Unit tests for face_restore.py
# ---------------------------------------------------------------------------

class TestComfyUIHealthCheck:
    """Test comfyui_healthy() liveness check."""

    def test_healthy_when_comfyui_responds_200(self, monkeypatch):
        """Returns True when ComfyUI /system_stats returns 200."""
        import app.face_restore as fr

        mock_response = MagicMock()
        mock_response.status_code = 200

        import httpx
        monkeypatch.setattr(httpx, "get", lambda url, **kw: mock_response)

        assert fr.comfyui_healthy() is True

    def test_unhealthy_when_comfyui_down(self, monkeypatch):
        """Returns False when ComfyUI is unreachable."""
        import app.face_restore as fr

        import httpx
        monkeypatch.setattr(
            httpx, "get",
            lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        )

        assert fr.comfyui_healthy() is False

    def test_unhealthy_when_comfyui_returns_500(self, monkeypatch):
        """Returns False when ComfyUI returns non-200."""
        import app.face_restore as fr

        mock_response = MagicMock()
        mock_response.status_code = 500

        import httpx
        monkeypatch.setattr(httpx, "get", lambda url, **kw: mock_response)

        assert fr.comfyui_healthy() is False


class TestFaceRestoreReady:
    """Test face_restore_ready() readiness check."""

    def test_ready_when_comfyui_healthy_and_nodes_present(self, monkeypatch):
        """Returns (True, ...) when ComfyUI is up and nodes are registered."""
        import app.face_restore as fr

        monkeypatch.setattr(fr, "comfyui_healthy", lambda: True)
        monkeypatch.setattr("app.comfy.check_nodes_available",
                            lambda nodes: (True, []))

        ok, msg = fr.face_restore_ready()
        assert ok is True
        assert "ready" in msg.lower()

    def test_not_ready_when_comfyui_down(self, monkeypatch):
        """Returns (False, ...) when ComfyUI is unreachable."""
        import app.face_restore as fr

        monkeypatch.setattr(fr, "comfyui_healthy", lambda: False)

        ok, msg = fr.face_restore_ready()
        assert ok is False
        assert "not reachable" in msg.lower()

    def test_not_ready_when_nodes_missing(self, monkeypatch):
        """Returns (False, ...) when Impact-Pack nodes are not registered."""
        import app.face_restore as fr

        monkeypatch.setattr(fr, "comfyui_healthy", lambda: True)
        monkeypatch.setattr("app.comfy.check_nodes_available",
                            lambda nodes: (False, ["FaceDetailer"]))

        ok, msg = fr.face_restore_ready()
        assert ok is False
        assert "FaceDetailer" in msg
        assert "Impact-Pack" in msg

    def test_install_hint_mentions_ultralytics(self):
        """Install hint should mention pip install ultralytics."""
        import app.face_restore as fr
        assert "pip install ultralytics" in fr._INSTALL_HINT, (
            "Install hint should mention ultralytics for UltralyticsDetectorProvider"
        )


class TestRestoreFacesViaComfyUI:
    """Test restore_faces_via_comfyui() workflow submission."""

    def test_success_returns_images(self, monkeypatch):
        """Happy path: ComfyUI processes the workflow and returns images."""
        import app.face_restore as fr

        monkeypatch.setattr(fr, "comfyui_healthy", lambda: True)
        monkeypatch.setattr(fr, "_find_checkpoint",
                            lambda: "sd_xl_base_1.0.safetensors")
        monkeypatch.setattr("app.comfy.check_nodes_available",
                            lambda nodes: (True, []))
        monkeypatch.setattr("app.comfy.run_workflow", lambda name, vars: {
            "images": ["http://comfyui:8188/view?filename=restored.png"],
            "videos": [],
        })

        result = fr.restore_faces_via_comfyui(
            "http://localhost:8000/files/test.png",
            "GFPGANv1.4.pth",
        )

        assert "images" in result
        assert len(result["images"]) == 1

    def test_raises_when_comfyui_down(self, monkeypatch):
        """Raises ComfyUIUnavailable when ComfyUI is offline."""
        import app.face_restore as fr

        monkeypatch.setattr(fr, "comfyui_healthy", lambda: False)

        with pytest.raises(fr.ComfyUIUnavailable, match="not reachable"):
            fr.restore_faces_via_comfyui("http://localhost:8000/files/test.png")

    def test_raises_when_nodes_missing(self, monkeypatch):
        """Raises FaceRestoreNodesNotInstalled when Impact-Pack is missing."""
        import app.face_restore as fr

        monkeypatch.setattr(fr, "comfyui_healthy", lambda: True)
        monkeypatch.setattr("app.comfy.check_nodes_available",
                            lambda nodes: (False, ["FaceDetailer"]))

        with pytest.raises(fr.FaceRestoreNodesNotInstalled, match="Impact-Pack"):
            fr.restore_faces_via_comfyui("http://localhost:8000/files/test.png")

    def test_raises_runtime_error_on_workflow_failure(self, monkeypatch):
        """Propagates RuntimeError when the ComfyUI workflow fails."""
        import app.face_restore as fr

        monkeypatch.setattr(fr, "comfyui_healthy", lambda: True)
        monkeypatch.setattr(fr, "_find_checkpoint",
                            lambda: "sd_xl_base_1.0.safetensors")
        monkeypatch.setattr("app.comfy.check_nodes_available",
                            lambda nodes: (True, []))

        def boom(name, vars):
            raise RuntimeError("ComfyUI internal error")

        monkeypatch.setattr("app.comfy.run_workflow", boom)

        with pytest.raises(RuntimeError, match="internal error"):
            fr.restore_faces_via_comfyui("http://localhost:8000/files/test.png")


# ---------------------------------------------------------------------------
# Integration tests for enhance endpoint (faces mode)
# ---------------------------------------------------------------------------

class TestEnhanceFacesMode:
    """Test the /v1/enhance endpoint with mode=faces."""

    def test_faces_mode_calls_comfyui(self, client, mock_outbound, monkeypatch):
        """Face restoration goes through ComfyUI (no standalone ML)."""

        @dataclass
        class MockConfig:
            mode: str = "faces"
            name: str = "Face Restoration"
            description: str = "Restore faces"
            workflow: str = "fix_faces_facedetailer"
            model_category: str = "face_restore"
            default_model_id: str = "GFPGANv1.4"
            param_name: str = "model_name"

        def mock_get_image_size(url):
            return (512, 512)

        def mock_get_enhance_model(mode):
            return ("GFPGANv1.4.pth", None, MockConfig())

        def mock_restore(image_url, model_filename="GFPGANv1.4.pth"):
            return {
                "images": ["http://comfyui:8188/view?filename=restored.png"],
                "videos": [],
            }

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.get_enhance_model", mock_get_enhance_model)
        monkeypatch.setattr("app.enhance.restore_faces_via_comfyui", mock_restore)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "faces",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["mode_used"] == "faces"
        assert data["model_used"] == "GFPGANv1.4.pth"

    def test_faces_mode_returns_503_when_comfyui_down(self, client, mock_outbound, monkeypatch):
        """Returns 503 with clear message when ComfyUI is offline."""

        @dataclass
        class MockConfig:
            mode: str = "faces"
            name: str = "Face Restoration"
            description: str = "Restore faces"
            workflow: str = "fix_faces_facedetailer"
            model_category: str = "face_restore"
            default_model_id: str = "GFPGANv1.4"
            param_name: str = "model_name"

        def mock_get_image_size(url):
            return (512, 512)

        def mock_get_enhance_model(mode):
            return ("GFPGANv1.4.pth", None, MockConfig())

        from app.face_restore import ComfyUIUnavailable

        def mock_restore(image_url, model_filename="GFPGANv1.4.pth"):
            raise ComfyUIUnavailable("ComfyUI is not reachable")

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.get_enhance_model", mock_get_enhance_model)
        monkeypatch.setattr("app.enhance.restore_faces_via_comfyui", mock_restore)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "faces",
        })

        assert response.status_code == 503
        assert "not reachable" in response.text.lower()

    def test_faces_mode_returns_503_when_nodes_missing(self, client, mock_outbound, monkeypatch):
        """Returns 503 with install instructions when Impact-Pack is missing."""

        @dataclass
        class MockConfig:
            mode: str = "faces"
            name: str = "Face Restoration"
            description: str = "Restore faces"
            workflow: str = "fix_faces_facedetailer"
            model_category: str = "face_restore"
            default_model_id: str = "GFPGANv1.4"
            param_name: str = "model_name"

        def mock_get_image_size(url):
            return (512, 512)

        def mock_get_enhance_model(mode):
            return ("GFPGANv1.4.pth", None, MockConfig())

        from app.face_restore import FaceRestoreNodesNotInstalled

        def mock_restore(image_url, model_filename="GFPGANv1.4.pth"):
            raise FaceRestoreNodesNotInstalled(
                "Missing nodes: FaceDetailer.\n"
                "Fix: install ComfyUI-Impact-Pack"
            )

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.get_enhance_model", mock_get_enhance_model)
        monkeypatch.setattr("app.enhance.restore_faces_via_comfyui", mock_restore)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "faces",
        })

        assert response.status_code == 503
        assert "impact-pack" in response.text.lower()

    def test_photo_mode_still_uses_workflow(self, client, mock_outbound, monkeypatch):
        """Photo mode uses ComfyUI workflow directly (not face restore path)."""

        @dataclass
        class MockConfig:
            mode: str = "photo"
            name: str = "Photo Enhancement"
            description: str = "Enhance photo"
            workflow: str = "upscale"
            model_category: str = "upscale"
            default_model_id: str = "4x-UltraSharp"
            param_name: str = "upscale_model"

        def mock_get_image_size(url):
            return (512, 512)

        def mock_get_enhance_model(mode):
            return ("4x-UltraSharp.pth", None, MockConfig())

        def mock_run_workflow(name, variables):
            assert name == "upscale"
            return {"images": ["/files/enhanced.png"], "videos": []}

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.get_enhance_model", mock_get_enhance_model)
        monkeypatch.setattr("app.enhance.run_workflow", mock_run_workflow)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "photo",
            "scale": 2,
        })

        assert response.status_code == 200
        data = response.json()
        assert data["mode_used"] == "photo"


# ---------------------------------------------------------------------------
# Test that backend has NO ML dependencies
# ---------------------------------------------------------------------------

class TestNoMLImports:
    """Verify the backend never imports ML libraries."""

    def test_face_restore_module_has_no_ml_imports(self):
        """face_restore.py must not import torch, gfpgan, basicsr, etc."""
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "app" / "face_restore.py"
        content = src.read_text()

        banned = ["import torch", "import gfpgan", "import basicsr",
                   "import facexlib", "import cv2", "from gfpgan",
                   "from basicsr", "from facexlib"]
        for keyword in banned:
            assert keyword not in content, (
                f"face_restore.py must NOT contain '{keyword}'. "
                f"All ML work runs in ComfyUI."
            )

    def test_enhance_module_has_no_ml_imports(self):
        """enhance.py must not import torch, gfpgan, basicsr, etc."""
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "app" / "enhance.py"
        content = src.read_text()

        banned = ["import torch", "import gfpgan", "import basicsr",
                   "import facexlib", "from gfpgan", "from basicsr",
                   "from facexlib"]
        for keyword in banned:
            assert keyword not in content, (
                f"enhance.py must NOT contain '{keyword}'. "
                f"All ML work runs in ComfyUI."
            )
