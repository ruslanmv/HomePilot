# Model storage locations

Where ComfyUI models (image, video, edit, upscale, LoRA…) are kept. Settings → Models →
**Model storage**; backend `backend/app/model_storage.py` (`GET/PUT /v1/models/storage`).

## Rules

- **The built-in folder never changes.** `models/comfy` (`providers.get_comfy_models_path`)
  is always the first location; nothing in it is moved, renamed or deleted.
- **Extra locations are added, not swapped.** e.g. `E:\homepilot-models` on an external drive
  (a Windows path is converted to `/mnt/e/…` under WSL). Each gets the usual ComfyUI
  subfolders (`checkpoints`, `loras`, `vae`, …).
- **One location receives new downloads.** The backend passes it to `scripts/download.py` as
  `HOMEPILOT_MODELS_ROOT`; LoRA installs use `get_lora_install_dir()`. Hugging Face's download
  cache goes on the same drive (`HF_HUB_CACHE`), so a download never needs twice its size on the
  system drive.
- **A missing drive is never an error.** An unplugged location is skipped, and downloads fall
  back to the built-in folder (the card says so).
- **No config, no change.** Without `backend/data/model-storage.json` everything behaves exactly
  as before.

## Who reads the locations

| Reader | How |
|---|---|
| ComfyUI (Linux runtime) | `--extra-model-paths-config backend/data/comfy-extra-model-paths.yaml` (scripts/start-comfyui.sh) |
| ComfyUI (Windows runtime) | `…comfy-extra-model-paths.windows.yaml`, Windows paths (scripts/start-comfyui.ps1) |
| "Installed?" checks, Delete | `model_storage.comfy_model_roots()` in `providers.scan_installed_models` and the delete endpoint |
| Single files (rembg, face restore, edit models) | `model_storage.find_model_file(rel)` |
| LoRAs | `lora_loader.get_lora_dirs()` / `find_lora_file()` |

ComfyUI reads extra locations at start-up: restart HomePilot after adding one.

## Not covered

Ollama (chat models) keeps one models folder (`OLLAMA_MODELS`); moving it would hide the models
already installed, so it is not part of this setting.
