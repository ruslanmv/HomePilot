import React, { useEffect, useMemo, useState, useCallback } from 'react'
import { Download, RefreshCw, Copy, CheckCircle2, AlertTriangle, XCircle, Settings2, Key, X, Trash2, Shield, ExternalLink } from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type Provider = {
  name: string
  label: string
  kind?: 'chat' | 'image' | 'video' | 'edit' | 'multi'
}

type ModelCatalogEntry = {
  id: string
  label?: string
  recommended?: boolean
  recommended_nsfw?: boolean
  protected?: boolean
  nsfw?: boolean
  description?: string
  size_gb?: number
  resolution?: string
  frames?: number
  // Civitai-specific fields
  civitai_url?: string
  civitai_version_id?: string
  // Addon dependencies (for video models)
  requires_addons?: string[]
  recommends_addons?: string[]
  // Addon-specific fields
  provides_nodes?: string[]
  // Optional install metadata (backend-supported)
  install?: {
    type: 'ollama_pull' | 'http_files' | 'hf_files' | 'hf_snapshot' | 'script' | 'git_repo'
    hint?: string
    requires_custom_nodes?: string[]
    repo_url?: string
    files?: Array<{
      url?: string
      repo_id?: string
      filename?: string
      dest: string
      sha256?: string
    }>
    repo_id?: string
    dest_dir?: string
  }
}

type ModelCatalogResponse = {
  providers?: Record<string, Record<string, ModelCatalogEntry[]>> // providers[providerName][modelType] = list
}

type ModelsListResponse = {
  provider: string
  model_type?: string
  base_url?: string
  models: string[]
  error?: string | null
}

type InstallRequest = {
  provider: string
  model_type: string
  model_id: string
  base_url?: string
  options?: Record<string, any>
}

type InstallResponse = {
  ok?: boolean
  job_id?: string
  message?: string
}

export type ModelsParams = {
  backendUrl: string
  apiKey?: string

  // Defaults from Enterprise Settings
  providerChat?: string
  providerImages?: string
  providerVideo?: string

  baseUrlChat?: string
  baseUrlImages?: string
  baseUrlVideo?: string

  // Experimental features
  experimentalCivitai?: boolean
  civitaiApiKey?: string  // Optional API key for Civitai NSFW content

  // NSFW/Spice Mode - shows additional adult content models
  nsfwMode?: boolean
}

// Avatar model types (from /v1/avatar-models endpoint)
type AvatarModelUsedBy = {
  feature: string
  role: 'required' | 'recommended'
}

type AvatarModelInfo = {
  id: string
  name: string
  description: string
  filename: string
  subdir: string
  installed: boolean
  license: string | null
  commercial_use_ok: boolean | null
  homepage: string | null
  download_url: string | null
  sha256: string | null
  requires: string[] | null
  is_default: boolean
  used_by: AvatarModelUsedBy[]
}

type AvatarFeatureStatus = {
  label: string
  description: string
  ready: boolean
  required_missing: string[]
  recommended_installed: boolean
  recommended_note: string | null
}

type AvatarModelsResponse = {
  category: string
  installed: string[]
  available: AvatarModelInfo[]
  defaults: string[]
  features: Record<string, AvatarFeatureStatus>
}

type AvatarDownloadResult = {
  id: string
  name?: string
  status: 'installed' | 'already_installed' | 'failed' | 'timeout' | 'error' | 'not_registered' | 'no_download_url'
  error?: string
  size?: number
  elapsed?: number
}

type AvatarDownloadStartResponse = {
  ok: boolean
  message?: string
  error?: string
  preset?: string
  total_models?: number
  model_ids?: string[]
}

type AvatarDownloadStatus = {
  running: boolean
  preset: string | null
  current_model: string | null
  current_index: number
  total_models: number
  results: AvatarDownloadResult[]
  finished: boolean
  error: string | null
  elapsed: number
  installed_count: number
  failed_count: number
  downloaded_bytes: number
}

// Civitai search result types
type CivitaiSearchVersion = {
  id: string
  name: string
  downloadUrl?: string
  sizeKB: number
  trainedWords: string[]
}

type CivitaiSearchResult = {
  id: string
  name: string
  type: string
  creator: string
  downloads: number
  rating: number
  ratingCount: number
  link: string | null
  thumbnail: string | null
  nsfw: boolean
  description: string
  tags: string[]
  versions: CivitaiSearchVersion[]
}

type CivitaiSearchResponse = {
  ok: boolean
  query: string
  model_type: string
  nsfw: boolean
  items: CivitaiSearchResult[]
  metadata: {
    currentPage: number
    pageSize: number
    totalItems: number
    totalPages: number
  }
}

// -----------------------------------------------------------------------------
// Fallback Model Catalogs (when backend /model-catalog is not available)
// -----------------------------------------------------------------------------

