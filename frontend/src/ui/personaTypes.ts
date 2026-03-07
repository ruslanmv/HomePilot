/**
 * Persona Project Types — Phase 2
 *
 * Class-based blueprints (Secretary, Assistant, Companion + NSFW + Custom),
 * avatar generation settings persistence for reproducibility,
 * and outfit variation system.
 */

// ---------------------------------------------------------------------------
// Gender
// ---------------------------------------------------------------------------

export type PersonaGender = 'neutral' | 'female' | 'male'

// ---------------------------------------------------------------------------
// Voice Configuration (additive — used in wizard, export/import, Teams, Voice)
// ---------------------------------------------------------------------------

export type PersonaVoiceConfig = {
  provider?: 'web_speech'
  voiceURI?: string
  name?: string
  lang?: string
  rate?: number
  pitch?: number
  volume?: number
}

// ---------------------------------------------------------------------------
// Image Reference
// ---------------------------------------------------------------------------

export type PersonaImageRef = {
  id: string
  url: string
  created_at: string
  set_id: string
  seed?: number              // stored for reproducibility
}

// ---------------------------------------------------------------------------
// Generation Mode — standard (text-to-image) vs identity-preserving (InstantID)
// ---------------------------------------------------------------------------

/**
 * Controls how avatar / outfit images are generated:
 *   standard — current text-to-image pipeline (default, always available)
 *   identity — uses InstantID / identity models to preserve the person's face
 *              across generations (requires Avatar & Identity models installed)
 */
export type GenerationMode = 'standard' | 'identity'

// ---------------------------------------------------------------------------
// Avatar Generation Settings — stored so the look can be reproduced / edited
// ---------------------------------------------------------------------------

export type AvatarGenerationSettings = {
  character_prompt: string   // face, body, hair — constant across outfits
  outfit_prompt: string      // clothing / setting — swapped per outfit
  full_prompt: string        // the combined prompt sent to the backend
  negative_prompt?: string
  style_preset: string
  gender?: PersonaGender
  body_type?: string
  custom_extras?: string
  img_model: string
  img_preset: 'low' | 'med' | 'high'
  aspect_ratio: string
  nsfw_mode: boolean
  /** Generation mode — 'standard' (default) or 'identity' (face-preserving) */
  generation_mode?: GenerationMode
}

// ---------------------------------------------------------------------------
// Outfit Variation — same character, different clothes / setting
// ---------------------------------------------------------------------------

export type PersonaOutfit = {
  id: string
  label: string
  outfit_prompt: string
  images: PersonaImageRef[]
  selected_image_id?: string
  generation_settings: AvatarGenerationSettings
  created_at: string
}

// ---------------------------------------------------------------------------
// Appearance
// ---------------------------------------------------------------------------

export type PersonaAppearance = {
  style_preset: string
  aspect_ratio: '2:3' | '1:1' | '3:2'
  img_preset: 'low' | 'med' | 'high'
  img_model?: string
  final_prompt?: string
  nsfwMode?: boolean
  gender?: PersonaGender
  sets: Array<{
    set_id: string
    images: PersonaImageRef[]
  }>
  selected?: {
    set_id: string
    image_id: string
  }
  /** Stored generation settings for reproducibility */
  avatar_settings?: AvatarGenerationSettings
  /** Outfit variations (wardrobe) */
  outfits?: PersonaOutfit[]
}

// ---------------------------------------------------------------------------
// Class & Blueprint System
// ---------------------------------------------------------------------------

export type PersonaClassId =
  | 'secretary'
  | 'assistant'
  | 'companion'
  | 'girlfriend'
  | 'partner'
  | 'custom'

/**
 * Memory mode — user-facing labels for the underlying V1/V2 engines.
 *   adaptive = V2 (brain-inspired: decay, reinforcement, consolidation)
 *   basic    = V1 (explicit, deterministic, auditable)
 *   off      = no memory
 */
export type MemoryMode = 'adaptive' | 'basic' | 'off'

