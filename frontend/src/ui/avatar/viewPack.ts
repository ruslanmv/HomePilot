import type { AvatarResult } from './types'
import type { FramingType } from './galleryTypes'

export type ViewAngle = 'front' | 'left' | 'right' | 'back'
export type ViewSource = 'anchor' | 'latest' | 'equipped'

export interface ViewAngleOption {
  id: ViewAngle
  label: string
  shortLabel: string
  /** Negative prompt tokens to prevent the reference pose from dominating. */
  negativePrompt: string
  icon: string
  /** Denoise override — higher values let the text prompt control pose.
   *  Front uses default (0.85), non-front uses 1.0 for full prompt control. */
  denoise: number
  /** Generation mode override for this angle:
   *  - 'identity'  → InstantID (face ControlNet + empty latent)
   *  - 'standard'  → text-only (no reference image at all)
   *  - 'reference' → img2img with reference (colors preserved, no face ControlNet)
   *  Defaults to 'identity' if not set. */
  generationMode?: 'identity' | 'standard' | 'reference'
}

// ---------------------------------------------------------------------------
// Framing-aware body range tokens — match the front view's composition
// ---------------------------------------------------------------------------

interface FramingTokens {
  bodyRange: string
  framingNegative: string
}

const FRAMING_TOKENS: Record<FramingType, FramingTokens> = {
  half_body: {
    bodyRange: 'from head to waist',
    framingNegative: 'full body, legs visible, knees visible, feet visible',
  },
  mid_body: {
    bodyRange: 'from head to hips',
    framingNegative: 'full body, knees visible, feet visible',
  },
  headshot: {
    bodyRange: 'from head to shoulders',
    framingNegative: 'full body, waist visible, legs visible',
  },
}

function getFramingTokens(framingType?: FramingType): FramingTokens {
  return FRAMING_TOKENS[framingType || 'half_body']
}

// ---------------------------------------------------------------------------
// Angle prompt builders — inject framing-appropriate body range tokens
// ---------------------------------------------------------------------------

function buildLeftPrompt(ft: FramingTokens): string {
  // Simplified to match back prompt's clean camera-position style.
  // Shorter prompt reduces CLIP token saturation on local GPUs.
  // Uses camera-position language instead of body-anatomy tokens.
  return `solo single person, left profile view from directly to the right, camera positioned to the right of the subject, person facing directly to the left, left side of body visible ${ft.bodyRange}, outfit visible in profile, identical outfit colors and design as front view, same fabric colors same pattern same garment style, same body proportions and height, consistent lighting, (left profile:1.4), (side view:1.3)`
}

function buildRightPrompt(ft: FramingTokens): string {
  // Simplified to match back prompt's clean camera-position style.
  return `solo single person, right profile view from directly to the left, camera positioned to the left of the subject, person facing directly to the right, right side of body visible ${ft.bodyRange}, outfit visible in profile, identical outfit colors and design as front view, same fabric colors same pattern same garment style, same body proportions and height, consistent lighting, (right profile:1.4), (side view:1.3)`
}

function buildBackPrompt(ft: FramingTokens): string {
  return `solo single person, rear view from directly behind, camera positioned behind the subject, person facing completely away from camera, back of head visible showing hair from behind, back of body visible ${ft.bodyRange} showing shoulders and upper back and lower back from behind, outfit visible from behind showing the rear design of the garment, spine centered in frame, no face visible at all, body visible ${ft.bodyRange}, identical outfit colors and design as front view, same fabric colors same pattern same garment style, same body proportions and height, consistent lighting, (rear view:1.4), (from behind:1.3)`
}

function buildFrontPrompt(ft: FramingTokens): string {
  return `front view, facing the camera directly, centered composition, standing naturally, body visible ${ft.bodyRange}, same person, same outfit, same hairstyle, same body proportions`
}

/** Build the identity-lock suffix with framing-appropriate body range. */
export function buildIdentityLockSuffix(framingType?: FramingType): string {
  const ft = getFramingTokens(framingType)
  return `fixed camera distance, preserve exact outfit including coverage level and skin exposure and garment fit, preserve exact hairstyle and accessories, same body shape and proportions, body framing ${ft.bodyRange}`
}

