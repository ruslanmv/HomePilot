/**
 * Avatar Gallery — persistent gallery types and constants.
 *
 * Additive — no existing types are modified.
 */
export const FRAMING_OPTIONS = [
    {
        id: 'half_body',
        label: 'Half-Body',
        icon: '\uD83D\uDC64',
        description: 'Head to waist — shows posture & clothing',
        promptPrefix: 'medium shot portrait, half-body framing from head to waist, upper body visible, showing torso arms and hands, clothing and outfit clearly visible, body posture and pose visible, waist-up composition',
        negativeHints: 'face only, cropped face',
        sd15: { width: 512, height: 768 },
        sdxl: { width: 1024, height: 1536 },
    },
    {
        id: 'mid_body',
        label: 'Half-Body (Mid)',
        icon: '\uD83D\uDC64',
        description: 'Head to hips — shows outfit & body shape',
        promptPrefix: 'medium shot portrait, mid-body framing from head to hips, upper body and hips visible, showing full torso and hip area, clothing and outfit clearly visible, body posture and pose visible, frame ends at upper thighs, hips included in frame, no knees visible, no legs below thighs',
        negativeHints: 'face only, cropped face',
        sd15: { width: 512, height: 768 },
        sdxl: { width: 832, height: 1216 },
    },
    {
        id: 'headshot',
        label: 'Headshot',
        icon: '\uD83D\uDE42',
        description: 'Close-up — head & shoulders, cinematic portrait',
        promptPrefix: 'close-up portrait, head and shoulders, face is primary subject, shallow depth of field, cinematic lighting, sharp facial detail',
        negativeHints: 'waist, hands',
        sd15: { width: 512, height: 768 },
        sdxl: { width: 1024, height: 1536 },
    },
];
export const SCENARIO_TAG_META = [
    // ── SFW: Standard ──
    { id: 'modern', label: 'Modern Lifestyle', icon: '\uD83D\uDC57', category: 'sfw' },
    { id: 'corporate', label: 'Corporate Formal', icon: '\uD83D\uDCBC', category: 'sfw' },
    { id: 'business', label: 'Business Casual', icon: '\uD83D\uDC54', category: 'sfw' },
    { id: 'executive', label: 'Executive Elegant', icon: '\uD83D\uDC51', category: 'sfw' },
    { id: 'smart_casual', label: 'Smart Casual', icon: '\u2615', category: 'sfw' },
    { id: 'casual', label: 'Casual Day', icon: '\uD83D\uDC55', category: 'sfw' },
    { id: 'evening', label: 'Evening Gala', icon: '\uD83E\uDD42', category: 'sfw' },
    { id: 'sporty', label: 'Active Wear', icon: '\uD83C\uDFC3', category: 'sfw' },
    // ── NSFW: Romance & Roleplay ──
    { id: 'lingerie', label: 'Lingerie', icon: '\uD83E\uDE71', category: 'nsfw' },
    { id: 'swimwear', label: 'Swimwear', icon: '\uD83D\uDC59', category: 'nsfw' },
    { id: 'cocktail', label: 'Cocktail', icon: '\uD83C\uDF78', category: 'nsfw' },
    { id: 'boudoir', label: 'Boudoir', icon: '\uD83D\uDD6F\uFE0F', category: 'nsfw' },
    { id: 'sheer', label: 'Sheer Bodysuit', icon: '\u2728', category: 'nsfw' },
    // ── NSFW: 18+ ──
    { id: 'topless_artistic', label: 'Topless Artistic', icon: '\uD83C\uDFA8', category: 'nsfw' },
    { id: 'artistic_nude', label: 'Artistic Nude', icon: '\uD83D\uDDBC\uFE0F', category: 'nsfw' },
    { id: 'fantasy_outfit', label: 'Fantasy Explicit', icon: '\u2728', category: 'nsfw' },
    { id: 'explicit', label: 'Explicit', icon: '\uD83D\uDD25', category: 'nsfw' },
    { id: 'latex_fetish', label: 'Latex & Fetish', icon: '\u26A1', category: 'nsfw' },
    { id: 'bedroom_nude', label: 'Bedroom Nude', icon: '\uD83D\uDECF\uFE0F', category: 'nsfw' },
    { id: 'custom', label: 'Custom', icon: '\u270F\uFE0F', category: 'sfw' },
];
/** Standard vibes — safe for any audience.
 *  All prompts enforce: front-facing, looking at camera, single person, portrait framing. */
