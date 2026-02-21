/**
 * Avatar Gallery — persistent gallery types and constants.
 *
 * Additive — no existing types are modified.
 */

import type { AvatarMode } from './types'

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
  /** Set when "Save as Persona Avatar" is used */
  personaProjectId?: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const GALLERY_STORAGE_KEY = 'homepilot_avatar_gallery'
export const GALLERY_MAX_ITEMS = 200
