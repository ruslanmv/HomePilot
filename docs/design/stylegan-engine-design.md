# StyleGAN Engine Integration — Additive Design Document

> Non-destructive, additive design to bring real StyleGAN2 face generation
> into HomePilot Avatar Studio while keeping ComfyUI as the default.

---

## Executive Summary

Your codebase **already has 80% of the plumbing** for StyleGAN. The `studio_random`
mode, avatar-service microservice, pack manifests, licensing gates, and availability
checks all exist. The only missing piece is the actual inference code and a small
frontend toggle to let users opt into it.

**This design avoids unnecessary abstraction.** Your mode-based routing in
`service.py` already acts as an engine selector. Adding a formal "engine plugin
architecture" would be over-engineering — the existing pattern is clean and proven.

---

## 0. Why the Proposed "Engine Abstraction" Is Unnecessary

Your `service.py:generate()` already does engine selection:

```python
# backend/app/avatar/service.py (current)
async def generate(req):
    if req.mode == "studio_random":
        # → avatar-service (StyleGAN)
        ...
    if req.mode in ("studio_reference", "studio_faceswap", "creative"):
        # → ComfyUI
        ...
```

This IS the engine abstraction — just without the ceremony of base classes and
registries. Adding `backend/app/avatar/engines/base.py` with an `AvatarEngine`
interface would:
- Create files that wrap single function calls
- Add indirection without adding capability
- Force refactoring of tested, working code

**Instead: keep the existing mode routing and make `studio_random` actually work.**

The proposed `GET /api/avatar/capabilities` endpoint is also redundant —
`GET /v1/avatars/packs` already returns `enabled_modes` and pack availability,
and the frontend already uses it (`useAvatarPacks.ts`).

---

## 1. What Needs to Change (Minimal Diff)

### Overview

```
avatar-service/           ← implement real inference (3 files)
backend/app/avatar/       ← zero changes needed (routing already works)
frontend/src/ui/avatar/   ← stop hiding studio_random mode (1 line)
```

| Layer | File | Change | Type |
|-------|------|--------|------|
| avatar-service | `stylegan/generator.py` | Implement real inference | Replace placeholder |
| avatar-service | `stylegan/loader.py` | Implement model loading | Replace placeholder |
| avatar-service | `stylegan/postprocess.py` | Implement resize+encode | Replace placeholder |
| avatar-service | `router.py` | Route to real generator | Small edit |
| avatar-service | `pyproject.toml` | Add torch dependency | Add line |
| frontend | `AvatarStudio.tsx:262` | Remove `studio_random → creative` remap | Remove 1 line |
| frontend | `AvatarStudio.tsx` | Add StyleGAN info label | Add ~10 lines |

**Backend `service.py`, `router.py`, `availability.py`, `schemas.py` — ZERO changes.**

They already route `studio_random` to avatar-service, check pack availability,
and handle errors. All of this is tested and working.

---

## 2. Avatar-Service: Implement Real Inference

### 2.1 Model Loading (`stylegan/loader.py`)

```python
"""
StyleGAN2 model loader — loads .pkl weights once at startup.

Supports both NVIDIA's original pickle format and converted .pt format.
Model is loaded to GPU if available, CPU otherwise.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import torch

_log = logging.getLogger(__name__)

_G: Optional[torch.nn.Module] = None
_device: torch.device = torch.device("cpu")


def load_model(weights_path: str | Path, device: str = "auto") -> None:
    """Load StyleGAN2 generator weights. Call once at startup."""
    global _G, _device

    weights_path = Path(weights_path)
    if not weights_path.exists():
        raise FileNotFoundError(f"StyleGAN2 weights not found: {weights_path}")

    if device == "auto":
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        _device = torch.device(device)

    _log.info("Loading StyleGAN2 from %s to %s", weights_path, _device)

    if weights_path.suffix == ".pkl":
        # NVIDIA pickle format (requires legacy imports)
        import pickle
        with open(weights_path, "rb") as f:
            data = pickle.load(f)
        _G = data["G_ema"].to(_device).eval()
    elif weights_path.suffix == ".pt":
        _G = torch.load(weights_path, map_location=_device, weights_only=False)
        _G = _G.eval()
    else:
        raise ValueError(f"Unsupported weight format: {weights_path.suffix}")

    _log.info("StyleGAN2 loaded (%s parameters)", sum(p.numel() for p in _G.parameters()))


def get_generator() -> torch.nn.Module:
    """Return the loaded generator. Raises if not loaded."""
    if _G is None:
        raise RuntimeError(
            "StyleGAN2 generator not loaded. "
            "Set STYLEGAN_WEIGHTS_PATH and restart the service."
        )
    return _G


def get_device() -> torch.device:
    return _device


def is_loaded() -> bool:
    return _G is not None
```

