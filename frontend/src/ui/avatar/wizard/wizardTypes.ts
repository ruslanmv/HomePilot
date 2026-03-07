/**
 * wizardTypes.ts — Type system, constants, and presets for the 7-step
 * Character Creation Wizard.
 *
 * All visual presets map to Stable Diffusion prompt fragments.
 * Professional options appear first; NSFW options gated by global setting.
 */

// ---------------------------------------------------------------------------
// Core enums
// ---------------------------------------------------------------------------

export type Gender = 'female' | 'male' | 'neutral'
export type AgeRange = 'young_adult' | 'adult' | 'mature'
export type RoleCategory = 'professional' | 'creative' | 'technical' | 'custom'
export type BodyType = 'slim' | 'average' | 'athletic' | 'curvy'
export type Posture = 'upright' | 'relaxed' | 'confident'
export type Polish = 'natural' | 'light_makeup' | 'formal'
export type Expression = 'neutral' | 'professional_smile' | 'serious' | 'warm' | 'playful'
export type PortraitType = 'headshot' | 'half_body' | 'mid_body' | 'full_body'
export type MemoryEngine = 'adaptive' | 'basic' | 'off'

// ---------------------------------------------------------------------------
// Character Draft — accumulates all wizard choices
// ---------------------------------------------------------------------------

export interface CharacterDraft {
  // Step 1: Identity
  name: string
  gender: Gender
  ageRange: AgeRange
  roleCategory: RoleCategory

  // Step 2: Body
  bodyType: BodyType
  heightCm: number
  posture: Posture
  skinTone: string
  polish: Polish

  // Step 3: Face
  facePreset: string
  eyeColor: string
  eyeShape: string
  expression: Expression
  jawline: number   // 0–100
  lips: number      // 0–100
  browDefinition: number // 0–100

  // Step 4: Hair
  hairStyle: string
  hairColor: string
  hairShine: number // 0–100

  // Step 5: Profession
  professionId: string
  tools: string[]
  memoryEngine: MemoryEngine
  autonomy: number // 1–10
  tone: string
  systemPrompt: string
  responseStyle: 'bullets' | 'narrative' | 'mixed'

  // Step 6: Outfit
  outfitStyle: string
  outfitPrimaryColor: string
  outfitSecondaryColor: string
  accessories: string[]
  lingerieType?: 'set' | 'top' | 'bottom' | 'bodysuit' | null
  lingerieStyle?: string | null
  lingerieFabric?: string | null
  lingerieBrand?: string | null
  lingerieExtras?: string[]
  /** Per-garment persistent selections (top, bottom, set, bodysuit each remember their picks) */
  lingerieSelections?: LingerieSelectionsMap
  /** Which garment types are actively selected (multi-piece outfit) */
  lingerieActiveGarments?: LingerieGarment[]
  // NSFW fields (only when globally enabled)
  nsfwExposure?: 'suggestive' | 'clothed_revealing' | 'partial_nudity' | 'topless' | 'full_nude' | 'explicit'
  nsfwIntensity?: number     // 0–10
  nsfwPose?: 'subtle' | 'confident' | 'intimate' | 'seductive_lean' | 'lying_down' | 'back_arch' | 'kneeling' | 'over_shoulder' | 'hands_above_head'
  nsfwDominanceStyle?: 'soft' | 'balanced' | 'strong'
  nsfwFantasyTone?: 'romantic' | 'seductive' | 'dramatic'

  // Step 7: Generate
  portraitType: PortraitType
  pose: string
  background: string
  generationMode: 'studio_random' | 'studio_reference' | 'studio_faceswap'
  referenceUrl?: string
  referencePreview?: string
  realism: number     // 0–100
  detailLevel: number // 0–100
  lighting: string
}

// ---------------------------------------------------------------------------
// Default draft
// ---------------------------------------------------------------------------