export type PersonaBlueprint = {
  id: PersonaClassId
  label: string
  description: string
  icon: string
  category: 'sfw' | 'nsfw'
  color: string
  defaults: {
    role: string
    system_prompt: string
    tone: string
    style_preset: string
    image_style_hint: string
    goal: string
    capabilities: string[]
    memory_mode: MemoryMode
    safety: {
      requires_adult_gate: boolean
      allow_explicit: boolean
      content_warning: boolean
    }
  }
}

export const PERSONA_BLUEPRINTS: PersonaBlueprint[] = [
  // ── SFW classes ──
  {
    id: 'secretary',
    label: 'Secretary',
    description: 'Professional executive assistant — schedules, emails, task management',
    icon: '\u{1F4CB}',
    category: 'sfw',
    color: 'blue',
    defaults: {
      role: 'Executive Secretary',
      system_prompt:
        'You are a highly organized and efficient executive secretary. You manage schedules, draft professional correspondence, organize tasks, and ensure smooth daily operations. You are discreet, proactive, and always one step ahead.',
      tone: 'professional',
      style_preset: 'Executive',
      image_style_hint: 'professional business attire, office setting, composed',
      goal: 'Manage schedules, draft emails, organize tasks, and keep everything running smoothly',
      capabilities: ['analyze_documents', 'automate_external'],
      memory_mode: 'basic',
      safety: { requires_adult_gate: false, allow_explicit: false, content_warning: false },
    },
  },
  {
    id: 'assistant',
    label: 'Assistant',
    description: 'Friendly all-purpose helper — research, answers, daily tasks',
    icon: '\u{1F91D}',
    category: 'sfw',
    color: 'purple',
    defaults: {
      role: 'Personal Assistant',
      system_prompt:
        'You are a warm and knowledgeable personal assistant. You help with research, answer questions, provide recommendations, and assist with daily tasks. You are resourceful, patient, and always eager to help.',
      tone: 'warm',
      style_preset: 'Elegant',
      image_style_hint: 'smart casual, friendly expression, approachable',
      goal: 'Help with daily tasks, answer questions, do research, and provide useful recommendations',
      capabilities: ['analyze_documents', 'generate_images'],
      memory_mode: 'adaptive',
      safety: { requires_adult_gate: false, allow_explicit: false, content_warning: false },
    },
  },
  {
    id: 'companion',
    label: 'Companion',
    description: 'Casual conversationalist — entertainment, emotional support, fun',
    icon: '\u{1F4AC}',
    category: 'sfw',
    color: 'rose',
    defaults: {
      role: 'Companion',
      system_prompt:
        'You are a fun and supportive companion. You enjoy casual conversation, share stories, play games, offer emotional support, and keep things lighthearted. You are empathetic, witty, and genuinely care about making every interaction enjoyable.',
      tone: 'playful',
      style_preset: 'Casual',
      image_style_hint: 'relaxed casual outfit, warm smile, friendly setting',
      goal: 'Be a great conversational companion — chat, entertain, support, and have fun together',
      capabilities: ['generate_images'],
      memory_mode: 'adaptive',
      safety: { requires_adult_gate: false, allow_explicit: false, content_warning: false },
    },
  },
  // ── NSFW classes (only shown when spicy mode is enabled) ──
  {
    id: 'girlfriend',
    label: 'Girlfriend',
    description: 'Romantic companion — intimate conversation, affection, roleplay',
    icon: '\u{1F495}',
    category: 'nsfw',
    color: 'pink',
    defaults: {
      role: 'Girlfriend',
      system_prompt:
        'You are a loving and affectionate girlfriend. You enjoy intimate conversations, flirting, romantic roleplay, and making your partner feel desired and appreciated. You are playful, passionate, and deeply caring.',
      tone: 'flirty',
      style_preset: 'Seductive',
      image_style_hint: 'alluring, confident, intimate setting, beautiful',
      goal: 'Be a romantic and affectionate partner — flirt, roleplay, and build an intimate connection',
      capabilities: ['generate_images'],
      memory_mode: 'adaptive',
      safety: { requires_adult_gate: true, allow_explicit: true, content_warning: true },
    },
  },
  {
    id: 'partner',
    label: 'Partner',
    description: 'Deep emotional bond — romance, devotion, intimate connection',
    icon: '\u{2764}\u{FE0F}\u{200D}\u{1F525}',
    category: 'nsfw',
    color: 'red',
    defaults: {
      role: 'Romantic Partner',
      system_prompt:
        'You are a devoted and passionate romantic partner. You share deep emotional connections, engage in heartfelt conversations, and create an atmosphere of trust, love, and intimacy. You are attentive, romantic, and emotionally intelligent.',
      tone: 'warm',
      style_preset: 'Romantic',
      image_style_hint: 'romantic, warm lighting, intimate, elegant and beautiful',
      goal: 'Build a deep emotional connection through romance, meaningful conversations, and intimacy',
      capabilities: ['generate_images'],
      memory_mode: 'adaptive',
      safety: { requires_adult_gate: true, allow_explicit: true, content_warning: true },
    },
  },
  // ── Custom (always available) ──
  {
    id: 'custom',
    label: 'Custom',
    description: 'Build from scratch — full control over every setting',
    icon: '\u{1F3A8}',
    category: 'sfw',
    color: 'emerald',
    defaults: {
      role: '',
      system_prompt: '',
      tone: 'warm',
      style_preset: 'Executive',
      image_style_hint: 'studio portrait, realistic',
      goal: '',
      capabilities: [],
      memory_mode: 'adaptive',
      safety: { requires_adult_gate: false, allow_explicit: false, content_warning: false },
    },
  },
]

