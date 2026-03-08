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
    skipIdentity: true,
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
    skipIdentity: true,
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

// ── Prompt sanitisation for non-front angles ────────────────────────────
// The outfit description often includes the anchor's character_prompt
// (appended by the backend via _strip_outfit_tokens).  This injects
// front-specific tokens, face detail, scene/setting, and identity phrases
// that contradict the target angle and waste CLIP's limited budget.
//
// We aggressively strip these before combining with the angle directive.
// The outfit tokens (clothing, accessories, mood) appear FIRST in the
// string and survive — only the character-prompt tail is cleaned.
// ─────────────────────────────────────────────────────────────────────────

// ── Layer 1: Front-facing orientation (strip for ALL non-front angles) ──
const FRONT_POSE_PATTERNS: RegExp[] = [
  /\bfront[- ]?facing\b/gi,
  /\bfacing\s+(?:the\s+)?camera(?:\s+directly)?\b/gi,
  /\blooking\s+(?:directly\s+)?(?:at|into)\s+(?:the\s+)?camera\b/gi,
  /\blooking\s+at\s+(?:the\s+)?viewer\b/gi,
  /\bfront\s+view\b/gi,
  /\bcentered\s+composition\b/gi,
  /\bstanding\s+naturally\b/gi,
  /\bcharacter\s+turntable\b/gi,
]

// ── Layer 2: Face/expression detail (strip for left/right/back) ─────────
// Profile views show limited face; back shows none.  These tokens fight
// the angle directive and waste CLIP budget.
const FACE_DETAIL_PATTERNS: RegExp[] = [
  /\bfine\s+facial\s+detail\b/gi,
  /\bfacial\s+detail\b/gi,
  /\bsharp\s+defined\s+facial\s+features\b/gi,
  /\bpores\s+visible\b/gi,
  /\bnatural\s+skin\s+imperfections\b/gi,
  /\bultra\s+realistic\s+skin\s+texture\b/gi,
  /\bboth\s+eyes\s+visible\b/gi,
  /\bsymmetrical\s+face\b/gi,
]

// ── Layer 3: Expression tokens (strip for ALL non-front angles) ──────────
// Profile views show the face in silhouette; expressions like "warm
// approachable" imply camera engagement and fight the profile directive.
const EXPRESSION_PATTERNS: RegExp[] = [
  /\bwarm\s+approachable\s+expression\b/gi,
  /\b(?:confident|natural|relaxed)\s+(?:poised\s+|natural\s+)?expression\b/gi,
  /\bsmoldering\s+gaze\b/gi,
  /\bbedroom\s+eyes\b/gi,
  /\bcoy\s+expression\b/gi,
]

// ── Layer 3b: Front-biased pose tokens (strip for ALL non-front) ─────────
// Pose descriptors that imply a frontal body orientation.
const FRONT_POSE_DESC_PATTERNS: RegExp[] = [
  /\bconfident\s+relaxed\s+pose\b/gi,
  /\bconfident\s+natural\s+pose\b/gi,
  /\bconfident\s+poised\s+pose\b/gi,
  /\brelaxed\s+natural\s+pose\b/gi,
  /\bnatural\s+confident\s+pose\b/gi,
]

// ── Layer 4: Character-prompt identity boilerplate (strip for ALL non-front) ─
// These come from the anchor's character_prompt and add nothing to angle views.
const IDENTITY_BOILERPLATE_PATTERNS: RegExp[] = [
  // "Solo portrait photograph of a single real female woman/executive/..."
  /\bSolo\s+portrait\s+photograph\s+of\s+a\s+single\s+real\s+\w+(?:\s+\w+)?\b/gi,
  // "portrait photograph of the same character"
  /\bportrait\s+photograph\s+of\s+the\s+same\s+character\b/gi,
]

// ── Layer 5: Persona-specific scenes (strip for ALL non-front) ──────────
// Only strip scene tokens tied to the anchor's persona (office, cafe).
// KEEP neutral studio backgrounds — they ensure visual consistency across
// all angles.  Without them the model generates random backgrounds (city,
// street, etc.) that don't match the front view.
const SCENE_SETTING_PATTERNS: RegExp[] = [
  /\bprofessional\s+office\b/gi,
  /\b(?:corporate|luxury\s+penthouse|modern)\s+office\b/gi,
  /\boffice\s+with\s+plants\b/gi,
  /\bupscale\s+cafe\s+background\b/gi,
]

// ── Layer 6: Professional/formal identity tokens (strip for ALL non-front) ─
// These describe the anchor's persona, not the outfit.  In lingerie/NSFW
// contexts they actively fight the target aesthetic.
const PROFESSIONAL_IDENTITY_PATTERNS: RegExp[] = [
  /\bprofessional\s+appearance\b/gi,
  /\bprofessional\s+photography\b/gi,
  /\bimpeccable\s+grooming\b/gi,
  /\bwell\s+groomed\b/gi,
  /\bformal\s+neckwear\b/gi,
]

// ── Layer 7: Quality/photography tokens the backend already appends ─────
// The backend adds "elegant lighting, realistic, sharp focus" so these
// duplicate tokens waste CLIP budget.
// NOTE: User-chosen lighting (e.g. "soft diffused lighting") is NOT stripped
// here — it ensures lighting consistency across all angles.
const BACKEND_QUALITY_PATTERNS: RegExp[] = [
  /\belegant\s+lighting\b/gi,
  /\brealistic\b/gi,
  /\bsharp\s+focus\b/gi,
]