export const AVATAR_VIBE_PRESETS = [
    // Standard
    { id: 'headshot', label: 'Professional', icon: '\uD83D\uDC54', prompt: 'professional studio portrait, single person, front-facing, looking at camera, highly detailed, 8k resolution, soft lighting, clean background', category: 'standard' },
    { id: 'cinematic', label: 'Cinematic', icon: '\uD83C\uDFAC', prompt: 'cinematic portrait of a single person, front-facing, looking at camera, dramatic lighting, movie still, shallow depth of field, moody atmosphere', category: 'standard' },
    { id: 'artistic', label: 'Artistic', icon: '\uD83C\uDFA8', prompt: 'artistic portrait of a single person, front-facing, looking at camera, oil painting style, creative lighting, fine art, gallery quality', category: 'standard' },
    { id: 'cyberpunk', label: 'Cyberpunk', icon: '\uD83D\uDE80', prompt: 'cyberpunk portrait of a single person, front-facing, looking at camera, neon lights, futuristic, sci-fi, dark city background, glowing accents', category: 'standard' },
    { id: 'anime', label: 'Anime', icon: '\uD83C\uDF38', prompt: 'anime style portrait of a single person, front-facing, looking at viewer, clean lines, vibrant colors, manga aesthetic, cel shading', category: 'standard' },
    { id: 'polaroid', label: 'Polaroid', icon: '\uD83D\uDCF8', prompt: 'polaroid photo portrait of a single person, front-facing, looking at camera, vintage filter, natural lighting, nostalgic warm tones', category: 'standard' },
    { id: 'sketch', label: 'Sketch', icon: '\u270F\uFE0F', prompt: 'detailed pencil sketch portrait of a single person, front-facing, looking at viewer, artistic hatching, monochrome, fine graphite drawing', category: 'standard' },
    { id: 'fantasy', label: 'Fantasy', icon: '\uD83C\uDFB2', prompt: 'fantasy portrait of a single person, front-facing, looking at camera, magical, ethereal lighting, mystical background, enchanted atmosphere', category: 'standard' },
    // Spicy (18+) — only shown when NSFW mode is on
    { id: 'girlfriend', label: 'Girlfriend', icon: '\uD83D\uDC96', prompt: 'solo portrait, girlfriend POV, single person, front-facing, intimate eye contact, casual home setting, warm lighting, romantic mood, loving smile', category: 'spicy' },
    { id: 'spouse', label: 'Spouse', icon: '\uD83D\uDC8D', prompt: 'solo intimate portrait, single person, front-facing, loving gaze at camera, home setting, natural light, romantic and tender expression', category: 'spicy' },
    { id: 'companion', label: 'Companion', icon: '\uD83E\uDD1D', prompt: 'solo portrait, single person, front-facing, soft smile, looking at camera, cozy setting, warm atmosphere, gentle expression', category: 'spicy' },
    { id: 'fan_service', label: 'Fan Service', icon: '\uD83C\uDF36\uFE0F', prompt: 'solo portrait, single person, front-facing, fan service pose, playful expression, looking at camera, fashionable revealing outfit, studio lighting, alluring', category: 'spicy' },
    { id: 'boudoir', label: 'Boudoir', icon: '\uD83D\uDC8B', prompt: 'solo boudoir portrait, single person, front-facing, looking at camera, elegant lingerie, soft studio lighting, sensual pose, intimate setting', category: 'spicy' },
    { id: 'dominant', label: 'Dominant', icon: '\u26D3\uFE0F', prompt: 'solo portrait, single person, front-facing, confident dominant pose, looking at camera, dark aesthetic, dramatic lighting, leather accents, powerful expression', category: 'spicy' },
    { id: 'therapist', label: 'Therapist', icon: '\uD83E\uDE7A', prompt: 'solo portrait, single person, front-facing, looking at camera, professional yet intimate setting, empathetic expression, soft lighting, warm and approachable', category: 'spicy' },
    { id: 'fantasy_plus', label: 'Fantasy+', icon: '\u2728', prompt: 'solo fantasy portrait, single person, front-facing, looking at camera, exotic daring costume, mystical setting, alluring pose, magical lighting', category: 'spicy' },
];
export const GENDER_OPTIONS = [
    { id: 'female', label: 'Female', icon: '\uD83D\uDC69' },
    { id: 'male', label: 'Male', icon: '\uD83D\uDC68' },
    { id: 'neutral', label: 'Neutral', icon: '\uD83E\uDDD1' },
];
const GENDER_DICT = {
    female: { gender: 'female', noun: 'woman', possessive: 'her' },
    male: { gender: 'male', noun: 'man', possessive: 'his' },
    neutral: { gender: 'androgynous', noun: 'person', possessive: 'their' },
};
/** Build a full character description from gender + style preset. */
export function buildCharacterPrompt(gender, preset) {
    const g = GENDER_DICT[gender];
    return preset.promptTemplate
        .replace(/\{gender\}/g, g.gender)
        .replace(/\{noun\}/g, g.noun)
        .replace(/\{possessive\}/g, g.possessive);
}
/** Photorealism quality suffix appended to all portrait prompts. */
const PHOTO_QUALITY = ', RAW photo, photorealistic, ultra realistic skin texture, pores visible, fine facial detail, natural skin imperfections, DSLR, 85mm lens, f/1.8, professional photography, 8k uhd';
export const CHARACTER_STYLE_PRESETS = [
    // ── Standard ──
    // All templates enforce: single real person, front-facing, looking at camera, photorealistic
    {
        id: 'modern',
        label: 'Modern',
        icon: '\u2728',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking directly at camera, modern stylish contemporary fashion, fitted top, mini skirt, clean modern aesthetic, delicate necklace, confident natural pose, warm approachable expression, soft diffused lighting, clean minimal studio background, body posture visible' + PHOTO_QUALITY,
        positiveAnchors: 'fitted top, mini skirt, modern fashion, clean aesthetic, delicate necklace',
        negativeHints: 'costume, fantasy, baggy clothing, long skirt, blazer, coat, layered clothing, uniform',
    },
    {
        id: 'executive',
        label: 'Executive',
        icon: '\uD83D\uDCBC',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single real {gender} executive, front-facing, looking directly at camera, sharp defined facial features, wearing formal business suit, blazer, professional office attire, confident poised expression, impeccable grooming, neutral studio background, clean studio lighting with soft fill, body posture visible' + PHOTO_QUALITY,
        positiveAnchors: 'professional appearance, well groomed, business suit visible, formal neckwear',
        negativeHints: 'distracting background, harsh shadows, nudity, underwear',
    },
    {
        id: 'elegant',
        label: 'Elegant',
        icon: '\uD83C\uDF77',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single elegant real {gender} {noun}, front-facing, looking directly at camera, refined graceful bone structure, tasteful elegant appearance, soft golden hour lighting, haute couture editorial, poised composed expression, shallow depth of field' + PHOTO_QUALITY,
        positiveAnchors: 'elegant appearance, refined features',
        negativeHints: 'harsh lighting, cluttered background',
    },
    {
        id: 'romantic',
        label: 'Romantic',
        icon: '\uD83C\uDF39',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking directly at camera, warm romantic aesthetic, soft natural features, dreamy tender expression, gentle warm window lighting, natural unretouched beauty, shallow depth of field' + PHOTO_QUALITY,
        positiveAnchors: 'flowing fabric, warm tones',
        negativeHints: 'formal suit, harsh shadows',
    },
    {
        id: 'casual_char',
        label: 'Casual',
        icon: '\u2615',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single real relaxed {gender} {noun}, front-facing, looking directly at camera, casual everyday style, genuine natural candid expression, comfortable modern outfit, warm natural daylight, street photography aesthetic' + PHOTO_QUALITY,
        positiveAnchors: 'everyday streetwear, relaxed fit',
        negativeHints: 'formal suit, studio backdrop',
    },
    {
        id: 'fantasy_char',
        label: 'Fantasy',
        icon: '\u2694\uFE0F',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single real {gender} person in fantasy cosplay, front-facing, looking directly at camera, striking facial features, elaborate ornate armor or costume, practical special effects lighting, cinematic fantasy film still, real person real skin' + PHOTO_QUALITY,
        positiveAnchors: 'ornate armor, mystical elements',
        negativeHints: 'modern clothing, plain background',
    },
    {
        id: 'scifi',
        label: 'Sci-Fi',
        icon: '\uD83D\uDE80',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single real {gender} person, front-facing, looking directly at camera, futuristic sci-fi film still, sleek practical cyberpunk costume, neon accent rim lighting, real person real skin, cinematic color grading' + PHOTO_QUALITY,
        positiveAnchors: 'tech accessories, neon accents',
        negativeHints: 'period costume, natural setting',
    },
    {
        id: 'edgy',
        label: 'Edgy',
        icon: '\uD83D\uDD76\uFE0F',
        category: 'standard',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking directly at camera, edgy rebellious street style, dark alternative clothing, sharp angular bone structure, dramatic shadow lighting, urban alley backdrop, moody cinematic color grading' + PHOTO_QUALITY,
        positiveAnchors: 'leather details, urban textures',
        negativeHints: 'bright colors, soft lighting',
    },
    // ── Spicy (18+) ──
    {
        id: 'cb_girlfriend',
        label: 'Girlfriend',
        icon: '\uD83D\uDC96',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single captivating real {gender} {noun}, front-facing, intimate eye contact with camera, girlfriend POV selfie aesthetic, casual home setting, warm soft natural lighting, romantic mood, loving playful smile' + PHOTO_QUALITY,
        positiveAnchors: 'casual intimacy, loving gaze',
        negativeHints: 'formal clothing, studio backdrop',
    },
    {
        id: 'cb_spouse',
        label: 'Spouse',
        icon: '\uD83D\uDC8D',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking at camera with loving tender gaze, intimate home setting, natural morning light, romantic vulnerable expression, real skin detail' + PHOTO_QUALITY,
        positiveAnchors: 'tender expression, morning light',
        negativeHints: 'formal pose, harsh lighting',
    },
    {
        id: 'cb_companion',
        label: 'Companion',
        icon: '\uD83E\uDD1D',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single real {gender} companion, front-facing, looking directly at camera, soft inviting smile, cozy intimate setting, warm ambient natural lighting, gentle approachable expression, comfortable casual attire' + PHOTO_QUALITY,
        positiveAnchors: 'inviting smile, cozy setting',
        negativeHints: 'formal clothing, cold lighting',
    },
    {
        id: 'cb_boudoir',
        label: 'Boudoir',
        icon: '\uD83D\uDC8B',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single captivating real {gender} {noun}, front-facing, looking directly at camera, intimate boudoir setting, soft romantic diffused lighting, wearing delicate lace, sensual elegant pose, tasteful editorial photography' + PHOTO_QUALITY,
        positiveAnchors: 'delicate lace, soft shadows',
        negativeHints: 'casual clothing, bright lighting',
    },
    {
        id: 'cb_therapist',
        label: 'Therapist',
        icon: '\uD83E\uDE7A',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking directly at camera, professional yet warm office setting, empathetic caring natural expression, soft warm lighting, approachable comforting presence' + PHOTO_QUALITY,
        positiveAnchors: 'empathetic warmth, office setting',
        negativeHints: 'revealing clothing, dark shadows',
    },
    {
        id: 'cb_dominant',
        label: 'Dominant',
        icon: '\u26D3\uFE0F',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking directly at camera, commanding dominant presence, intense piercing gaze, cinematic moody Rembrandt lighting, dark aesthetic, leather accents, powerful confident expression' + PHOTO_QUALITY,
        positiveAnchors: 'leather accents, commanding gaze',
        negativeHints: 'soft pastels, gentle lighting',
    },
    {
        id: 'cb_fan_service',
        label: 'Fan Service',
        icon: '\uD83C\uDF36\uFE0F',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking directly at camera, playful confident pose, flirtatious expression, fashionable revealing outfit, studio ring light, alluring confident energy, real person' + PHOTO_QUALITY,
        positiveAnchors: 'revealing outfit, playful energy',
        negativeHints: 'modest clothing, dull lighting',
    },
    {
        id: 'cb_fantasy_plus',
        label: 'Fantasy+',
        icon: '\uD83C\uDFB2',
        category: 'spicy',
        promptTemplate: 'Solo portrait photograph of a single real {gender} {noun}, front-facing, looking directly at camera, exotic daring fantasy cosplay costume, practical effects lighting, alluring confident pose, real person real skin, cinematic film still' + PHOTO_QUALITY,
        positiveAnchors: 'exotic costume, magical lighting',
        negativeHints: 'modern clothing, plain background',
    },
];
// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
export const GALLERY_STORAGE_KEY = 'homepilot_avatar_gallery';
export const GALLERY_MAX_ITEMS = 200;
