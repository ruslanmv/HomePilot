/**
 * Avatar Studio — TypeScript types (mirrors backend schemas).
 */

export type AvatarMode =
  | 'creative'
  | 'studio_random'
  | 'studio_reference'
  | 'studio_faceswap'

// ---------------------------------------------------------------------------
// Avatar Settings — checkpoint source selection
// ---------------------------------------------------------------------------

/** How Avatar Studio resolves the checkpoint (model) for generation. */
export type AvatarCheckpointSource = 'recommended' | 'global'

/** Recommended (portrait-optimised) checkpoints shipped with Avatar Studio. */
export interface RecommendedCheckpoint {
  id: string
  label: string
  description: string
  filename: string
}

export const RECOMMENDED_CHECKPOINTS: RecommendedCheckpoint[] = [
  {
    id: 'dreamshaper8',
    label: 'DreamShaper 8',
    description: 'SD 1.5 — balanced portraits, fast, low VRAM',
    filename: 'dreamshaper_8.safetensors',
  },
  {
    id: 'realisticvision',
    label: 'Realistic Vision V5.1',
    description: 'SD 1.5 — photorealistic faces, great skin detail',
    filename: 'realisticVisionV51_v51VAE.safetensors',
  },
  {
    id: 'epicrealism',
    label: 'epiCRealism',
    description: 'SD 1.5 — hyperrealistic portraits, natural lighting',
    filename: 'epicrealism_naturalSinRC1VAE.safetensors',
  },
]

/** Persisted avatar settings (stored in localStorage). */
export interface AvatarSettings {
  checkpointSource: AvatarCheckpointSource
  /** Which recommended checkpoint id is selected (only when source = 'recommended'). */
  recommendedCheckpointId: string
  /** Show the Character Description (Identity Anchor) textarea in the designer.
   *  Hidden by default to reduce prompt clutter for most users. */
  showCharacterDescription: boolean
}

export interface AvatarPackInfo {
  id: string
  title: string
  installed: boolean
  license: string
  commercial_ok: boolean
  modes_enabled: string[]
  notes?: string
}

export interface AvatarPacksResponse {
  packs: AvatarPackInfo[]
  enabled_modes: string[]
}

export interface AvatarGenerateRequest {
  mode: AvatarMode
  count?: number
  seed?: number
  truncation?: number
  prompt?: string
  reference_image_url?: string
  persona_id?: string
  /** Optional checkpoint override — when set, overrides the workflow's default model. */
  checkpoint_override?: string
}

export interface AvatarResult {
  url: string
  seed?: number
  metadata?: Record<string, unknown>
}

export interface AvatarGenerateResponse {
  mode: AvatarMode
  results: AvatarResult[]
  warnings?: string[]
}
