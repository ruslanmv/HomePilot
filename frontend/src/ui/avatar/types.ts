/**
 * Avatar Studio — TypeScript types (mirrors backend schemas).
 */

export type AvatarMode =
  | 'creative'
  | 'studio_random'
  | 'studio_reference'
  | 'studio_faceswap'

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
