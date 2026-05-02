/**
 * avatarPrompt.ts — MMORPG-style structured preferences → diffusion prompt builder.
 *
 * Maps user-friendly character preferences (skin tone, face shape, hair, etc.)
 * to stable, model-friendly prompt tokens for consistent avatar generation.
 *
 * Additive — does not modify existing gallery, types, or generation flow.
 */
// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------
/** European standard avatar preset — consistent baseline for diffusion models. */
export const DEFAULT_AVATAR_PREFS = {
    gender: 'neutral',
    skinTone: 'ivory',
    faceBase: 'blend',
    hairType: 'wavy',
    hairColor: 'brown',
    eyeColor: 'brown',
    stylePreset: 'casual',
    baseEthnicityPreset: 'european_standard',
    imageCount: 4,
    realism: 1,
    ageRange: 'adult',
};
// ---------------------------------------------------------------------------
// Token mappers (stable, model-friendly output)
// ---------------------------------------------------------------------------
function mapSkinTone(t) {
    const m = {
        espresso: 'deep dark skin tone',
        mocha: 'dark brown skin tone',
        umber: 'medium-dark skin tone',
        sienna: 'medium warm skin tone',
        olive: 'olive skin tone',
        sand: 'light warm skin tone',
        ivory: 'light skin tone',
        cream: 'fair skin tone',
    };
    return m[t];
}
function mapFaceBase(f) {
    const m = {
        strong: 'strong facial structure, defined jawline',
        angular: 'angular facial structure, sharp cheekbones',
        soft: 'soft facial structure, gentle features',
        blend: 'balanced facial structure, natural proportions',
    };
    return m[f];
}
function mapHairType(h) {
    return h === 'coily' ? 'coily textured hair' : `${h} hair`;
}
function mapHairColor(c) {
    const m = {
        black: 'black hair',
        brown: 'brown hair',
        blonde: 'blonde hair',
        auburn: 'auburn hair',
        neon_blue: 'neon blue hair',
        fuchsia: 'fuchsia hair',
    };
    return m[c];
}
export function mapEyeColor(c) {
    const m = {
        brown: 'brown eyes',
        blue: 'blue eyes',
        green: 'green eyes',
        hazel: 'hazel eyes',
        amber: 'amber eyes',
        grey: 'grey eyes',
    };
    return m[c];
}
function mapGender(g) {
    return g === 'neutral' ? 'androgynous' : g;
}
function mapAgeRange(a) {
    const m = {
        young_adult: 'young adult',
        adult: 'adult',
        mature: 'mature adult',
    };
    return m[a];
}
function mapRealism(r) {
    const m = {
        0: 'stylized mmorpg character portrait, game art style',
        1: 'high quality character portrait, semi-realistic, cinematic lighting',
        2: 'photorealistic character portrait, studio quality, natural skin texture',
    };
    return m[r];
}
function mapStylePreset(p) {
    const m = {
        modern: 'modern stylish contemporary fashion, fitted top, mini skirt, clean modern aesthetic, confident natural pose',
        executive: 'professional polished appearance, confident demeanor, clean minimal style',
        elegant: 'elegant outfit, refined fashion, premium look',
        casual: 'casual outfit, modern streetwear, relaxed fit',
        fantasy: 'fantasy adventurer outfit, subtle armor details, rpg style',
        scifi: 'sci-fi outfit, futuristic materials, sleek design',
        edgy: 'edgy outfit, dark fashion, high contrast',
        romantic: 'romantic style outfit, tasteful, elegant, classy',
    };
    return m[p];
}
function ethnicityHint(p) {
    if (p.baseEthnicityPreset === 'custom' && p.customEthnicityHint?.trim()) {
        return `ethnicity hint: ${p.customEthnicityHint.trim()}`;
    }
    if (p.baseEthnicityPreset === 'global_mixed') {
        return 'globally mixed features, inclusive, balanced';
    }
    return 'European features baseline, natural look';
}
// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------
/**
 * Build a single enhanced prompt string from structured preferences.
 * Can be appended to an existing character prompt or used standalone.
 */
export function buildGeneticsPromptFragment(prefs) {
    return [
        mapRealism(prefs.realism),
        mapGender(prefs.gender),
        mapAgeRange(prefs.ageRange),
        ethnicityHint(prefs),
        mapSkinTone(prefs.skinTone),
        mapFaceBase(prefs.faceBase),
        mapHairType(prefs.hairType),
        mapHairColor(prefs.hairColor),
    ].join(', ');
}
/** Build a complete prompt package with 4 controlled variations.
 *  When nsfwEnabled is true the NSFW/nudity negative tokens are omitted
 *  so the model is free to generate mature outfit variations later. */
