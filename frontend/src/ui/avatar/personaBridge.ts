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
  PersonaOutfit,
  PersonaClassId,
  PersonaBlueprint,
} from '../personaTypes'
import { PERSONA_BLUEPRINTS } from '../personaTypes'
import type { GalleryItem } from './galleryTypes'
import { SCENARIO_TAG_META } from './galleryTypes'

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
 * Resolve a human-readable label for an outfit's scenario tag.
 */
function outfitLabel(item: GalleryItem): string {
  if (item.scenarioTag) {
    const meta = SCENARIO_TAG_META.find((m) => m.id === item.scenarioTag)
    if (meta) return meta.label
  }
  return 'Outfit'
}

/**
 * Build a PersonaWizardDraft pre-populated with an existing avatar image.
 * The wizard can then skip straight to Step 1 (Identity & Skills).
 *
 * When `outfitItems` is provided (gallery items with `parentId` pointing
 * to this character), they are converted to `PersonaOutfit[]` and included
 * in the persona appearance so that exporting to .hpersona preserves the
 * full wardrobe.
 */
export function draftFromGalleryItem(
  item: GalleryItem,
  personaName: string,
  classId: PersonaClassId = 'custom',
  outfitItems?: GalleryItem[],
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

  // Convert outfit gallery items to PersonaOutfit entries
  if (outfitItems && outfitItems.length > 0) {
    appearance.outfits = outfitItems.map((oi): PersonaOutfit => {
      const oiRef: PersonaImageRef = {
        id: oi.id,
        url: oi.url,
        created_at: new Date(oi.createdAt).toISOString(),
        set_id: 'avatar_studio',
        seed: oi.seed,
      }
      return {
        id: `outfit_${oi.id}`,
        label: outfitLabel(oi),
        outfit_prompt: oi.prompt || '',
        images: [oiRef],
        selected_image_id: oi.id,
        generation_settings: {
          character_prompt: item.prompt || '',
          outfit_prompt: oi.prompt || '',
          full_prompt: oi.prompt || '',
          style_preset: appearance.style_preset,
          img_model: appearance.img_model || 'dreamshaper_8.safetensors',
          img_preset: appearance.img_preset || 'med',
          aspect_ratio: appearance.aspect_ratio,
          nsfw_mode: oi.nsfw || false,
        },
        created_at: new Date(oi.createdAt).toISOString(),
      }
    })
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
