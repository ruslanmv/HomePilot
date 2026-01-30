# ComfyUI Patches

This directory contains patches for ComfyUI to fix known issues.

## comfyui-ltx-vae-device-fix.patch

Fixes a device mismatch error in LTX-Video nodes where the VAE has weights on CPU (due to VRAM offloading) while the input tensor is on GPU. This causes the error:

```
RuntimeError: weight is on cpu, different from other tensors on cuda:0
```

### How to apply

From the `ComfyUI` directory:

```bash
git apply ../patches/comfyui-ltx-vae-device-fix.patch
```

### What it does

The patch ensures the VAE is loaded onto the GPU before encoding by calling `comfy.model_management.load_model_gpu()` or moving the model with `.to()`. This is applied to three locations:

1. `LTXVImgToVideo.execute()` - Main image-to-video node
2. `LTXVImgToVideoInplace.execute()` - In-place variant
3. `LTXVAddGuide.encode()` - Guide frame encoding

### Alternative fixes

If this patch doesn't work or you prefer not to modify ComfyUI:

1. **Start ComfyUI with**: `--force-fp16 --fp16-vae`
2. **Or use CPU VAE** (slower): `--cpu-vae`
3. **In ComfyUI Server Config**: Set VAE precision to fp16, VAE device to GPU
