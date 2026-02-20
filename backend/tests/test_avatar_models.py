"""
Tests for Avatar Generation model registry and pipeline integrity.

Golden Rule 1.0: These tests are additive — they validate the new
AVATAR_GENERATION model category without touching existing edit/enhance tests.

Validates:
  - AVATAR_GENERATION category exists in ModelCategory enum
  - All avatar models are registered with required metadata
  - ModelInfo additive fields (license, download_url, requires) are present
  - get_avatar_models_status() returns well-formed data
  - /v1/avatar-models endpoint responds correctly
  - Avatar models coexist with existing categories (non-destructive)
  - Existing edit/enhance model queries are unaffected
  - Avatar commit pipeline still works with avatar-registry models installed
  - Makefile avatar download targets exist

Non-destructive: no network, no LLM, no GPU, no model downloads.
CI-friendly: runs in <1 second.
"""

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. Registry — ModelCategory and ModelInfo integrity
# ---------------------------------------------------------------------------

class TestAvatarModelCategory:
    """AVATAR_GENERATION enum value exists and is additive."""

    def test_avatar_generation_category_exists(self):
        from app.edit_models import ModelCategory
        assert hasattr(ModelCategory, "AVATAR_GENERATION")
        assert ModelCategory.AVATAR_GENERATION.value == "avatar_generation"

    def test_existing_categories_unchanged(self):
        """Golden Rule 1.0: existing categories must not be altered."""
        from app.edit_models import ModelCategory
        assert ModelCategory.UPSCALE.value == "upscale"
        assert ModelCategory.FACE_RESTORE.value == "face_restore"
        assert ModelCategory.BACKGROUND.value == "background"

    def test_all_models_includes_avatar_generation(self):
        from app.edit_models import ALL_MODELS, ModelCategory
        assert ModelCategory.AVATAR_GENERATION in ALL_MODELS


class TestAvatarModelRegistry:
    """All avatar models are registered with complete metadata."""

    # The models we expect in the registry — enterprise-grade selection
    EXPECTED_MODEL_IDS = [
        "insightface-antelopev2",
        "insightface-inswapper-128",
        "instantid-ip-adapter",
        "instantid-controlnet",
        "photomaker-v2",
        "pulid-flux",
        "ip-adapter-faceid-plusv2",
        "stylegan2-ffhq-256",
        "stylegan2-ffhq-1024",
    ]

    def test_all_expected_models_registered(self):
        from app.edit_models import AVATAR_GENERATION_MODELS
        for model_id in self.EXPECTED_MODEL_IDS:
            assert model_id in AVATAR_GENERATION_MODELS, (
                f"Model '{model_id}' missing from AVATAR_GENERATION_MODELS"
            )

    def test_model_count_matches(self):
        """Guard against accidental removals."""
        from app.edit_models import AVATAR_GENERATION_MODELS
        assert len(AVATAR_GENERATION_MODELS) >= len(self.EXPECTED_MODEL_IDS)

    @pytest.mark.parametrize("model_id", EXPECTED_MODEL_IDS)
    def test_model_has_required_fields(self, model_id):
        from app.edit_models import AVATAR_GENERATION_MODELS, ModelCategory
        m = AVATAR_GENERATION_MODELS[model_id]

        # Core fields (inherited from existing ModelInfo)
        assert m.id == model_id
        assert len(m.name) > 0, f"{model_id}: name is empty"
        assert m.category == ModelCategory.AVATAR_GENERATION
        assert len(m.filename) > 0, f"{model_id}: filename is empty"
        assert len(m.subdir) > 0, f"{model_id}: subdir is empty"
        assert len(m.description) > 0, f"{model_id}: description is empty"

        # Additive metadata fields (new in this release)
        assert isinstance(m.license, str), f"{model_id}: license must be str"
        assert len(m.license) > 0, f"{model_id}: license is empty"
        assert isinstance(m.commercial_use_ok, bool), (
            f"{model_id}: commercial_use_ok must be bool, got {type(m.commercial_use_ok)}"
        )
        assert isinstance(m.homepage, str), f"{model_id}: homepage must be str"
        assert isinstance(m.download_url, str), f"{model_id}: download_url must be str"
        assert len(m.download_url) > 0, f"{model_id}: download_url is empty"
        assert isinstance(m.requires, list), f"{model_id}: requires must be list"

    def test_dependency_references_are_valid(self):
        """Every model ID listed in 'requires' must exist in the registry."""
        from app.edit_models import AVATAR_GENERATION_MODELS
        all_ids = set(AVATAR_GENERATION_MODELS.keys())
        for model_id, model in AVATAR_GENERATION_MODELS.items():
            for dep in model.requires:
                assert dep in all_ids, (
                    f"Model '{model_id}' depends on '{dep}' which is not in the registry"
                )

    def test_at_least_one_default_model(self):
        from app.edit_models import AVATAR_GENERATION_MODELS
        defaults = [m for m in AVATAR_GENERATION_MODELS.values() if m.is_default]
        assert len(defaults) >= 1, "At least one avatar model should be marked is_default"

    def test_insightface_is_default(self):
        """InsightFace AntelopeV2 is the universal dependency — it should be default."""
        from app.edit_models import AVATAR_GENERATION_MODELS
        assert AVATAR_GENERATION_MODELS["insightface-antelopev2"].is_default is True