### 2.2 Face Generation (`stylegan/generator.py`)

```python
"""
StyleGAN2 seeded face generation.

Generates face images from random or fixed seeds using the loaded
StyleGAN2 generator. Each seed produces a deterministic face.
"""
from __future__ import annotations

import random
from typing import List, Optional

import torch
from PIL import Image

from .loader import get_generator, get_device


def generate_faces(
    count: int = 4,
    seeds: Optional[List[int]] = None,
    truncation: float = 0.7,
    output_size: int = 512,
) -> List[dict]:
    """
    Generate face images from StyleGAN2.

    Returns list of dicts: {"image": PIL.Image, "seed": int}
    """
    G = get_generator()
    device = get_device()

    if seeds is None:
        seeds = [random.randint(0, 2**31 - 1) for _ in range(count)]
    elif len(seeds) < count:
        seeds = seeds + [random.randint(0, 2**31 - 1) for _ in range(count - len(seeds))]

    results = []
    with torch.no_grad():
        for seed in seeds[:count]:
            z = torch.from_numpy(
                __import__("numpy").random.RandomState(seed).randn(1, G.z_dim)
            ).to(device, dtype=torch.float32)

            # Truncation trick: interpolate toward mean
            if hasattr(G, "mapping"):
                w = G.mapping(z, None)
                w_avg = G.mapping.w_avg.unsqueeze(0).unsqueeze(1)
                w = w_avg + truncation * (w - w_avg)
                img = G.synthesis(w)
            else:
                # Simplified path for converted models
                img = G(z, truncation_psi=truncation)

            # Convert from [-1, 1] to [0, 255] PIL Image
            img = (img.clamp(-1, 1) + 1) * 127.5
            img = img[0].permute(1, 2, 0).cpu().to(torch.uint8).numpy()
            pil_img = Image.fromarray(img, "RGB")

            # Resize if needed
            if pil_img.size[0] != output_size:
                pil_img = pil_img.resize((output_size, output_size), Image.LANCZOS)

            results.append({"image": pil_img, "seed": seed})

    return results
```

### 2.3 Post-processing (`stylegan/postprocess.py`)

```python
"""
Post-processing for generated StyleGAN2 faces.

Handles encoding, optional enhancement, and quality output.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter


def resize_and_encode(
    img: Image.Image,
    output_path: Path,
    size: int = 512,
    sharpen: bool = True,
    quality: int = 92,
) -> None:
    """Resize, optionally sharpen, and save as PNG."""
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    if sharpen:
        img = img.filter(ImageFilter.SHARPEN)
    img.save(output_path, format="PNG", optimize=True)


def to_bytes(img: Image.Image, format: str = "PNG") -> bytes:
    """Encode image to bytes (for streaming responses)."""
    buf = BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()
```

### 2.4 Updated Router (`router.py`)

```python
"""
Avatar Service — FastAPI router.

Routes to real StyleGAN2 inference when model is loaded,
falls back to placeholder PNGs otherwise.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .schemas import GenerateRequest, GenerateResponse, Result
from .stylegan.loader import is_loaded

router = APIRouter()


@router.post("/v1/avatars/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    """Generate avatar face images."""
    if is_loaded():
        return _generate_stylegan(req)
    else:
        return _generate_placeholder(req)


def _generate_stylegan(req: GenerateRequest) -> GenerateResponse:
    """Real StyleGAN2 inference."""
    from .stylegan.generator import generate_faces
    from .stylegan.postprocess import resize_and_encode

    import os
    output_dir = Path(os.environ.get("AVATAR_OUTPUT_DIR", "../backend/data/avatars"))
    output_dir.mkdir(parents=True, exist_ok=True)

    faces = generate_faces(
        count=req.count,
        seeds=req.seeds,
        truncation=req.truncation,
    )

    results = []
    for face in faces:
        ts = int(time.time() * 1000)
        filename = f"avatar_{ts}_{face['seed']}.png"
        output_path = output_dir / filename
        resize_and_encode(face["image"], output_path)
        results.append(Result(
            url=f"/static/avatars/{filename}",
            seed=face["seed"],
            metadata={"generator": "stylegan2", "truncation": req.truncation},
        ))

    return GenerateResponse(results=results, warnings=[])


def _generate_placeholder(req: GenerateRequest) -> GenerateResponse:
    """Fallback: labeled placeholder PNGs."""
    from .storage.local_store import save_placeholder_pngs
    return save_placeholder_pngs(
        count=req.count,
        seeds=req.seeds,
        truncation=req.truncation,
    )
```

