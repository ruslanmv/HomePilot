import type { AvatarResult } from './types'

export type ViewAngle = 'front' | 'left' | 'right' | 'back'
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
// Only cardinal directions (0°, 90°, 180°) are supported.  45° angles were
// removed because InstantID's ControlNet conflicts with three-quarter poses,
// producing face distortion in the 30–60° "conflict zone".  Cardinal angles
// either align with InstantID (front) or are extreme enough that the model
// ignores the ControlNet entirely (left/right/back).
//
// Keep prompts lean — CLIP has limited token budget (~77 SD1.5 / ~256 SDXL).
// The backend appends its own quality suffix ("elegant lighting, realistic,
// sharp focus") so we skip lighting/quality cues here.
//
// Structure: [turntable context] [camera position] [visible anatomy] [what NOT to show]
// ────────────────────────────────────────────────────────────────────────

export const VIEW_ANGLE_OPTIONS: ViewAngleOption[] = [
  {
    id: 'front',
    label: 'Front',
    shortLabel: 'F',
    prompt: 'character turntable, front view, facing camera directly, centered composition, standing naturally',
    negativePrompt: 'side view, profile, three-quarter view, back view, turned away',
    icon: '\u25C9',
    denoise: 0.85,
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    prompt: 'character turntable, full right profile, camera directly to the left of subject, head turned 90 degrees right, only right side of face visible, right ear jaw line nose tip in silhouette',
    negativePrompt: 'front view, facing camera, both eyes visible, symmetrical face, three-quarter view, 45 degree turn, back view, rear view',
    icon: '\u25D1',
    denoise: 1.0,
  },
  {
    id: 'back',
    label: 'Back',
    shortLabel: 'B',
    prompt: 'character turntable, rear view from behind, camera behind subject, person facing completely away, back of head and back of body visible, spine centered, no face visible',
    negativePrompt: 'front view, facing camera, face visible, eyes visible, nose visible, mouth visible, frontal pose, turning head, looking over shoulder, three-quarter view, profile view, side view',
    icon: '\u25CE',
    denoise: 1.0,
    skipIdentity: true,
  },
  {
    id: 'left',
    label: 'Left',
    shortLabel: 'L',
    prompt: 'character turntable, full left profile, camera directly to the right of subject, head turned 90 degrees left, only left side of face visible, left ear jaw line nose tip in silhouette',
    negativePrompt: 'front view, facing camera, both eyes visible, symmetrical face, three-quarter view, 45 degree turn, back view, rear view',
    icon: '\u25D0',
    denoise: 1.0,
  },
]

// ── Outfit-aware rear emphasis ────────────────────────────────────────────
// When the outfit description contains NSFW/lingerie tokens, the back angle
// needs explicit body-from-behind cues so the model actually shows the
// garment's rear design (thong back, straps, bare skin, buttocks shape
// through fabric, etc.) instead of a generic spine shot.
// ──────────────────────────────────────────────────────────────────────────

const NSFW_REAR_KEYWORDS = [
  'lingerie', 'boudoir', 'thong', 'g-string', 'panties', 'underwear',
  'bikini', 'swimwear', 'nude', 'naked', 'topless', 'explicit',
  'sensual', 'erotic', 'provocative', 'revealing', 'sheer',
  'latex', 'fetish', 'stockings', 'garter', 'corset', 'bodysuit',
  'teddy', 'babydoll', 'chemise', 'negligee',
]

/** Returns true when the outfit description contains NSFW/lingerie tokens. */
export function isNsfwOutfit(outfitDesc: string): boolean {
  const lower = outfitDesc.toLowerCase()
  return NSFW_REAR_KEYWORDS.some((kw) => lower.includes(kw))
}

/**
 * Returns angle-specific emphasis tokens that guide the model to show the
 * rear of the garment and relevant body features.  Only applies to the back
 * angle, and only when the outfit is NSFW/lingerie.
 */
export function getRearEmphasis(angle: ViewAngle, outfitDesc: string): string {
  if (angle !== 'back') return ''
  if (!isNsfwOutfit(outfitDesc)) return ''

  const lower = outfitDesc.toLowerCase()
  const hasThong = lower.includes('thong') || lower.includes('g-string')
  const hasStockings = lower.includes('stockings') || lower.includes('garter')

  const tokens = [
    'outfit visible from behind',
    'back of garment and body details clearly visible',
    'rear view of clothing showing full back design',
    'buttocks shape and contour visible through outfit',
  ]
  if (hasThong) tokens.push('thong back strap visible between buttocks')
  if (hasStockings) tokens.push('stocking tops and garter straps visible from behind')
  return tokens.join(', ')
}

export type ViewResultMap = Partial<Record<ViewAngle, AvatarResult>>
export type ViewPreviewMap = Partial<Record<ViewAngle, string>>
/** Unix timestamps (Date.now()) for when each angle was generated/cached. */
export type ViewTimestampMap = Partial<Record<ViewAngle, number>>

export function getViewAngleOption(angle: ViewAngle): ViewAngleOption {
  return VIEW_ANGLE_OPTIONS.find((item) => item.id === angle) ?? VIEW_ANGLE_OPTIONS[0]
}

/**
 * Builds the exact outfit_prompt that would be sent to the backend for a
 * given angle + outfit description.  Used both by the generation hook and
 * by the View Pack panel to let users preview/copy the prompt.
 */
export function buildAnglePrompt(angle: ViewAngle, outfitDesc: string): string {
  const angleMeta = getViewAngleOption(angle)
  const desc = outfitDesc?.trim() || 'portrait photograph'
  const rearEmphasis = getRearEmphasis(angle, desc)
  return [
    angleMeta.prompt,
    desc,
    ...(rearEmphasis ? [rearEmphasis] : []),
    'full body visible head to knees',
  ].join(', ')
}

export function extractViewAngle(metadata?: Record<string, unknown> | null): ViewAngle | null {
  const value = metadata?.view_angle
  if (typeof value !== 'string') return null
  return VIEW_ANGLE_OPTIONS.some((item) => item.id === value) ? (value as ViewAngle) : null
}