export const DEFAULT_DRAFT: CharacterDraft = {
  name: '',
  gender: 'female',
  ageRange: 'adult',
  roleCategory: 'professional',

  bodyType: 'average',
  heightCm: 170,
  posture: 'upright',
  skinTone: 'light',
  polish: 'formal',

  facePreset: 'classic',
  eyeColor: 'brown',
  eyeShape: 'almond',
  expression: 'professional_smile',
  jawline: 50,
  lips: 50,
  browDefinition: 50,

  hairStyle: 'bun',
  hairColor: 'dark_brown',
  hairShine: 40,

  professionId: 'executive_secretary',
  tools: ['calendar', 'email', 'notes', 'tasks'],
  memoryEngine: 'basic',
  autonomy: 4,
  tone: 'Professional, proactive, precise',
  systemPrompt: '',
  responseStyle: 'bullets',

  outfitStyle: 'corporate_formal',
  outfitPrimaryColor: 'navy',
  outfitSecondaryColor: 'white',
  accessories: [],
  lingerieType: null,
  lingerieStyle: null,
  lingerieFabric: null,
  lingerieBrand: null,
  lingerieExtras: [],

  portraitType: 'headshot',
  pose: 'standing_professional',
  background: 'office',
  generationMode: 'studio_random',
  realism: 70,
  detailLevel: 70,
  lighting: 'soft',
}

// ---------------------------------------------------------------------------
// Step metadata
// ---------------------------------------------------------------------------

export const WIZARD_STEPS = [
  { key: 'identity',   label: 'Identity',   icon: '\uD83D\uDC64' },
  { key: 'body',       label: 'Body',       icon: '\uD83E\uDDD1' },
  { key: 'face',       label: 'Face',       icon: '\uD83D\uDE0A' },
  { key: 'hair',       label: 'Hair',       icon: '\u2702\uFE0F' },
  { key: 'profession', label: 'Profession', icon: '\uD83D\uDCBC' },
  { key: 'outfit',     label: 'Outfit',     icon: '\uD83D\uDC57' },
  { key: 'generate',   label: 'Generate',   icon: '\u2728' },
] as const

// ---------------------------------------------------------------------------
// Preset: Skin Tones
// ---------------------------------------------------------------------------

export interface PresetOption {
  id: string
  label: string
  prompt: string
  color?: string
}

export const SKIN_TONES: PresetOption[] = [
  { id: 'porcelain',    label: 'Porcelain',    prompt: 'porcelain skin',              color: '#FDEBD3' },
  { id: 'fair',         label: 'Fair',         prompt: 'fair skin',                   color: '#F5D6B8' },
  { id: 'light',        label: 'Light',        prompt: 'light skin tone',             color: '#E8C4A0' },
  { id: 'medium_light', label: 'Medium Light', prompt: 'medium light skin tone',      color: '#D4A574' },
  { id: 'medium',       label: 'Medium',       prompt: 'medium skin tone',            color: '#C08C5A' },
  { id: 'olive',        label: 'Olive',        prompt: 'olive skin tone',             color: '#A67B4B' },
  { id: 'tan',          label: 'Tan',          prompt: 'tan skin',                    color: '#8B6B3D' },
  { id: 'brown',        label: 'Brown',        prompt: 'brown skin',                  color: '#6B4E2E' },
  { id: 'dark_brown',   label: 'Dark Brown',   prompt: 'dark brown skin',             color: '#4A3520' },
  { id: 'deep',         label: 'Deep',         prompt: 'deep dark skin',              color: '#3B2812' },
]

// ---------------------------------------------------------------------------
// Preset: Eye Colors
// ---------------------------------------------------------------------------

export const EYE_COLORS: PresetOption[] = [
  { id: 'brown',       label: 'Brown',       prompt: 'brown eyes',        color: '#5C3317' },
  { id: 'dark_brown',  label: 'Dark Brown',  prompt: 'dark brown eyes',   color: '#3B1F0B' },
  { id: 'hazel',       label: 'Hazel',       prompt: 'hazel eyes',        color: '#8E7618' },
  { id: 'green',       label: 'Green',       prompt: 'green eyes',        color: '#2E8B57' },
  { id: 'blue',        label: 'Blue',        prompt: 'blue eyes',         color: '#3B7DD8' },
  { id: 'light_blue',  label: 'Light Blue',  prompt: 'light blue eyes',   color: '#87CEEB' },
  { id: 'gray',        label: 'Gray',        prompt: 'gray eyes',         color: '#808080' },
  { id: 'amber',       label: 'Amber',       prompt: 'amber eyes',        color: '#C68E17' },
]

