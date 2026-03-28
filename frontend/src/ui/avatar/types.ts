/**
 * Avatar Studio — TypeScript types (mirrors backend schemas).
 */

export type AvatarMode =
  | 'creative'
  | 'studio_random'
  | 'studio_reference'
  | 'studio_faceswap'
  | 'studio_quickface'

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
    filename: 'realisticVisionV51.safetensors',
  },
  {
    id: 'epicrealism',
    label: 'epiCRealism',
    description: 'SD 1.5 — hyperrealistic portraits, natural lighting',
    filename: 'epicrealism_pureEvolution.safetensors',
  },
]

/** Body generation workflow method — controls which pipeline is used for face→body. */
export type BodyWorkflowMethod = 'disabled' | 'default' | 'sdxl_hq' | 'pose'

/** Metadata for each body workflow method shown in the UI. */
export interface BodyWorkflowOption {
  id: BodyWorkflowMethod
  label: string
  description: string
  badge?: string
}

/** Available body workflow methods for the Advanced Settings selector. */
export const BODY_WORKFLOW_OPTIONS: BodyWorkflowOption[] = [
  {
    id: 'disabled',
    label: 'Disabled',
    description: 'Skip body generation. Go directly from face to outfits (original workflow).',
  },
  {
    id: 'default',
    label: 'InstantID (SDXL)',
    description: 'Default face-to-body with identity preservation. Balanced speed and quality.',
    badge: 'Default',
  },
  {
    id: 'sdxl_hq',
    label: 'SDXL High Quality',
    description: 'Higher quality 1024x1536 generation. Slower but more detailed output.',
    badge: 'HQ',
  },
  {
    id: 'pose',
    label: 'Pose Guided',
    description: 'Body generation with OpenPose control. Requires OpenPose ControlNet model. Falls back to default if missing.',
    badge: 'Pose',
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
  /** Use StyleGAN for face generation (studio_random mode).
   *  When enabled, faces are generated via StyleGAN and a Body step is added.
   *  When disabled, faces use the diffusion model (creative mode). */
  useStyleGAN: boolean
  /** Which body generation workflow to use (default | sdxl_hq | pose). */
  bodyWorkflowMethod: BodyWorkflowMethod
  /** Use square (1:1) aspect ratio for headshot generation instead of portrait (2:3).
   *  Default false — portrait ratio produces higher quality results. */
  headshot1to1?: boolean
  /** Start in 360° orbit mode by default instead of static view.
   *  Default true — orbit mode lets users drag/arrow through angles. */
  orbit360Default?: boolean
  /** Per-angle tuning overrides for view pack generation.
   *  Undefined fields fall back to the built-in defaults in viewPack.ts. */
  viewAngleTuning?: {
    left?:  { denoise?: number; promptWeight?: number }
    right?: { denoise?: number; promptWeight?: number }
    back?:  { denoise?: number; promptWeight?: number }
  }
  /** Auto-mirror left view after generation.
   *  When enabled, the backend mirrors the right-facing image to produce
   *  a correct left-facing result.  Default: true (enabled). */
  autoMirrorLeft?: boolean
  /** Auto-mirror right view after generation.
   *  When enabled and the right image faces the wrong way, the backend
   *  mirrors it.  Default: false (disabled — right prompt is reliable). */
  autoMirrorRight?: boolean
  /** @deprecated Use autoMirrorLeft / autoMirrorRight instead. Kept for
   *  backwards compatibility with existing localStorage data. */
  autoFixOrientation?: boolean
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
  stylegan_status?: StyleGANStatus
  /** Whether an OpenPose ControlNet is installed (for Pose Guided body generation). */
  openpose_available?: boolean
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
  /** Optional width override — controls output image width (framing). */
  width?: number
  /** Optional height override — controls output image height (framing). */
  height?: number
  /** Optional negative prompt — prevents unwanted elements (framing + style drift). */
  negative_prompt?: string
}

export interface AvatarResult {
  url: string
  seed?: number
  metadata?: Record<string, unknown>
  /** Outfit scenario tag — identifies which preset generated this outfit (used for filmstrip badges). */
  scenarioTag?: string
}

export interface AvatarGenerateResponse {
  mode: AvatarMode
  results: AvatarResult[]
  warnings?: string[]
}

// ---------------------------------------------------------------------------
// Capabilities — additive types for engine availability detection
// ---------------------------------------------------------------------------

export type AvatarEngine = 'comfyui' | 'stylegan' | 'quickface'

export interface AvatarEngineCapability {
  available: boolean
  reason?: string | null
  details?: string | null
}

export interface StyleGANPackStatus {
  installed: boolean
  resolution: number
}

export interface StyleGANStatus {
  installed: boolean
  active_pack: string | null
  resolution: number | null
  packs: Record<string, StyleGANPackStatus>
}

/** Quick Face engine status (additive). */
export interface QuickFaceStatus {
  available: boolean
  local_gpu: boolean
  web_fallback: boolean
  source: string
  resolution: number | null
}

export interface AvatarCapabilitiesResponse {
  default_engine: AvatarEngine
  engines: Record<AvatarEngine, AvatarEngineCapability>
  enabled_modes?: string[]
  stylegan_status?: StyleGANStatus
  /** Whether an OpenPose ControlNet is installed in ComfyUI (for Pose Guided body generation). */
  openpose_available?: boolean
  /** Quick Face engine availability (additive). */
  quickface_status?: QuickFaceStatus
}

// ---------------------------------------------------------------------------
// Hybrid pipeline — two-stage face → full-body generation
// ---------------------------------------------------------------------------

export interface HybridFullBodyRequest {
  face_image_url: string
  count?: number
  outfit_style?: string
  profession?: string
  body_type?: string
  posture?: string
  gender?: string
  age_range?: string
  background?: string
  lighting?: string
  prompt_extra?: string
  identity_strength?: number
  seed?: number
  /** Which body workflow to use: 'default' | 'sdxl_hq' | 'pose'. */
  workflow_method?: BodyWorkflowMethod
  /** URL of pose reference image (required for 'pose' workflow method). */
  pose_image_url?: string
}

export interface HybridFullBodyResult {
  url: string
  seed?: number
  metadata?: Record<string, unknown>
}

export interface HybridFullBodyResponse {
  stage: string
  results: HybridFullBodyResult[]
  warnings?: string[]
  used_checkpoint?: string | null
}
