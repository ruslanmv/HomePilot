#!/usr/bin/env bash
set -uo pipefail

# HomePilot Model Download Script
# Automatically downloads and manages AI models for ComfyUI and LLM services
# Usage: ./download_models.sh [preset]
#   Presets: minimal, recommended, full
#   Default: recommended

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
MODELS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/models"
COMFY_MODELS_DIR="${MODELS_DIR}/comfy"
LLM_MODELS_DIR="${MODELS_DIR}/llm"
PRESET="${1:-recommended}"

# Download statistics
TOTAL_DOWNLOADS=0
SUCCESSFUL_DOWNLOADS=0
SKIPPED_DOWNLOADS=0
FAILED_DOWNLOADS=0

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if a file exists and has non-zero size
file_exists_and_valid() {
    local filepath="$1"
    if [[ -f "$filepath" ]] && [[ -s "$filepath" ]]; then
        return 0
    fi
    return 1
}

# Download file with retry and resume support
download_file() {
    local url="$1"
    local output_path="$2"
    local description="${3:-file}"

    ((TOTAL_DOWNLOADS++))

    # Check if file already exists and is valid
    if file_exists_and_valid "$output_path"; then
        log_success "✓ $description already exists ($(du -h "$output_path" | cut -f1))"
        ((SKIPPED_DOWNLOADS++))
        return 0
    fi

    # Create directory if it doesn't exist
    mkdir -p "$(dirname "$output_path")"

    log_info "Downloading $description..."
    log_info "URL: $url"
    log_info "Destination: $output_path"

    # Download with wget (supports resume with -c flag)
    local retries=3
    local attempt=1

    while [[ $attempt -le $retries ]]; do
        if wget -c --progress=bar:force:noscroll \
                --timeout=30 \
                --tries=3 \
                --no-check-certificate \
                -O "$output_path" \
                "$url" 2>&1; then

            # Verify download
            if file_exists_and_valid "$output_path"; then
                log_success "✓ Downloaded $description ($(du -h "$output_path" | cut -f1))"
                ((SUCCESSFUL_DOWNLOADS++))
                return 0
            else
                log_error "Downloaded file is empty or invalid"
                rm -f "$output_path"
            fi
        fi

        log_warning "Download attempt $attempt/$retries failed"
        ((attempt++))

        if [[ $attempt -le $retries ]]; then
            local wait_time=$((attempt * 2))
            log_info "Retrying in ${wait_time}s..."
            sleep "$wait_time"
        fi
    done

    log_error "✗ Failed to download $description after $retries attempts"
    ((FAILED_DOWNLOADS++))
    return 1
}

# Display banner
show_banner() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║         HomePilot Model Download & Setup Utility            ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
}

# Display preset information
show_preset_info() {
    echo -e "Selected preset: ${BLUE}${PRESET}${NC}"
    echo ""

    case "$PRESET" in
        minimal)
            echo "📦 MINIMAL PRESET - Fast setup with essential models"
            echo "   • FLUX Schnell (4GB) - Fast image generation"
            echo "   • Shared CLIP & VAE encoders (3GB)"
            echo "   Upscale (Essential):"
            echo "   • 4x-UltraSharp (80MB) - Required for upscaling"
            echo "   • Total: ~7GB"
            echo "   • VRAM Required: 12-16GB"
            ;;
        recommended)
            echo "📦 RECOMMENDED PRESET - Balanced quality and performance"
            echo "   • FLUX Schnell (4GB) - Fast image generation"
            echo "   • SDXL Base (7GB) - High quality images"
            echo "   • Shared CLIP & VAE encoders (3GB)"
            echo "   Edit Mode Models:"
            echo "   • SDXL Inpainting 0.1 (5GB) - Natural image editing"
            echo "   • SD 1.5 Inpainting (4GB) - Fast fallback"
            echo "   • ControlNet Inpaint (1.4GB) - Edit guidance"
            echo "   • U2Net (170MB) - Background removal"
            echo "   Upscale/Enhance Models:"
            echo "   • 4x-UltraSharp (80MB) - Sharp upscaling"
            echo "   • RealESRGAN x4+ (80MB) - Photo upscaling"
            echo "   • SwinIR 4x (150MB) - Restoration"
            echo "   • Real-ESRGAN General (80MB) - Mixed content"
            echo "   • GFPGAN v1.4 (350MB) - Face restoration"
            echo "   • Total: ~25GB"
            echo "   • VRAM Required: 12-16GB"
            ;;
        full)
            echo "📦 FULL PRESET - All models for maximum flexibility"
            echo "   Image Models:"
            echo "   • FLUX Schnell (4GB) - Fast image generation"
            echo "   • FLUX Dev (24GB) - Highest quality images"
            echo "   • SDXL Base (7GB) - High quality images"
            echo "   • SD 1.5 Dreamshaper (2GB) - Lightweight option"
            echo "   Video Models:"
            echo "   • SVD (10GB) - Video generation"
            echo "   Edit Mode Models:"
            echo "   • SDXL Inpainting 0.1 (5GB) - Natural image editing"
            echo "   • SD 1.5 Inpainting (4GB) - Fast fallback"
            echo "   • ControlNet Inpaint (1.4GB) - Edit guidance"
            echo "   • SAM ViT-H (2.5GB) - Auto-mask segmentation"
            echo "   • U2Net (170MB) - Background removal"
            echo "   Upscale/Enhance Models:"
            echo "   • 4x-UltraSharp (80MB) - Sharp upscaling"
            echo "   • RealESRGAN x4+ (80MB) - Photo upscaling"
            echo "   • SwinIR 4x (150MB) - Restoration"
            echo "   • Real-ESRGAN General (80MB) - Mixed content"
            echo "   • GFPGAN v1.4 (350MB) - Face restoration"
            echo "   Shared:"
            echo "   • CLIP & VAE encoders (3GB)"
            echo "   • Total: ~64GB"
            echo "   • VRAM Required: 16-24GB (for FLUX Dev)"
            ;;
        *)
            log_error "Unknown preset: $PRESET"
            echo "Available presets: minimal, recommended, full"
            exit 1
            ;;
    esac
    echo ""
}