// ---------------------------------------------------------------------------
// Preset: Eye Shapes
// ---------------------------------------------------------------------------

export const EYE_SHAPES: PresetOption[] = [
  { id: 'almond',     label: 'Almond',     prompt: 'almond-shaped eyes' },
  { id: 'round',      label: 'Round',      prompt: 'round eyes' },
  { id: 'hooded',     label: 'Hooded',     prompt: 'hooded eyes' },
  { id: 'upturned',   label: 'Upturned',   prompt: 'upturned eyes' },
  { id: 'downturned', label: 'Downturned', prompt: 'downturned eyes' },
]

// ---------------------------------------------------------------------------
// Preset: Face Presets (maps to structure + feature descriptors)
// ---------------------------------------------------------------------------

export const FACE_PRESETS: PresetOption[] = [
  { id: 'classic',  label: 'Classic',  prompt: 'oval face, balanced proportions, symmetrical features' },
  { id: 'angular',  label: 'Angular',  prompt: 'angular face, defined cheekbones, sharp jawline' },
  { id: 'round',    label: 'Round',    prompt: 'round face, soft cheeks, gentle features' },
  { id: 'heart',    label: 'Heart',    prompt: 'heart-shaped face, wide forehead, delicate chin' },
  { id: 'square',   label: 'Square',   prompt: 'square face, strong jaw, broad forehead' },
  { id: 'diamond',  label: 'Diamond',  prompt: 'diamond face, prominent cheekbones, narrow forehead' },
  { id: 'oblong',   label: 'Oblong',   prompt: 'oblong face, elongated proportions, high cheekbones' },
  { id: 'soft',     label: 'Soft',     prompt: 'soft face, gentle rounded features, smooth contours' },
]

// ---------------------------------------------------------------------------
// Preset: Hair Styles (professional-first ordering)
// ---------------------------------------------------------------------------

export const HAIR_STYLES: PresetOption[] = [
  { id: 'bun',            label: 'Professional Bun',  prompt: 'neat professional bun hairstyle' },
  { id: 'straight_long',  label: 'Straight Long',     prompt: 'long straight hair' },
  { id: 'shoulder_cut',   label: 'Shoulder Cut',      prompt: 'shoulder-length layered hair' },
  { id: 'ponytail',       label: 'Ponytail',          prompt: 'sleek ponytail' },
  { id: 'wavy_medium',    label: 'Wavy Medium',       prompt: 'medium length wavy hair' },
  { id: 'bob',            label: 'Bob',               prompt: 'modern bob haircut' },
  { id: 'pixie',          label: 'Pixie',             prompt: 'short pixie cut' },
  { id: 'side_part',      label: 'Side Part',         prompt: 'side-parted styled hair' },
  { id: 'french_twist',   label: 'French Twist',      prompt: 'elegant french twist updo' },
  { id: 'loose_waves',    label: 'Loose Waves',       prompt: 'loose flowing waves' },
  { id: 'buzz',           label: 'Buzz Cut',          prompt: 'short buzz cut' },
  { id: 'crew',           label: 'Crew Cut',          prompt: 'neat crew cut' },
]

// ---------------------------------------------------------------------------
// Preset: Hair Colors
// ---------------------------------------------------------------------------

export const HAIR_COLORS: PresetOption[] = [
  { id: 'black',            label: 'Black',            prompt: 'black hair',            color: '#1a1a1a' },
  { id: 'dark_brown',       label: 'Dark Brown',       prompt: 'dark brown hair',       color: '#3b2010' },
  { id: 'medium_brown',     label: 'Medium Brown',     prompt: 'medium brown hair',     color: '#6b4226' },
  { id: 'light_brown',      label: 'Light Brown',      prompt: 'light brown hair',      color: '#a0724a' },
  { id: 'auburn',           label: 'Auburn',           prompt: 'auburn hair',           color: '#8b3a2a' },
  { id: 'red',              label: 'Red',              prompt: 'red hair',              color: '#c0392b' },
  { id: 'strawberry_blonde',label: 'Strawberry Blonde',prompt: 'strawberry blonde hair',color: '#d4a768' },
  { id: 'blonde',           label: 'Blonde',           prompt: 'blonde hair',           color: '#e8c870' },
  { id: 'platinum',         label: 'Platinum',         prompt: 'platinum blonde hair',  color: '#e8e0d0' },
  { id: 'gray',             label: 'Gray',             prompt: 'gray hair',             color: '#a0a0a0' },
  { id: 'white',            label: 'White',            prompt: 'white hair',            color: '#e8e4e0' },
]