/** Build the angle-specific positive prompt, adapted to the framing type. */
export function buildAnglePrompt(angle: ViewAngle, framingType?: FramingType): string {
  const ft = getFramingTokens(framingType)
  switch (angle) {
    case 'front': return buildFrontPrompt(ft)
    case 'left':  return buildLeftPrompt(ft)
    case 'right': return buildRightPrompt(ft)
    case 'back':  return buildBackPrompt(ft)
  }
}

export const VIEW_ANGLE_OPTIONS: ViewAngleOption[] = [
  {
    id: 'front',
    label: 'Front',
    shortLabel: 'F',
    negativePrompt: '',
    icon: '\u25C9',
    denoise: 0.85,
  },
  {
    id: 'left',
    label: 'Left',
    shortLabel: 'L',
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, right side visible, back view, rear view, facing forward, double person, two people, split image, multiple views',
    icon: '\u25D0',
    // Use 'reference' mode (img2img) so the front image anchors the generation
    // to a single person and preserves outfit colors.  Denoise 0.85 keeps ~15%
    // of the reference's color/structure signal for better identity anchoring
    // while the simplified prompt controls the angle with less CLIP saturation.
    denoise: 0.85,
    generationMode: 'reference',
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, left side visible, back view, rear view, facing forward, double person, two people, split image, multiple views',
    icon: '\u25D1',
    // Same as left — 'reference' mode preserves colors and prevents
    // dual-person generation that happens with pure text-only mode.
    denoise: 0.85,
    generationMode: 'reference',
  },
  {
    id: 'back',
    label: 'Back',
    shortLabel: 'B',
    negativePrompt: 'front view, facing camera, looking at camera, face visible, eyes visible, nose visible, mouth visible, front of body, frontal pose, turning head, looking over shoulder, three-quarter view, profile view, side view, facing forward, double person, double people, two people, two persons, split image, reference sheet, multiple views, side by side',
    icon: '\u25CE',
    // Use 'reference' mode (img2img) so the front image's outfit colors
    // (e.g. black skirt, white top) survive into the back view via the
    // reference latent. Denoise 0.9 preserves ~10% color signal from the
    // reference while the strong back-facing text prompt controls the pose.
    denoise: 0.9,
    generationMode: 'reference',
  },
]

export type ViewResultMap = Partial<Record<ViewAngle, AvatarResult>>
export type ViewPreviewMap = Partial<Record<ViewAngle, string>>
/** Unix timestamps (Date.now()) for when each angle was generated/cached. */
export type ViewTimestampMap = Partial<Record<ViewAngle, number>>

export function getViewAngleOption(angle: ViewAngle): ViewAngleOption {
  return VIEW_ANGLE_OPTIONS.find((item) => item.id === angle) ?? VIEW_ANGLE_OPTIONS[0]
}

// ---------------------------------------------------------------------------
// Prompt sanitiser — strips conflicting tokens from the base prompt so they
// don't fight the angle directive. Applied to ALL non-front angles.
//
// 10 layers of patterns, each targeting a specific category of tokens that
// waste CLIP budget or actively contradict the angle directive.
// ---------------------------------------------------------------------------

// Layer 1: Front pose / camera direction
const FRONT_POSE_PATTERNS: RegExp[] = [
  /front[- ]?facing/i,
  /facing\s+(the\s+)?camera\s*(directly)?/i,
  /looking\s+(directly\s+)?(at|into)\s+(the\s+)?camera/i,
  /looking\s+straight\s+ahead/i,
  /looking\s+over\b/i,
  /facing\s+(forward|ahead|straight)/i,
  /eye\s*contact/i,
  /gazing?\s+(at|into)\s+(the\s+)?(camera|viewer|lens)/i,
  /staring\s+(at|into)\s+(the\s+)?camera/i,
  /direct\s+(eye\s*contact|gaze)/i,
  /\bfront\s+view\b/i,
]