# Download shared encoders (used by FLUX models)
download_shared_encoders() {
    log_info "=== Downloading Shared Encoders (CLIP & VAE) ==="

    # T5-XXL Text Encoder (fp16)
    download_file \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" \
        "${COMFY_MODELS_DIR}/clip/t5xxl_fp16.safetensors" \
        "T5-XXL Text Encoder (fp16)"

    # CLIP-L Text Encoder
    download_file \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
        "${COMFY_MODELS_DIR}/clip/clip_l.safetensors" \
        "CLIP-L Text Encoder"

    # FLUX VAE
    download_file \
        "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors" \
        "${COMFY_MODELS_DIR}/vae/ae.safetensors" \
        "FLUX VAE Encoder"

    echo ""
}

# Download FLUX Schnell (recommended for speed + quality)
download_flux_schnell() {
    log_info "=== Downloading FLUX.1 Schnell (Fast, 4 steps) ==="

    download_file \
        "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors" \
        "${COMFY_MODELS_DIR}/unet/flux1-schnell.safetensors" \
        "FLUX.1 Schnell Model"

    echo ""
}

# Download FLUX Dev (higher quality, slower)
download_flux_dev() {
    log_info "=== Downloading FLUX.1 Dev (High Quality, 20 steps) ==="

    download_file \
        "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors" \
        "${COMFY_MODELS_DIR}/unet/flux1-dev.safetensors" \
        "FLUX.1 Dev Model"

    echo ""
}

# Download SDXL Base
download_sdxl() {
    log_info "=== Downloading Stable Diffusion XL Base ==="

    download_file \
        "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" \
        "${COMFY_MODELS_DIR}/checkpoints/sd_xl_base_1.0.safetensors" \
        "SDXL Base 1.0 Model"

    echo ""
}

# Download SD 1.5 (Dreamshaper 8)
download_sd15() {
    log_info "=== Downloading Stable Diffusion 1.5 (Dreamshaper 8) ==="

    # Note: This is a CivitAI model, using a direct download link
    # Users may need to manually download if this link expires
    download_file \
        "https://civitai.com/api/download/models/128713" \
        "${COMFY_MODELS_DIR}/checkpoints/dreamshaper_8.safetensors" \
        "Dreamshaper 8 Model" || {
        log_warning "If download fails, please manually download from:"
        log_warning "https://civitai.com/models/4384/dreamshaper"
        log_warning "Save as: ${COMFY_MODELS_DIR}/checkpoints/dreamshaper_8.safetensors"
    }

    echo ""
}

# Download SVD (Stable Video Diffusion)
download_svd() {
    log_info "=== Downloading Stable Video Diffusion ==="

    download_file \
        "https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors" \
        "${COMFY_MODELS_DIR}/checkpoints/svd.safetensors" \
        "Stable Video Diffusion Model"

    echo ""
}

# Download SDXL Inpainting (for Edit mode)
download_sdxl_inpainting() {
    log_info "=== Downloading SDXL Inpainting 0.1 (Edit Mode) ==="

    download_file \
        "https://huggingface.co/wangqyqq/sd_xl_base_1.0_inpainting_0.1.safetensors/resolve/main/sd_xl_base_1.0_inpainting_0.1.safetensors" \
        "${COMFY_MODELS_DIR}/checkpoints/sd_xl_base_1.0_inpainting_0.1.safetensors" \
        "SDXL Inpainting 0.1 Model"

    echo ""
}