### 2.5 Startup with Model Loading (`main.py`)

```python
"""HomePilot Avatar Service — StyleGAN2 face generation microservice."""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .router import router

_log = logging.getLogger(__name__)

app = FastAPI(title="HomePilot Avatar Service")
app.include_router(router)

# Serve generated avatars
_output_dir = os.environ.get("AVATAR_OUTPUT_DIR", "../backend/data/avatars")
os.makedirs(_output_dir, exist_ok=True)
app.mount("/static/avatars", StaticFiles(directory=_output_dir), name="avatars")


@app.on_event("startup")
async def _load_stylegan() -> None:
    """Attempt to load StyleGAN2 weights at startup. Graceful if missing."""
    weights_path = os.environ.get("STYLEGAN_WEIGHTS_PATH", "")
    if not weights_path:
        _log.info("STYLEGAN_WEIGHTS_PATH not set — running in placeholder mode")
        return

    try:
        from .stylegan.loader import load_model
        device = os.environ.get("STYLEGAN_DEVICE", "auto")
        load_model(weights_path, device=device)
        _log.info("StyleGAN2 model loaded successfully")
    except Exception as e:
        _log.warning("Failed to load StyleGAN2 model: %s — running in placeholder mode", e)
```

### 2.6 Updated Dependencies (`pyproject.toml`)

Add to the existing file:

```toml
[project.optional-dependencies]
gpu = [
    "torch>=2.0",
    "torchvision>=0.15",
    "numpy>=1.24",
]
```

This keeps the base install lightweight (placeholder mode works without torch).

---

## 3. Backend Changes: NONE Required

The existing backend code already handles everything:

### 3.1 Mode routing — already works

`backend/app/avatar/service.py:47-76`:
```python
if req.mode == "studio_random":
    enforce_license(commercial_ok=False, pack_id="avatar-stylegan2")
    # ... POST to avatar-service
```

### 3.2 Availability detection — already works

`backend/app/avatar/availability.py:64-70`:
```python
stylegan_ok = pack_installed("avatar-stylegan2")
if not stylegan_ok and _models_present(_STYLEGAN2_MODEL_IDS):
    stylegan_ok = True
    _ensure_marker("avatar-stylegan2")
if stylegan_ok:
    modes.append("studio_random")
```

### 3.3 Pack manifest — already exists

`backend/app/models/packs/manifests/avatar-stylegan2.json`:
```json
{
  "id": "avatar-stylegan2",
  "title": "Avatar Studio (StyleGAN2)",
  "license": "NVIDIA Non-commercial",
  "commercial_ok": false,
  "modes_enabled": ["studio_random"],
  "notes": "Random face generation via StyleGAN2."
}
```

### 3.4 Licensing — already enforced

`backend/app/avatar/licensing.py` blocks non-commercial models unless
`ALLOW_NON_COMMERCIAL_MODELS=true`.

### 3.5 Error handling — already covered

`backend/app/avatar/router.py` catches `FeatureUnavailable` (503),
`LicenseDenied` (403), and generic exceptions (500).

**Zero lines of backend code need to change.**

---

## 4. Frontend Changes: Minimal

### 4.1 Stop remapping `studio_random` → `creative`

Currently in `CharacterWizard.tsx:486`:
```typescript
const apiMode = draft.generationMode === 'studio_random' ? 'creative' : draft.generationMode
```

Change to:
```typescript
const apiMode = draft.generationMode
```

That's it. The backend will route `studio_random` to avatar-service.

In `AvatarStudio.tsx:262`, similar remap exists:
```typescript
const apiMode = mode === 'studio_random' ? 'creative' : mode
```