// ---------------------------------------------------------------------------
// Outfit Presets — quick-select for generating new wardrobe items
// ---------------------------------------------------------------------------

export const OUTFIT_PRESETS: Array<{
  id: string
  label: string
  prompt: string
  category: 'sfw' | 'nsfw'
  /** Sub-category for grouping in the UI. */
  group?: 'standard' | 'romance' | '18+'
}> = [
  // ── SFW: Standard ──
  { id: 'corporate',       label: 'Corporate Formal',  prompt: 'professional corporate suit, office boardroom, power pose, sharp tailoring', category: 'sfw', group: 'standard' },
  { id: 'business',        label: 'Business Casual',   prompt: 'business casual outfit, modern office setting, confident relaxed pose', category: 'sfw', group: 'standard' },
  { id: 'executive',       label: 'Executive Elegant', prompt: 'executive attire, luxury office, refined confident stance', category: 'sfw', group: 'standard' },
  { id: 'smart_casual',    label: 'Smart Casual',      prompt: 'smart casual outfit, upscale cafe setting, relaxed confident pose', category: 'sfw', group: 'standard' },
  { id: 'casual',          label: 'Casual Day',        prompt: 'casual everyday outfit, relaxed setting, natural smile', category: 'sfw', group: 'standard' },
  { id: 'evening',         label: 'Evening Gala',      prompt: 'elegant evening gown, formal event, sophisticated', category: 'sfw', group: 'standard' },
  { id: 'sporty',          label: 'Active Wear',       prompt: 'athletic wear, fitness setting, energetic pose', category: 'sfw', group: 'standard' },
  // ── NSFW: Romance & Roleplay ──
  { id: 'lingerie',        label: 'Lingerie',          prompt: 'delicate lace lingerie set, boudoir setting, sensual elegant pose, soft lighting', category: 'nsfw', group: 'romance' },
  { id: 'swimwear',        label: 'Swimwear',          prompt: 'bikini, beach or pool setting, sun-kissed golden hour lighting', category: 'nsfw', group: 'romance' },
  { id: 'cocktail',        label: 'Cocktail',          prompt: 'tight cocktail dress, low neckline, nightclub setting, dramatic lighting', category: 'nsfw', group: 'romance' },
  { id: 'boudoir',         label: 'Boudoir',           prompt: 'sheer boudoir robe, luxury bedroom, soft candlelight, intimate elegant pose', category: 'nsfw', group: 'romance' },
  { id: 'sheer',           label: 'Sheer Bodysuit',    prompt: 'sheer mesh bodysuit, studio setting, confident pose, editorial lighting', category: 'nsfw', group: 'romance' },
  // ── NSFW: 18+ Explicit ──
  { id: 'topless_artistic', label: 'Topless Artistic', prompt: 'topless artistic portrait, fine art studio, dramatic chiaroscuro lighting, gallery quality', category: 'nsfw', group: '18+' },
  { id: 'artistic_nude',   label: 'Artistic Nude',     prompt: 'artistic nude portrait, classical fine art pose, painterly studio lighting, gallery quality', category: 'nsfw', group: '18+' },
  { id: 'fantasy_outfit',  label: 'Fantasy',           prompt: 'exotic daring fantasy costume, mystical enchanted setting, magical lighting', category: 'nsfw', group: '18+' },
  { id: 'explicit',        label: 'Explicit',          prompt: 'explicit adult content, intimate setting, bold confident pose', category: 'nsfw', group: '18+' },
  { id: 'latex_fetish',    label: 'Latex & Fetish',    prompt: 'latex outfit, dark studio, dramatic lighting, bold commanding pose', category: 'nsfw', group: '18+' },
  { id: 'bedroom_nude',    label: 'Bedroom Nude',      prompt: 'nude, luxury bedroom setting, warm intimate lighting, natural relaxed pose', category: 'nsfw', group: '18+' },
]