// Layer 2: Face detail tokens (waste CLIP budget on profile/back where face is minimal or hidden)
const FACE_DETAIL_PATTERNS: RegExp[] = [
  /\bfine\s+facial\s+detail\b/i,
  /\bfacial\s+detail\b/i,
  /\bpores\s+visible\b/i,
  /\bultra\s+realistic\s+skin\s+texture\b/i,
  /\bnatural\s+skin\s+imperfections\b/i,
]

// Layer 3: Expression tokens (imply camera engagement / visible face)
const EXPRESSION_PATTERNS: RegExp[] = [
  /\bwarm\s+approachable\s+expression\b/i,
  /\balluring\s+gaze\b/i,
  /\bsmoldering\s+gaze\b/i,
  /\bbedroom\s+eyes\b/i,
  /\bcoy\s+expression\b/i,
  /\bseductive\s+expression\b/i,
  /\binviting\b/i,
  /\bexpression\b/i,
  /\bsmile\b/i,
  /\bsmiling\b/i,
]

// Layer 3b: Front-biased pose descriptions
const FRONT_POSE_DESC_PATTERNS: RegExp[] = [
  /\bconfident\s+(natural|relaxed)\s+pose\b/i,
  /\bconfident\s+display\b/i,
  /\binviting\s+pose\b/i,
  /\bpose\b/i,
  /\bstance\b/i,
  /\bposture\b/i,
]

// Layer 4: Identity boilerplate (wastes CLIP budget, adds no visual info for angles)
const IDENTITY_BOILERPLATE_PATTERNS: RegExp[] = [
  /solo\s+portrait\s+photograph\s+of\s+a\s+single\s+real/i,
  /portrait\s+photograph/i,
  /\bportrait\b/i,
  /\bsingle\s+real\s+(female|male)\s+(woman|man|person)\b/i,
]

// Layer 5: Scene/setting tokens (persona-specific; studio backgrounds are KEPT)
const SCENE_SETTING_PATTERNS: RegExp[] = [
  /\bprofessional\s+office\b/i,
  /\bcorporate\s+office\b/i,
  /\bupscale\s+cafe\s+background\b/i,
  /\burban\s+alley\s+backdrop\b/i,
  /\bboudoir\s+setting\b/i,
  /\bhome\s+setting\b/i,
  /\boffice\s+setting\b/i,
  /\bnightclub\b/i,
  /\bboardroom\b/i,
  // NOTE: "clean minimal studio background", "neutral studio background",
  // "clean studio lighting" are intentionally NOT stripped — they keep the
  // background consistent across all angles.
]

// Layer 6: Professional identity tokens (irrelevant to outfit appearance)
const PROFESSIONAL_IDENTITY_PATTERNS: RegExp[] = [
  /\bprofessional\s+appearance\b/i,
  /\bimpeccable\s+grooming\b/i,
  /\bformal\s+neckwear\b/i,
  /\bexecutive\s+assistant\s+professional\b/i,
  /\bcorporate\s+executive\b/i,
  /\bwell\s+groomed\b/i,
]

// Layer 7: Backend-duplicated quality tokens (already added by backend's outfit.py)
// NOTE: User-specified lighting like "soft diffused lighting" is intentionally KEPT.
const BACKEND_QUALITY_PATTERNS: RegExp[] = [
  /\belegant\s+lighting\b/i,
  /^realistic$/i,
  /^sharp\s+focus$/i,
]

// Layer 8: Framing / composition tokens (replaced by angle-specific framing)
const FRAMING_PATTERNS: RegExp[] = [
  /medium\s+shot\s+portrait/i,
  /medium\s+shot/i,
  /mid[- ]?body\s+framing(\s+from\s+head\s+to\s+(hips|waist))?/i,
  /half[- ]?body\s+framing(\s+from\s+head\s+to\s+(waist|hips|thighs))?/i,
  /upper\s+body\s+(and\s+hips\s+)?visible/i,
  /showing\s+full\s+torso\s+and\s+hip\s+area/i,
  /showing\s+torso\s+arms?\s+and\s+hands?/i,
  /frame\s+ends\s+at\s+upper\s+thighs/i,
  /hips\s+included\s+in\s+frame/i,
  /no\s+knees\s+visible/i,
  /no\s+legs\s+below\s+thighs/i,
  /full\s+body\s+visible\s+from\s+head\s+to\s+thighs/i,
  /body\s+posture\s+(and\s+pose\s+)?visible/i,
  /clothing\s+and\s+outfit\s+clearly\s+visible/i,
  /clothing\s+and\b/i,
  /waist[- ]?up\s+composition/i,
  /head\s+to\s+(waist|hips|thighs)\s+composition/i,
  /\bcentered\s+composition\b/i,
]