// ── Layer 8: Medium/half-body framing (strip for ALL non-front) ─────────
// The character prompt includes framing directives from the chosen Photo
// Style (Half-Body or Half-Body Mid) that directly contradict the angle
// view's "full body visible head to knees".
// Covers both Half-Body (head→waist) and Half-Body Mid (head→hips).
const MEDIUM_SHOT_FRAMING_PATTERNS: RegExp[] = [
  /\bmedium\s+shot\s+portrait\b/gi,
  // Half-Body Mid (head → hips)
  /\bmid-body\s+framing\s+from\s+head\s+to\s+hips\b/gi,
  /\bupper\s+body\s+and\s+hips\s+visible\b/gi,
  /\bshowing\s+full\s+torso\s+and\s+hip\s+area\b/gi,
  /\bframe\s+ends\s+at\s+upper\s+thighs\b/gi,
  /\bhips\s+included\s+in\s+frame\b/gi,
  /\bno\s+knees\s+visible\b/gi,
  /\bno\s+legs\s+below\s+thighs\b/gi,
  // Half-Body (head → waist)
  /\bhalf-body\s+framing\s+from\s+head\s+to\s+waist\b/gi,
  /\bupper\s+body\s+visible\b/gi,
  /\bshowing\s+torso\s+arms\s+and\s+hands\b/gi,
  /\bwaist-up\s+composition\b/gi,
  // Common to both
  /\bbody\s+posture\s+and\s+pose\s+visible\b/gi,
  /\bbody\s+posture\s+visible\b/gi,
  /\bclothing\s+and\s+outfit\s+clearly\s+visible\b/gi,
]

// ── Layer 9: Persona / role-identity tokens (strip for ALL non-front) ───
// The anchor's character_prompt often includes job titles or persona
// descriptors ("executive assistant professional") that add nothing to
// angle views and can fight outfit aesthetics.
const PERSONA_ROLE_PATTERNS: RegExp[] = [
  /\bexecutive\s+assistant\s+professional\b/gi,
  /\bexecutive\s+(?:professional|portrait)\b/gi,
  /\bcorporate\s+executive\b/gi,
  /\bbusiness\s+(?:professional|executive|woman|man)\b/gi,
]

/**
 * Remove comma-separated segments that are empty, whitespace-only, or
 * consist of a bare trailing conjunction after token stripping.
 * Also deduplicates identical segments to save CLIP budget.
 * Fixes artifacts like "fitted , , delicate ," → "fitted, delicate"
 * and "clothing and," → removed, and "fitted, ..., fitted" → "fitted, ..."
 */
function cleanCommaArtifacts(text: string): string {
  const seen = new Set<string>()
  return text
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    // Remove bare trailing conjunctions ("clothing and", "style or")
    .filter((s) => !/^\w+\s+(?:and|or)$/i.test(s))
    // Deduplicate identical segments
    .filter((s) => {
      const key = s.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .join(', ')
}

/** Apply a list of regex patterns, replacing all matches with empty string. */
function applyPatterns(text: string, patterns: RegExp[]): string {
  let result = text
  for (const pat of patterns) {
    result = result.replace(pat, '')
  }
  return result
}

/**
 * Sanitise the outfit/character description for a specific angle by removing
 * tokens that contradict or are irrelevant to the target pose.
 *
 * Stripping layers (cumulative — ALL non-front angles):
 *   front  → clean comma artifacts + dedup only
 *   left/right/back → front-facing, face detail, expressions, front-biased poses,
 *                      identity boilerplate, scene/setting, professional tokens,
 *                      medium-shot framing, persona/role, backend quality/lighting
 */
function sanitizeDescForAngle(desc: string, angle: ViewAngle): string {
  if (angle === 'front') return cleanCommaArtifacts(desc)

  let result = desc

  // All non-front angles: strip every category that fights the angle directive
  result = applyPatterns(result, FRONT_POSE_PATTERNS)
  result = applyPatterns(result, FACE_DETAIL_PATTERNS)
  result = applyPatterns(result, EXPRESSION_PATTERNS)
  result = applyPatterns(result, FRONT_POSE_DESC_PATTERNS)
  result = applyPatterns(result, IDENTITY_BOILERPLATE_PATTERNS)
  result = applyPatterns(result, SCENE_SETTING_PATTERNS)
  result = applyPatterns(result, PROFESSIONAL_IDENTITY_PATTERNS)
  result = applyPatterns(result, BACKEND_QUALITY_PATTERNS)
  result = applyPatterns(result, MEDIUM_SHOT_FRAMING_PATTERNS)
  result = applyPatterns(result, PERSONA_ROLE_PATTERNS)

  return cleanCommaArtifacts(result)
}

/**
 * Builds the exact outfit_prompt that would be sent to the backend for a
 * given angle + outfit description.  Used both by the generation hook and
 * by the View Pack panel to let users preview/copy the prompt.
 *
 * The description is sanitised per-angle to remove tokens that contradict
 * the target pose (e.g. "front-facing" is stripped for back/side angles).
 */
export function buildAnglePrompt(angle: ViewAngle, outfitDesc: string): string {
  const angleMeta = getViewAngleOption(angle)
  const rawDesc = outfitDesc?.trim() || 'portrait photograph'
  const desc = sanitizeDescForAngle(rawDesc, angle)
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