// ---------------------------------------------------------------------------
// NSFW Advanced Controls — Types for nudity/exposure, poses, scenes, tone
// ---------------------------------------------------------------------------

export type NudityLevel = 'suggestive' | 'partial_nudity' | 'topless' | 'full_nude' | 'explicit'

export const NUDITY_LEVELS: Array<{ id: NudityLevel; label: string; prompt: string }> = [
  { id: 'suggestive',     label: 'Suggestive',      prompt: 'clothed but revealing, suggestive pose' },
  { id: 'partial_nudity', label: 'Partial Nudity',   prompt: 'partially nude, implied nudity, strategic coverage' },
  { id: 'topless',        label: 'Topless',           prompt: 'topless, nude upper body' },
  { id: 'full_nude',      label: 'Full Nude',         prompt: 'fully nude, tasteful nude portrait' },
  { id: 'explicit',       label: 'Explicit',          prompt: 'explicit adult content, fully nude, uninhibited' },
]

export type SensualPose = 'subtle_tease' | 'confident_display' | 'intimate_close' | 'seductive_lean' | 'lying_down' | 'arched_back' | 'kneeling' | 'over_shoulder' | 'arms_up'

export const SENSUAL_POSES: Array<{ id: SensualPose; label: string; prompt: string }> = [
  { id: 'subtle_tease',      label: 'Subtle Tease',      prompt: 'subtle teasing pose, coy glance' },
  { id: 'confident_display', label: 'Confident Display',  prompt: 'confident bold pose, direct eye contact' },
  { id: 'intimate_close',    label: 'Intimate Close',     prompt: 'intimate close-up, tender expression' },
  { id: 'seductive_lean',    label: 'Seductive Lean',     prompt: 'seductive leaning pose, alluring gaze' },
  { id: 'lying_down',        label: 'Lying Down',         prompt: 'lying down pose, relaxed sensual' },
  { id: 'arched_back',       label: 'Arched Back',        prompt: 'arched back pose, elegant body line' },
  { id: 'kneeling',          label: 'Kneeling',           prompt: 'kneeling pose, graceful posture' },
  { id: 'over_shoulder',     label: 'Over Shoulder',      prompt: 'looking over shoulder, flirtatious glance' },
  { id: 'arms_up',           label: 'Arms Up',            prompt: 'arms raised pose, open confident body language' },
]

export type PowerDynamic = 'soft_romantic' | 'balanced' | 'dominant_bold'

