# HomePilot Model Paths Analysis

## ✅ All Paths Are Now Correct and Consistent!

All download mechanisms now use the same base path: `./models/comfy/`

---

## 📁 Path Structure

```
HomePilot/
├── models/
│   └── comfy/               # ← Single source of truth for all ComfyUI models
│       ├── checkpoints/     # SDXL, SD 1.5, SVD, Pony, etc.
│       ├── unet/            # FLUX models (Schnell, Dev)
│       ├── clip/            # Text encoders (T5-XXL, CLIP-L)
│       └── vae/             # VAE encoders (ae.safetensors)
├── ComfyUI/
│   └── models/              # → Should be symlinked to ../models/comfy
└── comfyui/
    └── workflows/           # Workflow JSON templates
```

---

## 🔍 Path Analysis by Component

### 1. **Makefile Download Targets** ✅

| Target | Command | Destination |
|--------|---------|-------------|
| `make download-minimal` | `scripts/download_models.sh minimal` | `./models/comfy/` |
| `make download-recommended` | `scripts/download_models.sh recommended` | `./models/comfy/` |
| `make download-full` | `scripts/download_models.sh full` | `./models/comfy/` |
| `make download-verify` | Checks paths | `./models/comfy/{checkpoints,unet,clip,vae}` |

**Status**: ✅ All correct

---

### 2. **scripts/download_models.sh** ✅

| Model Type | Download Path | Correct? |
|------------|---------------|----------|
| **FLUX Schnell** | `./models/comfy/unet/flux1-schnell.safetensors` | ✅ |
| **FLUX Dev** | `./models/comfy/unet/flux1-dev.safetensors` | ✅ |
| **SDXL Base** | `./models/comfy/checkpoints/sd_xl_base_1.0.safetensors` | ✅ |
| **SD 1.5** | `./models/comfy/checkpoints/dreamshaper_8.safetensors` | ✅ |
| **SVD** | `./models/comfy/checkpoints/svd.safetensors` | ✅ |
| **T5-XXL (CLIP)** | `./models/comfy/clip/t5xxl_fp16.safetensors` | ✅ |
| **CLIP-L** | `./models/comfy/clip/clip_l.safetensors` | ✅ |
| **FLUX VAE** | `./models/comfy/vae/ae.safetensors` | ✅ |

**Status**: ✅ All paths use `COMFY_MODELS_DIR="${MODELS_DIR}/comfy"`

---

### 3. **scripts/download.py (UI Downloads)** ✅

| Setting | Value | Correct? |
|---------|-------|----------|
| `COMFYUI_ROOT` | `PROJECT_ROOT / "models" / "comfy"` | ✅ |
| Image models path | `COMFYUI_ROOT / "checkpoints"` | ✅ |
| Video models path | `COMFYUI_ROOT / "checkpoints"` | ✅ |
| Catalog path handling | Strips `"models/"` prefix | ✅ |

**Example UI Downloads:**
- SDXL → `./models/comfy/checkpoints/sd_xl_base_1.0.safetensors` ✅
- Flux → `./models/comfy/unet/flux1-schnell.safetensors` ✅

**Status**: ✅ Fixed! Now consistent with `download_models.sh`

---

### 4. **backend/app/model_catalog_data.json** ✅

| Model | Catalog Path | Final Destination | Correct? |
|-------|-------------|-------------------|----------|
| SDXL Base | `"checkpoints/"` | `./models/comfy/checkpoints/` | ✅ |
| FLUX Schnell | `"unet/"` | `./models/comfy/unet/` | ✅ |
| FLUX Dev | `"unet/"` | `./models/comfy/unet/` | ✅ |
| Pony XL | `"checkpoints/"` | `./models/comfy/checkpoints/` | ✅ |
| SD 1.5 | `"checkpoints/"` | `./models/comfy/checkpoints/` | ✅ |
| SVD XT | `"checkpoints/"` | `./models/comfy/checkpoints/` | ✅ |

**Note**: Catalog uses relative paths without `"models/"` prefix. The script prepends `COMFYUI_ROOT`.

**Status**: ✅ Fixed! All paths updated from `"models/checkpoints/"` to `"checkpoints/"` or `"unet/"`

---

### 5. **ComfyUI Integration** ⚠️ Requires Symlink

ComfyUI expects models in `./ComfyUI/models/`, but HomePilot downloads to `./models/comfy/`.

**Solution**: Create symlink

```bash
rm -rf ./ComfyUI/models
ln -s $(pwd)/models/comfy ./ComfyUI/models
```

**After symlink, ComfyUI sees:**
```
ComfyUI/models/
├── checkpoints/ → ../models/comfy/checkpoints/
├── unet/ → ../models/comfy/unet/
├── clip/ → ../models/comfy/clip/
└── vae/ → ../models/comfy/vae/
```

**Status**: ⚠️ User must create symlink manually (one-time setup)

---

## 📊 Download Size Estimates

| Preset | What's Downloaded | Total Size |
|--------|------------------|------------|
| **minimal** | FLUX Schnell + encoders (CLIP, VAE) | ~7 GB |
| **recommended** | FLUX Schnell + SDXL + encoders | ~14 GB |
| **full** | FLUX Schnell + Dev, SDXL, SD 1.5, SVD + encoders | ~65 GB |

---

## 🔧 Verification Commands

```bash
# 1. Check what's downloaded
make download-verify

# 2. Manual check
ls -lh models/comfy/checkpoints/
ls -lh models/comfy/unet/
ls -lh models/comfy/clip/
ls -lh models/comfy/vae/

# 3. Check total size
du -sh models/comfy/

# 4. Verify symlink
ls -la ComfyUI/models
```

---

## ✅ Consistency Matrix

| Component | Path Used | Consistent? |
|-----------|-----------|-------------|
| `download_models.sh` | `./models/comfy/` | ✅ |
| `download.py` (UI) | `./models/comfy/` | ✅ |
| `model_catalog_data.json` | Relative paths → `./models/comfy/` | ✅ |
| `Makefile verify` | Checks `./models/comfy/` | ✅ |
| ComfyUI (via symlink) | `./ComfyUI/models/` → `./models/comfy/` | ✅ |

---

## 🎯 Summary

**Everything is now consistent!**

- ✅ `make download-*` commands → `./models/comfy/`
- ✅ UI "Install" button → `./models/comfy/`
- ✅ Catalog paths updated → No `"models/"` prefix
- ✅ ComfyUI integration → Via symlink
- ✅ All paths verified and documented

**No path mismatches remain!**

---

## 🚀 Quick Start Guide

```bash
# 1. Download models
make download-recommended

# 2. Create symlink for ComfyUI
rm -rf ./ComfyUI/models
ln -s $(pwd)/models/comfy ./ComfyUI/models

# 3. Verify installation
make download-verify

# 4. Start everything
make start
```

---

Generated: 2026-01-21
