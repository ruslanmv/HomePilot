import type { AvatarResult, AvatarSettings } from './types'
import type { FramingType, WizardMeta } from './galleryTypes'

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
// Visual descriptor extraction — pull concrete attributes (hair color, skin
// tone, ethnicity, eye color) from the base prompt so CLIP knows the actual
// appearance instead of vague "same hairstyle" that means nothing to it.
// ---------------------------------------------------------------------------

const VISUAL_DESCRIPTOR_PATTERNS: Array<{ re: RegExp; category: string }> = [
  // Hair color — match multi-word color + hair
  { re: /\b(platinum\s+blonde|strawberry\s+blonde|dirty\s+blonde|ash\s+blonde|honey\s+blonde|light\s+brown|dark\s+brown|reddish\s+brown|jet\s+black|dark\s+black|bright\s+red|dark\s+red|silver\s+grey|blue\s+black|black|blonde|brunette|brown|red|auburn|ginger|white|grey|gray|silver|pink|blue|green|purple|copper|chestnut|mahogany|caramel|golden|sandy|strawberry|platinum|raven|ebony)\s+hair\b/i, category: 'hair_color' },
  // Hair length/style
  { re: /\b(long|short|medium[- ]length|shoulder[- ]length|waist[- ]length|pixie|bob|curly|wavy|straight|braided|ponytail|twin[- ]tails?|bun|updo|bangs|fringe)\s+hair\b/i, category: 'hair_style' },
  // Standalone hair descriptors (e.g. "with long flowing hair")
  { re: /\bhair\s+(flowing|cascading|tied|pulled\s+back)/i, category: 'hair_style' },
  // Ethnicity / race
  { re: /\b(asian|east\s+asian|southeast\s+asian|korean|japanese|chinese|vietnamese|thai|filipina?|indian|south\s+asian|middle\s+eastern|arab|persian|african|black|caucasian|white|european|latina?o?|hispanic|mixed[- ]race|biracial)\b/i, category: 'ethnicity' },
  // Skin tone
  { re: /\b(pale|fair|light|olive|tan|tanned|dark|brown|ebony|porcelain|ivory|warm|cool|golden|bronze[d]?)\s+skin(?:\s+tone)?\b/i, category: 'skin' },
  // Eye color
  { re: /\b(blue|green|brown|hazel|amber|grey|gray|dark|light|black)\s+eyes\b/i, category: 'eyes' },
]

/**
 * Extract concrete visual descriptors from a prompt string.
 * Returns a short string like "dark black hair, Asian, pale skin" that can
 * be prepended to angle prompts so CLIP generates the correct appearance.
 */
export function extractVisualDescriptors(prompt: string): string {
  const found: Map<string, string> = new Map()
  for (const { re, category } of VISUAL_DESCRIPTOR_PATTERNS) {
    if (found.has(category)) continue  // first match wins per category
    const m = prompt.match(re)
    if (m) found.set(category, m[0].trim())
  }
  return Array.from(found.values()).join(', ')
}

/**
 * Build visual descriptors from structured WizardMeta appearance fields.
 * This is the preferred path — returns exact tokens like "black hair, olive skin tone,
 * brown eyes" without any regex guessing. Falls back to empty string if no
 * appearance data is present (legacy items created before this feature).
 */
export function buildVisualDescriptorsFromMeta(meta?: WizardMeta): string {
  if (!meta) return ''
  const parts: string[] = []
  if (meta.hairColor) parts.push(`${meta.hairColor} hair`)
  if (meta.hairType) parts.push(`${meta.hairType} hair texture`)
  if (meta.skinTone) parts.push(`${meta.skinTone} skin tone`)
  if (meta.eyeColor) parts.push(`${meta.eyeColor} eyes`)
  return parts.join(', ')
}

/**
 * Strip segments from the base prompt that duplicate the extracted visual descriptors.
 * For example, if visual descriptors contain "brown hair" then remove any segment
 * containing "brown hair" from the base prompt to avoid wasting CLIP budget on
 * duplicate tokens. Also strips ethnicity/realism boilerplate that isn't visual.
 */
export function stripDescriptorDuplicates(basePrompt: string, descriptors: string): string {
  if (!descriptors) return basePrompt

  // Build matcher tokens from the descriptors (e.g. ["brown hair", "wavy hair", "light skin tone"])
  const descriptorTokens = descriptors.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean)

  // Also strip non-visual boilerplate that adds no CLIP value for angle generation
  const BOILERPLATE_PATTERNS: RegExp[] = [
    /\b(european|global)\s+features\s+baseline\b/i,
    /\bnatural\s+look\b/i,
    /\bglobally\s+mixed\s+features\b/i,
    /\binclusive\b/i,
    /\bbalanced\s+facial\s+structure\b/i,
    /\bnatural\s+proportions\b/i,
    /\b(strong|angular|soft)\s+facial\s+structure\b/i,
    /\b(defined|sharp)\s+(jawline|cheekbones)\b/i,
    /\bhigh\s+quality\s+character\s+portrait\b/i,
    /\bsemi-realistic\b/i,
    /\bcinematic\s+lighting\b/i,
    /\bandrogynous\b/i,
    /\b(young\s+)?adult\b/i,
    /\bmature\s+adult\b/i,
  ]

  const segments = basePrompt.split(',').map((s) => s.trim()).filter(Boolean)

  const kept = segments.filter((seg) => {
    const lower = seg.toLowerCase()
    // Check if this segment duplicates any descriptor token
    for (const dt of descriptorTokens) {
      if (lower.includes(dt) || dt.includes(lower)) return false
    }
    // Check boilerplate patterns
    for (const re of BOILERPLATE_PATTERNS) {
      if (re.test(seg)) return false
    }
    return true
  })

  return cleanCommaArtifacts(kept.join(', '))
}