// ---------------------------------------------------------------------------
// Preset: Outfit Styles (SFW)
// ---------------------------------------------------------------------------

export const OUTFIT_STYLES_SFW: PresetOption[] = [
  { id: 'corporate_formal',  label: 'Corporate Formal',  prompt: 'wearing formal corporate business suit, tailored, professional' },
  { id: 'business_casual',   label: 'Business Casual',   prompt: 'wearing business casual attire, smart and comfortable' },
  { id: 'executive_elegant', label: 'Executive Elegant', prompt: 'wearing elegant executive outfit, refined, luxurious fabric' },
  { id: 'smart_casual',      label: 'Smart Casual',      prompt: 'wearing smart casual outfit, modern, stylish yet relaxed' },
  { id: 'secretary_chic',    label: 'Secretary Chic',    prompt: 'wearing fitted blouse with top button open, short mini skirt, delicate necklace, light stockings, smart heels, polished secretary look, attractive yet professional' },
  { id: 'modern_minimal',    label: 'Modern Minimal',    prompt: 'wearing clean white halter crop top, short mini skirt, minimal jewelry, body-conscious fit, modern editorial fashion' },
]

// ---------------------------------------------------------------------------
// Preset: Outfit Styles (NSFW — gated)
// ---------------------------------------------------------------------------

export const OUTFIT_STYLES_NSFW: PresetOption[] = [
  // Office-to-intimate gradient (pairs with Modern Chic / Secretary Chic)
  { id: 'office_after_hours', label: 'Office After Hours', prompt: 'wearing unbuttoned blouse showing lace bra underneath, mini skirt hiked up, stockings with garter belt visible, after-hours intimate mood' },
  { id: 'secretary_intimate', label: 'Secretary Intimate', prompt: 'wearing open shirt falling off one shoulder, lace camisole visible, mini skirt, stockings, disheveled secretary look, seductive inviting expression' },
  // Suggestive tier
  { id: 'lingerie',         label: 'Lingerie',          prompt: 'wearing delicate lace lingerie, sheer fabric, intimate, sensual pose' },
  { id: 'swimwear',         label: 'Swimwear',          prompt: 'wearing fashionable swimwear, toned body, confident pose, beach setting' },
  { id: 'cocktail',         label: 'Cocktail',          prompt: 'wearing revealing cocktail dress, deep neckline, glamorous, alluring' },
  { id: 'boudoir_wear',     label: 'Boudoir',           prompt: 'wearing elegant boudoir attire, silk robe, intimate bedroom setting, soft lighting' },
  // Explicit tier
  { id: 'sheer_bodysuit',   label: 'Sheer Bodysuit',    prompt: 'wearing sheer mesh bodysuit, see-through fabric, provocative, nude undertones visible' },
  { id: 'topless',          label: 'Topless',           prompt: 'topless, bare chest, artistic nude, tasteful lighting, confident pose' },
  { id: 'nude_artistic',    label: 'Artistic Nude',     prompt: 'fully nude, artistic nude photography, elegant pose, studio lighting, fine art' },
  { id: 'fantasy_explicit', label: 'Fantasy Explicit',  prompt: 'wearing exotic fantasy costume, barely-there outfit, daring, mystical, exposed skin' },
  { id: 'latex_fetish',     label: 'Latex & Fetish',    prompt: 'wearing glossy latex outfit, fetish wear, dominant pose, dramatic lighting' },
  { id: 'bedroom_nude',     label: 'Bedroom Nude',      prompt: 'nude in bed, silk sheets, intimate bedroom setting, warm ambient light, sensual pose' },
]

// ---------------------------------------------------------------------------
// Lingerie Builder — additive sub-options (only when lingerie/boudoir selected)
// ---------------------------------------------------------------------------

export type LingerieGarment = 'set' | 'top' | 'bottom' | 'bodysuit'

/** Per-garment lingerie selections — persists choices when switching between garment types */
export interface LingerieGarmentSelection {
  style?: string | null
  fabric?: string | null
  brand?: string | null
}