# Download SD 1.5 Inpainting (fast fallback for Edit mode)
download_sd15_inpainting() {
    log_info "=== Downloading SD 1.5 Inpainting (Edit Mode Fallback) ==="

    download_file \
        "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-inpainting/resolve/main/sd-v1-5-inpainting.ckpt" \
        "${COMFY_MODELS_DIR}/checkpoints/sd-v1-5-inpainting.ckpt" \
        "SD 1.5 Inpainting Model"

    echo ""
}

# Download ControlNet Inpaint (guidance for Edit mode)
download_controlnet_inpaint() {
    log_info "=== Downloading ControlNet SD1.5 Inpaint (Edit Mode Guidance) ==="

    download_file \
        "https://huggingface.co/lllyasviel/control_v11p_sd15_inpaint/resolve/main/diffusion_pytorch_model.safetensors" \
        "${COMFY_MODELS_DIR}/controlnet/control_v11p_sd15_inpaint.safetensors" \
        "ControlNet SD1.5 Inpaint"

    echo ""
}

# Download SAM (Segment Anything Model for Edit mode - optional)
download_sam() {
    log_info "=== Downloading SAM (Segment Anything Model) ==="

    download_file \
        "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth" \
        "${COMFY_MODELS_DIR}/sams/sam_vit_h_4b8939.pth" \
        "SAM ViT-H Model"

    echo ""
}

# Download U2Net (Background Removal for Edit mode - optional)
download_u2net() {
    log_info "=== Downloading U2Net (Background Removal) ==="

    download_file \
        "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx" \
        "${COMFY_MODELS_DIR}/rembg/u2net.onnx" \
        "U2Net Background Removal Model"

    echo ""
}

# Download 4x-UltraSharp (MANDATORY upscaler for minimal preset)
download_upscale_essential() {
    log_info "=== Downloading 4x-UltraSharp (Essential Upscaler) ==="

    download_file \
        "https://huggingface.co/philz1337x/upscaler/resolve/main/4x-UltraSharp.pth" \
        "${COMFY_MODELS_DIR}/upscale_models/4x-UltraSharp.pth" \
        "4x-UltraSharp Upscaler (REQUIRED)"

    echo ""
}

# Download RealESRGAN x4+ (excellent for photos)
download_realesrgan() {
    log_info "=== Downloading RealESRGAN x4+ (Photo Upscaler) ==="

    download_file \
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" \
        "${COMFY_MODELS_DIR}/upscale_models/RealESRGAN_x4plus.pth" \
        "RealESRGAN x4+ Photo Upscaler"

    echo ""
}

# Download SwinIR 4x (restoration upscaler)
download_swinir() {
    log_info "=== Downloading SwinIR 4x (Restoration Upscaler) ==="

    download_file \
        "https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/003_realSR_BSRGAN_DFOWMFC_s64w8_SwinIR-L_x4_GAN.pth" \
        "${COMFY_MODELS_DIR}/upscale_models/SwinIR_4x.pth" \
        "SwinIR 4x Restoration Upscaler"

    echo ""
}

# Download Real-ESRGAN General x4v3 (mixed content)
download_realesrgan_general() {
    log_info "=== Downloading Real-ESRGAN General x4v3 ==="

    download_file \
        "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth" \
        "${COMFY_MODELS_DIR}/upscale_models/realesr-general-x4v3.pth" \
        "Real-ESRGAN General x4v3 Upscaler"

    echo ""
}

# Download GFPGAN v1.4 (face restoration)
download_gfpgan() {
    log_info "=== Downloading GFPGAN v1.4 (Face Restoration) ==="

    download_file \
        "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth" \
        "${COMFY_MODELS_DIR}/gfpgan/GFPGANv1.4.pth" \
        "GFPGAN v1.4 Face Restoration"

    echo ""
}

# Download all upscale/enhance models (for recommended/full presets)
download_upscale_models() {
    log_info "=== Downloading Upscale/Enhance Models ==="
    echo ""
    download_upscale_essential
    download_realesrgan
    download_swinir
    download_realesrgan_general
    download_gfpgan
}

# Download all edit models (for recommended/full presets)
download_edit_models() {
    log_info "=== Downloading Edit Mode Models ==="
    echo ""
    download_sdxl_inpainting
    download_sd15_inpainting
    download_controlnet_inpaint
}

# Download extra edit models (SAM + U2Net for full preset)
download_edit_extras() {
    log_info "=== Downloading Edit Mode Extras (SAM + U2Net) ==="
    echo ""
    download_sam
    download_u2net
}

