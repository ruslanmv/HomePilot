"""
Tests for the standalone face restoration service (face_restore.py).

These tests verify:
1. Availability checking logic
2. Model path discovery
3. Fallback chain in enhance endpoint (standalone → ComfyUI → error)
4. Image processing flow (mocked)
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass
from pathlib import Path


class TestStandaloneAvailability:
    """Test check_standalone_available() dependency detection."""

    def test_available_when_all_deps_present(self, monkeypatch):
        """When gfpgan, facexlib, basicsr, torch are importable and model exists."""
        import app.face_restore as fr

        # Reset cache
        fr._gfpgan_available = None

        # Mock all imports as successful
        import importlib
        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        # Mock _find_model_path to return a valid path
        monkeypatch.setattr(fr, "_find_model_path", lambda name: Path("/fake/GFPGANv1.4.pth"))

        # Mock the import checks by pre-setting the cache
        fr._gfpgan_available = True
        ok, reason = fr.check_standalone_available()
        assert ok is True
        assert "ready" in reason.lower()

    def test_unavailable_when_gfpgan_missing(self, monkeypatch):
        """When gfpgan is not installed."""
        import app.face_restore as fr

        # Reset cache
        fr._gfpgan_available = None

        # Make gfpgan import fail
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == 'gfpgan':
                raise ImportError("No module named 'gfpgan'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        ok, reason = fr.check_standalone_available()
        assert ok is False
        assert "gfpgan" in reason.lower()

    def test_unavailable_when_model_missing(self, monkeypatch):
        """When dependencies are installed but model weights are missing."""
        import app.face_restore as fr

        # Reset cache
        fr._gfpgan_available = None

        # Mock all imports as available
        for mod_name in ['torch', 'gfpgan', 'facexlib', 'basicsr']:
            monkeypatch.setitem(__import__('sys').modules, mod_name, MagicMock())

        # But model file doesn't exist
        monkeypatch.setattr(fr, "_find_model_path", lambda name: None)

        ok, reason = fr.check_standalone_available()
        assert ok is False
        assert "not found" in reason.lower() or "model" in reason.lower()


class TestModelPathDiscovery:
    """Test _find_model_path() model file search logic."""

    def test_finds_model_in_comfy_gfpgan_dir(self, tmp_path, monkeypatch):
        """Model found in models/comfy/gfpgan/."""
        import app.face_restore as fr

        # Create fake model file
        model_dir = tmp_path / "models" / "comfy" / "gfpgan"
        model_dir.mkdir(parents=True)
        model_file = model_dir / "GFPGANv1.4.pth"
        model_file.write_bytes(b"fake model data")

        # Override search dirs to include our tmp_path
        original_find = fr._find_model_path

        def patched_find(model_filename="GFPGANv1.4.pth"):
            candidate = model_dir / model_filename
            if candidate.exists() and candidate.stat().st_size > 0:
                return candidate
            return None

        monkeypatch.setattr(fr, "_find_model_path", patched_find)

        result = fr._find_model_path("GFPGANv1.4.pth")
        assert result is not None
        assert result.name == "GFPGANv1.4.pth"

    def test_returns_none_when_no_model(self, monkeypatch):
        """Returns None when model file not found anywhere."""
        import app.face_restore as fr

        # Make all paths non-existent
        monkeypatch.setattr(fr, "_find_model_path", lambda name: None)
        assert fr._find_model_path("GFPGANv1.4.pth") is None


class TestRestoreFaces:
    """Test the restore_faces() processing function."""

    def test_restore_faces_returns_filename_on_success(self, monkeypatch, tmp_path):
        """Successful face restoration returns output filename."""
        import app.face_restore as fr

        # Mock cv2 and numpy
        mock_cv2 = MagicMock()
        mock_np = MagicMock()

        # Mock image loading
        fake_img = MagicMock()
        fake_img.shape = (512, 512, 3)
        mock_cv2.imread.return_value = fake_img
        mock_cv2.IMREAD_COLOR = 1
        mock_cv2.imwrite.return_value = True

        # Mock GFPGANer
        mock_restorer = MagicMock()
        mock_restorer.enhance.return_value = (
            [fake_img],  # cropped_faces
            [fake_img],  # restored_faces
            fake_img,    # output_img
        )

        monkeypatch.setattr(fr, "_get_gfpganer", lambda **kw: mock_restorer)
        monkeypatch.setattr(fr, "UPLOAD_DIR", str(tmp_path))

        # Mock imports inside restore_faces
        import sys
        sys.modules['cv2'] = mock_cv2
        sys.modules['numpy'] = mock_np

        output_filename, error = fr.restore_faces(
            image_path=str(tmp_path / "test.png"),
            model_name="GFPGANv1.4.pth",
        )

        # Clean up mocked modules
        del sys.modules['cv2']
        del sys.modules['numpy']

        # restore_faces should have called enhance()
        mock_restorer.enhance.assert_called_once()

    def test_restore_faces_handles_no_faces(self, monkeypatch, tmp_path):
        """Returns error when no faces are detected."""
        import app.face_restore as fr

        mock_cv2 = MagicMock()
        mock_np = MagicMock()

        fake_img = MagicMock()
        fake_img.shape = (512, 512, 3)
        mock_cv2.imread.return_value = fake_img
        mock_cv2.IMREAD_COLOR = 1

        # GFPGANer returns no faces
        mock_restorer = MagicMock()
        mock_restorer.enhance.return_value = ([], [], None)

        monkeypatch.setattr(fr, "_get_gfpganer", lambda **kw: mock_restorer)
        monkeypatch.setattr(fr, "UPLOAD_DIR", str(tmp_path))

        import sys
        sys.modules['cv2'] = mock_cv2
        sys.modules['numpy'] = mock_np

        output_filename, error = fr.restore_faces(
            image_path=str(tmp_path / "test.png"),
        )

        del sys.modules['cv2']
        del sys.modules['numpy']

        assert output_filename is None
        assert error is not None
        assert "no face" in error.lower()

    def test_restore_faces_handles_invalid_image(self, monkeypatch, tmp_path):
        """Returns error when image cannot be loaded."""
        import app.face_restore as fr

        mock_cv2 = MagicMock()
        mock_np = MagicMock()

        mock_cv2.imread.return_value = None
        mock_cv2.IMREAD_COLOR = 1

        monkeypatch.setattr(fr, "UPLOAD_DIR", str(tmp_path))

        import sys
        sys.modules['cv2'] = mock_cv2
        sys.modules['numpy'] = mock_np

        output_filename, error = fr.restore_faces(
            image_path=str(tmp_path / "nonexistent.png"),
        )

        del sys.modules['cv2']
        del sys.modules['numpy']

        assert output_filename is None
        assert error is not None
        assert "failed to load" in error.lower()


class TestEnhanceFallbackChain:
    """Test the fallback chain in the enhance endpoint."""

    def test_faces_mode_uses_standalone_first(self, client, mock_outbound, monkeypatch):
        """Face restoration should try standalone before ComfyUI."""

        @dataclass
        class MockConfig:
            mode: str = "faces"
            name: str = "Face Restoration"
            description: str = "Restore faces"
            workflow: str = "fix_faces_gfpgan"
            model_category: str = "face_restore"
            default_model_id: str = "GFPGANv1.4"
            param_name: str = "model_name"

        calls = {"standalone": 0, "comfyui": 0}

        def mock_get_image_size(url):
            return (512, 512)

        def mock_get_enhance_model(mode):
            return ("GFPGANv1.4.pth", None, MockConfig())

        def mock_standalone(image_url, model_filename):
            calls["standalone"] += 1
            return {"images": ["/files/restored.png"], "videos": []}

        def mock_comfyui(image_url, model_filename):
            calls["comfyui"] += 1
            return {"images": ["/files/restored_comfy.png"], "videos": []}

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.get_enhance_model", mock_get_enhance_model)
        monkeypatch.setattr("app.enhance._run_face_restore_standalone", mock_standalone)
        monkeypatch.setattr("app.enhance._run_face_restore_comfyui", mock_comfyui)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "faces",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["mode_used"] == "faces"
        assert "standalone" in data["model_used"]
        # Standalone was tried first and succeeded
        assert calls["standalone"] == 1
        assert calls["comfyui"] == 0

    def test_faces_mode_falls_back_to_comfyui(self, client, mock_outbound, monkeypatch):
        """When standalone fails, falls back to ComfyUI."""

        @dataclass
        class MockConfig:
            mode: str = "faces"
            name: str = "Face Restoration"
            description: str = "Restore faces"
            workflow: str = "fix_faces_gfpgan"
            model_category: str = "face_restore"
            default_model_id: str = "GFPGANv1.4"
            param_name: str = "model_name"

        calls = {"standalone": 0, "comfyui": 0}

        def mock_get_image_size(url):
            return (512, 512)

        def mock_get_enhance_model(mode):
            return ("GFPGANv1.4.pth", None, MockConfig())

        def mock_standalone(image_url, model_filename):
            calls["standalone"] += 1
            return None  # Standalone not available

        def mock_comfyui(image_url, model_filename):
            calls["comfyui"] += 1
            return {"images": ["/files/restored_comfy.png"], "videos": []}

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.get_enhance_model", mock_get_enhance_model)
        monkeypatch.setattr("app.enhance._run_face_restore_standalone", mock_standalone)
        monkeypatch.setattr("app.enhance._run_face_restore_comfyui", mock_comfyui)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "faces",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["mode_used"] == "faces"
        assert "comfyui" in data["model_used"]
        # Standalone tried first, then ComfyUI
        assert calls["standalone"] == 1
        assert calls["comfyui"] == 1

    def test_faces_mode_returns_503_when_both_fail(self, client, mock_outbound, monkeypatch):
        """When both standalone and ComfyUI fail, returns 503 with instructions."""

        @dataclass
        class MockConfig:
            mode: str = "faces"
            name: str = "Face Restoration"
            description: str = "Restore faces"
            workflow: str = "fix_faces_gfpgan"
            model_category: str = "face_restore"
            default_model_id: str = "GFPGANv1.4"
            param_name: str = "model_name"

        def mock_get_image_size(url):
            return (512, 512)

        def mock_get_enhance_model(mode):
            return ("GFPGANv1.4.pth", None, MockConfig())

        def mock_standalone(image_url, model_filename):
            return None

        def mock_comfyui(image_url, model_filename):
            return None

        def mock_check_standalone():
            return (False, "Missing Python packages: gfpgan")

        monkeypatch.setattr("app.enhance._get_image_size", mock_get_image_size)
        monkeypatch.setattr("app.enhance.get_enhance_model", mock_get_enhance_model)
        monkeypatch.setattr("app.enhance._run_face_restore_standalone", mock_standalone)
        monkeypatch.setattr("app.enhance._run_face_restore_comfyui", mock_comfyui)
        monkeypatch.setattr("app.enhance.check_standalone_available", mock_check_standalone)

        response = client.post("/v1/enhance", json={
            "image_url": "http://localhost:8000/files/test.png",
            "mode": "faces",
        })

        assert response.status_code == 503
        body = response.text.lower()
        assert "option a" in body or "standalone" in body
        assert "option b" in body or "comfyui" in body

    def test_photo_mode_still_uses_workflow(self, client, mock_outbound, monkeypatch):
        """Photo mode should NOT use the face restore fallback chain."""

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


class TestCacheInvalidation:
    """Test model cache management."""

    def test_invalidate_clears_cache(self):
        """invalidate_model_cache() resets singleton and availability flag."""
        import app.face_restore as fr

        fr._gfpganer_instance = "fake_instance"
        fr._gfpgan_available = True

        fr.invalidate_model_cache()

        assert fr._gfpganer_instance is None
        assert fr._gfpgan_available is None
