/**
 * personaBridge — builds a PersonaWizardDraft from a GalleryItem.
 *
 * Additive utility — no existing persona code is modified.
 * Used by SaveAsPersonaModal to pre-populate PersonaWizard.
 */

import type {
  PersonaWizardDraft,
  PersonaAppearance,
  PersonaImageRef,
  PersonaClassId,
  PersonaBlueprint,
} from '../personaTypes'
import { PERSONA_BLUEPRINTS } from '../personaTypes'
import type { GalleryItem } from './galleryTypes'

// ---------------------------------------------------------------------------
// Default builders (mirror PersonaWizard helpers, but importable)
// ---------------------------------------------------------------------------

function defaultAppearance(): PersonaAppearance {
  return {
    style_preset: 'Executive',
    aspect_ratio: '2:3',
    img_preset: 'med',
    img_model: 'dreamshaper_8.safetensors',
    nsfwMode: false,
    gender: 'female',
    sets: [],
    outfits: [],
  }
}

function defaultPersonaAgent() {
  return {
    id: `persona_${Date.now()}`,
    label: '',
    category: 'custom',
    role: '',
    system_prompt: '',
    safety: { requires_adult_gate: false, allow_explicit: false, content_warning: false },
    voice_style: { rate_bias: 0, pitch_bias: 0, pause_style: 'natural' },
    response_style: { max_length: 500, tone: 'warm', use_emoji: false },
    allowed_tools: [],
    image_style_hint: 'studio portrait, realistic',
  }
}

// ---------------------------------------------------------------------------
// Bridge function
// ---------------------------------------------------------------------------

/**
 * Build a PersonaWizardDraft pre-populated with an existing avatar image.
 * The wizard can then skip straight to Step 1 (Identity & Skills).
 */
export function draftFromGalleryItem(
  item: GalleryItem,
  personaName: string,
  classId: PersonaClassId = 'custom',
): PersonaWizardDraft {
  const imageRef: PersonaImageRef = {
    id: item.id,
    url: item.url,
    created_at: new Date(item.createdAt).toISOString(),
    set_id: 'avatar_studio',
    seed: item.seed,
  }

  const appearance: PersonaAppearance = {
    ...defaultAppearance(),
    sets: [{ set_id: 'avatar_studio', images: [imageRef] }],
    selected: { set_id: 'avatar_studio', image_id: item.id },
  }

  // Apply blueprint defaults if a specific class was chosen
  const blueprint = PERSONA_BLUEPRINTS.find((bp) => bp.id === classId)
  const agent = defaultPersonaAgent()
  agent.label = personaName

  if (blueprint) {
    agent.role = blueprint.defaults.role
    agent.system_prompt = blueprint.defaults.system_prompt
    agent.response_style = { ...agent.response_style, tone: blueprint.defaults.tone }
    agent.image_style_hint = blueprint.defaults.image_style_hint
    agent.safety = { ...blueprint.defaults.safety }
    appearance.style_preset = blueprint.defaults.style_preset
  }

  return {
    persona_class: classId,
    persona_agent: agent,
    persona_appearance: appearance,
    memory_mode: blueprint?.defaults.memory_mode || 'adaptive',
    agentic: {
      goal: blueprint?.defaults.goal || '',
      capabilities: blueprint?.defaults.capabilities || [],
    },
  }
}

/**
 * Get visible blueprints for the class selector.
 */
export function getVisibleBlueprints(nsfwEnabled: boolean): PersonaBlueprint[] {
  return PERSONA_BLUEPRINTS.filter((bp) => bp.category === 'sfw' || nsfwEnabled)
}