export type LingerieSelectionsMap = Partial<Record<LingerieGarment, LingerieGarmentSelection>>

export const LINGERIE_GARMENTS: Array<{ id: LingerieGarment; label: string; icon: string; prompt: string }> = [
  { id: 'set',      label: 'Matching Set', icon: '\uD83E\uDE71', prompt: 'matching lingerie set, coordinated bra and panty' },
  { id: 'top',      label: 'Top',          icon: '\uD83D\uDC59', prompt: 'lingerie top piece' },
  { id: 'bottom',   label: 'Bottom',       icon: '\uD83E\uDE72', prompt: 'lingerie bottom piece' },
  { id: 'bodysuit', label: 'Bodysuit',     icon: '\uD83E\uDE71', prompt: 'one-piece bodysuit lingerie' },
]

/** Sub-styles per garment type — shown only when that garment is selected */
export const LINGERIE_STYLES: Record<LingerieGarment, Array<{ id: string; label: string; prompt: string }>> = {
  bottom: [
    { id: 'thong',      label: 'Thong',      prompt: 'thong panty, minimal rear coverage' },
    { id: 'brazilian',  label: 'Brazilian',  prompt: 'brazilian cut panty, moderate rear coverage' },
    { id: 'italian',    label: 'Italian',    prompt: 'italian brief, elegant cut' },
    { id: 'cheeky',     label: 'Cheeky',     prompt: 'cheeky panty, playful cut' },
    { id: 'hipster',    label: 'Hipster',    prompt: 'hipster panty, low-rise wide sides' },
    { id: 'boyshort',   label: 'Boyshort',   prompt: 'boyshort panty, full coverage shorts style' },
    { id: 'high_waist', label: 'High-Waist', prompt: 'high-waist panty, retro vintage style' },
    { id: 'perizoma',   label: 'Perizoma',   prompt: 'perizoma string, ultra-minimal' },
  ],
  top: [
    { id: 'bralette',   label: 'Bralette',   prompt: 'soft bralette, unlined wireless' },
    { id: 'balconette', label: 'Balconette', prompt: 'balconette bra, half-cup low neckline' },
    { id: 'push_up',    label: 'Push-up',    prompt: 'push-up bra, enhanced cleavage' },
    { id: 'triangle',   label: 'Triangle',   prompt: 'triangle bra, minimal wire-free' },
  ],
  set: [
    { id: 'romantic', label: 'Romantic', prompt: 'romantic lace lingerie set, delicate feminine details' },
    { id: 'minimal',  label: 'Minimal',  prompt: 'minimal clean lingerie set, simple elegant lines' },
    { id: 'luxury',   label: 'Luxury',   prompt: 'luxury lingerie set, premium embroidered details' },
    { id: 'bridal',   label: 'Bridal',   prompt: 'bridal lingerie set, white lace with satin accents' },
  ],
  bodysuit: [
    { id: 'lace_body',    label: 'Lace',    prompt: 'lace bodysuit, allover lace pattern' },
    { id: 'mesh_body',    label: 'Mesh',    prompt: 'mesh bodysuit, sheer stretch fabric' },
    { id: 'sheer_body',   label: 'Sheer',   prompt: 'sheer bodysuit, see-through minimal' },
    { id: 'minimal_body', label: 'Minimal', prompt: 'minimal bodysuit, clean seamless design' },
  ],
}

export const LINGERIE_FABRICS: Array<{ id: string; label: string; prompt: string }> = [
  { id: 'lace',   label: 'Lace',   prompt: 'lace fabric, intricate floral pattern' },
  { id: 'satin',  label: 'Satin',  prompt: 'satin fabric, smooth glossy sheen' },
  { id: 'mesh',   label: 'Mesh',   prompt: 'sheer mesh fabric, semi-transparent' },
  { id: 'cotton', label: 'Cotton', prompt: 'soft cotton fabric, comfortable natural' },
  { id: 'silk',   label: 'Silk',   prompt: 'pure silk fabric, luxurious drape' },
]

