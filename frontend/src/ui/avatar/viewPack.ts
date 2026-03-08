import type { AvatarResult } from './types'

export type ViewAngle = 'front' | 'left_45' | 'left' | 'right_45' | 'right' | 'back'
export type ViewSource = 'anchor' | 'latest' | 'equipped'

export interface ViewAngleOption {
  id: ViewAngle
  label: string
  shortLabel: string
  prompt: string
  /** Negative prompt tokens to prevent the reference pose from dominating. */
  negativePrompt: string
  icon: string
  /** Denoise override — higher values let the text prompt control pose.
   *  Front uses default (0.85), non-front uses 1.0 for full prompt control. */
  denoise: number
  /** When true, use 'standard' generation mode instead of 'identity' to avoid
   *  face preservation fighting the desired pose (e.g. back view). */
  skipIdentity?: boolean
}

// ── Angle prompt design notes ───────────────────────────────────────────
// These prompts go into the `character_prompt` field (NOT outfit_prompt).
// The backend strips clothing/garment tokens from character_prompt, so
// these must NOT contain outfit words (dress, lingerie, suit, etc.).
//
// Keep prompts lean — CLIP has limited token budget (~77 SD1.5 / ~256 SDXL).
// The backend appends its own quality suffix ("elegant lighting, realistic,
// sharp focus") so we skip lighting/quality cues here.
//
// Structure: [turntable context] [camera position] [visible anatomy] [what NOT to show]
// Identity/consistency cues are appended by the generation hook separately.
// ────────────────────────────────────────────────────────────────────────

export const VIEW_ANGLE_OPTIONS: ViewAngleOption[] = [
  {
    id: 'front',
    label: 'Front',
    shortLabel: 'F',
    prompt: 'character turntable, front view, facing camera directly, centered composition, standing naturally',
    negativePrompt: '',
    icon: '\u25C9',
    denoise: 0.85,
  },
  {
    id: 'left_45',
    label: '45\u00B0 Left',
    shortLabel: 'L45',
    prompt: 'character turntable, three-quarter view from the left, camera 45 degrees right of subject, head and torso rotated 45 degrees left, left cheek and left ear visible, left shoulder closer to camera',
    negativePrompt: 'front view, facing camera, symmetrical face, full frontal, back view, rear view',
    icon: '\u25D6',
    denoise: 1.0,
  },
  {
    id: 'left',
    label: 'Left',
    shortLabel: 'L',
    prompt: 'character turntable, full left profile, camera directly to the right of subject, head turned 90 degrees left, only left side of face visible, left ear jaw line nose tip in silhouette',
    negativePrompt: 'front view, facing camera, both eyes visible, symmetrical face, three-quarter view, back view',
    icon: '\u25D0',
    denoise: 1.0,
  },
  {
    id: 'right_45',
    label: '45\u00B0 Right',
    shortLabel: 'R45',
    prompt: 'character turntable, three-quarter view from the right, camera 45 degrees left of subject, head and torso rotated 45 degrees right, right cheek and right ear visible, right shoulder closer to camera',
    negativePrompt: 'front view, facing camera, symmetrical face, full frontal, back view, rear view',
    icon: '\u25D7',
    denoise: 1.0,
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    prompt: 'character turntable, full right profile, camera directly to the left of subject, head turned 90 degrees right, only right side of face visible, right ear jaw line nose tip in silhouette',
    negativePrompt: 'front view, facing camera, both eyes visible, symmetrical face, three-quarter view, back view',
    icon: '\u25D1',
    denoise: 1.0,
  },
  {
    id: 'back',
    label: 'Back',
    shortLabel: 'B',
    prompt: 'character turntable, rear view from behind, camera behind subject, person facing completely away, back of head and back of body visible, spine centered, no face visible',
    negativePrompt: 'front view, facing camera, face visible, eyes visible, nose visible, mouth visible, frontal pose, turning head, looking over shoulder, three-quarter view, profile view',
    icon: '\u25CE',
    denoise: 1.0,
    skipIdentity: true,
  },
]

export type ViewResultMap = Partial<Record<ViewAngle, AvatarResult>>
export type ViewPreviewMap = Partial<Record<ViewAngle, string>>
/** Unix timestamps (Date.now()) for when each angle was generated/cached. */
export type ViewTimestampMap = Partial<Record<ViewAngle, number>>

export function getViewAngleOption(angle: ViewAngle): ViewAngleOption {
  return VIEW_ANGLE_OPTIONS.find((item) => item.id === angle) ?? VIEW_ANGLE_OPTIONS[0]
}

export function extractViewAngle(metadata?: Record<string, unknown> | null): ViewAngle | null {
  const value = metadata?.view_angle
  if (typeof value !== 'string') return null
  return VIEW_ANGLE_OPTIONS.some((item) => item.id === value) ? (value as ViewAngle) : null
}