# Display download summary
show_summary() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    Download Summary                          ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Total files processed:    $TOTAL_DOWNLOADS"
    echo -e "${GREEN}✓ Successfully downloaded: $SUCCESSFUL_DOWNLOADS${NC}"
    echo -e "${YELLOW}⊘ Already existed:         $SKIPPED_DOWNLOADS${NC}"
    echo -e "${RED}✗ Failed downloads:        $FAILED_DOWNLOADS${NC}"
    echo ""

    if [[ $FAILED_DOWNLOADS -gt 0 ]]; then
        log_warning "Some downloads failed. You may need to:"
        echo "  1. Check your internet connection"
        echo "  2. Manually download failed models from HuggingFace or CivitAI"
        echo "  3. Run this script again to retry"
        echo ""
    fi

    # Display disk usage
    if [[ -d "$COMFY_MODELS_DIR" ]]; then
        local total_size
        total_size=$(du -sh "$COMFY_MODELS_DIR" 2>/dev/null | cut -f1 || echo "unknown")
        log_info "Total model storage used: $total_size"
        echo ""
    fi

    if [[ $FAILED_DOWNLOADS -eq 0 ]]; then
        log_success "🎉 All models downloaded successfully!"
        log_info "You can now start HomePilot with: make run"
        echo ""
        log_info "Available image models:"
        echo "  • flux-schnell  - Fast generation (4 steps)"
        echo "  • flux-dev      - High quality (20 steps) [full preset only]"
        echo "  • sdxl          - Stable Diffusion XL [recommended/full preset]"
        echo "  • sd15          - Lightweight SD 1.5 [full preset only]"
        echo ""
        log_info "Available edit models: [recommended/full preset]"
        echo "  • sdxl-inpainting - High quality editing at 1024px"
        echo "  • sd15-inpainting - Fast editing fallback at 512px"
        echo "  • controlnet-inpaint - Structure-preserving guidance"
        echo "  • u2net           - Background removal"
        echo "  • sam             - Auto-mask segmentation [full preset only]"
        echo ""
        log_info "Available upscale/enhance models:"
        echo "  • 4x-UltraSharp    - Sharp, clean upscaling (default)"
        echo "  • RealESRGAN x4+   - Photo upscaling [recommended/full preset]"
        echo "  • SwinIR 4x        - Restoration upscaler [recommended/full preset]"
        echo "  • Real-ESRGAN Gen  - Mixed content [recommended/full preset]"
        echo "  • GFPGAN v1.4      - Face restoration [recommended/full preset]"
        echo ""
        log_info "Set IMAGE_MODEL in .env to change the default model"
    fi
    echo ""
}

# Main download logic based on preset
main() {
    show_banner
    show_preset_info

    # Confirm before proceeding
    if [[ "${SKIP_CONFIRM:-}" != "1" ]]; then
        read -p "Proceed with download? [y/N] " yn
        if [[ "${yn:-}" != "y" && "${yn:-}" != "Y" ]]; then
            log_warning "Download cancelled by user"
            exit 0
        fi
        echo ""
    fi

    # Create base directories
    mkdir -p "$COMFY_MODELS_DIR"/{checkpoints,unet,clip,vae,controlnet,sams,rembg,upscale_models,gfpgan}
    mkdir -p "$LLM_MODELS_DIR"

    log_info "Models directory: $MODELS_DIR"
    echo ""

    # Download based on preset
    case "$PRESET" in
        minimal)
            download_shared_encoders
            download_flux_schnell
            download_upscale_essential  # Required for upscaling to work
            ;;
        recommended)
            download_shared_encoders
            download_flux_schnell
            download_sdxl
            download_edit_models
            download_u2net  # Background removal for Edit mode
            download_upscale_models  # All upscale/enhance models
            ;;
        full)
            download_shared_encoders
            download_flux_schnell
            download_flux_dev
            download_sdxl
            download_sd15
            download_svd
            download_edit_models
            download_edit_extras
            download_upscale_models  # All upscale/enhance models
            ;;
    esac

    # Note about LLM models
    log_info "=== LLM Models (Optional) ==="
    echo "LLM models are managed by Ollama or vLLM."
    echo ""
    echo "For Ollama (recommended):"
    echo "  1. Start HomePilot: make run"
    echo "  2. Ollama will auto-pull models when needed"
    echo "  3. Or manually: docker exec -it homepilot-ollama-1 ollama pull llama3:8b"
    echo ""
    echo "For vLLM (advanced):"
    echo "  Place HuggingFace models in: $LLM_MODELS_DIR"
    echo "  Example: huggingface-cli download meta-llama/Meta-Llama-3-8B-Instruct"
    echo ""

    show_summary
}

# Run main function
main "$@"