export const LINGERIE_BRANDS: Array<{ id: string; label: string; prompt: string }> = [
  { id: 'intimissimi', label: 'Intimissimi', prompt: 'inspired by Intimissimi Italian lingerie style' },
  { id: 'victoria',    label: "Victoria's Secret", prompt: "inspired by Victoria's Secret glamorous style" },
  { id: 'laperla',     label: 'La Perla',    prompt: 'inspired by La Perla luxury haute couture lingerie' },
]

export const LINGERIE_EXTRAS: Array<{ id: string; label: string; icon: string; prompt: string }> = [
  { id: 'stockings', label: 'Stockings', icon: '\uD83E\uDE73', prompt: 'wearing sheer thigh-high stockings' },
  { id: 'garters',   label: 'Garters',   icon: '\uD83D\uDC5F', prompt: 'wearing lace garter belt with straps' },
  { id: 'choker',    label: 'Choker',     icon: '\u2728',       prompt: 'wearing delicate choker necklace' },
]

// ---------------------------------------------------------------------------
// Preset: NSFW Poses (only when Spice Mode enabled)
// ---------------------------------------------------------------------------

export const NSFW_POSES: PresetOption[] = [
  { id: 'seductive_lean',     label: 'Seductive Lean',     prompt: 'leaning forward seductively, alluring gaze, inviting pose' },
  { id: 'lying_down',         label: 'Lying Down',         prompt: 'lying down on bed, relaxed sensual pose, looking at camera' },
  { id: 'back_arch',          label: 'Arched Back',        prompt: 'arched back, accentuated curves, confident sensual pose' },
  { id: 'kneeling',           label: 'Kneeling',           prompt: 'kneeling pose, intimate angle, seductive expression' },
  { id: 'over_shoulder',      label: 'Over Shoulder',      prompt: 'looking over bare shoulder, teasing, coy expression, partial back view' },
  { id: 'hands_above_head',   label: 'Arms Up',            prompt: 'arms raised above head, elongated body, confident display' },
]

// ---------------------------------------------------------------------------
// Preset: NSFW Backgrounds (only when Spice Mode enabled)
// ---------------------------------------------------------------------------

export const NSFW_BACKGROUNDS: PresetOption[] = [
  { id: 'luxury_bedroom',     label: 'Luxury Bedroom',     prompt: 'luxury bedroom, silk sheets, warm candlelight, intimate ambiance' },
  { id: 'penthouse_suite',    label: 'Penthouse Suite',     prompt: 'penthouse hotel suite, panoramic city view, mood lighting' },
  { id: 'bathtub_spa',        label: 'Bathtub / Spa',      prompt: 'elegant bathtub, steam, rose petals, spa setting, warm glow' },
  { id: 'pool_side',          label: 'Poolside',           prompt: 'luxurious poolside, tropical setting, golden hour sunlight' },
  { id: 'dark_studio',        label: 'Dark Studio',        prompt: 'dark studio backdrop, dramatic rim lighting, artistic noir' },
  { id: 'mirror_room',        label: 'Mirror Room',        prompt: 'room with mirrors, multiple reflections, glamorous, moody lighting' },
]

// ---------------------------------------------------------------------------
// Preset: Colors (shared palette for outfit primary/secondary)
// ---------------------------------------------------------------------------

export const COLOR_PALETTE: PresetOption[] = [
  { id: 'navy',       label: 'Navy',        prompt: 'navy blue',       color: '#1B2A4A' },
  { id: 'black',      label: 'Black',       prompt: 'black',           color: '#1a1a1a' },
  { id: 'white',      label: 'White',       prompt: 'white',           color: '#f5f5f5' },
  { id: 'charcoal',   label: 'Charcoal',    prompt: 'charcoal gray',   color: '#36454F' },
  { id: 'burgundy',   label: 'Burgundy',    prompt: 'burgundy',        color: '#6F1E38' },
  { id: 'ivory',      label: 'Ivory',       prompt: 'ivory',           color: '#FFFFF0' },
  { id: 'forest',     label: 'Forest',      prompt: 'forest green',    color: '#228B22' },
  { id: 'royal_blue', label: 'Royal Blue',  prompt: 'royal blue',      color: '#2B4FA3' },
  { id: 'blush',      label: 'Blush',       prompt: 'blush pink',      color: '#DE5D83' },
  { id: 'gold',       label: 'Gold',        prompt: 'gold',            color: '#CFB53B' },
  { id: 'crimson',    label: 'Crimson',     prompt: 'crimson red',     color: '#DC143C' },
  { id: 'teal',       label: 'Teal',        prompt: 'teal',            color: '#008080' },
]