// ---------------------------------------------------------------------------
// Angle prompt builders — concise directives that leave CLIP budget for the
// visual descriptors and outfit tokens from the base prompt.
// ---------------------------------------------------------------------------

function buildLeftPrompt(ft: FramingTokens, w: number, autoMirror: boolean): string {
  if (autoMirror) {
    // Auto-mirror ON: generate right-facing (reliable) — backend mirrors to left.
    return `(right profile view:${w.toFixed(1)}), (side view:1.3), facing right, ${ft.bodyRange}, solo, consistent lighting`
  }
  // Auto-mirror OFF: original left-facing prompt — no backend post-processing.
  return `(left profile view:${w.toFixed(1)}), (side view:1.3), facing left, ${ft.bodyRange}, solo, consistent lighting`
}

function buildRightPrompt(ft: FramingTokens, w: number): string {
  return `(right profile view:${w.toFixed(1)}), (side view:1.3), facing right, ${ft.bodyRange}, solo, consistent lighting`
}

function buildBackPrompt(ft: FramingTokens, w: number): string {
  return `(rear view:${w.toFixed(1)}), (from behind:1.3), facing away from camera, back of head visible, no face visible, ${ft.bodyRange}, solo, consistent lighting`
}

function buildFrontPrompt(ft: FramingTokens): string {
  return `front view, facing camera, ${ft.bodyRange}, solo`
}

/** Build the identity-lock suffix — concise to save CLIP budget.
 *  NOTE: bodyRange is NOT included here because buildAnglePrompt already
 *  emits it — duplicating it wastes ~2 CLIP tokens on every angle. */
export function buildIdentityLockSuffix(_framingType?: FramingType): string {
  return 'same outfit, same hairstyle, same body proportions'
}

/** Build the angle-specific positive prompt, adapted to the framing type.
 *  When `settings` is provided, per-angle prompt weights from viewAngleTuning
 *  override the built-in defaults. */
export function buildAnglePrompt(angle: ViewAngle, framingType?: FramingType, settings?: AvatarSettings): string {
  const ft = getFramingTokens(framingType)
  switch (angle) {
    case 'front': return buildFrontPrompt(ft)
    case 'left':  return buildLeftPrompt(ft, resolveAngleTuning('left', settings).promptWeight, settings?.autoMirrorLeft ?? true)
    case 'right': return buildRightPrompt(ft, resolveAngleTuning('right', settings).promptWeight)
    case 'back':  return buildBackPrompt(ft, resolveAngleTuning('back', settings).promptWeight)
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
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, back view, rear view, double person, two people, split image, multiple views',
    icon: '\u25D0',
    // Use 'reference' mode (img2img) so the front image anchors the generation.
    // Denoise 0.78 keeps ~22% of the reference latent — enough to preserve
    // hair color, skin tone, and outfit colors while still allowing rotation.
    denoise: 0.78,
    generationMode: 'reference',
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    negativePrompt: 'front view, facing camera, looking at camera, frontal, both eyes visible, symmetrical face, back view, rear view, double person, two people, split image, multiple views',
    icon: '\u25D1',
    // Same as left — 'reference' mode at 0.78 denoise preserves colors
    // while the simplified prompt focuses CLIP on angle rotation.
    denoise: 0.78,
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

// ---------------------------------------------------------------------------
// Per-angle tuning defaults & resolver
// ---------------------------------------------------------------------------

export interface AngleTuning {
  denoise: number
  promptWeight: number
}

type TunableAngle = 'left' | 'right' | 'back'

/** Built-in defaults — these are the values used when no user override exists. */
export const ANGLE_TUNING_DEFAULTS: Record<TunableAngle, AngleTuning> = {
  left:  { denoise: 0.78, promptWeight: 1.4 },
  right: { denoise: 0.78, promptWeight: 1.5 },
  back:  { denoise: 0.90, promptWeight: 1.4 },
}

/** Resolve effective tuning for an angle, merging user overrides with defaults. */
export function resolveAngleTuning(
  angle: TunableAngle,
  settings?: AvatarSettings,
): AngleTuning {
  const defaults = ANGLE_TUNING_DEFAULTS[angle]
  const overrides = settings?.viewAngleTuning?.[angle]
  if (!overrides) return defaults
  return {
    denoise: overrides.denoise ?? defaults.denoise,
    promptWeight: overrides.promptWeight ?? defaults.promptWeight,
  }
}

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
  /\bgaze\b/i,
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
 * - Remove orphaned adjective stubs left by backend's _strip_outfit_tokens
 *   (e.g. "fitted", "delicate", "modern stylish" when the noun was stripped)
 * - Deduplicate identical segments ("fitted, ..., fitted" → "fitted, ...")
 */
function cleanCommaArtifacts(text: string): string {
  // Single-word or two-word orphans that are adjectives with no noun —
  // these are leftovers from the backend stripping outfit nouns like
  // "fitted top" → "fitted", "delicate necklace" → "delicate"
  const ORPHAN_STUBS = /^(fitted|delicate|clean|modern\s+stylish|stylish|elegant|fancy|gorgeous|beautiful|lovely|stunning|modern\s+fashion|clean\s+aesthetic|clean\s+modern|modern\s+clean)$/i

  const seen = new Set<string>()
  return text
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .filter((s) => !ORPHAN_STUBS.test(s))            // orphaned adjective stubs
    .filter((s) => !/^\w+\s+(?:and|or)$/i.test(s))   // trailing conjunctions
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
