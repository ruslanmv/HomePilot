/**
 * Avatar Gallery — persistent gallery types and constants.
 *
 * Additive — no existing types are modified.
 */

import type { AvatarMode } from './types'

// ---------------------------------------------------------------------------
// Outfit Scenario Tags — used for wardrobe tagging & filtering
// ---------------------------------------------------------------------------

/** Well-known outfit scenario tag IDs (mirrors OUTFIT_PRESETS). */
export type OutfitScenarioTag =
  | 'business'
  | 'casual'
  | 'evening'
  | 'sporty'
  | 'lingerie'
  | 'swimwear'
  | 'cocktail'
  | 'fantasy_outfit'
  | 'custom'

/** Display metadata for scenario tags. */
export interface ScenarioTagMeta {
  id: OutfitScenarioTag
  label: string
  icon: string
  category: 'sfw' | 'nsfw'
}

export const SCENARIO_TAG_META: ScenarioTagMeta[] = [
  { id: 'business',       label: 'Business',  icon: '\uD83D\uDCBC', category: 'sfw' },
  { id: 'casual',         label: 'Casual',    icon: '\u2615',       category: 'sfw' },
  { id: 'evening',        label: 'Evening',   icon: '\uD83E\uDD42', category: 'sfw' },
  { id: 'sporty',         label: 'Active',    icon: '\uD83C\uDFC3', category: 'sfw' },
  { id: 'swimwear',       label: 'Swimwear',  icon: '\uD83D\uDC59', category: 'nsfw' },
  { id: 'cocktail',       label: 'Cocktail',  icon: '\uD83C\uDF78', category: 'nsfw' },
  { id: 'fantasy_outfit', label: 'Fantasy',   icon: '\u2728',       category: 'nsfw' },
  { id: 'lingerie',       label: 'Lingerie',  icon: '\uD83E\uDE71', category: 'nsfw' },
  { id: 'custom',         label: 'Custom',    icon: '\u270F\uFE0F', category: 'sfw' },
]

// ---------------------------------------------------------------------------
// Avatar Vibe Presets — "Zero-Prompt Wizard" for the Command Center
// ---------------------------------------------------------------------------

export type VibeCategory = 'standard' | 'spicy'

export interface AvatarVibePreset {
  id: string
  label: string
  icon: string
  prompt: string
  category: VibeCategory
}

/** Standard vibes — safe for any audience */
export const AVATAR_VIBE_PRESETS: AvatarVibePreset[] = [
  // Standard
  { id: 'headshot',  label: 'Headshot',  icon: '\uD83D\uDC54', prompt: 'professional studio headshot, highly detailed, 8k resolution, soft lighting, clean background', category: 'standard' },
  { id: 'cinematic', label: 'Cinematic', icon: '\uD83C\uDFAC', prompt: 'cinematic portrait, dramatic lighting, movie still, shallow depth of field, moody atmosphere', category: 'standard' },
  { id: 'artistic',  label: 'Artistic',  icon: '\uD83C\uDFA8', prompt: 'artistic portrait, oil painting style, creative lighting, fine art, gallery quality', category: 'standard' },
  { id: 'cyberpunk', label: 'Cyberpunk', icon: '\uD83D\uDE80', prompt: 'cyberpunk portrait, neon lights, futuristic, sci-fi, dark city background, glowing accents', category: 'standard' },
  { id: 'anime',     label: 'Anime',     icon: '\uD83C\uDF38', prompt: 'anime style portrait, clean lines, vibrant colors, manga aesthetic, cel shading', category: 'standard' },
  { id: 'polaroid',  label: 'Polaroid',  icon: '\uD83D\uDCF8', prompt: 'polaroid photo, vintage filter, candid shot, natural lighting, nostalgic warm tones', category: 'standard' },
  { id: 'sketch',    label: 'Sketch',    icon: '\u270F\uFE0F', prompt: 'detailed pencil sketch portrait, artistic hatching, monochrome, fine graphite drawing', category: 'standard' },
  { id: 'fantasy',   label: 'Fantasy',   icon: '\uD83C\uDFB2', prompt: 'fantasy portrait, magical, ethereal lighting, mystical background, enchanted atmosphere', category: 'standard' },
  // Spicy (18+) — only shown when NSFW mode is on
  { id: 'girlfriend',   label: 'Girlfriend',   icon: '\uD83D\uDC96', prompt: 'girlfriend POV, intimate eye contact, casual home setting, warm lighting, romantic mood, loving smile', category: 'spicy' },
  { id: 'spouse',       label: 'Spouse',       icon: '\uD83D\uDC8D', prompt: 'intimate couple POV, loving gaze, home setting, natural light, romantic and tender', category: 'spicy' },
  { id: 'companion',    label: 'Companion',    icon: '\uD83E\uDD1D', prompt: 'close companion portrait, soft smile, cozy setting, warm atmosphere, gentle expression', category: 'spicy' },
  { id: 'fan_service',  label: 'Fan Service',  icon: '\uD83C\uDF36\uFE0F', prompt: 'fan service pose, playful expression, fashionable revealing outfit, studio lighting, alluring', category: 'spicy' },
  { id: 'boudoir',      label: 'Boudoir',      icon: '\uD83D\uDC8B', prompt: 'boudoir portrait, elegant lingerie, soft studio lighting, sensual pose, intimate setting', category: 'spicy' },
  { id: 'dominant',     label: 'Dominant',     icon: '\u26D3\uFE0F', prompt: 'confident dominant pose, dark aesthetic, dramatic lighting, leather accents, powerful expression', category: 'spicy' },
  { id: 'therapist',    label: 'Therapist',    icon: '\uD83E\uDE7A', prompt: 'professional yet intimate setting, empathetic expression, soft lighting, warm and approachable', category: 'spicy' },
  { id: 'fantasy_plus', label: 'Fantasy+',     icon: '\u2728',       prompt: 'fantasy costume, exotic and daring, mystical setting, alluring pose, magical lighting', category: 'spicy' },
]

// ---------------------------------------------------------------------------
// Gallery Item
// ---------------------------------------------------------------------------

export interface GalleryItem {
  /** Unique ID (uuid-style) */
  id: string
  /** Full image URL (ComfyUI or backend-served) */
  url: string
  /** Generation seed for reproducibility */
  seed?: number
  /** Prompt used during generation */
  prompt?: string
  /** Which avatar mode produced this image */
  mode: AvatarMode
  /** Reference/identity image URL (if identity-based generation) */
  referenceUrl?: string
  /** Unix timestamp (Date.now()) */
  createdAt: number
  /** Optional user-defined tags */
  tags?: string[]
  /** Outfit scenario tag — identifies which preset or 'custom' created this outfit */
  scenarioTag?: OutfitScenarioTag
  /** Vibe preset ID used during avatar generation (from the wizard) */
  vibeTag?: string
  /** Whether this was generated with a spicy (18+) vibe */
  nsfw?: boolean
  /** Set when "Save as Persona Avatar" is used */
  personaProjectId?: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const GALLERY_STORAGE_KEY = 'homepilot_avatar_gallery'
export const GALLERY_MAX_ITEMS = 200