// Layer 9: Persona role tokens (persona description, not visual)
const PERSONA_ROLE_PATTERNS: RegExp[] = [
  /\bexecutive\s+assistant\b/i,
  /\bcorporate\s+executive\b/i,
  /\bprofessional\s+executive\b/i,
  /\boffice\s+attire\b/i,
]

// Layer 10: Specific body actions that imply a fixed camera angle
const BODY_ACTION_PATTERNS: RegExp[] = [
  /\bstanding\s+(naturally|professionally)\b/i,
  /\bseated\b/i,
  /\bkneeling\b/i,
  /\blying\s+down\b/i,
  /\bleaning\s+(forward|casually)\b/i,
  /\bleaning\s+forward\s+seductively\b/i,
  /\barched\s+back\b/i,
  /\barms?\s+(raised|crossed|above)\b/i,
  /\bwalking\s+confidently\b/i,
  /\bgiving\s+a\s+presentation\b/i,
  /\bhands?\s+(on|at)\s+(hip|side|waist)s?/i,
  /\belongated\s+body\b/i,
]

/** All pattern layers applied for non-front angles. */
const ALL_SANITISE_LAYERS: RegExp[][] = [
  FRONT_POSE_PATTERNS,
  FACE_DETAIL_PATTERNS,
  EXPRESSION_PATTERNS,
  FRONT_POSE_DESC_PATTERNS,
  IDENTITY_BOILERPLATE_PATTERNS,
  SCENE_SETTING_PATTERNS,
  PROFESSIONAL_IDENTITY_PATTERNS,
  BACKEND_QUALITY_PATTERNS,
  FRAMING_PATTERNS,
  PERSONA_ROLE_PATTERNS,
  BODY_ACTION_PATTERNS,
]

/**
 * Clean comma artifacts after stripping tokens:
 * - Remove empty segments
 * - Remove trailing conjunctions ("clothing and" → removed)
 * - Deduplicate identical segments ("fitted, ..., fitted" → "fitted, ...")
 */
function cleanCommaArtifacts(text: string): string {
  const seen = new Set<string>()
  return text
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .filter((s) => !/^\w+\s+(?:and|or)$/i.test(s)) // trailing conjunctions
    .filter((s) => {
      const key = s.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .join(', ')
}

/**
 * Strip conflicting tokens from a prompt for non-front angles.
 *
 * For `front` angle this is a no-op — returns the cleaned prompt unchanged.
 * For all other angles, applies all 10+ sanitisation layers to remove tokens
 * that fight the angle directive, waste CLIP budget, or duplicate backend tokens.
 */
export function sanitiseBasePromptForAngle(basePrompt: string, angle: ViewAngle): string {
  if (angle === 'front') return cleanCommaArtifacts(basePrompt)

  // Split on commas — each segment is an independent CLIP token group
  const segments = basePrompt.split(',').map((s) => s.trim()).filter(Boolean)

  const kept = segments.filter((seg) => {
    for (const layer of ALL_SANITISE_LAYERS) {
      for (const re of layer) {
        if (re.test(seg)) return false
      }
    }
    return true
  })

  return cleanCommaArtifacts(kept.join(', '))
}

export function extractViewAngle(metadata?: Record<string, unknown> | null): ViewAngle | null {
  const value = metadata?.view_angle
  if (typeof value !== 'string') return null
  return VIEW_ANGLE_OPTIONS.some((item) => item.id === value) ? (value as ViewAngle) : null
}