// ---------------------------------------------------------------------------
// Preset: Accessories
// ---------------------------------------------------------------------------

export const ACCESSORIES: PresetOption[] = [
  { id: 'glasses',   label: 'Glasses',   prompt: 'wearing stylish glasses' },
  { id: 'necklace',  label: 'Necklace',  prompt: 'wearing an elegant necklace' },
  { id: 'watch',     label: 'Watch',     prompt: 'wearing a luxury watch' },
  { id: 'earrings',  label: 'Earrings',  prompt: 'wearing earrings' },
  { id: 'folder',    label: 'Folder',    prompt: 'holding a leather folder' },
  { id: 'badge',     label: 'ID Badge',  prompt: 'wearing a corporate ID badge' },
  { id: 'scarf',     label: 'Scarf',     prompt: 'wearing a stylish scarf' },
  { id: 'hat',       label: 'Hat',       prompt: 'wearing a fashionable hat' },
]

// ---------------------------------------------------------------------------
// Preset: Poses
// ---------------------------------------------------------------------------

export const POSES: PresetOption[] = [
  { id: 'standing_professional', label: 'Standing Professional', prompt: 'standing professionally, confident posture' },
  { id: 'seated_desk',          label: 'Seated at Desk',        prompt: 'seated at a desk, working' },
  { id: 'walking',              label: 'Walking',               prompt: 'walking confidently' },
  { id: 'presentation',         label: 'Presentation',          prompt: 'giving a presentation, gesturing' },
  { id: 'casual_lean',          label: 'Casual Lean',           prompt: 'leaning casually, relaxed pose' },
  { id: 'arms_crossed',         label: 'Arms Crossed',          prompt: 'arms crossed, confident stance' },
]

// ---------------------------------------------------------------------------
// Preset: Backgrounds
// ---------------------------------------------------------------------------

export const BACKGROUNDS: PresetOption[] = [
  { id: 'office',          label: 'Office',          prompt: 'modern office background, clean interior' },
  { id: 'neutral_studio',  label: 'Studio',          prompt: 'neutral studio background, gradient backdrop' },
  { id: 'library',         label: 'Library',         prompt: 'elegant library background, bookshelves' },
  { id: 'modern_workspace',label: 'Workspace',       prompt: 'modern co-working space background' },
  { id: 'outdoor_city',    label: 'City',            prompt: 'outdoor urban city backdrop, bokeh' },
  { id: 'home_cozy',       label: 'Home',            prompt: 'cozy home interior, warm ambient light' },
]

// ---------------------------------------------------------------------------
// Preset: Lighting
// ---------------------------------------------------------------------------

export const LIGHTING_OPTIONS: PresetOption[] = [
  { id: 'soft',      label: 'Soft',      prompt: 'soft diffused lighting, gentle shadows' },
  { id: 'bright',    label: 'Bright',    prompt: 'bright even lighting, clean illumination' },
  { id: 'dramatic',  label: 'Dramatic',  prompt: 'dramatic lighting, strong shadows, moody' },
  { id: 'natural',   label: 'Natural',   prompt: 'natural window lighting, golden hour' },
  { id: 'studio',    label: 'Studio',    prompt: 'professional studio lighting, three-point setup' },
]

// ---------------------------------------------------------------------------
// Preset: Expressions
// ---------------------------------------------------------------------------

export const EXPRESSIONS: PresetOption[] = [
  { id: 'neutral',             label: 'Neutral',             prompt: 'neutral expression' },
  { id: 'professional_smile',  label: 'Professional Smile',  prompt: 'warm professional smile' },
  { id: 'serious',             label: 'Serious',             prompt: 'serious focused expression' },
  { id: 'warm',                label: 'Warm',                prompt: 'warm friendly expression' },
  { id: 'playful',             label: 'Playful',             prompt: 'playful flirtatious expression' },
]

// ---------------------------------------------------------------------------
// Helpers: find preset by ID
// ---------------------------------------------------------------------------

export function findPreset(list: PresetOption[], id: string): PresetOption | undefined {
  return list.find((p) => p.id === id)
}