Change to:
```typescript
const apiMode = mode
```

### 4.2 Add StyleGAN info label (additive)

When `studio_random` is selected, show a small informational note:

```tsx
{mode === 'studio_random' && (
  <div className="text-[10px] text-white/30 mt-2 flex items-center gap-1.5">
    <Zap size={10} />
    StyleGAN generates face portraits only. Outfit and pose settings
    are applied via text prompt as guidance.
  </div>
)}
```

### 4.3 Mode availability is already handled

The frontend already disables modes when not in `enabledModes`:

`AvatarStudio.tsx:461`:
```typescript
const enabled = enabledModes.includes(o.value)
```

If StyleGAN pack isn't installed → `studio_random` not in `enabled_modes` →
button is disabled → no user confusion.

### 4.4 No new settings needed

The existing settings panel already has checkpoint selection. StyleGAN doesn't
use checkpoints — it uses its own weights. The backend handles this distinction
transparently (different modes route to different services).

---

## 5. UX Design: How It Appears to Users

### 5.1 Default experience (unchanged)

Users who don't have StyleGAN weights installed see:

```
┌─────────────────────────────────────────────────────┐
│  Design Character     From Reference   Face + Style │
│  ░░░░░░░░░░░░░░░░░    [active]         [active]     │
│  (disabled)                                          │
└─────────────────────────────────────────────────────┘
```

"Design Character" button is grayed out. Hover shows: "Install StyleGAN2 model to enable".
This is identical to the current behavior.

### 5.2 With StyleGAN installed

```
┌─────────────────────────────────────────────────────┐
│  Design Character     From Reference   Face + Style │
│  [active]             [active]         [active]     │
│                                                      │
│  ⚡ StyleGAN generates face portraits only.          │
│    Outfit and pose settings are applied via prompt.  │
└─────────────────────────────────────────────────────┘
```

The user clicks "Design Character", goes through the wizard, and on step 7 the
actual StyleGAN service generates faces instead of falling back to ComfyUI `creative` mode.

### 5.3 Generation flow

```
User selects "Design Character"
  → Steps 1-6: same wizard experience (all presets still work)
  → Step 7: clicks Generate
  → Backend routes to avatar-service
  → StyleGAN generates face(s) in ~1-3 seconds (vs 5-20s for ComfyUI)
  → Results displayed in grid
  → User picks favorite → Create Avatar
```

**Key UX benefit**: StyleGAN generation is significantly faster than ComfyUI
(~1-3s vs 5-20s), so the "Design Character" flow becomes the snappiest option.

### 5.4 Wizard field compatibility

Not all wizard fields map to StyleGAN controls. Here's how they degrade gracefully:

| Wizard Field | StyleGAN Effect | Notes |
|-------------|----------------|-------|
| Gender | Not directly controlled | StyleGAN generates diverse faces |
| Seed | Direct mapping | Same seed = same face (deterministic) |
| Truncation | Maps to realism slider | Higher = more "average" face |
| Body type | No effect | Face-only generation |
| Hair style/color | No effect | StyleGAN decides |
| Outfit | No effect | Face-only generation |
| Count | Direct mapping | Generate N faces |

**This is fine.** The "Design Character" mode is explicitly labeled as face generation.
Users who want full control over body/outfit/hair use "From Reference" or "Face + Style"
with ComfyUI, which is the current default behavior.

---

## 6. Hybrid Path: StyleGAN Face → ComfyUI Body (Future Enhancement)

A natural extension (Phase 2) would chain the engines:

```
StyleGAN generates face
  → User picks favorite face
  → Face becomes reference image for ComfyUI
  → ComfyUI generates full body with wizard outfit/pose settings
  → Identity preserved via InstantID
```

This requires **zero new architecture** — it's just:
1. Save StyleGAN result as file
2. Pass its URL as `reference_image_url` to a `studio_reference` request
3. The existing outfit/pose prompt from the wizard drives ComfyUI

The frontend flow would be:

```
Step 7a: Generate Faces (StyleGAN, ~1-3s)
  → User picks face
Step 7b: Generate Full Avatar (ComfyUI, ~10-20s)
  → Uses picked face as reference
  → Applies wizard body/outfit/pose/background settings
  → Returns final high-quality avatar
```

