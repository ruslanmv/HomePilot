"""
Tests for persona avatar commit (Phase 3 — must never break).

Validates:
  - commit_persona_avatar copies image into project-owned storage
  - Thumbnail is generated as .webp
  - Relative paths are correct for /files serving
  - Invalid filenames are rejected (path traversal prevention)
  - Missing source raises FileNotFoundError

Non-destructive: uses tmp_path from pytest.
CI-friendly: no network, no LLM, only PIL for thumbnail.
"""
import struct
from pathlib import Path

import pytest
from PIL import Image


def _create_test_image(path: Path, width: int = 128, height: int = 192) -> None:
    """Create a real PNG image for testing (portrait ratio for face crop)."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    img.save(path, format="PNG")


class TestAvatarCommit:
    """Avatar commit to project-owned storage."""

    def test_commit_creates_owned_avatar_and_thumb(self, tmp_path: Path):
        from app.personas.avatar_assets import commit_persona_avatar

        upload_root = tmp_path / "uploads"
        upload_root.mkdir(parents=True, exist_ok=True)

        # Create a realistic source image (as ComfyUI would generate)
        src = upload_root / "ComfyUI_00001_.png"
        _create_test_image(src)

        project_root = upload_root / "projects" / "pid123"
        project_root.mkdir(parents=True, exist_ok=True)

        result = commit_persona_avatar(upload_root, project_root, "ComfyUI_00001_.png")

        # Paths should be relative to upload_root
        assert result.selected_filename.startswith("projects/pid123/persona/appearance/avatar_")
        assert result.thumb_filename.startswith("projects/pid123/persona/appearance/thumb_avatar_")
        assert result.thumb_filename.endswith(".webp")

        # Files must actually exist on disk
        avatar_path = upload_root / result.selected_filename
        thumb_path = upload_root / result.thumb_filename
        assert avatar_path.exists(), f"Avatar file not found: {avatar_path}"
        assert thumb_path.exists(), f"Thumbnail file not found: {thumb_path}"

        # Thumbnail should be a valid image
        with Image.open(thumb_path) as im:
            assert im.size == (256, 256)
            assert im.format == "WEBP"

    def test_commit_preserves_extension(self, tmp_path: Path):
        from app.personas.avatar_assets import commit_persona_avatar

        upload_root = tmp_path / "uploads"
        upload_root.mkdir(parents=True, exist_ok=True)

        src = upload_root / "portrait.jpg"
        _create_test_image(src)
        src.rename(upload_root / "portrait.jpg")  # keep extension
        _create_test_image(upload_root / "portrait.jpg")

        project_root = upload_root / "projects" / "pid456"
        project_root.mkdir(parents=True, exist_ok=True)

        result = commit_persona_avatar(upload_root, project_root, "portrait.jpg")

        assert result.selected_filename.endswith(".jpg")
        assert result.thumb_filename.endswith(".webp")  # thumb always webp

    def test_commit_rejects_path_traversal(self, tmp_path: Path):
        from app.personas.avatar_assets import commit_persona_avatar

        upload_root = tmp_path / "uploads"
        upload_root.mkdir(parents=True, exist_ok=True)

        project_root = upload_root / "projects" / "pid789"
        project_root.mkdir(parents=True, exist_ok=True)

        with pytest.raises(ValueError, match="Invalid filename"):
            commit_persona_avatar(upload_root, project_root, "../../etc/passwd")

        with pytest.raises(ValueError, match="Invalid filename"):
            commit_persona_avatar(upload_root, project_root, "..")

    def test_commit_raises_on_missing_source(self, tmp_path: Path):
        from app.personas.avatar_assets import commit_persona_avatar

        upload_root = tmp_path / "uploads"
        upload_root.mkdir(parents=True, exist_ok=True)

        project_root = upload_root / "projects" / "pid000"
        project_root.mkdir(parents=True, exist_ok=True)

        with pytest.raises(FileNotFoundError, match="Source image not found"):
            commit_persona_avatar(upload_root, project_root, "nonexistent.png")

    def test_commit_idempotent(self, tmp_path: Path):
        """Committing the same image twice overwrites cleanly."""
        from app.personas.avatar_assets import commit_persona_avatar

        upload_root = tmp_path / "uploads"
        upload_root.mkdir(parents=True, exist_ok=True)

        src = upload_root / "avatar_gen.png"
        _create_test_image(src)

        project_root = upload_root / "projects" / "pidX"
        project_root.mkdir(parents=True, exist_ok=True)

        r1 = commit_persona_avatar(upload_root, project_root, "avatar_gen.png")
        r2 = commit_persona_avatar(upload_root, project_root, "avatar_gen.png")

        assert r1.selected_filename == r2.selected_filename
        assert r1.thumb_filename == r2.thumb_filename

        # Only one avatar + one thumb should exist
        appearance_dir = project_root / "persona" / "appearance"
        files = list(appearance_dir.iterdir())
        assert len(files) == 2  # avatar + thumb


class TestTopCropThumb:
    """Thumbnail generation edge cases."""

    def test_square_image(self, tmp_path: Path):
        """Square input should produce a 256x256 thumb without distortion."""
        from app.personas.avatar_assets import _top_crop_thumb

        src = tmp_path / "square.png"
        _create_test_image(src, width=512, height=512)

        dst = tmp_path / "thumb.webp"
        _top_crop_thumb(src, dst, size=256)

        with Image.open(dst) as im:
            assert im.size == (256, 256)

    def test_landscape_image(self, tmp_path: Path):
        """Landscape input: crop center-top square, then resize."""
        from app.personas.avatar_assets import _top_crop_thumb

        src = tmp_path / "landscape.png"
        _create_test_image(src, width=800, height=400)

        dst = tmp_path / "thumb.webp"
        _top_crop_thumb(src, dst, size=256)

        with Image.open(dst) as im:
            assert im.size == (256, 256)

    def test_tall_portrait(self, tmp_path: Path):
        """Tall portrait: crop top square (face zone)."""
        from app.personas.avatar_assets import _top_crop_thumb

        src = tmp_path / "tall.png"
        _create_test_image(src, width=300, height=900)

        dst = tmp_path / "thumb.webp"
        _top_crop_thumb(src, dst, size=256)

        with Image.open(dst) as im:
            assert im.size == (256, 256)