class TestAvatarModelLicenseMetadata:
    """License metadata is correct for enterprise/commercial decision-making."""

    def test_apache2_models_are_commercial_ok(self):
        """Models tagged Apache 2.0 must have commercial_use_ok=True."""
        from app.edit_models import AVATAR_GENERATION_MODELS
        apache_models = ["instantid-ip-adapter", "instantid-controlnet",
                         "photomaker-v2", "pulid-flux"]
        for mid in apache_models:
            m = AVATAR_GENERATION_MODELS[mid]
            assert m.commercial_use_ok is True, (
                f"{mid} is Apache 2.0 but commercial_use_ok={m.commercial_use_ok}"
            )

    def test_nvidia_models_are_non_commercial(self):
        """StyleGAN2 models from NVIDIA must be flagged non-commercial."""
        from app.edit_models import AVATAR_GENERATION_MODELS
        nvidia_models = ["stylegan2-ffhq-256", "stylegan2-ffhq-1024"]
        for mid in nvidia_models:
            m = AVATAR_GENERATION_MODELS[mid]
            assert m.commercial_use_ok is False, (
                f"{mid} is NVIDIA-licensed but commercial_use_ok={m.commercial_use_ok}"
            )


# ---------------------------------------------------------------------------
# 2. Status helper — get_avatar_models_status()
# ---------------------------------------------------------------------------

class TestAvatarModelsStatus:
    """get_avatar_models_status() returns well-formed data for the UI."""

    def test_status_returns_dict(self):
        from app.edit_models import get_avatar_models_status
        status = get_avatar_models_status()
        assert isinstance(status, dict)

    def test_status_has_required_keys(self):
        from app.edit_models import get_avatar_models_status
        status = get_avatar_models_status()
        assert "category" in status
        assert "installed" in status
        assert "available" in status
        assert "defaults" in status

    def test_status_category_is_avatar_generation(self):
        from app.edit_models import get_avatar_models_status
        status = get_avatar_models_status()
        assert status["category"] == "avatar_generation"

    def test_status_available_has_all_models(self):
        from app.edit_models import get_avatar_models_status, AVATAR_GENERATION_MODELS
        status = get_avatar_models_status()
        available_ids = {m["id"] for m in status["available"]}
        registry_ids = set(AVATAR_GENERATION_MODELS.keys())
        assert available_ids == registry_ids

    def test_status_each_model_has_ui_fields(self):
        """Each model in 'available' has the fields the UI needs to render."""
        from app.edit_models import get_avatar_models_status
        status = get_avatar_models_status()
        required_keys = {
            "id", "name", "description", "filename", "subdir",
            "installed", "license", "commercial_use_ok", "homepage",
            "download_url", "sha256", "requires", "is_default",
        }
        for model_info in status["available"]:
            missing = required_keys - set(model_info.keys())
            assert not missing, (
                f"Model '{model_info.get('id', '?')}' missing UI keys: {missing}"
            )

    def test_status_installed_is_list(self):
        from app.edit_models import get_avatar_models_status
        status = get_avatar_models_status()
        assert isinstance(status["installed"], list)

    def test_status_defaults_contains_insightface(self):
        from app.edit_models import get_avatar_models_status
        status = get_avatar_models_status()
        assert "insightface-antelopev2" in status["defaults"]


# ---------------------------------------------------------------------------
# 3. API endpoint — /v1/avatar-models
# ---------------------------------------------------------------------------

class TestAvatarModelsEndpoint:
    """GET /v1/avatar-models endpoint is live and returns correct data."""

    def test_endpoint_exists(self, client):
        response = client.get("/v1/avatar-models")
        assert response.status_code == 200

    def test_endpoint_returns_json(self, client):
        response = client.get("/v1/avatar-models")
        data = response.json()
        assert isinstance(data, dict)
        assert "category" in data
        assert "available" in data

    def test_endpoint_category_value(self, client):
        response = client.get("/v1/avatar-models")
        data = response.json()
        assert data["category"] == "avatar_generation"

    def test_endpoint_lists_all_models(self, client):
        from app.edit_models import AVATAR_GENERATION_MODELS
        response = client.get("/v1/avatar-models")
        data = response.json()
        api_ids = {m["id"] for m in data["available"]}
        assert api_ids == set(AVATAR_GENERATION_MODELS.keys())


# ---------------------------------------------------------------------------
# 4. Non-destructive coexistence — existing categories unaffected
# ---------------------------------------------------------------------------