const FALLBACK_CATALOGS: Record<string, Record<string, ModelCatalogEntry[]>> = {
  ollama: {
    chat: [
      // Standard Chat
      { id: 'llama3:8b', label: 'Llama 3 8B', recommended: true },
      { id: 'llama3:70b', label: 'Llama 3 70B' },
      { id: 'llama3.1', label: 'Llama 3.1 (8B)', recommended: true },
      { id: 'llama3.1:70b', label: 'Llama 3.1 70B' },
      { id: 'llama3.2', label: 'Llama 3.2 (3B)', recommended: true },
      { id: 'mistral:7b', label: 'Mistral 7B' },
      { id: 'mistral-nemo', label: 'Mistral Nemo (12B)', recommended: true },
      { id: 'mixtral:8x7b', label: 'Mixtral 8x7B' },
      { id: 'qwen2.5', label: 'Qwen 2.5 (7B)', recommended: true },
      { id: 'gemma2', label: 'Gemma 2 (9B)' },
      { id: 'phi3:3.8b', label: 'Phi-3 3.8B' },
      { id: 'phi4', label: 'Phi-4 (14B)' },
      { id: 'deepseek-r1:latest', label: 'DeepSeek R1 (7B)' },
      // Uncensored & Roleplay (hidden when Spice Mode off)
      { id: 'dolphin3', label: 'Dolphin 3.0 (8B)', nsfw: true, recommended_nsfw: true },
      { id: 'dolphin-llama3', label: 'Dolphin Llama 3 (8B)', nsfw: true },
      { id: 'dolphin-mistral', label: 'Dolphin Mistral (7B)', nsfw: true, recommended_nsfw: true },
      { id: 'dolphin-mixtral:8x7b', label: 'Dolphin Mixtral (8x7B MoE)', nsfw: true },
      { id: 'hermes3', label: 'Hermes 3 (8B)', nsfw: true, recommended_nsfw: true },
      { id: 'solar', label: 'Solar (10.7B)', nsfw: true },
      { id: 'wizardlm2', label: 'WizardLM2 (7B)', nsfw: true },
      // Legacy Uncensored
      { id: 'llama2-uncensored', label: 'Llama 2 Uncensored (7B)', nsfw: true },
      { id: 'wizardlm-uncensored', label: 'WizardLM Uncensored (13B)', nsfw: true },
      { id: 'wizard-vicuna-uncensored', label: 'Wizard Vicuna Uncensored (7B)', nsfw: true },
      // Abliterated - Mannix
      { id: 'mannix/llama3.1-8b-abliterated', label: 'Llama 3.1 Abliterated (8B)', nsfw: true },
      { id: 'mannix/dolphin-2.9-llama3-8b', label: 'Dolphin 2.9 Llama 3 (8B)', nsfw: true },
      // Abliterated - Huihui.ai
      { id: 'huihui_ai/qwen3-abliterated', label: 'Qwen3 Abliterated', nsfw: true, recommended_nsfw: true },
      { id: 'huihui_ai/qwen3-abliterated:8b', label: 'Qwen3 Abliterated (8B)', nsfw: true, recommended_nsfw: true },
      { id: 'huihui_ai/qwen3-abliterated:4b', label: 'Qwen3 Abliterated (4B)', nsfw: true, recommended_nsfw: true },
      { id: 'huihui_ai/qwen3-coder-abliterated', label: 'Qwen3 Coder Abliterated', nsfw: true },
      { id: 'huihui_ai/qwen3-next-abliterated', label: 'Qwen3-Next Abliterated', nsfw: true },
      { id: 'huihui_ai/dolphin3-abliterated', label: 'Dolphin 3 Abliterated (8B)', nsfw: true, recommended_nsfw: true },
      { id: 'huihui_ai/huihui-moe-abliterated', label: 'Huihui MoE Abliterated', nsfw: true },
      { id: 'huihui_ai/gpt-oss-abliterated', label: 'GPT-OSS Abliterated', nsfw: true },
      // Abliterated - JOSIEFIED
      { id: 'goekdenizguelmez/JOSIEFIED-Qwen3', label: 'JOSIEFIED Qwen3', nsfw: true, recommended_nsfw: true },
      { id: 'goekdenizguelmez/JOSIEFIED-Qwen3:8b', label: 'JOSIEFIED Qwen3 (8B)', nsfw: true, recommended_nsfw: true },
      { id: 'goekdenizguelmez/JOSIEFIED-Qwen2.5', label: 'JOSIEFIED Qwen2.5', nsfw: true },
      { id: 'goekdenizguelmez/JOSIEFIED-Qwen2.5:7b', label: 'JOSIEFIED Qwen2.5 (7B)', nsfw: true, recommended_nsfw: true },
      { id: 'goekdenizguelmez/JOSIEFIED-Qwen2.5:14b', label: 'JOSIEFIED Qwen2.5 (14B)', nsfw: true },
      { id: 'goekdenizguelmez/JOSIEFIED-Qwen2.5:3b', label: 'JOSIEFIED Qwen2.5 (3B)', nsfw: true, recommended_nsfw: true },
      // Vision
      { id: 'huihui_ai/qwen3-vl-abliterated:8b-instruct', label: 'Qwen3 Vision Abliterated (8B)', nsfw: true },
      // Niche Uncensored
      { id: 'yarn-mistral', label: 'Yarn Mistral (7B)', nsfw: true },
      { id: 'openhermes', label: 'OpenHermes (7B)', nsfw: true },
      { id: 'neural-chat', label: 'Neural Chat (7B)', nsfw: true },
      // Additional Abliterated
      { id: 'huihui_ai/llama3.2-abliterate:3b', label: 'Llama 3.2 Abliterated (3B)', nsfw: true },
      { id: 'huihui_ai/gemma3-abliterated', label: 'Gemma 3 Abliterated', nsfw: true },
      { id: 'huihui_ai/deepseek-r1-abliterated:8b', label: 'DeepSeek R1 Abliterated (8B)', nsfw: true },
      { id: 'huihui_ai/deepseek-r1-abliterated:14b', label: 'DeepSeek R1 Abliterated (14B)', nsfw: true },
      { id: 'huihui_ai/deepseek-r1-abliterated:1.5b', label: 'DeepSeek R1 Abliterated (1.5B)', nsfw: true },
      { id: 'dolphincoder', label: 'Dolphin Coder (7B)', nsfw: true },
      { id: 'goekdenizguelmez/JOSIEFIED-Llama', label: 'JOSIEFIED Llama', nsfw: true, recommended_nsfw: true },
      { id: 'samantha-mistral', label: 'Samantha Mistral (7B)', nsfw: true, recommended_nsfw: true },
    ],
    multimodal: [
      // SFW Vision Models
      { id: 'moondream', label: 'Moondream (1.6 GB)', recommended: true, description: 'Ultra-light vision captioning + OCR.' },
      { id: 'gemma3:4b', label: 'Gemma 3 Vision 4B (3 GB)', recommended: true, description: 'Best overall edge multimodal model.' },
      { id: 'llava:7b', label: 'LLaVA 1.6 7B (4.7 GB)', recommended: true, description: 'Strong general-purpose vision model.' },
      { id: 'minicpm-v:latest', label: 'MiniCPM-V 2.6 (5 GB)', description: 'Strong multi-image reasoning.' },
      { id: 'llama3.2-vision:11b', label: 'Llama 3.2 Vision 11B (7 GB)', description: 'Best reasoning near RAM limit.' },
      // NSFW Vision Models
      { id: 'huihui_ai/qwen3-vl-abliterated:8b-instruct', label: 'Qwen3-VL Abliterated 8B (5 GB)', nsfw: true, recommended_nsfw: true, description: 'Unfiltered image descriptions.' },
      { id: 'internvl3:8b', label: 'InternVL3 8B (7 GB)', nsfw: true, recommended_nsfw: true, description: 'Detailed scene analysis.' },
      { id: 'smolvlm2:latest', label: 'SmolVLM2 2.2B (2 GB)', nsfw: true, recommended_nsfw: true, description: 'Fast unrestricted captioning.' },
    ],
  },
  comfyui: {
    image: [
      // Standard SFW models
      { id: 'sd_xl_base_1.0.safetensors', label: 'SDXL Base 1.0 (7GB)', recommended: true, nsfw: false },
      { id: 'flux1-schnell.safetensors', label: 'Flux.1 Schnell (23GB)', nsfw: false },
      { id: 'flux1-dev.safetensors', label: 'Flux.1 Dev (23GB)', nsfw: false },
      { id: 'sd15.safetensors', label: 'Stable Diffusion 1.5 (4GB)', nsfw: false },
      { id: 'realisticVisionV51.safetensors', label: 'Realistic Vision v5.1 (2GB)', nsfw: false },
      // NSFW models (shown when Spice Mode enabled)
      { id: 'ponyDiffusionV6XL.safetensors', label: 'Pony Diffusion v6 XL (7GB)', nsfw: true },
      { id: 'dreamshaper_8.safetensors', label: 'DreamShaper 8 (2GB)', nsfw: true, recommended_nsfw: true },
      { id: 'deliberate_v3.safetensors', label: 'Deliberate v3 (2GB)', nsfw: true },
      { id: 'epicrealism_pureEvolution.safetensors', label: 'epiCRealism Pure Evolution (2GB)', nsfw: true, recommended_nsfw: true },
      { id: 'cyberrealistic_v42.safetensors', label: 'CyberRealistic v4.2 (2GB)', nsfw: true },
      { id: 'absolutereality_v181.safetensors', label: 'AbsoluteReality v1.8.1 (2GB)', nsfw: true },
      { id: 'aZovyaRPGArtist_v5.safetensors', label: 'aZovya RPG Artist v5 (2GB)', nsfw: true },
      { id: 'unstableDiffusion.safetensors', label: 'Unstable Diffusion (4GB)', nsfw: true },
      { id: 'majicmixRealistic_v7.safetensors', label: 'MajicMix Realistic v7 (2GB)', nsfw: true },
      { id: 'bbmix_v4.safetensors', label: 'BBMix v4 (2GB)', nsfw: true },
      { id: 'realisian_v50.safetensors', label: 'Realisian v5.0 (2GB)', nsfw: true },
    ],
    video: [
      { id: 'svd_xt_1_1.safetensors', label: 'Stable Video Diffusion XT 1.1 (10GB)', recommended: true, nsfw: false },
      { id: 'svd_xt.safetensors', label: 'Stable Video Diffusion XT (10GB)', nsfw: false },
      { id: 'svd.safetensors', label: 'Stable Video Diffusion (10GB)', nsfw: false },
      { id: 'ltx-video-2b-v0.9.1.safetensors', label: 'LTX-Video 2B v0.9.1 (6GB)', recommended: true, nsfw: false, description: 'Best for RTX 4080. Fast, lightweight video model.' },
      { id: 'hunyuanvideo_t2v_720p_gguf_q4_k_m_pack', label: 'HunyuanVideo GGUF Q4_K_M Pack (10GB)', recommended: true, nsfw: false, description: 'GGUF pack for 16GB cards. Requires ComfyUI-GGUF.' },
      { id: 'wan2.2_5b_fp16_pack', label: 'Wan 2.2 5B FP16 Pack (22GB)', recommended: true, nsfw: false, description: 'Strong motion + modern video. Official Comfy-Org repack.' },
      { id: 'mochi_preview_fp8_pack', label: 'Mochi 1 Preview FP8 Pack (28GB)', nsfw: false, description: 'Heavier model - may push VRAM limits on 16GB.' },
      { id: 'cogvideox1.5_5b_i2v_snapshot', label: 'CogVideoX 1.5 5B I2V (20GB)', nsfw: false, description: 'Diffusers-style repo. Requires CogVideoX wrapper.' },
    ],
    edit: [
      { id: 'sd_xl_base_1.0_inpainting_0.1.safetensors', label: 'SDXL Inpainting 0.1 (7GB)', recommended: true, nsfw: false },
      { id: 'sd-v1-5-inpainting.ckpt', label: 'SD 1.5 Inpainting (4GB)', recommended: true, nsfw: false },
      { id: 'control_v11p_sd15_inpaint.safetensors', label: 'ControlNet Inpaint (1.5GB)', recommended: true, nsfw: false },
      { id: 'sam_vit_h_4b8939.pth', label: 'SAM ViT-H (2.5GB)', nsfw: false },
      { id: 'u2net.onnx', label: 'Background Remove U2Net (170MB)', nsfw: false },
    ],
    enhance: [
      { id: '4x-UltraSharp.pth', label: '4x UltraSharp (Upscale)', recommended: true, nsfw: false, description: 'Sharp, clean 4x upscaler for general photos.' },
      { id: 'RealESRGAN_x4plus.pth', label: 'RealESRGAN x4+ (Photo)', recommended: true, nsfw: false, description: 'Excellent photo upscaling with natural texture recovery.' },
      { id: 'realesr-general-x4v3.pth', label: 'Real-ESRGAN General x4v3', nsfw: false, description: 'General-purpose Real-ESRGAN model, good for mixed content.' },
      { id: 'SwinIR_4x.pth', label: 'SwinIR 4x (Restore)', nsfw: false, description: 'Restoration upscaler for compression and mild blur cleanup.' },
      { id: 'GFPGANv1.4.pth', label: 'GFPGAN v1.4 (Face Restore)', nsfw: false, description: 'Optional face restoration after heavy edits or upscaling.' },
      { id: 'u2net.onnx', label: 'U2Net (Background Remove)', recommended: true, nsfw: false, description: 'Background removal for Edit mode. Downloads to ~/.u2net or models/comfy/rembg.' },
    ],
    addons: [
      // Text Encoders (required for video models)
      {
        id: 't5xxl_fp8_e4m3fn.safetensors',
        label: 'T5-XXL FP8 Text Encoder (5GB)',
        recommended: true,
        nsfw: false,
        description: 'For 12-16GB VRAM (RTX 4080, 3080). Uses ~5GB vs ~10GB for FP16. Required for LTX-Video on limited VRAM.',
        install: {
          type: 'hf_files',
          files: [{
            repo_id: 'comfyanonymous/flux_text_encoders',
            filename: 't5xxl_fp8_e4m3fn.safetensors',
            dest: 'models/clip/t5xxl_fp8_e4m3fn.safetensors'
          }],
          hint: 'Download to ComfyUI/models/clip folder'
        }
      },
      {
        id: 't5xxl_fp16.safetensors',
        label: 'T5-XXL FP16 Text Encoder (10GB)',
        recommended: true,
        nsfw: false,
        description: 'For 24GB+ VRAM (RTX 4090, A5000). Full precision for best quality. Baseline ~20GB + sampling ~6-10GB peak.',
        install: {
          type: 'hf_files',
          files: [{
            repo_id: 'comfyanonymous/flux_text_encoders',
            filename: 't5xxl_fp16.safetensors',
            dest: 'models/clip/t5xxl_fp16.safetensors'
          }],
          hint: 'Download to ComfyUI/models/clip folder'
        }
      },
      // VAE Models
      {
        id: 'mochi_vae.safetensors',
        label: 'Mochi VAE (400MB)',
        nsfw: false,
        description: 'Required VAE for Mochi video model.',
        install: {
          type: 'hf_files',
          files: [{
            repo_id: 'Comfy-Org/mochi_preview_repackaged',
            filename: 'split_files/vae/mochi_vae.safetensors',
            dest: 'models/vae/mochi_vae.safetensors'
          }],
          hint: 'Download to ComfyUI/models/vae folder'
        }
      },
      // CLIP Models
      {
        id: 'clip_l.safetensors',
        label: 'CLIP-L Text Encoder (250MB)',
        nsfw: false,
        description: 'CLIP-L text encoder for SDXL and video models.',
        install: {
          type: 'hf_files',
          files: [{
            repo_id: 'comfyanonymous/flux_text_encoders',
            filename: 'clip_l.safetensors',
            dest: 'models/clip/clip_l.safetensors'
          }],
          hint: 'Download to ComfyUI/models/clip folder'
        }
      },
    ],
  },
  openai_compat: {
    chat: [
      { id: 'local-model', label: 'Local Model (auto-detect)', recommended: true },
    ],
  },
  civitai: {
    image: [
      // Recommended Civitai models for image generation
      {
        id: 'pony_diffusion_v6_xl',
        label: 'Pony Diffusion V6 XL',
        recommended: true,
        nsfw: true,
        description: 'Base model for character consistency and prompt adherence',
        civitai_url: 'https://civitai.com/models/257749/pony-diffusion-v6-xl',
        civitai_version_id: '290640'
      },
      {
        id: 'cyberrealistic_pony',
        label: 'CyberRealistic Pony',
        recommended: true,
        nsfw: true,
        description: 'Best blend of Pony prompt understanding with photorealism',
        civitai_url: 'https://civitai.com/models/443821/cyberrealistic-pony',
        civitai_version_id: '544666'
      },
      {
        id: 'realvisxl_v50',
        label: 'RealVisXL V5.0',
        recommended: true,
        nsfw: false,
        description: 'Gold standard for photorealistic skin texture and lighting',
        civitai_url: 'https://civitai.com/models/139562/realvisxl-v50',
        civitai_version_id: '361593'
      },
      {
        id: 'juggernaut_xl',
        label: 'Juggernaut XL',
        recommended: true,
        nsfw: false,
        description: 'Cinematic and moody photorealism',
        civitai_url: 'https://civitai.com/models/133005/juggernaut-xl',
        civitai_version_id: '471120'
      },
      {
        id: 'flux1_checkpoint',
        label: 'Flux.1 Checkpoint (Easy)',
        nsfw: false,
        description: 'High-quality Flux checkpoint for ComfyUI',
        civitai_url: 'https://civitai.com/models/628682/flux-1-checkpoint-easy-to-use',
        civitai_version_id: '704954'
      },
    ],
    video: [
      // Recommended Civitai models for video generation
      {
        id: 'ltx_video_workflow',
        label: 'LTX Video (I2V)',
        recommended: true,
        nsfw: false,
        description: 'Fast, lightweight video generation for RTX cards',
        civitai_url: 'https://civitai.com/models/995093/ltx-image-to-video-with-stg-caption-and-clip-extend-workflow',
        civitai_version_id: '1119428'
      },
      {
        id: 'mochi_1_pack',
        label: 'Mochi 1 Video Pack',
        recommended: true,
        nsfw: false,
        description: 'High motion fidelity video model',
        civitai_url: 'https://civitai.com/models/886896/donut-mochi-pack-video-generation',
        civitai_version_id: '992820'
      },
      {
        id: 'animatediff_sdxl',
        label: 'AnimateDiff SDXL',
        nsfw: false,
        description: 'Animate SDXL images using AnimateDiff',
        civitai_url: 'https://civitai.com/models/331700/odinson-sdxl-animatediff',
        civitai_version_id: '373089'
      },
      {
        id: 'animatediff_lightning',
        label: 'AnimateDiff Lightning',
        nsfw: false,
        description: 'Fast 4-step AnimateDiff model',
        civitai_url: 'https://civitai.com/models/500187/animatediff-lightning',
        civitai_version_id: '554533'
      },
    ],
  },
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

function cleanBase(url: string) {
  return (url || '').trim().replace(/\/+$/, '')
}

async function getJson<T>(baseUrl: string, path: string, apiKey?: string): Promise<T> {
  const url = `${cleanBase(baseUrl)}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'GET',
    headers: {
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

async function postJson<T>(baseUrl: string, path: string, body: any, apiKey?: string): Promise<T> {
  const url = `${cleanBase(baseUrl)}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
    },
    credentials: 'include',
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

function chipClass(kind: 'ok' | 'warn' | 'bad' | 'muted') {
  switch (kind) {
    case 'ok':
      return 'bg-emerald-500/10 text-emerald-200 border-emerald-500/20'
    case 'warn':
      return 'bg-amber-500/10 text-amber-200 border-amber-500/20'
    case 'bad':
      return 'bg-rose-500/10 text-rose-200 border-rose-500/20'
    default:
      return 'bg-white/5 text-white/60 border-white/10'
  }
}

function IconStatus({ kind }: { kind: 'ok' | 'warn' | 'bad' | 'muted' }) {
  if (kind === 'ok') return <CheckCircle2 size={14} className="text-emerald-300" />
  if (kind === 'warn') return <AlertTriangle size={14} className="text-amber-300" />
  if (kind === 'bad') return <XCircle size={14} className="text-rose-300" />
  return <Settings2 size={14} className="text-white/50" />
}

function safeLabel(id: string, label?: string) {
  return label?.trim() ? label.trim() : id
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

export default function ModelsView(props: ModelsParams) {
  const authKey = (props.apiKey || '').trim()
  const backendUrl = cleanBase(props.backendUrl)

  const [providers, setProviders] = useState<Provider[]>([])
  const [providersError, setProvidersError] = useState<string | null>(null)

  const [modelType, setModelType] = useState<'chat' | 'multimodal' | 'image' | 'video' | 'edit' | 'enhance' | 'addons'>('chat')
  const [provider, setProvider] = useState<string>(props.providerChat || 'ollama')

  const defaultBaseUrl = useMemo(() => {
    if (modelType === 'chat') return props.baseUrlChat || ''
    if (modelType === 'multimodal') return props.baseUrlChat || ''
    if (modelType === 'image') return props.baseUrlImages || ''
    if (modelType === 'edit') return props.baseUrlImages || ''
    if (modelType === 'enhance') return props.baseUrlImages || ''
    if (modelType === 'addons') return props.baseUrlImages || ''
    return props.baseUrlVideo || ''
  }, [modelType, props.baseUrlChat, props.baseUrlImages, props.baseUrlVideo])

  const [baseUrl, setBaseUrl] = useState<string>(defaultBaseUrl)

  // Installed models (dynamic)
  const [installed, setInstalled] = useState<string[]>([])
  const [installedError, setInstalledError] = useState<string | null>(null)
  const [installedLoading, setInstalledLoading] = useState(false)

  // Supported models (curated) — optional endpoint
  const [catalog, setCatalog] = useState<ModelCatalogResponse | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(false)

  // Install/delete jobs — optional endpoint (we degrade if not present)
  const [installBusy, setInstallBusy] = useState<string | null>(null)
  const [deleteBusy, setDeleteBusy] = useState<string | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  // Civitai-specific state
  const [civitaiVersionId, setCivitaiVersionId] = useState<string>('')

  // Civitai search state
  const [civitaiQuery, setCivitaiQuery] = useState<string>('')
  const [civitaiResults, setCivitaiResults] = useState<CivitaiSearchResult[]>([])
  const [civitaiSearchLoading, setCivitaiSearchLoading] = useState(false)
  const [civitaiSearchError, setCivitaiSearchError] = useState<string | null>(null)
  const [civitaiPage, setCivitaiPage] = useState(1)
  const [civitaiTotalPages, setCivitaiTotalPages] = useState(1)

  // API Keys state (optional - for gated models)
  const [apiKeysExpanded, setApiKeysExpanded] = useState(false)
  const [apiKeysStatus, setApiKeysStatus] = useState<Record<string, { configured: boolean; source: string; masked: string | null }>>({})
  const [apiKeyInput, setApiKeyInput] = useState<{ huggingface: string; civitai: string }>({ huggingface: '', civitai: '' })
  const [apiKeyTesting, setApiKeyTesting] = useState<string | null>(null)
  const [apiKeySaving, setApiKeySaving] = useState<string | null>(null)

  // Avatar & Identity models state (shown in Add-ons tab)
  const [avatarModels, setAvatarModels] = useState<AvatarModelInfo[]>([])
  const [avatarFeatures, setAvatarFeatures] = useState<Record<string, AvatarFeatureStatus>>({})
  const [avatarModelsLoading, setAvatarModelsLoading] = useState(false)
  const [avatarModelsError, setAvatarModelsError] = useState<string | null>(null)
  const [avatarDownloadBusy, setAvatarDownloadBusy] = useState<string | null>(null) // 'basic' | 'full' | null
  const [avatarDownloadStatus, setAvatarDownloadStatus] = useState<AvatarDownloadStatus | null>(null)
  const [avatarDeleteConfirm, setAvatarDeleteConfirm] = useState<string | null>(null)
  const [avatarDeleteBusy, setAvatarDeleteBusy] = useState<string | null>(null)
  const [avatarInstallBusy, setAvatarInstallBusy] = useState<string | null>(null) // model ID being installed

  // Filter providers based on model type
  const availableProviders = useMemo(() => {
    if (modelType === 'chat') {
      // For chat: all providers EXCEPT comfyui and civitai
      return providers.filter(p => p.name !== 'comfyui' && p.name !== 'civitai')
    } else if (modelType === 'multimodal') {
      // Multimodal: only Ollama (vision models run locally)
      return providers.filter(p => p.name === 'ollama')
    } else {
      // For image/video/edit/enhance: comfyui + civitai (if experimental enabled)
      const filtered = providers.filter(p => p.name === 'comfyui')

      // Add Civitai only for image/video (Civitai API only supports these types)
      if (props.experimentalCivitai && (modelType === 'image' || modelType === 'video')) {
        filtered.push({
          name: 'civitai',
          label: '🧪 Civitai (Experimental)',
          kind: modelType as any,
        })
      }

      return filtered
    }
  }, [providers, modelType, props.experimentalCivitai])

  useEffect(() => {
    // When modelType changes, update provider + baseUrl defaults
    if (modelType === 'chat') {
      // Switch to a chat provider (prefer the one from settings, or default to ollama)
      const newProvider = props.providerChat || 'ollama'
      setProvider(newProvider)
      setBaseUrl(props.baseUrlChat || '')
    } else if (modelType === 'multimodal') {
      // Multimodal models are served via Ollama (vision-capable models)
      setProvider('ollama')
      setBaseUrl(props.baseUrlChat || '')
    } else if (modelType === 'image') {
      // Switch to comfyui for images
      setProvider('comfyui')
      setBaseUrl(props.baseUrlImages || '')
    } else if (modelType === 'addons') {
      // Switch to comfyui for addons (extensions)
      setProvider('comfyui')
      setBaseUrl(props.baseUrlImages || '')
    } else {
      // Switch to comfyui for videos
      setProvider('comfyui')
      setBaseUrl(props.baseUrlVideo || '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelType])

  // Load providers list from backend
  useEffect(() => {
    let mounted = true
    setProvidersError(null)

    ;(async () => {
      try {
        const res = await getJson<{ ok: boolean; providers: Record<string, any> }>(backendUrl, '/providers', authKey)
        if (!mounted) return
        const providerList: Provider[] = Object.entries(res.providers || {}).map(([name, info]: [string, any]) => ({
          name,
          label: info.label || name,
          kind: 'multi',
        }))
        setProviders(providerList)
      } catch (e: any) {
        if (!mounted) return
        setProviders([])
        setProvidersError(e?.message || String(e))
      }
    })()

    return () => {
      mounted = false
    }
  }, [backendUrl, authKey])

  // Load supported catalog (optional)
  const refreshCatalog = async () => {
    setCatalogLoading(true)
    setCatalogError(null)
    try {
      const data = await getJson<ModelCatalogResponse>(backendUrl, '/model-catalog', authKey)
      setCatalog(data)
    } catch (e: any) {
      // Degrade gracefully if endpoint doesn't exist
      setCatalog(null)
      setCatalogError(e?.message || String(e))
    } finally {
      setCatalogLoading(false)
    }
  }

  // Load installed models (only for local providers)
  const refreshInstalled = async () => {
    // Skip fetching installed models for remote API providers and Civitai
    // Remote providers: they're cloud services, not local installations
    // Civitai: download-only provider, models get installed to ComfyUI after download
    const skipProviders = ['openai', 'claude', 'watsonx', 'civitai']

    if (skipProviders.includes(provider)) {
      setInstalled([])
      setInstalledError(null)
      setInstalledLoading(false)
      return
    }

    setInstalledLoading(true)
    setInstalledError(null)
    setInstalled([])  // Clear stale list immediately so old type models don't flash
    try {
      const q = new URLSearchParams()
      q.set('provider', provider)
      if (baseUrl.trim()) q.set('base_url', baseUrl.trim())
      // Pass model_type so backend returns correct installed models for this type
      if (modelType && provider === 'comfyui') q.set('model_type', modelType)
      // For Ollama multimodal, filter to vision-capable models only
      if (modelType === 'multimodal' && provider === 'ollama') q.set('model_type', 'multimodal')

      const data = await getJson<ModelsListResponse>(backendUrl, `/models?${q.toString()}`, authKey)
      setInstalled(Array.isArray(data.models) ? data.models : [])
      if (data.error) setInstalledError(String(data.error))
    } catch (e: any) {
      setInstalled([])
      setInstalledError(e?.message || String(e))
    } finally {
      setInstalledLoading(false)
    }
  }

  useEffect(() => {
    refreshInstalled()
    // Load catalog once initially (optional)
    if (catalog === null && catalogError === null && !catalogLoading) {
      refreshCatalog()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, modelType, baseUrl, backendUrl])

  const supportedForSelection: ModelCatalogEntry[] = useMemo(() => {
    let list: ModelCatalogEntry[] = []

    // Try backend catalog first
    const p = catalog?.providers?.[provider]
    if (p) {
      const catalogList = p?.[modelType] || []
      if (Array.isArray(catalogList) && catalogList.length > 0) {
        list = catalogList
      }
    }

    // Fallback to hardcoded catalogs if backend catalog not available
    if (list.length === 0) {
      const fallback = FALLBACK_CATALOGS[provider]?.[modelType]
      list = Array.isArray(fallback) ? fallback : []
    }

    // Filter based on NSFW mode:
    // - When nsfwMode is OFF: show only non-NSFW models (nsfw !== true)
    // - When nsfwMode is ON: show ALL models (both SFW and NSFW)
    if (!props.nsfwMode) {
      list = list.filter((m) => m.nsfw !== true)
    }

    return list
  }, [catalog, provider, modelType, props.nsfwMode])

  const installedSet = useMemo(() => new Set(installed), [installed])

  // For Ollama: also match "model" with "model:latest" (Ollama convention)
  const isInstalled = useCallback((id: string): boolean => {
    if (installedSet.has(id)) return true
    // Check if installed list contains id:latest (e.g. catalog has "moondream", Ollama reports "moondream:latest")
    if (!id.includes(':') && installedSet.has(`${id}:latest`)) return true
    // Check if catalog has "model:tag" and installed has exactly that
    return false
  }, [installedSet])

  // Merge supported + installed
  const merged = useMemo(() => {
    const supportedMap = new Map<string, ModelCatalogEntry>()
    for (const s of supportedForSelection) supportedMap.set(s.id, s)

    const rows: Array<{
      id: string
      label: string
      recommended?: boolean
      recommended_nsfw?: boolean
      protected?: boolean
      nsfw?: boolean
      description?: string
      civitai_url?: string
      civitai_version_id?: string
      status: 'installed' | 'missing' | 'installed_unsupported'
      install?: ModelCatalogEntry['install']
    }> = []

    // Supported first
    for (const s of supportedForSelection) {
      rows.push({
        id: s.id,
        label: safeLabel(s.id, s.label),
        recommended: s.recommended,
        recommended_nsfw: s.recommended_nsfw,
        protected: s.protected,
        nsfw: s.nsfw,
        description: s.description,
        civitai_url: s.civitai_url,
        civitai_version_id: s.civitai_version_id,
        status: isInstalled(s.id) ? 'installed' : 'missing',
        install: s.install,
      })
    }

    // Then show installed but not in supported catalog
    // Use the catalog as source of truth to prevent type mixing:
    // e.g. video checkpoints (svd_xt_1_1, ltx-video) must NOT appear
    // in the Image tab just because they share the checkpoints/ directory.
    const otherTypeIds = new Set<string>()
    if (provider === 'comfyui' && catalog?.providers?.comfyui) {
      const comfyui = catalog.providers.comfyui as Record<string, ModelCatalogEntry[]>
      for (const [t, entries] of Object.entries(comfyui)) {
        if (t !== modelType && Array.isArray(entries)) {
          for (const entry of entries) {
            if (entry.id) otherTypeIds.add(entry.id)
          }
        }
      }
    }

    // Heuristic: filter out "custom" models that clearly belong to the wrong type.
    // Checkpoint files (.safetensors, .ckpt) should never appear in the chat tab;
    // Ollama-style models (name:tag) should never appear in image/video/edit tabs.
    const isCheckpointFile = (id: string) =>
      /\.(safetensors|ckpt|pth|onnx|gguf|pt|bin)$/i.test(id)
    const isLlmModel = (id: string) =>
      id.includes(':') || /^(llama|mistral|gemma|qwen|phi|deepseek|codellama|vicuna|samantha)/i.test(id)

    // Check if an installed model name matches any supported catalog entry
    // e.g. "moondream:latest" matches catalog "moondream"
    const matchesSupportedEntry = (modelName: string): boolean => {
      if (supportedMap.has(modelName)) return true
      // "model:latest" → try "model" (Ollama convention)
      if (modelName.endsWith(':latest')) {
        const base = modelName.slice(0, -':latest'.length)
        if (supportedMap.has(base)) return true
      }
      return false
    }

    for (const m of installed) {
      if (!matchesSupportedEntry(m)) {
        // Skip models that belong to another type's catalog
        if (otherTypeIds.has(m)) continue
        // Skip checkpoint files on the chat tab
        if (modelType === 'chat' && isCheckpointFile(m)) continue
        // Skip LLM models on ComfyUI tabs (image/video/edit/enhance)
        if (modelType !== 'chat' && provider === 'comfyui' && isLlmModel(m)) continue
        rows.push({
          id: m,
          label: m,
          status: 'installed_unsupported',
        })
      }
    }

    // Sorting: recommended → recommended_nsfw → installed → missing → unsupported
    rows.sort((a, b) => {
      // Priority: recommended (or recommended_nsfw in NSFW mode) first
      const isRecommendedA = a.recommended || (props.nsfwMode && a.recommended_nsfw)
      const isRecommendedB = b.recommended || (props.nsfwMode && b.recommended_nsfw)
      const ar = isRecommendedA ? 0 : 1
      const br = isRecommendedB ? 0 : 1
      if (ar !== br) return ar - br
      const order = (s: string) =>
        s === 'installed' ? 0 : s === 'missing' ? 1 : 2
      return order(a.status) - order(b.status)
    })

    return rows
  }, [supportedForSelection, installed, installedSet, isInstalled, props.nsfwMode, modelType, provider])

  const tryInstall = async (modelId: string, install?: ModelCatalogEntry['install']) => {
    setInstallBusy(modelId)

    try {
      const body: InstallRequest = {
        provider,
        model_type: modelType,
        model_id: modelId,
        base_url: baseUrl.trim() || undefined,
        options: {},
      }

      // Add civitai_version_id if provider is civitai
      if (provider === 'civitai') {
        if (!civitaiVersionId.trim()) {
          setToast('Please enter a Civitai version ID')
          setInstallBusy(null)
          return
        }
        (body as any).civitai_version_id = civitaiVersionId.trim()
        setToast(`Starting Civitai download for version ${civitaiVersionId}...`)
      } else {
        setToast(`Starting download for ${modelId}...`)
      }

      const res = await postJson<InstallResponse>(backendUrl, '/models/install', body, authKey)

      if (res?.ok) {
        setToast(res.message || `Successfully installed ${modelId}`)
        // Refresh installed list after successful installation
        setTimeout(() => {
          refreshInstalled()
        }, 2000)
      } else {
        setToast(res?.message || 'Installation request sent.')
      }
    } catch (e: any) {
      // Fallback to copy-paste instructions if API fails
      if (provider === 'ollama') {
        const cmd = `ollama pull ${modelId}`
        navigator.clipboard?.writeText(cmd).catch(() => {})
        setToast(`API failed. Command copied: ${cmd}`)
      } else if (provider === 'comfyui') {
        navigator.clipboard?.writeText(`Run: python scripts/download.py --model ${modelId}`).catch(() => {})
        setToast('API failed. Download command copied to clipboard.')
      } else if (provider === 'civitai') {
        setToast(`Installation failed: ${e?.message || String(e)}`)
      } else {
        setToast(`Installation failed: ${e?.message || String(e)}`)
      }
    } finally {
      setInstallBusy(null)
    }
  }

  const tryDelete = async (modelId: string) => {
    setDeleteBusy(modelId)
    setDeleteConfirm(null)
    try {
      const body = {
        provider,
        model_type: modelType,
        model_id: modelId,
      }
      setToast(`Deleting ${modelId}...`)
      const res = await postJson<{ ok?: boolean; message?: string }>(backendUrl, '/models/delete', body, authKey)
      if (res?.ok) {
        setToast(res.message || `Deleted ${modelId}`)
        setTimeout(() => refreshInstalled(), 500)
      } else {
        setToast(res?.message || 'Delete failed.')
      }
    } catch (e: any) {
      setToast(`Delete failed: ${e?.message || String(e)}`)
    } finally {
      setDeleteBusy(null)
    }
  }

  // Civitai search function
  const searchCivitai = async (page = 1) => {
    if (!civitaiQuery.trim()) {
      setToast('Please enter a search query')
      return
    }

    setCivitaiSearchLoading(true)
    setCivitaiSearchError(null)

    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(authKey ? { 'x-api-key': authKey } : {}),
      }

      // Pass Civitai API key if available and NSFW mode is enabled
      if (props.civitaiApiKey && props.nsfwMode) {
        headers['X-Civitai-Api-Key'] = props.civitaiApiKey
      }

      const res = await fetch(`${backendUrl}/civitai/search`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          query: civitaiQuery.trim(),
          // Civitai only supports 'image' or 'video' - map other types appropriately
          model_type: modelType === 'video' ? 'video' : 'image',
          nsfw: props.nsfwMode || false,
          limit: 20,
          page,
          sort: 'Highest Rated',
        }),
      })

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}: ${text}`)
      }

      const data: CivitaiSearchResponse = await res.json()

      if (data.ok) {
        setCivitaiResults(data.items || [])
        setCivitaiPage(data.metadata?.currentPage || page)
        setCivitaiTotalPages(data.metadata?.totalPages || 1)

        if (data.items.length === 0) {
          setToast('No models found. Try a different search term.')
        }
      } else {
        throw new Error('Search failed')
      }
    } catch (e: any) {
      console.error('[Civitai Search Error]', e)
      setCivitaiSearchError(e?.message || String(e))
      setToast(`Search failed: ${e?.message || 'Unknown error'}`)
    } finally {
      setCivitaiSearchLoading(false)
    }
  }

  // Install from Civitai search result
  const installFromCivitaiResult = async (model: CivitaiSearchResult, versionId: string) => {
    setInstallBusy(model.id)

    try {
      const body = {
        provider: 'civitai',
        model_type: modelType === 'edit' ? 'image' : modelType, // Civitai uses 'image' for edit models
        model_id: model.id,
        civitai_version_id: versionId,
        civitai_api_key: props.nsfwMode ? props.civitaiApiKey : undefined,
      }

      setToast(`Starting download for ${model.name}...`)

      const res = await postJson<InstallResponse>(backendUrl, '/models/install', body, authKey)

      if (res?.ok) {
        setToast(res.message || `Successfully installed ${model.name}`)
        // Refresh installed list after successful installation
        setTimeout(() => {
          refreshInstalled()
        }, 2000)
      } else {
        setToast(res?.message || 'Installation request sent.')
      }
    } catch (e: any) {
      setToast(`Installation failed: ${e?.message || String(e)}`)
    } finally {
      setInstallBusy(null)
    }
  }

  // API Keys management functions
  const loadApiKeysStatus = async () => {
    try {
      const data = await getJson<{ ok: boolean; keys: Record<string, any> }>(backendUrl, '/settings/api-keys', authKey)
      if (data.keys) {
        setApiKeysStatus(data.keys)
      }
    } catch (e) {
      // API keys endpoint not available - that's OK, it's optional
      console.debug('[API Keys] Endpoint not available:', e)
    }
  }

  const saveApiKey = async (provider: 'huggingface' | 'civitai') => {
    const key = apiKeyInput[provider].trim()
    if (!key) {
      setToast(`Please enter a ${provider === 'huggingface' ? 'HuggingFace' : 'Civitai'} API key`)
      return
    }

    setApiKeySaving(provider)
    try {
      const res = await postJson<{ ok: boolean; message?: string }>(
        backendUrl,
        '/settings/api-keys',
        { provider, key },
        authKey
      )
      if (res.ok) {
        setToast(res.message || `${provider} API key saved successfully`)
        setApiKeyInput(prev => ({ ...prev, [provider]: '' }))
        await loadApiKeysStatus()
      } else {
        setToast(`Failed to save ${provider} API key`)
      }
    } catch (e: any) {
      setToast(`Error saving API key: ${e?.message || String(e)}`)
    } finally {
      setApiKeySaving(null)
    }
  }

  const testApiKey = async (provider: 'huggingface' | 'civitai') => {
    setApiKeyTesting(provider)
    try {
      const keyToTest = apiKeyInput[provider].trim() || undefined
      const res = await postJson<{ ok: boolean; valid: boolean; message: string; username?: string }>(
        backendUrl,
        '/settings/api-keys/test',
        { provider, key: keyToTest },
        authKey
      )
      if (res.valid) {
        setToast(`${provider} key valid: ${res.message}`)
      } else {
        setToast(`${provider} key invalid: ${res.message}`)
      }
    } catch (e: any) {
      setToast(`Error testing API key: ${e?.message || String(e)}`)
    } finally {
      setApiKeyTesting(null)
    }
  }

  const deleteApiKey = async (provider: 'huggingface' | 'civitai') => {
    try {
      const res = await fetch(`${backendUrl}/settings/api-keys/${provider}`, {
        method: 'DELETE',
        headers: authKey ? { 'x-api-key': authKey } : {},
      })
      const data = await res.json()
      if (data.ok) {
        setToast(data.message || `${provider} API key removed`)
        await loadApiKeysStatus()
      }
    } catch (e: any) {
      setToast(`Error removing API key: ${e?.message || String(e)}`)
    }
  }

  // Load API keys status when expanded
  useEffect(() => {
    if (apiKeysExpanded) {
      loadApiKeysStatus()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKeysExpanded])

  // Fetch avatar models when Add-ons tab is active
  const refreshAvatarModels = useCallback(async () => {
    setAvatarModelsLoading(true)
    setAvatarModelsError(null)
    try {
      const data = await getJson<AvatarModelsResponse>(backendUrl, '/v1/avatar-models', authKey)
      setAvatarModels(data.available || [])
      setAvatarFeatures(data.features || {})
    } catch (e: any) {
      setAvatarModelsError(e?.message || String(e))
      setAvatarModels([])
      setAvatarFeatures({})
    } finally {
      setAvatarModelsLoading(false)
    }
  }, [backendUrl, authKey])

  useEffect(() => {
    if (modelType === 'addons') {
      refreshAvatarModels()
    }
  }, [modelType, refreshAvatarModels])

  const downloadAvatarPreset = async (preset: 'basic' | 'full') => {
    setAvatarDownloadBusy(preset)
    setAvatarDownloadStatus(null)
    setToast(`Starting ${preset === 'basic' ? 'Basic' : 'Full'} avatar model download...`)
    try {
      const res = await fetch(`${backendUrl}/v1/avatar-models/download?preset=${preset}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authKey ? { 'x-api-key': authKey } : {}),
        },
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ''}`)
      }
      const data: AvatarDownloadStartResponse = await res.json()
      if (!data.ok) {
        setToast(data.error || 'Download failed to start.')
        setAvatarDownloadBusy(null)
        return
      }
      setToast(data.message || 'Download started — monitoring progress...')
      // Start polling
    } catch (e: any) {
      setToast(`Download error: ${e?.message || String(e)}`)
      setAvatarDownloadBusy(null)
    }
  }

  // Poll download status while a download is active
  useEffect(() => {
    if (!avatarDownloadBusy) return

    let cancelled = false
    const poll = async () => {
      while (!cancelled) {
        await new Promise((r) => setTimeout(r, 4000))
        if (cancelled) break
        try {
          const res = await fetch(`${backendUrl}/v1/avatar-models/download/status`, {
            headers: authKey ? { 'x-api-key': authKey } : {},
          })
          if (!res.ok) continue
          const status: AvatarDownloadStatus = await res.json()
          if (cancelled) break

          setAvatarDownloadStatus(status)

          if (status.finished || !status.running) {
            // Done — show final summary toast only once
            const msg = `Download complete: ${status.installed_count}/${status.total_models} installed`
              + (status.failed_count > 0 ? ` (${status.failed_count} failed)` : '')
              + ` — ${formatBytes(status.downloaded_bytes)} in ${Math.round(status.elapsed)}s`
            setToast(msg)
            setAvatarDownloadBusy(null)
            // Refresh model list
            setTimeout(() => refreshAvatarModels(), 500)
            break
          }
        } catch {
          // Network hiccup — keep polling
        }
      }
    }
    poll()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [avatarDownloadBusy, backendUrl, authKey])

  const deleteAvatarModel = async (modelId: string) => {
    setAvatarDeleteBusy(modelId)
    setAvatarDeleteConfirm(null)
    try {
      const res = await fetch(`${backendUrl}/v1/avatar-models/${modelId}`, {
        method: 'DELETE',
        headers: authKey ? { 'x-api-key': authKey } : {},
      })
      const data = await res.json()
      if (data.ok) {
        setToast(`Uninstalled ${data.name || modelId} — freed ${data.freed_human || ''}`)
        setTimeout(() => refreshAvatarModels(), 500)
      } else {
        setToast(`Delete failed: ${data.error || 'unknown error'}`)
      }
    } catch (e: any) {
      setToast(`Delete error: ${e?.message || String(e)}`)
    } finally {
      setAvatarDeleteBusy(null)
    }
  }

  const installSingleAvatarModel = async (modelId: string) => {
    setAvatarInstallBusy(modelId)
    setToast(`Starting download for ${modelId}...`)
    try {
      const res = await fetch(`${backendUrl}/v1/avatar-models/${modelId}/install`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authKey ? { 'x-api-key': authKey } : {}),
        },
      })
      const data = await res.json()
      if (data.ok) {
        if (data.already_installed) {
          setToast(`${modelId} is already installed`)
          setAvatarInstallBusy(null)
          return
        }
        // Start polling for progress
        setAvatarDownloadBusy(`single:${modelId}`)
      } else {
        setToast(`Install failed: ${data.error || 'unknown error'}`)
      }
    } catch (e: any) {
      setToast(`Install error: ${e?.message || String(e)}`)
    } finally {
      setAvatarInstallBusy(null)
    }
  }

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  return (
    <div className="h-full w-full bg-black text-white overflow-hidden flex flex-col">
      {/* Header */}
      <div className="px-8 py-6 border-b border-white/10 flex items-center justify-between bg-gradient-to-b from-white/[0.02] to-transparent">
        <div>
          <div className="text-2xl font-bold text-white tracking-tight">Model Management</div>
          <div className="text-sm text-white/40 mt-1">Configure and deploy AI models across providers</div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => refreshCatalog()}
            disabled={catalogLoading}
            className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-semibold flex items-center gap-2.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={15} className={catalogLoading ? 'animate-spin' : ''} />
            Refresh Catalog
          </button>

          <button
            type="button"
            onClick={() => refreshInstalled()}
            disabled={installedLoading}
            className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-semibold flex items-center gap-2.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={15} className={installedLoading ? 'animate-spin' : ''} />
            Refresh Installed
          </button>

          {/* API Keys Settings Button */}
          <button
            type="button"
            onClick={() => setApiKeysExpanded(true)}
            className="p-2.5 rounded-xl bg-transparent hover:bg-white/5 border border-transparent hover:border-white/10 text-white/40 hover:text-white/70 transition-all"
            title="API Keys (for gated models)"
          >
            <Key size={16} />
          </button>
        </div>
      </div>

      {/* API Keys Modal */}
      {apiKeysExpanded && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setApiKeysExpanded(false)}
          />

          {/* Modal */}
          <div className="relative bg-zinc-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-white/[0.02]">
              <div className="flex items-center gap-3">
                <Key size={18} className="text-white/50" />
                <div>
                  <h2 className="text-lg font-bold text-white">API Keys</h2>
                  <p className="text-xs text-white/40">Optional - for gated HuggingFace and Civitai models</p>
                </div>
              </div>
              <button
                onClick={() => setApiKeysExpanded(false)}
                className="p-2 rounded-lg hover:bg-white/5 text-white/40 hover:text-white/70 transition-all"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* HuggingFace Token */}
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <div className="text-sm font-bold text-white">HuggingFace Token</div>
                    <div className="text-[10px] text-white/40 mt-0.5">For FLUX, SVD XT 1.1, gated models</div>
                  </div>
                  {apiKeysStatus.huggingface?.configured && (
                    <span className={`px-2 py-1 rounded text-[10px] font-bold uppercase ${
                      apiKeysStatus.huggingface.source === 'environment'
                        ? 'bg-blue-500/20 text-blue-300'
                        : 'bg-emerald-500/20 text-emerald-300'
                    }`}>
                      {apiKeysStatus.huggingface.source === 'environment' ? 'ENV' : 'Stored'}
                    </span>
                  )}
                </div>

                {apiKeysStatus.huggingface?.configured ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 bg-white/5 rounded-lg px-3 py-2">
                      <span className="text-emerald-400 text-sm">✓</span>
                      <span className="text-xs text-white/60 font-mono">{apiKeysStatus.huggingface.masked}</span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => testApiKey('huggingface')}
                        disabled={apiKeyTesting === 'huggingface'}
                        className="flex-1 px-3 py-2 text-xs font-semibold rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all disabled:opacity-50"
                      >
                        {apiKeyTesting === 'huggingface' ? 'Testing...' : 'Test'}
                      </button>
                      {apiKeysStatus.huggingface.source !== 'environment' && (
                        <button
                          onClick={() => deleteApiKey('huggingface')}
                          className="px-3 py-2 text-xs font-semibold rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/20 transition-all"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <input
                      type="password"
                      value={apiKeyInput.huggingface}
                      onChange={(e) => setApiKeyInput(prev => ({ ...prev, huggingface: e.target.value }))}
                      placeholder="hf_xxxxxxxxxxxxxxxxxx"
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono outline-none focus:border-white/30 transition-all placeholder:text-white/20"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => testApiKey('huggingface')}
                        disabled={!apiKeyInput.huggingface.trim() || apiKeyTesting === 'huggingface'}
                        className="flex-1 px-3 py-2 text-xs font-semibold rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all disabled:opacity-50"
                      >
                        {apiKeyTesting === 'huggingface' ? 'Testing...' : 'Test'}
                      </button>
                      <button
                        onClick={() => saveApiKey('huggingface')}
                        disabled={!apiKeyInput.huggingface.trim() || apiKeySaving === 'huggingface'}
                        className="flex-1 px-3 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-all disabled:opacity-50"
                      >
                        {apiKeySaving === 'huggingface' ? 'Saving...' : 'Save'}
                      </button>
                    </div>
                    <a
                      href="https://huggingface.co/settings/tokens"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[10px] text-blue-400 hover:text-blue-300"
                    >
                      Get token from huggingface.co →
                    </a>
                  </div>
                )}
              </div>

              {/* Civitai API Key */}
              <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <div className="text-sm font-bold text-white">Civitai API Key</div>
                    <div className="text-[10px] text-white/40 mt-0.5">For NSFW and restricted downloads</div>
                  </div>
                  {apiKeysStatus.civitai?.configured && (
                    <span className={`px-2 py-1 rounded text-[10px] font-bold uppercase ${
                      apiKeysStatus.civitai.source === 'environment'
                        ? 'bg-blue-500/20 text-blue-300'
                        : 'bg-emerald-500/20 text-emerald-300'
                    }`}>
                      {apiKeysStatus.civitai.source === 'environment' ? 'ENV' : 'Stored'}
                    </span>
                  )}
                </div>

                {apiKeysStatus.civitai?.configured ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 bg-white/5 rounded-lg px-3 py-2">
                      <span className="text-emerald-400 text-sm">✓</span>
                      <span className="text-xs text-white/60 font-mono">{apiKeysStatus.civitai.masked}</span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => testApiKey('civitai')}
                        disabled={apiKeyTesting === 'civitai'}
                        className="flex-1 px-3 py-2 text-xs font-semibold rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all disabled:opacity-50"
                      >
                        {apiKeyTesting === 'civitai' ? 'Testing...' : 'Test'}
                      </button>
                      {apiKeysStatus.civitai.source !== 'environment' && (
                        <button
                          onClick={() => deleteApiKey('civitai')}
                          className="px-3 py-2 text-xs font-semibold rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/20 transition-all"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <input
                      type="password"
                      value={apiKeyInput.civitai}
                      onChange={(e) => setApiKeyInput(prev => ({ ...prev, civitai: e.target.value }))}
                      placeholder="xxxxxxxxxxxxxxxxxxxxxxxx"
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono outline-none focus:border-white/30 transition-all placeholder:text-white/20"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => testApiKey('civitai')}
                        disabled={!apiKeyInput.civitai.trim() || apiKeyTesting === 'civitai'}
                        className="flex-1 px-3 py-2 text-xs font-semibold rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all disabled:opacity-50"
                      >
                        {apiKeyTesting === 'civitai' ? 'Testing...' : 'Test'}
                      </button>
                      <button
                        onClick={() => saveApiKey('civitai')}
                        disabled={!apiKeyInput.civitai.trim() || apiKeySaving === 'civitai'}
                        className="flex-1 px-3 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-all disabled:opacity-50"
                      >
                        {apiKeySaving === 'civitai' ? 'Saving...' : 'Save'}
                      </button>
                    </div>
                    <a
                      href="https://civitai.com/user/account"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[10px] text-blue-400 hover:text-blue-300"
                    >
                      Get API key from civitai.com →
                    </a>
                  </div>
                )}
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-white/10 bg-white/[0.02]">
              <p className="text-[11px] text-white/30">
                Keys are stored locally and never sent to external servers except for authentication.
                Environment variables (HF_TOKEN, CIVITAI_API_KEY) take precedence over stored keys.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="px-8 py-5 border-b border-white/10 bg-white/[0.01]">
        <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr_1fr] gap-4 max-w-7xl">
          <div>
            <label className="text-[10px] text-white/40 font-bold uppercase tracking-wider block mb-2.5">Model Type</label>
            <div className="flex flex-col gap-1.5">
              {(['chat', 'multimodal', 'image', 'edit', 'video', 'enhance', 'addons'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setModelType(t)}
                  className={`px-4 py-2.5 rounded-lg border text-xs font-bold uppercase tracking-wide transition-all ${
                    modelType === t
                      ? 'bg-white text-black border-white shadow-lg shadow-white/20'
                      : 'bg-transparent border-white/10 text-white/60 hover:bg-white/5 hover:border-white/20 hover:text-white/80'
                  }`}
                >
                  {t === 'addons' ? '🧩 Add-ons' : t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[10px] text-white/40 font-bold uppercase tracking-wider block mb-2.5">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-white/30 focus:bg-white/10 transition-all"
            >
              {availableProviders.length > 0 ? (
                availableProviders.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.label || p.name}
                  </option>
                ))
              ) : (
                // Fallback options when providers haven't loaded
                modelType === 'chat' ? (
                  <>
                    <option value="ollama">Ollama</option>
                    <option value="openai_compat">OpenAI-compatible (vLLM)</option>
                    <option value="openai">OpenAI</option>
                    <option value="claude">Claude</option>
                    <option value="watsonx">Watsonx</option>
                  </>
                ) : (
                  <option value="comfyui">ComfyUI</option>
                )
              )}
            </select>
            {providersError ? <div className="mt-2 text-xs text-rose-400/80">{providersError}</div> : null}
          </div>

          <div>
            <label className="text-[10px] text-white/40 font-bold uppercase tracking-wider block mb-2.5">Base URL Override</label>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={modelType === 'chat' ? 'http://localhost:11434' : 'http://localhost:8188'}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-white/30 focus:bg-white/10 transition-all placeholder:text-white/30"
            />
            <div className="mt-2 text-[10px] text-white/30 font-medium">
              Optional. Leave empty to use default configuration.
            </div>
          </div>
        </div>
      </div>

      {/* Civitai Input Section (only when provider is civitai) */}
      {provider === 'civitai' && (
        <div className="px-8 py-4 border-b border-white/10 bg-gradient-to-br from-blue-500/5 to-blue-500/0">
          <div className="max-w-7xl">
            {/* Search Bar */}
            <div className="mb-6">
              <label className="text-[10px] text-cyan-400 font-bold uppercase tracking-wider block mb-2.5">
                🔍 Search Civitai Models
              </label>
              <div className="flex items-center gap-3">
                <input
                  value={civitaiQuery}
                  onChange={(e) => setCivitaiQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && searchCivitai()}
                  placeholder={`Search ${modelType === 'video' ? 'video' : 'image'} models on Civitai...`}
                  className="flex-1 bg-white/5 border border-cyan-500/20 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-cyan-500/40 focus:bg-white/10 transition-all placeholder:text-white/30"
                />
                <button
                  type="button"
                  onClick={() => searchCivitai()}
                  disabled={civitaiSearchLoading || !civitaiQuery.trim()}
                  className={[
                    "px-6 py-3 rounded-xl text-white text-sm font-bold uppercase tracking-wide transition-all shadow-lg",
                    civitaiSearchLoading
                      ? "bg-cyan-700 cursor-wait shadow-cyan-700/30"
                      : !civitaiQuery.trim()
                      ? "bg-cyan-600/50 cursor-not-allowed shadow-cyan-600/10"
                      : "bg-cyan-600 hover:bg-cyan-500 shadow-cyan-600/20 hover:shadow-cyan-600/30 hover:scale-105 active:scale-95"
                  ].join(" ")}
                >
                  {civitaiSearchLoading ? (
                    <svg className="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  ) : (
                    'Search'
                  )}
                </button>
              </div>
              {civitaiSearchError && (
                <div className="mt-2 text-[10px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                  ⚠️ {civitaiSearchError}
                </div>
              )}
            </div>

            {/* Search Results */}
            {civitaiResults.length > 0 && (
              <div className="mb-6">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-[10px] text-cyan-400 font-bold uppercase tracking-wider">
                    Search Results ({civitaiResults.length} models)
                  </div>
                  {civitaiTotalPages > 1 && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => searchCivitai(civitaiPage - 1)}
                        disabled={civitaiPage <= 1 || civitaiSearchLoading}
                        className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                      >
                        ← Prev
                      </button>
                      <span className="text-xs text-white/50">
                        Page {civitaiPage} of {civitaiTotalPages}
                      </span>
                      <button
                        onClick={() => searchCivitai(civitaiPage + 1)}
                        disabled={civitaiPage >= civitaiTotalPages || civitaiSearchLoading}
                        className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                      >
                        Next →
                      </button>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 max-h-[400px] overflow-y-auto pr-2 scrollbar-hide">
                  {civitaiResults.map((model) => (
                    <div
                      key={model.id}
                      className="bg-white/5 border border-white/10 rounded-xl overflow-hidden hover:border-cyan-500/30 transition-all group"
                    >
                      {/* Thumbnail */}
                      <div className="relative h-32 bg-black/50">
                        {model.thumbnail ? (
                          <img
                            src={model.thumbnail}
                            alt={model.name}
                            className="w-full h-full object-cover"
                            loading="lazy"
                          />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-white/20">
                            <span className="text-4xl">🖼️</span>
                          </div>
                        )}
                        {model.nsfw && (
                          <span className="absolute top-2 right-2 px-2 py-1 text-[9px] font-bold uppercase bg-red-600 text-white rounded">
                            NSFW
                          </span>
                        )}
                      </div>

                      {/* Info */}
                      <div className="p-3">
                        <div className="font-semibold text-sm text-white truncate mb-1">{model.name}</div>
                        <div className="text-[10px] text-white/40 mb-2">by {model.creator}</div>

                        <div className="flex items-center gap-3 text-[10px] text-white/50 mb-3">
                          <span>⬇️ {model.downloads >= 1000 ? `${(model.downloads / 1000).toFixed(1)}K` : model.downloads}</span>
                          <span>⭐ {model.rating.toFixed(1)}</span>
                          <span>({model.ratingCount})</span>
                        </div>

                        {model.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1 mb-3">
                            {model.tags.slice(0, 3).map((tag) => (
                              <span key={tag} className="px-2 py-0.5 text-[9px] bg-white/5 rounded text-white/40">
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}

                        {/* Version selector and install */}
                        {model.versions.length > 0 && (
                          <div className="flex items-center gap-2">
                            <select
                              className="flex-1 bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-xs outline-none focus:border-cyan-500/30"
                              defaultValue={model.versions[0]?.id}
                              id={`version-${model.id}`}
                            >
                              {model.versions.map((v) => (
                                <option key={v.id} value={v.id}>
                                  {v.name} ({(v.sizeKB / 1024 / 1024).toFixed(1)}GB)
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={() => {
                                const select = document.getElementById(`version-${model.id}`) as HTMLSelectElement
                                const versionId = select?.value || model.versions[0]?.id
                                installFromCivitaiResult(model, versionId)
                              }}
                              disabled={installBusy === model.id}
                              className={[
                                "px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-all",
                                installBusy === model.id
                                  ? "bg-cyan-700 text-white cursor-wait"
                                  : "bg-cyan-600 text-white hover:bg-cyan-500"
                              ].join(" ")}
                            >
                              {installBusy === model.id ? (
                                <svg className="animate-spin h-3 w-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                </svg>
                              ) : (
                                <Download size={12} />
                              )}
                              Install
                            </button>
                          </div>
                        )}

                        {model.link && (
                          <a
                            href={model.link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block mt-2 text-[10px] text-cyan-400 hover:text-cyan-300"
                          >
                            View on Civitai →
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Manual Version ID Input */}
            <div className="flex items-start gap-4 mb-6 border-t border-white/10 pt-4">
              <div className="flex-1">
                <label className="text-[10px] text-blue-400 font-bold uppercase tracking-wider block mb-2.5">
                  📋 Direct Version ID (Advanced)
                </label>
                <input
                  value={civitaiVersionId}
                  onChange={(e) => setCivitaiVersionId(e.target.value)}
                  placeholder="e.g., 128713 (from Civitai model URL)"
                  className="w-full bg-white/5 border border-blue-500/20 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-blue-500/40 focus:bg-white/10 transition-all placeholder:text-white/30"
                />
                <div className="mt-2 text-[10px] text-blue-300/60 font-medium">
                  Enter a version ID from any Civitai model URL (e.g., civitai.com/models/<strong>128713</strong>)
                </div>
              </div>
              <div className="flex-shrink-0 pt-7">
                <button
                  type="button"
                  onClick={() => {
                    if (!civitaiVersionId.trim()) {
                      setToast('Please enter a Civitai version ID first')
                      return
                    }
                    tryInstall(civitaiVersionId, undefined)
                  }}
                  disabled={!civitaiVersionId.trim() || installBusy !== null}
                  className={[
                    "px-6 py-3 rounded-xl text-white text-sm font-bold uppercase tracking-wide transition-all shadow-lg relative overflow-hidden",
                    installBusy !== null
                      ? "bg-blue-700 cursor-wait shadow-blue-700/30"
                      : !civitaiVersionId.trim()
                      ? "bg-blue-600/50 cursor-not-allowed shadow-blue-600/10"
                      : "bg-blue-600 hover:bg-blue-500 shadow-blue-600/20 hover:shadow-blue-600/30 hover:scale-105 active:scale-95"
                  ].join(" ")}
                >
                  {installBusy !== null && (
                    <span className="absolute inset-0 bg-gradient-to-r from-blue-700 via-blue-600 to-blue-700 animate-shimmer" style={{
                      backgroundSize: '200% 100%',
                      animation: 'shimmer 2s infinite linear'
                    }} />
                  )}
                  <span className="relative z-10 flex items-center gap-2.5 justify-center">
                    {installBusy !== null ? (
                      <>
                        <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        <span>Downloading...</span>
                      </>
                    ) : (
                      <>
                        <Download size={16} strokeWidth={2.5} />
                        <span>Download</span>
                      </>
                    )}
                  </span>
                </button>
              </div>
            </div>

            {/* Recommended Models Info */}
            <div className="border-t border-blue-500/20 pt-4">
              <div className="text-[10px] text-blue-400 font-bold uppercase tracking-wider mb-3">
                ⭐ Recommended {modelType === 'image' ? 'Image' : 'Video'} Models from Civitai
              </div>
              <div className="text-[10px] text-blue-300/60 font-medium">
                Click "Install" on any model below to download directly from Civitai. Models are installed to your ComfyUI models folder.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-8 py-6 scrollbar-hide">
        <div className="flex flex-col gap-4 max-w-7xl mx-auto">
          {/* Error messages - hide for Civitai since it's download-only */}
          {installedError && provider !== 'civitai' ? (
            <div className={`rounded-xl border p-5 ${
              installedError.includes('Ollama') || installedError.includes('11434')
                ? 'border-white/10 bg-white/[0.03] text-white/60'
                : 'border-amber-500/30 bg-gradient-to-br from-amber-500/10 to-amber-500/5 text-amber-200'
            }`}>
              <div className={`font-bold text-sm ${
                installedError.includes('Ollama') || installedError.includes('11434')
                  ? 'text-white/70'
                  : 'text-amber-100'
              }`}>
                {installedError.includes('Ollama') || installedError.includes('11434')
                  ? 'Ollama Not Running'
                  : 'Configuration Required'}
              </div>
              <div className="text-xs mt-2 font-medium opacity-70">
                {installedError.includes('Ollama') || installedError.includes('11434')
                  ? 'Ollama is not reachable. Start Ollama or switch to a different provider tab. ComfyUI models and Add-ons still work normally.'
                  : installedError.includes('LLM_BASE_URL')
                    ? 'Configure LLM_BASE_URL environment variable to use OpenAI-compatible (vLLM) provider. Or switch to a different provider.'
                    : installedError}
              </div>
            </div>
          ) : null}

          {catalogError && !supportedForSelection.length ? (
            <div className="rounded-xl border border-blue-500/20 bg-gradient-to-br from-blue-500/10 to-blue-500/5 p-5 text-blue-200">
              <div className="font-bold text-sm text-blue-100">Backend catalog unavailable</div>
              <div className="mt-2 text-xs text-blue-200/70 font-medium">
                Using fallback model list. Configure <span className="font-mono bg-blue-500/20 px-1.5 py-0.5 rounded text-blue-100">/model-catalog</span> endpoint for enhanced functionality.
              </div>
            </div>
          ) : null}

          {/* Models table */}
          <div className="rounded-2xl border border-white/10 overflow-hidden bg-gradient-to-b from-white/[0.02] to-transparent">
            <div className="bg-white/5 px-6 py-4 flex items-center justify-between border-b border-white/10">
              <div className="text-xs font-bold text-white uppercase tracking-wider">Available Models</div>
              <div className="text-xs text-white/50 font-semibold">
                {(() => {
                  const isRemoteProvider = ['openai', 'claude', 'watsonx'].includes(provider)
                  if (installedLoading) return 'Loading…'
                  if (provider === 'civitai') {
                    return `🧪 ${supportedForSelection.length} Recommended Models`
                  }
                  if (isRemoteProvider) {
                    return `${supportedForSelection.length} API Models`
                  }
                  return `${installed.length} Installed${supportedForSelection.length ? ` · ${supportedForSelection.length} Available` : ''}`
                })()}
              </div>
            </div>

            <div className="divide-y divide-white/5">
              {merged.length === 0 ? (
                <div className="p-12 text-white/50 text-sm text-center font-medium">
                  {provider === 'civitai' ? (
                    <div className="space-y-2">
                      <div className="text-blue-400 font-bold">🧪 Civitai Download</div>
                      <div>Enter a Civitai version ID above to download models.</div>
                      <div className="text-xs text-white/40">
                        Find models at <a href="https://civitai.com" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline">civitai.com</a>
                      </div>
                    </div>
                  ) : (
                    'No models found. Try changing provider/base URL and refresh.'
                  )}
                </div>
              ) : (
                merged.map((row) => {
                  const statusKind =
                    row.status === 'installed'
                      ? 'ok'
                      : row.status === 'missing'
                      ? 'warn'
                      : 'muted'

                  const statusLabel =
                    row.status === 'installed'
                      ? 'Installed'
                      : row.status === 'missing'
                      ? 'Available'
                      : 'Custom'

                  // Only allow downloads for local providers (Ollama, ComfyUI, Civitai)
                  // Remote API providers (OpenAI, Claude, Watsonx, openai_compat) don't support local installation
                  const isLocalProvider = provider === 'ollama' || provider === 'comfyui' || provider === 'civitai'
                  const canDownload = row.status === 'missing' && isLocalProvider
                  const canDelete = (row.status === 'installed' || row.status === 'installed_unsupported') && isLocalProvider && !row.protected
                  const isCivitai = provider === 'civitai'

                  return (
                    <div key={row.id} className="p-5 flex items-center justify-between gap-4 hover:bg-white/[0.02] transition-all group">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2.5 mb-3">
                          <div className={`px-3 py-1.5 rounded-lg border text-[10px] font-bold uppercase tracking-wider flex items-center gap-1.5 ${chipClass(statusKind)}`}>
                            <IconStatus kind={statusKind} />
                            <span>{statusLabel}</span>
                          </div>
                          {row.recommended ? (
                            <div className="px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-[10px] font-bold uppercase tracking-wider text-blue-200">
                              ⭐ Recommended
                            </div>
                          ) : null}
                          {row.recommended_nsfw && props.nsfwMode ? (
                            <div className="px-3 py-1.5 rounded-lg border border-pink-500/30 bg-pink-500/10 text-[10px] font-bold uppercase tracking-wider text-pink-200">
                              🔥 NSFW Pick
                            </div>
                          ) : null}
                          {row.nsfw ? (
                            <div className="px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-[10px] font-bold uppercase tracking-wider text-red-200">
                              🌶️ Adult
                            </div>
                          ) : null}
                          {isCivitai && row.civitai_version_id ? (
                            <div className="px-3 py-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/10 text-[10px] font-bold uppercase tracking-wider text-cyan-200">
                              v{row.civitai_version_id}
                            </div>
                          ) : null}
                          {row.protected && (row.status === 'installed' || row.status === 'installed_unsupported') ? (
                            <div className="px-3 py-1.5 rounded-lg border border-white/20 bg-white/5 text-[10px] font-bold uppercase tracking-wider text-white/50">
                              🔒 Default
                            </div>
                          ) : null}
                        </div>

                        <div className="font-bold text-base text-white truncate group-hover:text-white transition-colors">{row.label}</div>
                        <div className="text-[11px] text-white/40 font-mono truncate mt-1">{row.id}</div>
                        {row.description ? (
                          <div className="text-[11px] text-white/30 truncate mt-1">{row.description}</div>
                        ) : null}

                        {/* Pack metadata - shows file count, required nodes, and hints */}
                        {row.install?.files && row.install.files.length > 1 ? (
                          <div className="text-[11px] text-purple-400/80 mt-1">
                            Pack: <span className="font-semibold">{row.install.files.length}</span> files
                          </div>
                        ) : null}

                        {row.install?.requires_custom_nodes && row.install.requires_custom_nodes.length > 0 ? (
                          <div className="text-[11px] text-amber-400/70 mt-1 truncate">
                            Requires:{" "}
                            <span className="font-semibold">
                              {row.install.requires_custom_nodes.join(", ")}
                            </span>
                          </div>
                        ) : null}

                        {row.install?.hint ? (
                          <div className="text-[11px] text-white/25 mt-1 truncate">
                            {row.install.hint}
                          </div>
                        ) : null}

                        {isCivitai && row.civitai_url ? (
                          <a
                            href={row.civitai_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[11px] text-blue-400 hover:text-blue-300 underline mt-1 inline-block"
                          >
                            View on Civitai →
                          </a>
                        ) : null}
                      </div>

                      <div className="flex items-center gap-3 flex-shrink-0">
                        <button
                          type="button"
                          className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-bold flex items-center gap-2 transition-all hover:scale-105 active:scale-95"
                          onClick={() => {
                            navigator.clipboard?.writeText(row.id).catch(() => {})
                            setToast('Model ID copied to clipboard')
                          }}
                          title="Copy model ID"
                        >
                          <Copy size={14} />
                          <span>Copy</span>
                        </button>

                        {canDownload ? (
                          <button
                            type="button"
                            className={[
                              "px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wide flex items-center gap-2.5 transition-all shadow-lg relative overflow-hidden",
                              installBusy === row.id
                                ? "bg-blue-600 text-white cursor-wait shadow-blue-600/30"
                                : isCivitai
                                ? "bg-cyan-600 text-white hover:bg-cyan-500 hover:shadow-cyan-600/30 hover:scale-105 active:scale-95 shadow-cyan-600/20"
                                : "bg-white text-black hover:bg-gray-100 hover:shadow-white/30 hover:scale-105 active:scale-95 shadow-white/20"
                            ].join(" ")}
                            disabled={installBusy === row.id}
                            onClick={() => {
                              // For Civitai, use the version ID if available
                              if (isCivitai && row.civitai_version_id) {
                                setCivitaiVersionId(row.civitai_version_id)
                                void tryInstall(row.civitai_version_id, row.install)
                              } else {
                                void tryInstall(row.id, row.install)
                              }
                            }}
                            title={installBusy === row.id ? "Downloading model... Please wait" : isCivitai ? "Download from Civitai" : "Download and install model"}
                          >
                            {installBusy === row.id && (
                              <span className="absolute inset-0 bg-gradient-to-r from-blue-600 via-blue-500 to-blue-600 animate-shimmer" style={{
                                backgroundSize: '200% 100%',
                                animation: 'shimmer 2s infinite linear'
                              }} />
                            )}
                            <span className="relative z-10 flex items-center gap-2.5">
                              {installBusy === row.id ? (
                                <>
                                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                  </svg>
                                  <span>Downloading...</span>
                                </>
                              ) : (
                                <>
                                  <Download size={15} strokeWidth={2.5} />
                                  <span>Install</span>
                                </>
                              )}
                            </span>
                          </button>
                        ) : null}

                        {canDelete ? (
                          deleteConfirm === row.id ? (
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                className="px-4 py-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-xs font-bold text-white flex items-center gap-2 transition-all hover:scale-105 active:scale-95"
                                disabled={deleteBusy === row.id}
                                onClick={() => void tryDelete(row.id)}
                              >
                                {deleteBusy === row.id ? (
                                  <>
                                    <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                    </svg>
                                    <span>Deleting...</span>
                                  </>
                                ) : (
                                  <span>Confirm</span>
                                )}
                              </button>
                              <button
                                type="button"
                                className="px-3 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-bold transition-all"
                                onClick={() => setDeleteConfirm(null)}
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-red-600/20 border border-white/10 hover:border-red-500/30 text-xs font-bold flex items-center gap-2 transition-all hover:scale-105 active:scale-95 text-white/60 hover:text-red-400"
                              onClick={() => setDeleteConfirm(row.id)}
                              title="Delete this model from disk"
                            >
                              <Trash2 size={14} />
                              <span>Delete</span>
                            </button>
                          )
                        ) : null}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* Avatar & Identity Section (Add-ons tab only) */}
          {modelType === 'addons' && (
            <div className="rounded-2xl border border-purple-500/20 overflow-hidden bg-gradient-to-b from-purple-500/[0.03] to-transparent">
              <div className="bg-purple-500/5 px-6 py-4 flex items-center justify-between border-b border-purple-500/20">
                <div className="flex items-center gap-3">
                  <div className="text-xs font-bold text-purple-200 uppercase tracking-wider">Avatar & Identity Models</div>
                  <div className="px-2.5 py-1 rounded-md bg-purple-500/10 border border-purple-500/20 text-[10px] font-bold text-purple-300 uppercase tracking-wider">
                    Persona
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {avatarModelsLoading ? (
                    <div className="text-xs text-purple-300/50 font-semibold">Loading...</div>
                  ) : (
                    <div className="text-xs text-purple-300/50 font-semibold">
                      {avatarModels.filter(m => m.installed).length} / {avatarModels.length} Installed
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => refreshAvatarModels()}
                    disabled={avatarModelsLoading}
                    className="p-2 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 transition-all disabled:opacity-50"
                    title="Refresh avatar models"
                  >
                    <RefreshCw size={13} className={avatarModelsLoading ? 'animate-spin' : ''} />
                  </button>
                </div>
              </div>

              {avatarModelsError ? (
                <div className="p-5 text-xs text-purple-300/60">
                  Could not load avatar models: {avatarModelsError}
                </div>
              ) : (
                <>
                  {/* Feature readiness dashboard */}
                  {Object.keys(avatarFeatures).length > 0 && (
                    <div className="px-6 py-4 border-b border-purple-500/10">
                      <div className="text-[10px] text-white/40 font-bold uppercase tracking-wider mb-3">Feature Readiness</div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                        {Object.entries(avatarFeatures).map(([featId, feat]) => (
                          <div
                            key={featId}
                            className={`rounded-xl border p-3 transition-all ${
                              feat.ready
                                ? 'border-emerald-500/20 bg-emerald-500/5'
                                : 'border-white/10 bg-white/[0.02]'
                            }`}
                          >
                            <div className="flex items-center gap-2 mb-1.5">
                              {feat.ready ? (
                                <CheckCircle2 size={13} className="text-emerald-400 flex-shrink-0" />
                              ) : (
                                <XCircle size={13} className="text-white/30 flex-shrink-0" />
                              )}
                              <div className={`text-[11px] font-bold ${feat.ready ? 'text-emerald-200' : 'text-white/50'}`}>
                                {feat.label}
                              </div>
                            </div>
                            <div className="text-[10px] text-white/30 leading-relaxed">
                              {feat.description}
                            </div>
                            {!feat.ready && feat.required_missing.length > 0 && (
                              <div className="mt-2 text-[10px] text-amber-400/70">
                                Missing: {feat.required_missing.join(', ')}
                              </div>
                            )}
                            {feat.ready && !feat.recommended_installed && feat.recommended_note && (
                              <div className="mt-2 text-[10px] text-blue-300/60">
                                Tip: {feat.recommended_note}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 text-[10px] text-white/20">
                        Existing personas and avatars work without any of these models. These enable optional enhanced features only.
                      </div>
                    </div>
                  )}

                  {/* Quick-install preset buttons */}
                  <div className="px-6 py-4 border-b border-purple-500/10 flex flex-wrap items-center gap-3">
                    <span className="text-[10px] text-white/40 font-bold uppercase tracking-wider mr-1">Quick Install:</span>
                    <button
                      type="button"
                      onClick={() => downloadAvatarPreset('basic')}
                      disabled={avatarDownloadBusy !== null}
                      className={[
                        "px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wide flex items-center gap-2.5 transition-all shadow-lg relative overflow-hidden",
                        avatarDownloadBusy === 'basic'
                          ? "bg-purple-700 text-white cursor-wait shadow-purple-700/30"
                          : "bg-purple-600 text-white hover:bg-purple-500 shadow-purple-600/20 hover:shadow-purple-600/30 hover:scale-105 active:scale-95"
                      ].join(" ")}
                    >
                      {avatarDownloadBusy === 'basic' ? (
                        <>
                          <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          <span>Downloading...</span>
                        </>
                      ) : (
                        <>
                          <Download size={14} strokeWidth={2.5} />
                          <span>Basic Pack (~4.3 GB)</span>
                        </>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => downloadAvatarPreset('full')}
                      disabled={avatarDownloadBusy !== null}
                      className={[
                        "px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wide flex items-center gap-2.5 transition-all shadow-lg relative overflow-hidden",
                        avatarDownloadBusy === 'full'
                          ? "bg-purple-700 text-white cursor-wait shadow-purple-700/30"
                          : "bg-white/5 text-white/70 hover:bg-white/10 border border-white/10 hover:border-purple-500/30 hover:text-white shadow-none hover:shadow-purple-600/10 hover:scale-105 active:scale-95"
                      ].join(" ")}
                    >
                      {avatarDownloadBusy === 'full' ? (
                        <>
                          <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                          </svg>
                          <span>Downloading...</span>
                        </>
                      ) : (
                        <>
                          <Download size={14} strokeWidth={2.5} />
                          <span>Full Pack (~9.5 GB)</span>
                        </>
                      )}
                    </button>
                    <span className="text-[10px] text-white/25 ml-2">
                      Basic = InsightFace + InstantID (portraits + outfits, ~4.3 GB). Full = all 9 models (~9.5 GB, + face swap, random faces).
                    </span>
                  </div>

                  {/* Download progress panel (visible during active download) */}
                  {avatarDownloadStatus && (avatarDownloadStatus.running || avatarDownloadStatus.finished) && (
                    <div className="px-6 py-4 border-b border-purple-500/10 bg-gradient-to-r from-purple-500/[0.03] to-transparent">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2.5">
                          {avatarDownloadStatus.running && (
                            <svg className="animate-spin h-4 w-4 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                          )}
                          {avatarDownloadStatus.finished && (
                            <CheckCircle2 size={16} className="text-emerald-400" />
                          )}
                          <span className="text-xs font-bold text-white">
                            {avatarDownloadStatus.finished
                              ? `Download Complete — ${avatarDownloadStatus.installed_count}/${avatarDownloadStatus.total_models} installed`
                              : `Downloading ${avatarDownloadStatus.preset?.toUpperCase()} preset — ${avatarDownloadStatus.current_index}/${avatarDownloadStatus.total_models}`
                            }
                          </span>
                        </div>
                        <div className="text-[10px] text-white/40 font-mono">
                          {Math.round(avatarDownloadStatus.elapsed)}s
                          {avatarDownloadStatus.downloaded_bytes > 0 && (
                            <> | {formatBytes(avatarDownloadStatus.downloaded_bytes)}</>
                          )}
                        </div>
                      </div>

                      {/* Progress bar */}
                      {avatarDownloadStatus.total_models > 0 && (
                        <div className="h-2 bg-white/10 rounded-full overflow-hidden mb-3">
                          <div
                            className={`h-full rounded-full transition-all duration-700 ${
                              avatarDownloadStatus.finished ? 'bg-emerald-500' : 'bg-purple-500'
                            }`}
                            style={{
                              width: `${Math.round(
                                ((avatarDownloadStatus.results?.length || 0) / avatarDownloadStatus.total_models) * 100
                              )}%`,
                            }}
                          />
                        </div>
                      )}

                      {/* Per-model status rows */}
                      <div className="space-y-1">
                        {(avatarDownloadStatus.results || []).map((r) => (
                          <div key={r.id} className="flex items-center gap-2 text-[11px]">
                            {r.status === 'installed' ? (
                              <CheckCircle2 size={11} className="text-emerald-400 shrink-0" />
                            ) : r.status === 'already_installed' ? (
                              <CheckCircle2 size={11} className="text-white/30 shrink-0" />
                            ) : (
                              <XCircle size={11} className="text-red-400 shrink-0" />
                            )}
                            <span className={r.status === 'already_installed' ? 'text-white/30' : 'text-white/60'}>
                              {r.name || r.id}
                            </span>
                            <span className="text-white/20 ml-auto">
                              {r.status === 'installed' && r.size ? formatBytes(r.size) : ''}
                              {r.status === 'installed' && r.elapsed ? ` (${r.elapsed}s)` : ''}
                              {r.status === 'already_installed' ? 'already installed' : ''}
                              {r.status === 'failed' ? 'failed' : ''}
                              {r.status === 'timeout' ? 'timeout' : ''}
                              {r.status === 'error' ? r.error || 'error' : ''}
                            </span>
                          </div>
                        ))}

                        {/* Currently downloading indicator */}
                        {avatarDownloadStatus.running && avatarDownloadStatus.current_model && (
                          <div className="flex items-center gap-2 text-[11px]">
                            <svg className="animate-spin h-3 w-3 text-purple-400 shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            <span className="text-purple-300">
                              {avatarModels.find(m => m.id === avatarDownloadStatus.current_model)?.name || avatarDownloadStatus.current_model}
                            </span>
                            <span className="text-white/20 ml-auto">downloading...</span>
                          </div>
                        )}
                      </div>

                      {/* Dismiss when finished */}
                      {avatarDownloadStatus.finished && (
                        <button
                          type="button"
                          onClick={() => setAvatarDownloadStatus(null)}
                          className="mt-3 text-[10px] text-white/30 hover:text-white/50 transition-colors"
                        >
                          Dismiss
                        </button>
                      )}
                    </div>
                  )}

                  {/* Model list */}
                  <div className="divide-y divide-purple-500/10">
                    {avatarModels.map((m) => {
                      const statusKind = m.installed ? 'ok' : 'warn'
                      const statusLabel = m.installed ? 'Installed' : 'Not Installed'

                      // Basic pack models are tagged as "Recommended" — minimum needed for Avatar to work
                      const BASIC_PACK_IDS = new Set(['insightface-antelopev2', 'instantid-ip-adapter', 'instantid-controlnet'])
                      const isRecommended = BASIC_PACK_IDS.has(m.id)

                      // Feature labels from used_by
                      const FEATURE_LABELS: Record<string, { label: string; color: string }> = {
                        photo_variations: { label: 'Portraits', color: 'purple' },
                        outfit_generation: { label: 'Outfits', color: 'indigo' },
                        face_swap: { label: 'Face Swap', color: 'cyan' },
                        random_faces: { label: 'Random Faces', color: 'pink' },
                      }

                      return (
                        <div key={m.id} className="p-5 flex items-center justify-between gap-4 hover:bg-white/[0.02] transition-all group">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2.5 mb-2 flex-wrap">
                              <div className={`px-3 py-1.5 rounded-lg border text-[10px] font-bold uppercase tracking-wider flex items-center gap-1.5 ${chipClass(statusKind)}`}>
                                <IconStatus kind={statusKind} />
                                <span>{statusLabel}</span>
                              </div>
                              {m.is_default && (
                                <div className="px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-[10px] font-bold uppercase tracking-wider text-blue-200">
                                  Core
                                </div>
                              )}
                              {isRecommended && (
                                <div className="px-3 py-1.5 rounded-lg border border-purple-500/30 bg-purple-500/10 text-[10px] font-bold uppercase tracking-wider text-purple-200">
                                  Recommended
                                </div>
                              )}
                              {m.license && (
                                <div className="px-2.5 py-1 rounded-lg border border-white/10 bg-white/5 text-[10px] font-medium text-white/40 flex items-center gap-1">
                                  <Shield size={10} />
                                  {m.license}
                                </div>
                              )}
                              {m.commercial_use_ok === true && (
                                <div className="px-2.5 py-1 rounded-lg border border-emerald-500/20 bg-emerald-500/5 text-[10px] font-medium text-emerald-300/70">
                                  Commercial OK
                                </div>
                              )}
                              {m.commercial_use_ok === false && (
                                <div className="px-2.5 py-1 rounded-lg border border-amber-500/20 bg-amber-500/5 text-[10px] font-medium text-amber-300/70">
                                  Non-Commercial
                                </div>
                              )}
                            </div>

                            <div className="font-bold text-base text-white truncate group-hover:text-white transition-colors">{m.name}</div>
                            <div className="text-[11px] text-white/40 font-mono truncate mt-1">{m.id}</div>
                            {m.description && (
                              <div className="text-[11px] text-white/30 mt-1">{m.description}</div>
                            )}
                            {m.requires && m.requires.length > 0 && (
                              <div className="text-[11px] text-amber-400/70 mt-1 truncate">
                                Requires: <span className="font-semibold">{m.requires.join(', ')}</span>
                              </div>
                            )}

                            {/* Feature tags: which features this model enables */}
                            {m.used_by && m.used_by.length > 0 && (
                              <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                                <span className="text-[10px] text-white/25">Enables:</span>
                                {m.used_by.map((ub) => {
                                  const fl = FEATURE_LABELS[ub.feature]
                                  if (!fl) return null
                                  const isRequired = ub.role === 'required'
                                  return (
                                    <span
                                      key={`${ub.feature}-${ub.role}`}
                                      className={`px-2 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider border ${
                                        isRequired
                                          ? `border-${fl.color}-500/30 bg-${fl.color}-500/10 text-${fl.color}-300`
                                          : 'border-white/10 bg-white/5 text-white/40'
                                      }`}
                                      title={isRequired ? `Required for ${fl.label}` : `Recommended for ${fl.label}`}
                                    >
                                      {fl.label}{!isRequired ? ' (opt)' : ''}
                                    </span>
                                  )
                                })}
                              </div>
                            )}
                          </div>

                          <div className="flex items-center gap-3 flex-shrink-0">
                            {m.homepage && (
                              <a
                                href={m.homepage}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="px-3 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-bold flex items-center gap-2 transition-all text-white/50 hover:text-white/70"
                                title="View project page"
                              >
                                <ExternalLink size={13} />
                                <span>Info</span>
                              </a>
                            )}

                            {/* Install button — only for not-installed models with a download URL */}
                            {!m.installed && m.download_url && (
                              <button
                                type="button"
                                className="px-4 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-xs font-bold text-white flex items-center gap-2 transition-all hover:scale-105 active:scale-95 shadow-lg shadow-purple-600/20 disabled:opacity-50 disabled:cursor-wait"
                                disabled={avatarInstallBusy === m.id || avatarDownloadBusy !== null}
                                onClick={() => installSingleAvatarModel(m.id)}
                                title={`Download and install ${m.name}`}
                              >
                                {avatarInstallBusy === m.id ? (
                                  <>
                                    <svg className="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                    </svg>
                                    <span>Installing...</span>
                                  </>
                                ) : (
                                  <>
                                    <Download size={13} />
                                    <span>Install</span>
                                  </>
                                )}
                              </button>
                            )}

                            {/* Uninstall button — only for installed models */}
                            {m.installed && (
                              avatarDeleteConfirm === m.id ? (
                                <div className="flex items-center gap-2">
                                  <button
                                    type="button"
                                    className="px-4 py-2.5 rounded-xl bg-red-600 hover:bg-red-500 text-xs font-bold text-white flex items-center gap-2 transition-all hover:scale-105 active:scale-95"
                                    disabled={avatarDeleteBusy === m.id}
                                    onClick={() => deleteAvatarModel(m.id)}
                                  >
                                    {avatarDeleteBusy === m.id ? (
                                      <>
                                        <svg className="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                        <span>Deleting...</span>
                                      </>
                                    ) : (
                                      <span>Confirm</span>
                                    )}
                                  </button>
                                  <button
                                    type="button"
                                    className="px-3 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-bold transition-all"
                                    onClick={() => setAvatarDeleteConfirm(null)}
                                  >
                                    Cancel
                                  </button>
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-red-600/20 border border-white/10 hover:border-red-500/30 text-xs font-bold flex items-center gap-2 transition-all hover:scale-105 active:scale-95 text-white/60 hover:text-red-400"
                                  onClick={() => setAvatarDeleteConfirm(m.id)}
                                  title="Uninstall this model to free disk space"
                                >
                                  <Trash2 size={13} />
                                  <span>Uninstall</span>
                                </button>
                              )
                            )}
                          </div>
                        </div>
                      )
                    })}

                    {avatarModels.length === 0 && !avatarModelsLoading && (
                      <div className="p-8 text-center text-white/40 text-sm">
                        No avatar models registered. Check backend configuration.
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Toast notification */}
      {toast ? (
        <div className="fixed bottom-8 right-8 z-50 bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-xl border border-white/20 rounded-2xl px-6 py-4 text-sm text-white shadow-2xl shadow-black/40 animate-in slide-in-from-bottom-4 flex items-center gap-3 min-w-[320px]">
          {toast.includes('Successfully') || toast.includes('installed') ? (
            <div className="flex-shrink-0">
              <CheckCircle2 size={18} className="text-emerald-400" />
            </div>
          ) : toast.includes('failed') || toast.includes('error') || toast.includes('Error') ? (
            <div className="flex-shrink-0">
              <XCircle size={18} className="text-red-400" />
            </div>
          ) : (
            <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse flex-shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-white/90 truncate">{toast}</div>
            {installBusy && (
              <div className="text-[10px] text-white/50 mt-1 font-medium">
                Large models may take several minutes...
              </div>
            )}
          </div>
        </div>
      ) : null}

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }

        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }

        .animate-shimmer {
          animation: shimmer 2s infinite linear;
        }
      `}</style>
    </div>
  )
}
