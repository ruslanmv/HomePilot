"""Model storage locations: built-in models/comfy stays as is; extra locations are added."""
import importlib
import sys

import pytest


def _ms():
    return sys.modules.get("app.model_storage") or importlib.import_module("app.model_storage")


@pytest.fixture()
def storage(tmp_path, monkeypatch, app):
    ms = _ms()
    builtin = tmp_path / "models_comfy"
    (builtin / "checkpoints").mkdir(parents=True)
    _write_safetensors(builtin / "checkpoints" / "old.safetensors", 16, 16)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(ms, "builtin_root", lambda: builtin)
    monkeypatch.setattr(ms, "_data_dir", lambda: data)
    monkeypatch.setattr(ms, "is_wsl", lambda: False)
    return ms, builtin, data, tmp_path


def test_no_config_means_exactly_the_old_behaviour(storage):
    ms, builtin, data, _ = storage
    assert ms.comfy_model_roots() == [builtin]
    assert ms.download_root() == builtin
    assert not (data / "comfy-extra-model-paths.yaml").exists()


def test_add_location_creates_folders_and_comfy_paths_file(storage, client):
    ms, builtin, data, tmp = storage
    ext = tmp / "external" / "homepilot-models"
    r = client.put("/v1/models/storage", json={"locations": [{"path": str(ext), "label": "External"}],
                                                "download_target": str(ext)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (ext / "checkpoints").is_dir() and (ext / "loras").is_dir()
    assert ms.download_root() == ext
    assert ms.comfy_model_roots() == [builtin, ext]
    names = [l["label"] for l in body["locations"]]
    assert names[0].startswith("Built-in") and "External" in names
    assert [l for l in body["locations"] if l["is_download_target"]][0]["path"] == str(ext)
    yaml = (data / "comfy-extra-model-paths.yaml").read_text()
    assert f'base_path: "{ext}"' in yaml and "checkpoints: checkpoints" in yaml
    # The built-in model is untouched.
    assert (builtin / "checkpoints" / "old.safetensors").exists()


def test_missing_drive_falls_back_to_builtin_for_downloads(storage, client):
    ms, builtin, data, tmp = storage
    ext = tmp / "usb"
    client.put("/v1/models/storage", json={"locations": [{"path": str(ext)}], "download_target": str(ext)})
    import shutil
    shutil.rmtree(ext)  # drive unplugged
    assert ms.download_root() == builtin
    assert ms.comfy_model_roots() == [builtin]
    status = client.get("/v1/models/storage").json()
    assert status["download_target_fallback"] is True


def test_target_must_be_a_listed_location(storage, client):
    ms, builtin, data, tmp = storage
    r = client.put("/v1/models/storage", json={"locations": [], "download_target": str(tmp / "elsewhere")})
    assert r.status_code == 400


def test_windows_paths_under_wsl(monkeypatch, app):
    ms = _ms()
    monkeypatch.setattr(ms, "is_wsl", lambda: True)
    assert str(ms.to_local_path(r"E:\homepilot-models")) == "/mnt/e/homepilot-models"
    assert ms.to_windows_path(ms.Path("/mnt/e/homepilot-models")) == r"E:\homepilot-models"
    with pytest.raises(ValueError):
        ms.to_local_path("relative/path")


def test_installed_models_and_loras_found_in_extra_location(storage, client, monkeypatch):
    ms, builtin, data, tmp = storage
    ext = tmp / "ext"
    client.put("/v1/models/storage", json={"locations": [{"path": str(ext)}], "download_target": str(ext)})
    _write_safetensors(ext / "checkpoints" / "new_on_external.safetensors", 16, 16)
    (ext / "loras" / "style.safetensors").write_bytes(b"z" * 10)

    providers = sys.modules.get("app.providers") or importlib.import_module("app.providers")
    monkeypatch.setattr(providers, "get_comfy_models_path", lambda: builtin)
    installed = providers.scan_installed_models("image")
    assert "old.safetensors" in installed and "new_on_external.safetensors" in installed

    lora = sys.modules.get("app.models.lora_loader") or importlib.import_module("app.models.lora_loader")
    assert lora.find_lora_file("style.safetensors") == ext / "loras" / "style.safetensors"
    assert lora.get_lora_install_dir() == ext / "loras"


def _write_safetensors(path, data_len, actual_len):
    import json as _json
    header = _json.dumps({"w": {"dtype": "F32", "shape": [data_len // 4], "data_offsets": [0, data_len]}}).encode()
    path.write_bytes(len(header).to_bytes(8, "little") + header + b"\0" * actual_len)


def test_truncated_model_is_not_installed_and_blocks_generation(storage, monkeypatch):
    ms, builtin, data, tmp = storage
    (builtin / "unet").mkdir()
    _write_safetensors(builtin / "unet" / "cut.safetensors", 4000, 1000)
    _write_safetensors(builtin / "unet" / "good.safetensors", 4000, 4000)
    assert "incomplete" in ms.incomplete_model_reason(builtin / "unet" / "cut.safetensors")
    assert ms.incomplete_model_reason(builtin / "unet" / "good.safetensors") is None

    providers = sys.modules.get("app.providers") or importlib.import_module("app.providers")
    monkeypatch.setattr(providers, "get_comfy_models_path", lambda: builtin)
    installed = providers.scan_installed_models("image")
    assert "good.safetensors" in installed and "cut.safetensors" not in installed

    comfy = sys.modules.get("app.comfy") or importlib.import_module("app.comfy")
    with pytest.raises(RuntimeError, match="cut.safetensors.*incomplete"):
        comfy._check_model_files({"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "cut.safetensors"}}})
    comfy._check_model_files({"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "good.safetensors"}}})
