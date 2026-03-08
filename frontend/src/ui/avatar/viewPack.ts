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

export const VIEW_ANGLE_OPTIONS: ViewAngleOption[] = [
  {
    id: 'front',
    label: 'Front',
    shortLabel: 'F',
    prompt: 'front view, facing the camera directly, centered composition, standing naturally, full body visible from head to thighs, same person, same outfit, same hairstyle, same body proportions',
    negativePrompt: '',
    icon: '\u25C9',
    denoise: 0.85,
  },
  {
    id: 'left',
    label: 'Left',
    shortLabel: 'L',
    prompt: 'character turntable reference sheet, full left profile view, camera positioned directly to the right of the subject, head and body turned 90 degrees to the left, only left side of face visible showing left ear left cheekbone jaw line and nose tip in profile silhouette, left shoulder directly facing camera, full body profile silhouette visible showing bust contour waist curve hip shape and thigh line from the side, outfit visible in profile showing how garment fits along the body silhouette, full body visible from head to thighs, identical person same outfit same skin tone same body proportions same outfit colors, consistent lighting, (left profile:1.4), (side view:1.3)',
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, three-quarter view, 45 degree angle, right side visible, back view, rear view, facing forward, head facing forward',
    icon: '\u25D0',
    denoise: 1.0,
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    prompt: 'character turntable reference sheet, full right profile view, camera positioned directly to the left of the subject, head and body turned 90 degrees to the right, only right side of face visible showing right ear right cheekbone jaw line and nose tip in profile silhouette, right shoulder directly facing camera, full body profile silhouette visible showing bust contour waist curve hip shape and thigh line from the side, outfit visible in profile showing how garment fits along the body silhouette, full body visible from head to thighs, identical person same outfit same skin tone same body proportions same outfit colors, consistent lighting, (right profile:1.4), (side view:1.3)',
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, three-quarter view, 45 degree angle, left side visible, back view, rear view, facing forward, head facing forward',
    icon: '\u25D1',
    denoise: 1.0,
  },
  {
    id: 'back',
    label: 'Back',
    shortLabel: 'B',
    prompt: 'character turntable reference sheet, rear view from directly behind, camera positioned behind the subject, person facing completely away from camera, back of head visible showing hair from behind, full back of body visible showing shoulders and upper back and lower back and waist and hips and buttocks and upper thighs from behind, outfit visible from behind showing the rear design of the garment how it fits across the back and hips and backside, spine centered in frame, no face visible at all, full body visible from head to thighs, identical outfit colors and design as front view, same fabric colors same pattern same garment style, same body proportions and height, consistent lighting, (rear view:1.4), (from behind:1.3)',
    negativePrompt: 'front view, facing camera, looking at camera, face visible, eyes visible, nose visible, mouth visible, front of body, frontal pose, turning head, looking over shoulder, three-quarter view, profile view, side view, facing forward',
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

// ---------------------------------------------------------------------------
// Prompt sanitiser — strips pose / camera / framing tokens from the anchor
// or outfit prompt so they don't contradict the angle-specific directive.
// Only outfit, appearance, quality, and technical tokens are kept.
// ---------------------------------------------------------------------------

/** Phrases that describe camera direction, body pose, or framing — these must
 *  NOT leak into non-front angle prompts because they fight the angle directive.
 *
 *  Catch-all patterns (e.g. /\bpose\b/, /\bstance\b/) are used so that new
 *  outfit presets, NSFW modifiers, or user-typed prompts are automatically
 *  handled without needing per-phrase regex additions. */
const POSE_CAMERA_PHRASES: RegExp[] = [
  // ── Camera / gaze direction ──
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
  /\balluring\s+gaze\b/i,
  /\bsmoldering\s+gaze\b/i,
  /\bbedroom\s+eyes\b/i,
  /\bcoy\s+expression\b/i,
  /\bseductive\s+expression\b/i,
  /\binviting\s+pose\b/i,

  // ── Body framing / cropping instructions ──
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

  // ── Catch-all pose / stance / posture — any segment containing these words
  //    is a body-direction token that conflicts with non-front angles ──
  /\bpose\b/i,
  /\bstance\b/i,
  /\bposture\b/i,

  // ── Specific body actions that imply a fixed camera angle ──
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
  /\bcentered\s+composition\b/i,
  /\belongated\s+body\b/i,
  /\bconfident\s+display\b/i,

  // ── Generic "portrait" framing that biases front ──
  /solo\s+portrait\s+photograph\s+of\s+a\s+single\s+real/i,
  /portrait\s+photograph/i,
  /\bportrait\b/i,
]

/** Extra patterns stripped ONLY for the back angle — face/expression tokens
 *  that fight the "no face visible" directive. */
const BACK_ONLY_PHRASES: RegExp[] = [
  /\bfacial\s+detail\b/i,
  /\bfine\s+facial\b/i,
  /\bexpression\b/i,
  /\bsmile\b/i,
  /\bsmiling\b/i,
  /\bface\b/i,
  /\beyes?\b/i,
  /\blips?\b/i,
  /\bnose\b/i,
  /\bmouth\b/i,
  /\bcheek(bone)?s?\b/i,
  /\bjaw\s*line\b/i,
  /\bskin\s+imperfections\b/i,
]

/**
 * Strip pose / camera / framing tokens from a prompt, keeping only appearance,
 * outfit, quality, and technical photography tokens.
 *
 * For `front` angle this is a no-op — the full prompt is returned unchanged.
 * For `back` angle, face-related tokens are additionally stripped.
 */
export function sanitiseBasePromptForAngle(basePrompt: string, angle: ViewAngle): string {
  if (angle === 'front') return basePrompt

  // Split on commas — each segment is an independent CLIP token group
  const segments = basePrompt.split(',').map((s) => s.trim()).filter(Boolean)

  const kept = segments.filter((seg) => {
    for (const re of POSE_CAMERA_PHRASES) {
      if (re.test(seg)) return false
    }
    // Back view: additionally strip face/expression tokens
    if (angle === 'back') {
      for (const re of BACK_ONLY_PHRASES) {
        if (re.test(seg)) return false
      }
    }
    return true
  })

  return kept.join(', ')
}

export function extractViewAngle(metadata?: Record<string, unknown> | null): ViewAngle | null {
  const value = metadata?.view_angle
  if (typeof value !== 'string') return null
  return VIEW_ANGLE_OPTIONS.some((item) => item.id === value) ? (value as ViewAngle) : null
}