export function buildAvatarPromptPackage(prefs, nsfwEnabled = false) {
    const core = [
        'single character portrait, centered composition',
        'head and shoulders, looking at camera',
        'clean background, soft depth of field',
        mapRealism(prefs.realism),
        mapGender(prefs.gender),
        mapAgeRange(prefs.ageRange),
        ethnicityHint(prefs),
        mapSkinTone(prefs.skinTone),
        mapFaceBase(prefs.faceBase),
        mapHairType(prefs.hairType),
        mapHairColor(prefs.hairColor),
        mapStylePreset(prefs.stylePreset),
        'high detail face, consistent anatomy, symmetrical eyes',
    ];
    const negative = [
        'low quality', 'blurry', 'jpeg artifacts', 'bad anatomy',
        'deformed face', 'extra limbs', 'extra fingers', 'crooked eyes',
        'text', 'watermark', 'logo',
        ...(nsfwEnabled ? [] : ['nsfw', 'nudity', 'underwear', 'explicit content']),
    ];
    const basePrompt = core.join(', ');
    const baseNegative = negative.join(', ');
    const variations = [
        { label: 'Variant A — Neutral studio', prompt: `${basePrompt}, neutral studio light, soft shadows`, negative_prompt: baseNegative },
        { label: 'Variant B — Cinematic rim light', prompt: `${basePrompt}, cinematic rim lighting, subtle film grain`, negative_prompt: baseNegative },
        { label: 'Variant C — Slight pose', prompt: `${basePrompt}, slight head tilt, natural expression`, negative_prompt: baseNegative },
        { label: 'Variant D — Outfit emphasis', prompt: `${basePrompt}, outfit details visible, premium textures`, negative_prompt: baseNegative },
    ];
    return { prompt: basePrompt, negative_prompt: baseNegative, variations };
}
// ---------------------------------------------------------------------------
// UI option arrays (for rendering choice rows in the wizard)
// ---------------------------------------------------------------------------
export const SKIN_TONE_OPTIONS = [
    { key: 'espresso', label: 'Espresso' },
    { key: 'mocha', label: 'Mocha' },
    { key: 'umber', label: 'Umber' },
    { key: 'sienna', label: 'Sienna' },
    { key: 'olive', label: 'Olive' },
    { key: 'sand', label: 'Sand' },
    { key: 'ivory', label: 'Ivory' },
    { key: 'cream', label: 'Cream' },
];
export const FACE_BASE_OPTIONS = [
    { key: 'strong', label: 'Strong' },
    { key: 'angular', label: 'Angular' },
    { key: 'soft', label: 'Soft' },
    { key: 'blend', label: 'Blend' },
];
export const HAIR_TYPE_OPTIONS = [
    { key: 'straight', label: 'Straight' },
    { key: 'wavy', label: 'Wavy' },
    { key: 'curly', label: 'Curly' },
    { key: 'coily', label: 'Coily' },
];
export const HAIR_COLOR_OPTIONS = [
    { key: 'black', label: 'Black' },
    { key: 'brown', label: 'Brown' },
    { key: 'blonde', label: 'Blonde' },
    { key: 'auburn', label: 'Auburn' },
    { key: 'neon_blue', label: 'Neon Blue' },
    { key: 'fuchsia', label: 'Fuchsia' },
];
export const AGE_RANGE_OPTIONS = [
    { key: 'young_adult', label: 'Young Adult' },
    { key: 'adult', label: 'Adult' },
    { key: 'mature', label: 'Mature' },
];
export const REALISM_OPTIONS = [
    { key: '0', label: 'MMORPG Stylized' },
    { key: '1', label: 'Semi-Real' },
    { key: '2', label: 'Photoreal' },
];
export const EYE_COLOR_OPTIONS = [
    { key: 'brown', label: 'Brown' },
    { key: 'blue', label: 'Blue' },
    { key: 'green', label: 'Green' },
    { key: 'hazel', label: 'Hazel' },
    { key: 'amber', label: 'Amber' },
    { key: 'grey', label: 'Grey' },
];
export const ETHNICITY_OPTIONS = [
    { key: 'european_standard', label: 'European Standard' },
    { key: 'global_mixed', label: 'Global Mixed' },
    { key: 'custom', label: 'Custom' },
];
