/**
 * Persona Project Types — Phase 2
 *
 * Class-based blueprints (Secretary, Assistant, Companion + NSFW + Custom),
 * avatar generation settings persistence for reproducibility,
 * and outfit variation system.
 */

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
// Avatar Generation Settings — stored so the look can be reproduced / edited
// ---------------------------------------------------------------------------

export type AvatarGenerationSettings = {
  character_prompt: string   // face, body, hair — constant across outfits
  outfit_prompt: string      // clothing / setting — swapped per outfit
  full_prompt: string        // the combined prompt sent to the backend
  negative_prompt?: string
  style_preset: string
  body_type?: string
  custom_extras?: string
  img_model: string
  img_preset: 'low' | 'med' | 'high'
  aspect_ratio: string
  nsfw_mode: boolean
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
}> = [
  // SFW
  { id: 'business', label: 'Business Meeting', prompt: 'professional business suit, office setting, confident pose', category: 'sfw' },
  { id: 'casual', label: 'Casual Day', prompt: 'casual everyday outfit, relaxed setting, natural smile', category: 'sfw' },
  { id: 'evening', label: 'Evening Gala', prompt: 'elegant evening gown, formal event, sophisticated', category: 'sfw' },
  { id: 'sporty', label: 'Active Wear', prompt: 'athletic wear, fitness setting, energetic pose', category: 'sfw' },
  // NSFW
  { id: 'lingerie', label: 'Lingerie', prompt: 'lace lingerie set, boudoir setting, sensual pose', category: 'nsfw' },
  { id: 'swimwear', label: 'Swimwear', prompt: 'bikini, beach or pool setting, sun-kissed', category: 'nsfw' },
  { id: 'cocktail', label: 'Cocktail Night', prompt: 'tight cocktail dress, low neckline, nightclub setting', category: 'nsfw' },
  { id: 'fantasy_outfit', label: 'Fantasy', prompt: 'fantasy costume, exotic and daring, mystical setting', category: 'nsfw' },
]

// ---------------------------------------------------------------------------
// Wizard Draft
// ---------------------------------------------------------------------------

export type PersonaWizardDraft = {
  persona_class: PersonaClassId
  persona_agent: any
  persona_appearance: PersonaAppearance
  agentic: {
    goal: string
    capabilities: string[]
  }
}
