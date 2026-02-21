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
// Character Builder — RPG-style character creator for Design mode
// ---------------------------------------------------------------------------

export type CharacterGender = 'female' | 'male' | 'neutral'

export interface GenderOption {
  id: CharacterGender
  label: string
  icon: string
}

export const GENDER_OPTIONS: GenderOption[] = [
  { id: 'female',  label: 'Female',  icon: '\uD83D\uDC69' },
  { id: 'male',    label: 'Male',    icon: '\uD83D\uDC68' },
  { id: 'neutral', label: 'Neutral', icon: '\uD83E\uDDD1' },
]

export interface CharacterStylePreset {
  id: string
  label: string
  icon: string
  category: VibeCategory
  /** Prompt template — use {gender}, {noun}, {possessive} placeholders */
  promptTemplate: string
}

const GENDER_DICT: Record<CharacterGender, { gender: string; noun: string; possessive: string }> = {
  female:  { gender: 'female',      noun: 'woman',  possessive: 'her' },
  male:    { gender: 'male',        noun: 'man',    possessive: 'his' },
  neutral: { gender: 'androgynous', noun: 'person', possessive: 'their' },
}

/** Build a full character description from gender + style preset. */
export function buildCharacterPrompt(gender: CharacterGender, preset: CharacterStylePreset): string {
  const g = GENDER_DICT[gender]
  return preset.promptTemplate
    .replace(/\{gender\}/g, g.gender)
    .replace(/\{noun\}/g, g.noun)
    .replace(/\{possessive\}/g, g.possessive)
}

export const CHARACTER_STYLE_PRESETS: CharacterStylePreset[] = [
  // ── Standard ──
  {
    id: 'executive',
    label: 'Executive',
    icon: '\uD83D\uDCBC',
    category: 'standard',
    promptTemplate: 'A sophisticated {gender} executive with sharp facial features, professional attire, confident expression, impeccable grooming, clean studio lighting, highly detailed portrait, 8k resolution',
  },
  {
    id: 'elegant',
    label: 'Elegant',
    icon: '\uD83C\uDF77',
    category: 'standard',
    promptTemplate: 'An elegant {gender} {noun} with refined graceful features, luxurious evening attire, soft golden lighting, haute couture aesthetic, poised expression, cinematic portrait',
  },
  {
    id: 'romantic',
    label: 'Romantic',
    icon: '\uD83C\uDF39',
    category: 'standard',
    promptTemplate: 'A {gender} {noun} with a warm romantic aesthetic, soft delicate features, dreamy expression, gentle warm lighting, natural beauty, intimate close-up portrait',
  },
  {
    id: 'casual_char',
    label: 'Casual',
    icon: '\u2615',
    category: 'standard',
    promptTemplate: 'A relaxed {gender} {noun} in casual everyday style, natural candid expression, comfortable modern outfit, warm natural lighting, authentic portrait feel',
  },
  {
    id: 'fantasy_char',
    label: 'Fantasy',
    icon: '\u2694\uFE0F',
    category: 'standard',
    promptTemplate: 'A {gender} fantasy character with striking mystical features, elaborate ornate armor or costume, ethereal magical lighting, enchanted atmosphere, epic detailed portrait',
  },
  {
    id: 'scifi',
    label: 'Sci-Fi',
    icon: '\uD83D\uDE80',
    category: 'standard',
    promptTemplate: 'A {gender} character in a futuristic sci-fi setting, sleek cybernetic enhancements, neon accent lighting, advanced technology backdrop, cinematic detailed portrait',
  },
  {
    id: 'edgy',
    label: 'Edgy',
    icon: '\uD83D\uDD76\uFE0F',
    category: 'standard',
    promptTemplate: 'A {gender} {noun} with an edgy rebellious aesthetic, dark alternative clothing, sharp angular features, dramatic shadows, urban backdrop, moody cinematic lighting',
  },
  {
    id: 'soft',
    label: 'Soft',
    icon: '\uD83C\uDF38',
    category: 'standard',
    promptTemplate: 'A {gender} {noun} with soft delicate features, gentle ethereal expression, pastel tones, dreamy atmosphere, natural beauty, soft diffused lighting, studio portrait',
  },
  // ── Spicy (18+) ──
  {
    id: 'cb_girlfriend',
    label: 'Girlfriend',
    icon: '\uD83D\uDC96',
    category: 'spicy',
    promptTemplate: 'A captivating {gender} {noun} in a girlfriend POV, intimate eye contact, casual home setting, warm soft lighting, romantic mood, loving playful smile, close-up portrait',
  },
  {
    id: 'cb_spouse',
    label: 'Spouse',
    icon: '\uD83D\uDC8D',
    category: 'spicy',
    promptTemplate: 'A {gender} {noun} in an intimate spouse perspective, loving tender gaze, cozy home setting, natural soft light, romantic vulnerable expression, close-up portrait',
  },
  {
    id: 'cb_companion',
    label: 'Companion',
    icon: '\uD83E\uDD1D',
    category: 'spicy',
    promptTemplate: 'A {gender} companion with a soft inviting smile, cozy intimate setting, warm ambient atmosphere, gentle expression, comfortable casual attire, close-up portrait',
  },
  {
    id: 'cb_boudoir',
    label: 'Boudoir',
    icon: '\uD83D\uDC8B',
    category: 'spicy',
    promptTemplate: 'A captivating {gender} {noun} in an intimate boudoir setting, soft romantic lighting, wearing delicate lace, sensual elegant pose, tasteful and artistic, portrait',
  },
  {
    id: 'cb_therapist',
    label: 'Therapist',
    icon: '\uD83E\uDE7A',
    category: 'spicy',
    promptTemplate: 'A {gender} {noun} in a professional yet intimate setting, empathetic caring expression, soft warm lighting, approachable comforting presence, close-up portrait',
  },
  {
    id: 'cb_dominant',
    label: 'Dominant',
    icon: '\u26D3\uFE0F',
    category: 'spicy',
    promptTemplate: 'A {gender} {noun} with a commanding dominant presence, intense piercing gaze, cinematic moody lighting, dark aesthetic, leather accents, powerful confident expression, portrait',
  },
  {
    id: 'cb_fan_service',
    label: 'Fan Service',
    icon: '\uD83C\uDF36\uFE0F',
    category: 'spicy',
    promptTemplate: 'A {gender} {noun} in a playful fan service pose, flirtatious expression, fashionable revealing outfit, studio lighting, alluring confident energy, portrait',
  },
  {
    id: 'cb_fantasy_plus',
    label: 'Fantasy+',
    icon: '\uD83C\uDFB2',
    category: 'spicy',
    promptTemplate: 'A {gender} {noun} in an exotic daring fantasy costume, mystical enchanted setting, alluring seductive pose, magical ethereal lighting, detailed portrait',
  },
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
  /** Links outfit variations to their parent character (MMORPG-style grouping).
   *  Root characters have no parentId. Outfits point to the root character's id. */
  parentId?: string
  /** Set when "Save as Persona Avatar" is used */
  personaProjectId?: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const GALLERY_STORAGE_KEY = 'homepilot_avatar_gallery'
export const GALLERY_MAX_ITEMS = 200