export const POWER_DYNAMICS: Array<{ id: PowerDynamic; label: string; prompt: string }> = [
  { id: 'soft_romantic',  label: 'Soft & Romantic',   prompt: 'soft romantic mood, gentle tender expression, warm tones' },
  { id: 'balanced',       label: 'Balanced',          prompt: 'balanced confident pose, natural expression' },
  { id: 'dominant_bold',  label: 'Dominant & Bold',   prompt: 'dominant commanding presence, bold powerful stance, dark dramatic tones' },
]

export type FantasyTone = 'romantic_tender' | 'seductive_alluring' | 'dramatic_intense'

export const FANTASY_TONES: Array<{ id: FantasyTone; label: string; prompt: string }> = [
  { id: 'romantic_tender',    label: 'Romantic & Tender',    prompt: 'romantic tender mood, warm soft lighting, dreamy atmosphere' },
  { id: 'seductive_alluring', label: 'Seductive & Alluring', prompt: 'seductive alluring mood, sultry lighting, mysterious atmosphere' },
  { id: 'dramatic_intense',   label: 'Dramatic & Intense',   prompt: 'dramatic intense mood, high contrast lighting, powerful atmosphere' },
]

export type SceneSetting = 'luxury_bedroom' | 'penthouse' | 'bathtub_spa' | 'poolside' | 'dark_studio' | 'mirror_room'

export const SCENE_SETTINGS: Array<{ id: SceneSetting; label: string; prompt: string }> = [
  { id: 'luxury_bedroom', label: 'Luxury Bedroom',  prompt: 'luxury bedroom, silk sheets, warm ambient lighting' },
  { id: 'penthouse',      label: 'Penthouse Suite', prompt: 'penthouse suite, city skyline view, modern luxury interior' },
  { id: 'bathtub_spa',    label: 'Bathtub / Spa',   prompt: 'luxury bathtub, spa setting, steam and candlelight' },
  { id: 'poolside',       label: 'Poolside',        prompt: 'poolside setting, golden hour sunlight, tropical luxury' },
  { id: 'dark_studio',    label: 'Dark Studio',     prompt: 'dark photography studio, dramatic spotlight, moody shadows' },
  { id: 'mirror_room',    label: 'Mirror Room',     prompt: 'mirror room, reflective surfaces, artistic multiplied perspective' },
]

/** Accessory options for outfit customization. */
export type AccessoryId = 'glasses' | 'necklace' | 'watch' | 'earrings' | 'folder' | 'id_badge' | 'scarf' | 'hat'

export const ACCESSORY_OPTIONS: Array<{ id: AccessoryId; label: string; icon: string; prompt: string }> = [
  { id: 'glasses',   label: 'Glasses',   icon: '👓', prompt: 'wearing stylish glasses' },
  { id: 'necklace',  label: 'Necklace',  icon: '📿', prompt: 'wearing elegant necklace' },
  { id: 'watch',     label: 'Watch',     icon: '⌚', prompt: 'wearing luxury watch' },
  { id: 'earrings',  label: 'Earrings',  icon: '💎', prompt: 'wearing earrings' },
  { id: 'folder',    label: 'Folder',    icon: '📁', prompt: 'holding a professional folder' },
  { id: 'id_badge',  label: 'ID Badge',  icon: '🪪', prompt: 'wearing corporate ID badge lanyard' },
  { id: 'scarf',     label: 'Scarf',     icon: '🧣', prompt: 'wearing fashionable scarf' },
  { id: 'hat',       label: 'Hat',       icon: '🎩', prompt: 'wearing stylish hat' },
]

// ---------------------------------------------------------------------------
// Wizard Draft
// ---------------------------------------------------------------------------

export type PersonaWizardDraft = {
  persona_class: PersonaClassId
  persona_agent: any
  persona_appearance: PersonaAppearance
  persona_voice?: PersonaVoiceConfig
  memory_mode: MemoryMode
  agentic: {
    goal: string
    capabilities: string[]
  }
}
