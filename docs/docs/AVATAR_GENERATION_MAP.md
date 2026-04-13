# Avatar generation map (local + remote)

## Goal format to match gallery

Target outputs for each persona avatar package:
- `avatar_<name>.png` at **512×512** (square, 1:1)
- `thumb_avatar_<name>.webp` at **256×256** (square, 1:1)
- gallery preview should come from the thumbnail/webp path when available

## Where generation happens now

### 1) Remote/web generator (thispersondoesnotexist)

1. **Backend utility generator**
   - File: `backend/app/personas/avatar_generator.py`
   - Pulls faces from `https://thispersondoesnotexist.com/`.
   - Resizes to 512×512 PNG and 256×256 WEBP.
   - This is already aligned with the requested dimensions.

2. **Avatar-service QuickFace web fallback**
   - File: `avatar-service/app/quickface_router.py`
   - If local StyleGAN is unavailable, it fetches from `thispersondoesnotexist.com`.
   - It resizes fetched image to requested `output_size` (backend passes 512).
   - Stores PNG via `save_pil_images()`.

### 2) Local generator (StyleGAN)

1. **Local inference endpoint**
   - File: `avatar-service/app/stylegan/generator.py`
   - `generate_faces(..., output_size=512)` produces square PIL images.
   - Uses loaded local StyleGAN model when enabled.

2. **Model/source wiring**
   - File: `avatar-service/app/config.py`
   - Controlled by env vars:
     - `STYLEGAN_ENABLED=true`
     - `STYLEGAN_WEIGHTS_PATH=/path/to/model.pkl`

3. **Model download for local usage**
   - File: `Makefile`
   - `make download-avatar-models-full` downloads:
     - `stylegan2-ffhq-256x256.pkl`
     - `stylegan2-ffhq-1024x1024.pkl`

## Orchestration (how backend chooses remote/local)

- File: `backend/app/avatar/service.py`
- `studio_random` flow:
  1. try avatar-service `/v1/avatars/generate` (local StyleGAN if loaded)
  2. if unavailable/placeholder, fallback to ComfyUI creative
  3. last resort placeholder
- `studio_quickface` flow:
  1. call avatar-service `/v1/avatars/quickface`
  2. avatar-service does: local StyleGAN → web thispersondoesnotexist → placeholder

## Thumbnail + preview pipeline

1. **Durable thumbnail creation**
   - File: `backend/app/personas/avatar_assets.py`
   - `_top_crop_thumb(..., size=256)` creates square top-anchored WEBP thumbnails.

2. **Community/sample package generation**
   - File: `community/sample/generate_community_personas.py`
   - Generates `avatar_<slug>.png` as 512×512 and `thumb_avatar_<slug>.webp` as 256×256.
   - Writes `persona_appearance.json` with:
     - `aspect_ratio: "1:1"`
     - `selected_filename`
     - `selected_thumb_filename`

3. **Gallery preview extraction preference**
   - File: `community/scripts/process_submission.py`
   - For package previews, extraction prefers thumbnail files (`thumb*`) before full avatar.

## Important implementation note

- In avatar-service, `save_pil_images()` writes only PNG outputs.
- The 256×256 WEBP thumb is produced later by backend avatar commit utilities (`avatar_assets.py`) or sample/community packaging flows.
- So: the **final gallery-compatible pair** is assembled by backend/package tooling, not by avatar-service alone.

## Practical commands for future avatar creation

### Local StyleGAN path

1. Install models:
   - `make download-avatar-models-full`
2. Start avatar-service:
   - `make start-avatar-service`
3. Generate through backend mode:
   - use `studio_random` (or `studio_quickface`) via backend API
4. Commit selected image to persona storage:
   - backend commit path generates `thumb_avatar_*.webp`

### Remote/web path (thispersondoesnotexist)

- Option A (direct utility):
  - run `python -m backend.app.personas.avatar_generator --name <name> --out <dir>`
- Option B (via service fallback):
  - use `studio_quickface` when local StyleGAN is not loaded

Both paths can yield the required output pair (512 PNG + 256 WEBP) once the commit/package step is applied.
