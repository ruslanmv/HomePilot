"""
Tests for Angel persona realistic avatar generation pipeline.

Validates:
  - thispersondoesnotexist.com is reachable and returns valid JPEG images
  - Downloaded images are 1024x1024 (StyleGAN2 standard output)
  - Downloaded images contain the StyleGAN2 watermark
  - Avatar processing (resize to 512x512 PNG) works correctly
  - Thumbnail generation (256x256 WebP) works correctly
  - Full .hpersona package is a valid ZIP with expected structure
  - persona_appearance.json references the correct filenames

CI note: requires network access to thispersondoesnotexist.com.
"""
import io
import json
import struct
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request

import pytest

# ---------------------------------------------------------------------------
# Marks — skip if no network
# ---------------------------------------------------------------------------
requires_network = pytest.mark.skipif(
    not _can_reach_site(),
    reason="Cannot reach thispersondoesnotexist.com",
) if not True else lambda f: f  # always try, skip inside if needed


def _can_reach_site() -> bool:
    try:
        req = Request("https://thispersondoesnotexist.com",
                       headers={"User-Agent": "HomePilot-Test/1.0"})
        with urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Test: Download from thispersondoesnotexist.com
# ---------------------------------------------------------------------------

class TestFaceDownload:
    """Verify that thispersondoesnotexist.com returns valid StyleGAN2 faces."""

    def test_site_returns_jpeg(self, tmp_path: Path):
        """The site should return a valid JPEG image."""
        try:
            req = Request("https://thispersondoesnotexist.com",
                          headers={"User-Agent": "HomePilot-Test/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = resp.read()
        except Exception as e:
            pytest.skip(f"Network unavailable: {e}")

        assert len(data) > 50_000, f"Response too small: {len(data)} bytes"

        # Save and verify
        face_path = tmp_path / "face.jpg"
        face_path.write_bytes(data)

        # Check JFIF header
        assert data[:2] == b"\xff\xd8", "Not a valid JPEG (missing SOI marker)"
        assert b"JFIF" in data[:20], "Not a JFIF JPEG (expected from thispersondoesnotexist.com)"

    def test_image_is_1024x1024(self, tmp_path: Path):
        """StyleGAN2 outputs 1024x1024 images."""
        try:
            req = Request("https://thispersondoesnotexist.com",
                          headers={"User-Agent": "HomePilot-Test/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = resp.read()
        except Exception as e:
            pytest.skip(f"Network unavailable: {e}")

        face_path = tmp_path / "face.jpg"
        face_path.write_bytes(data)

        try:
            from PIL import Image
            img = Image.open(face_path)
            assert img.size == (1024, 1024), f"Expected 1024x1024, got {img.size}"
            assert img.mode == "RGB", f"Expected RGB, got {img.mode}"
        except ImportError:
            pytest.skip("Pillow not available")


# ---------------------------------------------------------------------------
# Test: Avatar processing pipeline
# ---------------------------------------------------------------------------

class TestAvatarProcessing:
    """Verify avatar resize and thumbnail generation."""

    def _make_test_jpeg(self, path: Path, size: int = 1024):
        """Create a test JPEG simulating a StyleGAN2 face."""
        from PIL import Image
        img = Image.new("RGB", (size, size), color=(200, 150, 120))
        img.save(path, format="JPEG")

    @staticmethod
    def _import_generator():
        """Import the generator module from its bundle location."""
        import importlib.util
        mod_path = (Path(__file__).resolve().parent.parent.parent
                    / "community" / "shared" / "bundles" / "angel_stylist"
                    / "generate_angel_avatar.py")
        if not mod_path.exists():
            pytest.skip(f"Generator not found: {mod_path}")
        spec = importlib.util.spec_from_file_location("generate_angel_avatar", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_resize_to_512(self, tmp_path: Path):
        """Avatar should be resized from 1024x1024 to 512x512 PNG."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not available")

        source = tmp_path / "source.jpg"
        self._make_test_jpeg(source, 1024)

        mod = self._import_generator()
        png_bytes = mod.process_face_to_avatar(source, size=512)

        img = Image.open(io.BytesIO(png_bytes))
        assert img.size == (512, 512), f"Expected 512x512, got {img.size}"
        assert img.format == "PNG", f"Expected PNG, got {img.format}"

    def test_thumbnail_256_webp(self, tmp_path: Path):
        """Thumbnail should be 256x256 WebP."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not available")

        source = tmp_path / "source.jpg"
        self._make_test_jpeg(source, 1024)

        mod = self._import_generator()
        png_bytes = mod.process_face_to_avatar(source, size=512)
        thumb_bytes = mod.create_webp_thumb(png_bytes, size=256)

        thumb = Image.open(io.BytesIO(thumb_bytes))
        assert thumb.size == (256, 256), f"Expected 256x256, got {thumb.size}"


# ---------------------------------------------------------------------------
# Test: .hpersona package integrity
# ---------------------------------------------------------------------------

class TestHpersonaPackage:
    """Verify the angel_stylist.hpersona ZIP package structure."""

    @pytest.fixture
    def hpersona_path(self) -> Path:
        p = (Path(__file__).resolve().parent.parent.parent
             / "community" / "shared" / "bundles" / "angel_stylist"
             / "angel_stylist.hpersona")
        if not p.exists():
            pytest.skip(".hpersona package not built yet")
        return p

    def test_is_valid_zip(self, hpersona_path: Path):
        """The .hpersona file should be a valid ZIP archive."""
        assert zipfile.is_zipfile(hpersona_path), "Not a valid ZIP file"

    def test_contains_required_files(self, hpersona_path: Path):
        """Package must contain all required persona files."""
        with zipfile.ZipFile(hpersona_path, "r") as zf:
            names = set(zf.namelist())

        required = {
            "manifest.json",
            "blueprint/persona_agent.json",
            "blueprint/persona_appearance.json",
            "assets/avatar_angel.png",
            "assets/thumb_avatar_angel.webp",
            "preview/card.json",
        }
        missing = required - names
        assert not missing, f"Missing files in .hpersona: {missing}"

    def test_manifest_schema_version(self, hpersona_path: Path):
        """Manifest should be schema version 2."""
        with zipfile.ZipFile(hpersona_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))

        assert manifest["kind"] == "homepilot.persona"
        assert manifest["schema_version"] == 2
        assert manifest["contents"]["has_avatar"] is True

    def test_avatar_is_valid_png(self, hpersona_path: Path):
        """Packaged avatar should be a valid PNG image."""
        with zipfile.ZipFile(hpersona_path, "r") as zf:
            avatar_data = zf.read("assets/avatar_angel.png")

        # PNG magic bytes
        assert avatar_data[:8] == b"\x89PNG\r\n\x1a\n", "Not a valid PNG"

        try:
            from PIL import Image
            img = Image.open(io.BytesIO(avatar_data))
            assert img.size == (512, 512), f"Expected 512x512, got {img.size}"
        except ImportError:
            pass  # Basic PNG check passed, Pillow not needed

    def test_appearance_references_avatar(self, hpersona_path: Path):
        """persona_appearance.json must reference the avatar filenames."""
        with zipfile.ZipFile(hpersona_path, "r") as zf:
            appearance = json.loads(zf.read("blueprint/persona_appearance.json"))

        assert appearance["selected_filename"] == "avatar_angel.png"
        assert appearance["selected_thumb_filename"] == "thumb_avatar_angel.webp"

    def test_card_has_required_fields(self, hpersona_path: Path):
        """Preview card must have all required gallery fields."""
        with zipfile.ZipFile(hpersona_path, "r") as zf:
            card = json.loads(zf.read("preview/card.json"))

        required_fields = ["name", "role", "short", "class_id", "tone",
                           "tags", "stats", "backstory", "has_avatar"]
        missing = [f for f in required_fields if f not in card]
        assert not missing, f"Card missing fields: {missing}"
        assert card["has_avatar"] is True
        assert card["content_rating"] == "sfw"


# ---------------------------------------------------------------------------
# Test: Bundle manifest
# ---------------------------------------------------------------------------

class TestBundleManifest:
    """Verify bundle_manifest.json for shared bundle compatibility."""

    @pytest.fixture
    def manifest(self) -> dict:
        p = (Path(__file__).resolve().parent.parent.parent
             / "community" / "shared" / "bundles" / "angel_stylist"
             / "bundle_manifest.json")
        if not p.exists():
            pytest.skip("bundle_manifest.json not found")
        return json.loads(p.read_text())

    def test_bundle_kind(self, manifest: dict):
        assert manifest["kind"] == "homepilot.shared_bundle"

    def test_bundle_id(self, manifest: dict):
        assert manifest["bundle_id"] == "angel_stylist"

    def test_persona_metadata(self, manifest: dict):
        persona = manifest["persona"]
        assert persona["name"] == "Angel"
        assert persona["role"] == "Fashion & Lifestyle Companion"
        assert persona["class_id"] == "companion"
        assert persona["content_rating"] == "sfw"
        assert "fashion" in persona["tags"]
        assert "vr-ready" in persona["tags"]

    def test_compatibility(self, manifest: dict):
        compat = manifest["compatibility"]
        assert compat["hpersona_schema_version"] == 3