This hybrid gives the best of both worlds:
- Fast face exploration with StyleGAN
- Full character control with ComfyUI
- Identity preservation via InstantID

**But this is Phase 2.** Phase 1 (this design) just makes StyleGAN work as a
standalone face generator — which is already valuable and complete.

---

## 7. Configuration & Deployment

### 7.1 Environment variables (avatar-service)

```env
# Required to enable real inference
STYLEGAN_WEIGHTS_PATH=/models/stylegan2/stylegan2-ffhq-256.pkl

# Optional
STYLEGAN_DEVICE=auto          # "auto", "cuda", "cpu"
AVATAR_OUTPUT_DIR=../backend/data/avatars
AVATAR_SERVICE_PORT=8020
```

### 7.2 Docker Compose (additive)

Add GPU support to the existing avatar-service container:

```yaml
avatar-service:
  build: ./avatar-service
  ports:
    - "8020:8020"
  volumes:
    - ./models/stylegan2:/models/stylegan2:ro
    - ./backend/data/avatars:/app/data/avatars
  environment:
    - STYLEGAN_WEIGHTS_PATH=/models/stylegan2/stylegan2-ffhq-256.pkl
    - STYLEGAN_DEVICE=auto
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

### 7.3 Model download

Add to the Makefile download targets:

```makefile
download-stylegan2:
	@echo "Downloading StyleGAN2 FFHQ 256..."
	@mkdir -p models/stylegan2
	@curl -L -o models/stylegan2/stylegan2-ffhq-256.pkl \
		"https://nvlabs-fi-cdn.nvidia.com/stylegan2/networks/stylegan2-ffhq-config-f.pkl"
	@echo "Done. Model saved to models/stylegan2/"
```

### 7.4 Graceful degradation

If the model file is missing or fails to load:
- avatar-service starts in placeholder mode (existing behavior)
- Backend health check detects `studio_random` as unavailable
- Frontend disables "Design Character" button (existing behavior)
- Zero impact on other modes

---

## 8. What Stays Exactly the Same

| Component | Behavior |
|-----------|----------|
| `backend/app/avatar/service.py` | Unchanged — already routes `studio_random` to avatar-service |
| `backend/app/avatar/router.py` | Unchanged — existing error handling covers all cases |
| `backend/app/avatar/availability.py` | Unchanged — already checks StyleGAN pack |
| `backend/app/avatar/schemas.py` | Unchanged — `AvatarMode` already includes `studio_random` |
| `backend/app/avatar/config.py` | Unchanged — `AVATAR_SERVICE_URL` already configurable |
| `backend/app/avatar/licensing.py` | Unchanged — already enforces non-commercial for StyleGAN |
| `backend/app/models/packs/manifests/` | Unchanged — `avatar-stylegan2.json` already exists |
| ComfyUI pipeline | Unchanged — `studio_reference`, `studio_faceswap`, `creative` unaffected |
| Gallery system | Unchanged — stores any `AvatarResult` regardless of source |
| Outfit variations | Unchanged — uses `studio_reference` mode (ComfyUI) |
| Settings panel | Unchanged — checkpoint selection only affects ComfyUI modes |
| Pack installation | Unchanged — `installAvatarPack()` already supports `avatar-stylegan2` |

---

## 9. Implementation Phases

### Phase 1: Make StyleGAN Work (This Design)

```
Effort: ~2-3 days
Risk: Low (additive only, existing behavior unchanged)

Tasks:
1. Implement loader.py, generator.py, postprocess.py  (avatar-service)
2. Update router.py to use real generator when loaded  (avatar-service)
3. Update main.py with startup model loading           (avatar-service)
4. Add torch to optional dependencies                  (avatar-service)
5. Remove studio_random → creative remap               (frontend, 2 lines)
6. Add StyleGAN info label in wizard                   (frontend, ~10 lines)
7. Add Makefile download target                        (project root)
8. Test with real weights
```

### Phase 2: Hybrid Face → Body (Future)

```
Effort: ~3-5 days
Risk: Low (additive to Phase 1)

Tasks:
1. Add "Refine with AI" button after StyleGAN results
2. Chain StyleGAN face → ComfyUI studio_reference
3. Add two-stage progress UI (face → body)
4. Optional: latent interpolation in avatar-service
```

### Phase 3: Advanced StyleGAN Features (Future)

```
Effort: ~1-2 weeks
Risk: Medium