class TestExistingCategoriesUnaffected:
    """Golden Rule 1.0: existing edit/enhance model queries must be unchanged."""

    def test_upscale_models_still_present(self):
        from app.edit_models import ALL_MODELS, ModelCategory
        assert ModelCategory.UPSCALE in ALL_MODELS
        assert len(ALL_MODELS[ModelCategory.UPSCALE]) > 0

    def test_face_restore_models_still_present(self):
        from app.edit_models import ALL_MODELS, ModelCategory
        assert ModelCategory.FACE_RESTORE in ALL_MODELS
        assert len(ALL_MODELS[ModelCategory.FACE_RESTORE]) > 0

    def test_background_models_still_present(self):
        from app.edit_models import ALL_MODELS, ModelCategory
        assert ModelCategory.BACKGROUND in ALL_MODELS

    def test_edit_models_status_still_works(self):
        from app.edit_models import get_edit_models_status
        status = get_edit_models_status()
        assert "upscale" in status
        assert "enhance" in status

    def test_existing_capabilities_endpoint_unaffected(self, client):
        response = client.get("/v1/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert "capabilities" in data
        # All existing capabilities still listed
        for cap in ["enhance_photo", "enhance_restore", "enhance_faces",
                     "upscale", "background_remove"]:
            assert cap in data["capabilities"], f"Missing capability: {cap}"

    def test_edit_models_endpoint_unaffected(self, client):
        response = client.get("/v1/edit-models")
        assert response.status_code == 200
        data = response.json()
        assert "upscale" in data
        assert "enhance" in data


# ---------------------------------------------------------------------------
# 5. Avatar commit pipeline — still works (unchanged by model registry)
# ---------------------------------------------------------------------------

class TestAvatarCommitPipelineIntegrity:
    """Avatar commit pipeline remains functional with new registry in place."""

    def test_commit_avatar_still_works(self, tmp_path: Path):
        """The core commit function is unaffected by the model registry."""
        from PIL import Image
        from app.personas.avatar_assets import commit_persona_avatar

        upload_root = tmp_path / "uploads"
        upload_root.mkdir(parents=True)
        project_root = upload_root / "projects" / "avatar_test"
        project_root.mkdir(parents=True)

        # Create a test image (simulates ComfyUI output)
        src = upload_root / "ComfyUI_avatar_test.png"
        img = Image.new("RGB", (512, 768), color=(80, 120, 200))
        img.save(src, format="PNG")

        result = commit_persona_avatar(upload_root, project_root, "ComfyUI_avatar_test.png")

        # Core contract: avatar and thumbnail exist
        avatar_path = upload_root / result.selected_filename
        thumb_path = upload_root / result.thumb_filename
        assert avatar_path.exists()
        assert thumb_path.exists()

        # Thumbnail is 256x256 WebP
        with Image.open(thumb_path) as im:
            assert im.size == (256, 256)
            assert im.format == "WEBP"

    def test_avatar_commit_endpoint_still_exists(self, client):
        """POST /projects/{id}/persona/avatar/commit must still exist."""
        # We expect 422 (missing body) or 404 (project not found), not 405/500
        response = client.post("/projects/fake-id/persona/avatar/commit", json={})
        assert response.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# 6. Makefile — avatar download targets exist
# ---------------------------------------------------------------------------

class TestMakefileAvatarTargets:
    """Makefile has avatar model download targets."""

    def _read_makefile(self) -> str:
        makefile_path = Path(__file__).resolve().parent.parent.parent / "Makefile"
        return makefile_path.read_text()

    def test_download_avatar_basic_target_exists(self):
        content = self._read_makefile()
        assert "download-avatar-models-basic:" in content

    def test_download_avatar_full_target_exists(self):
        content = self._read_makefile()
        assert "download-avatar-models-full:" in content

    def test_avatar_model_dirs_in_install(self):
        """Avatar model directories are created during make install."""
        content = self._read_makefile()
        assert "models/comfy/insightface" in content
        assert "models/comfy/instantid" in content

    def test_download_avatar_basic_in_phony(self):
        content = self._read_makefile()
        assert "download-avatar-models-basic" in content.split(".PHONY:")[1].split("\n\n")[0]


# ---------------------------------------------------------------------------
# 7. Download script — avatar models in recommended preset
# ---------------------------------------------------------------------------

class TestDownloadScriptAvatarIntegration:
    """download_models.sh includes avatar models in recommended/full presets."""

    def _read_download_script(self) -> str:
        script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "download_models.sh"
        return script_path.read_text()

    def test_download_script_has_avatar_function(self):
        content = self._read_download_script()
        assert "download_avatar_core" in content, (
            "download_models.sh should have a download_avatar_core function"
        )

    def test_recommended_preset_includes_avatar(self):
        content = self._read_download_script()
        # Find the execution block (second 'recommended)' occurrence — in main())
        first = content.find("recommended)")
        rec_start = content.find("recommended)", first + 1)
        rec_end = content.find(";;", rec_start)
        rec_block = content[rec_start:rec_end]
        assert "download_avatar_core" in rec_block, (
            "recommended preset should call download_avatar_core"
        )

    def test_insightface_url_in_script(self):
        content = self._read_download_script()
        assert "antelopev2" in content, (
            "download_models.sh should download InsightFace AntelopeV2"
        )

    def test_instantid_url_in_script(self):
        content = self._read_download_script()
        assert "InstantID" in content, (
            "download_models.sh should download InstantID"
        )
