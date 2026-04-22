/**
 * personaBridge — builds a PersonaWizardDraft from a GalleryItem.
 *
 * Additive utility — no existing persona code is modified.
 * Used by SaveAsPersonaModal to pre-populate PersonaWizard.
 */
import { PERSONA_BLUEPRINTS } from '../personaTypes';
import { SCENARIO_TAG_META } from './galleryTypes';
// ---------------------------------------------------------------------------
// Default builders (mirror PersonaWizard helpers, but importable)
// ---------------------------------------------------------------------------
function defaultAppearance() {
    return {
        style_preset: 'Executive',
        aspect_ratio: '2:3',
        img_preset: 'med',
        img_model: 'dreamshaper_8.safetensors',
        nsfwMode: false,
        gender: 'female',
        sets: [],
        outfits: [],
    };
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
    };
}
// ---------------------------------------------------------------------------
// Bridge function
// ---------------------------------------------------------------------------
/**
 * Map an avatar wizard profession to a suggested persona class.
 */
export function professionToPersonaClass(professionId) {
    switch (professionId) {
        case 'executive_secretary':
        case 'office_administrator':
            return 'secretary';
        case 'project_manager':
        case 'research_analyst':
        case 'customer_support':
        case 'automation_operator':
        case 'code_architect':
            return 'assistant';
        case 'product_designer':
        case 'creative_director':
            return 'companion';
        default:
            return 'custom';
    }
}
/**
 * Resolve a human-readable label for an outfit's scenario tag.
 */
function outfitLabel(item) {
    if (item.scenarioTag) {
        const meta = SCENARIO_TAG_META.find((m) => m.id === item.scenarioTag);
        if (meta)
            return meta.label;
    }
    return 'Outfit';
}
/**
 * Build a PersonaWizardDraft pre-populated with an existing avatar image.
 * The wizard can then skip straight to Step 1 (Identity & Skills).
 *
 * When `outfitItems` is provided (gallery items with `parentId` pointing
 * to this character), they are converted to `PersonaOutfit[]` and included
 * in the persona appearance so that exporting to .hpersona preserves the
 * full wardrobe.
 *
 * When `batchSiblings` is provided (other images from the same generation
 * batch), they are included as additional portraits in the `sets` array
 * so the persona profile shows all generated variations.
 */
export function draftFromGalleryItem(item, personaName, classId = 'custom', outfitItems, batchSiblings) {
    const imageRef = {
        id: item.id,
        url: item.url,
        created_at: new Date(item.createdAt).toISOString(),
        set_id: 'avatar_studio',
        seed: item.seed,
    };
    // Include the selected image + all batch siblings as portraits
    const allPortraitRefs = [imageRef];
    if (batchSiblings && batchSiblings.length > 0) {
        for (const sibling of batchSiblings) {
            allPortraitRefs.push({
                id: sibling.id,
                url: sibling.url,
                created_at: new Date(sibling.createdAt).toISOString(),
                set_id: 'avatar_studio',
                seed: sibling.seed,
            });
        }
    }
    const appearance = {
        ...defaultAppearance(),
        sets: [{ set_id: 'avatar_studio', images: allPortraitRefs }],
        selected: { set_id: 'avatar_studio', image_id: item.id },
    };
    // Apply blueprint defaults if a specific class was chosen
    const blueprint = PERSONA_BLUEPRINTS.find((bp) => bp.id === classId);
    const agent = defaultPersonaAgent();
    agent.label = personaName;
    // Use wizard metadata (profession/tools/tone) to populate agent fields
    const meta = item.wizardMeta;
    if (meta) {
        // Profession description → role
        if (meta.professionLabel) {
            agent.role = meta.professionLabel;
        }
        // Profession system prompt → system_prompt
        if (meta.systemPrompt) {
            agent.system_prompt = meta.systemPrompt;
        }
        // Tone from wizard
        if (meta.tone) {
            agent.response_style = { ...agent.response_style, tone: meta.tone };
        }
        // Tools from wizard → allowed_tools
        if (meta.tools && meta.tools.length > 0) {
            agent.allowed_tools = meta.tools;
        }
        // Gender for appearance
        if (meta.gender) {
            appearance.gender = meta.gender;
        }
    }
    // Blueprint overrides wizard defaults when a specific persona class is chosen
    // (user explicitly picked Secretary/Assistant/etc. in the export dialog)
    if (blueprint && classId !== 'custom') {
        agent.role = blueprint.defaults.role;
        agent.system_prompt = blueprint.defaults.system_prompt;
        agent.response_style = { ...agent.response_style, tone: blueprint.defaults.tone };
        agent.image_style_hint = blueprint.defaults.image_style_hint;
        agent.safety = { ...blueprint.defaults.safety };
        appearance.style_preset = blueprint.defaults.style_preset;
    }
    else if (!meta && blueprint) {
        // No wizard meta and a blueprint was selected — use blueprint defaults
        agent.role = blueprint.defaults.role;
        agent.system_prompt = blueprint.defaults.system_prompt;
        agent.response_style = { ...agent.response_style, tone: blueprint.defaults.tone };
        agent.image_style_hint = blueprint.defaults.image_style_hint;
        agent.safety = { ...blueprint.defaults.safety };
        appearance.style_preset = blueprint.defaults.style_preset;
    }
    // Convert outfit gallery items to PersonaOutfit entries
    if (outfitItems && outfitItems.length > 0) {
        appearance.outfits = outfitItems.map((oi) => {
            const oiRef = {
                id: oi.id,
                url: oi.url,
                created_at: new Date(oi.createdAt).toISOString(),
                set_id: 'avatar_studio',
                seed: oi.seed,
            };
            // Extract view_pack from GalleryItem field or localStorage cache
            let viewPack;
            if (oi.view_pack && Object.keys(oi.view_pack).length > 0) {
                viewPack = oi.view_pack;
            }
            else {
                try {
                    const cacheKey = `hp_viewpack_${oi.id}`;
                    const raw = localStorage.getItem(cacheKey);
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        const results = parsed?.results ?? parsed;
                        if (results && typeof results === 'object') {
                            const vp = {};
                            for (const angle of ['front', 'left', 'right', 'back']) {
                                const entry = results[angle];
                                if (entry?.url)
                                    vp[angle] = entry.url;
                            }
                            if (Object.keys(vp).length > 0)
                                viewPack = vp;
                        }
                    }
                }
                catch { /* corrupt cache — skip */ }
            }
            const hasViewPack = viewPack && Object.keys(viewPack).length > 0;
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
                ...(hasViewPack ? {
                    view_pack: viewPack,
                    interactive_preview: true,
                    preview_mode: 'view_pack',
                    hero_view: viewPack.front ? 'front' : Object.keys(viewPack)[0],
                } : {}),
            };
        });
    }
    return {
        persona_class: classId,
        persona_agent: agent,
        persona_appearance: appearance,
        memory_mode: meta?.memoryEngine || blueprint?.defaults.memory_mode || 'adaptive',
        agentic: {
            goal: blueprint?.defaults.goal || (meta?.professionDescription || ''),
            capabilities: blueprint?.defaults.capabilities || [],
        },
    };
}
/**
 * Get visible blueprints for the class selector.
 */
export function getVisibleBlueprints(nsfwEnabled) {
    return PERSONA_BLUEPRINTS.filter((bp) => bp.category === 'sfw' || nsfwEnabled);
}