Tasks:
1. Latent interpolation (morph between faces)
2. Conditional generation (if using conditional model)
3. Face editing (age, expression, style)
4. StyleGAN3 support
5. Higher resolution (1024px)
```

---

## 10. Comparison with Proposed Design

| Proposed | This Design | Rationale |
|----------|------------|-----------|
| Engine abstraction (`engines/base.py`) | Not needed | Mode routing in `service.py` already does this |
| New capabilities endpoint | Not needed | `/v1/avatars/packs` already returns `enabled_modes` |
| New generic generate endpoint | Not needed | Existing `/v1/avatars/generate` handles all modes |
| Normalized output format | Not needed | `AvatarResult` already normalizes across engines |
| Job system | Not needed | Both engines return synchronously through the same API |
| Engine dropdown in settings | Not needed | Mode selection in the wizard IS the engine choice |
| Feature flags | Already exist | `AVATAR_ENABLED`, `ALLOW_NON_COMMERCIAL_MODELS`, pack markers |
| Compatibility rules | Info label | Simple text note is sufficient; no wizard field disabling |

**Key insight**: Your codebase was designed with this feature in mind. The
`studio_random` mode, avatar-service microservice, pack manifests, and licensing
are all pre-built scaffolding waiting for the actual StyleGAN inference to be plugged in.

The cleanest implementation is to fill in the placeholders and remove the workarounds,
not to add new architectural layers on top.

---

## 11. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| StyleGAN generates low-quality faces at 256px | Medium | Low | Resize to 512px with LANCZOS; Phase 3 adds 1024px |
| NVIDIA pickle format compatibility issues | Low | Medium | Support .pt converted format as fallback |
| GPU memory conflict with ComfyUI | Low | Medium | Separate container with own GPU allocation |
| Users expect full control (outfit, body) from StyleGAN | Medium | Low | Info label + Phase 2 hybrid flow |
| Model download is large | Low | Low | Optional download; clear docs |

---

## 12. Files Touched (Complete List)

### Modified (minimal changes)

| File | Lines Changed | Description |
|------|--------------|-------------|
| `avatar-service/app/stylegan/generator.py` | ~50 → ~60 | Replace `NotImplementedError` with real inference |
| `avatar-service/app/stylegan/loader.py` | ~15 → ~55 | Replace `NotImplementedError` with model loading |
| `avatar-service/app/stylegan/postprocess.py` | ~12 → ~35 | Replace `NotImplementedError` with resize+encode |
| `avatar-service/app/router.py` | ~23 → ~50 | Route to real generator when model loaded |
| `avatar-service/app/main.py` | ~10 → ~30 | Add startup model loading |
| `avatar-service/pyproject.toml` | +3 lines | Add optional GPU dependencies |
| `frontend/src/ui/avatar/AvatarStudio.tsx` | -1, +12 lines | Remove remap, add info label |
| `frontend/src/ui/avatar/wizard/CharacterWizard.tsx` | -1 line | Remove remap |

### Not modified (zero changes)

- `backend/app/avatar/*` (all files)
- `backend/app/services/comfyui/*` (all files)
- `backend/app/models/packs/manifests/*` (all files)
- `frontend/src/ui/avatar/types.ts`
- `frontend/src/ui/avatar/avatarApi.ts`
- `frontend/src/ui/avatar/useGenerateAvatars.ts`
- `frontend/src/ui/avatar/useAvatarPacks.ts`
- `frontend/src/ui/avatar/AvatarSettingsPanel.tsx`
- `frontend/src/ui/avatar/AvatarGallery.tsx`
- `frontend/src/ui/avatar/AvatarViewer.tsx`
- `frontend/src/ui/avatar/galleryTypes.ts`
- `frontend/src/ui/avatar/wizard/wizardTypes.ts`

---

## Summary

The shortest path to working StyleGAN generation is:

1. **Fill the 3 placeholder files** in avatar-service (`generator.py`, `loader.py`, `postprocess.py`)
2. **Update the router** to use real inference when the model is loaded
3. **Remove 2 lines** of frontend workaround code
4. **Add 12 lines** of UI info label

Everything else — routing, availability, licensing, error handling, gallery storage,
pack manifests — is already built and waiting.
