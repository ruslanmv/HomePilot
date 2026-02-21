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
  /** Set when "Save as Persona Avatar" is used */
  personaProjectId?: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const GALLERY_STORAGE_KEY = 'homepilot_avatar_gallery'
export const GALLERY_MAX_ITEMS = 200
