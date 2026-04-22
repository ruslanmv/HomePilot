/**
 * Persona Project Types — Phase 2
 *
 * Class-based blueprints (Secretary, Assistant, Companion + NSFW + Custom),
 * avatar generation settings persistence for reproducibility,
 * and outfit variation system.
 */
export const PERSONA_BLUEPRINTS = [
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
            system_prompt: 'You are a highly organized and efficient executive secretary. You manage schedules, draft professional correspondence, organize tasks, and ensure smooth daily operations. You are discreet, proactive, and always one step ahead.',
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
            system_prompt: 'You are a warm and knowledgeable personal assistant. You help with research, answer questions, provide recommendations, and assist with daily tasks. You are resourceful, patient, and always eager to help.',
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
            system_prompt: 'You are a fun and supportive companion. You enjoy casual conversation, share stories, play games, offer emotional support, and keep things lighthearted. You are empathetic, witty, and genuinely care about making every interaction enjoyable.',
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
            system_prompt: 'You are a loving and affectionate girlfriend. You enjoy intimate conversations, flirting, romantic roleplay, and making your partner feel desired and appreciated. You are playful, passionate, and deeply caring.',
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
            system_prompt: 'You are a devoted and passionate romantic partner. You share deep emotional connections, engage in heartfelt conversations, and create an atmosphere of trust, love, and intimacy. You are attentive, romantic, and emotionally intelligent.',
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
];
// ---------------------------------------------------------------------------
// Outfit Presets — quick-select for generating new wardrobe items
// ---------------------------------------------------------------------------
export const OUTFIT_PRESETS = [
    // ── SFW: Standard ──
    // Each preset uses SPECIFIC garment names (not vibes) so the outfit_prompt
    // is strong enough to override any residual clothing tokens from the
    // character_prompt.  NSFW presets already work well — don't touch them.
    { id: 'modern', label: 'Modern Lifestyle', prompt: 'wearing white fitted crop top and high-waisted mini skirt, white sneakers, minimal gold necklace, clean studio background, confident relaxed pose', category: 'sfw', group: 'standard', positiveAnchors: 'crop top visible, mini skirt visible', negativeHints: 'suit, blazer' },
    { id: 'corporate', label: 'Corporate Formal', prompt: 'wearing navy blue tailored blazer over white button-up shirt, matching pencil skirt, pearl earrings, black pointed heels, corporate office background, power pose', category: 'sfw', group: 'standard', positiveAnchors: 'blazer visible, button-up collar visible', negativeHints: 'casual clothing, sneakers' },
    { id: 'business', label: 'Business Casual', prompt: 'wearing light blue oxford shirt tucked into beige chinos, brown leather belt, loafers, wristwatch, modern office with plants, relaxed confident pose', category: 'sfw', group: 'standard', positiveAnchors: 'oxford shirt visible, chinos visible', negativeHints: 'formal suit, tie' },
    { id: 'executive', label: 'Executive Elegant', prompt: 'wearing black fitted sheath dress with gold belt, statement necklace, pointed stilettos, luxury penthouse office, refined confident stance', category: 'sfw', group: 'standard', positiveAnchors: 'sheath dress visible, gold accessories visible', negativeHints: 'casual clothing, sneakers' },
    { id: 'smart_casual', label: 'Smart Casual', prompt: 'wearing cream cashmere turtleneck sweater and dark jeans, ankle boots, simple bracelet, upscale cafe background, relaxed seated pose', category: 'sfw', group: 'standard', positiveAnchors: 'turtleneck sweater visible, dark jeans visible', negativeHints: 'formal suit, gown' },
    { id: 'casual', label: 'Casual Day', prompt: 'wearing oversized graphic t-shirt and denim shorts, white canvas sneakers, sunglasses on head, urban park setting, natural candid pose', category: 'sfw', group: 'standard', positiveAnchors: 'graphic tee visible, denim shorts visible', negativeHints: 'formal suit, heels' },
    { id: 'evening', label: 'Evening Gala', prompt: 'wearing floor-length red satin evening gown with thigh-high slit, diamond drop earrings, silver clutch, grand ballroom with chandelier, elegant pose', category: 'sfw', group: 'standard', positiveAnchors: 'satin gown visible, chandelier lighting', negativeHints: 'casual clothing, sneakers' },
    { id: 'sporty', label: 'Active Wear', prompt: 'wearing black sports bra and matching leggings, running shoes, fitness tracker on wrist, modern gym with mirrors, energetic athletic pose', category: 'sfw', group: 'standard', positiveAnchors: 'sports bra visible, leggings visible', negativeHints: 'formal suit, gown' },
    // ── NSFW: Romance & Roleplay ──
    { id: 'lingerie', label: 'Lingerie', prompt: 'delicate lace lingerie set, boudoir setting, sensual elegant pose, soft lighting', category: 'nsfw', group: 'romance', positiveAnchors: 'delicate lace, soft shadows', negativeHints: 'casual clothing, bright lighting' },
    { id: 'swimwear', label: 'Swimwear', prompt: 'bikini, beach or pool setting, sun-kissed golden hour lighting', category: 'nsfw', group: 'romance', positiveAnchors: 'bikini visible, sun-kissed skin', negativeHints: 'formal clothing, indoor setting' },
    { id: 'cocktail', label: 'Cocktail', prompt: 'tight cocktail dress, low neckline, nightclub setting, dramatic lighting', category: 'nsfw', group: 'romance', positiveAnchors: 'cocktail dress visible, nightclub ambiance', negativeHints: 'casual clothing, daylight' },
    { id: 'boudoir', label: 'Boudoir', prompt: 'sheer boudoir robe, luxury bedroom, soft candlelight, intimate elegant pose', category: 'nsfw', group: 'romance', positiveAnchors: 'delicate lace, soft shadows', negativeHints: 'casual clothing, bright lighting' },
    { id: 'sheer', label: 'Sheer Bodysuit', prompt: 'sheer mesh bodysuit, studio setting, confident pose, editorial lighting', category: 'nsfw', group: 'romance', positiveAnchors: 'sheer mesh fabric, editorial style', negativeHints: 'casual clothing, natural setting' },
    // ── NSFW: 18+ Explicit ──
    { id: 'topless_artistic', label: 'Topless Artistic', prompt: 'topless artistic portrait, fine art studio, dramatic chiaroscuro lighting, gallery quality', category: 'nsfw', group: '18+', positiveAnchors: 'fine art composition, chiaroscuro lighting', negativeHints: 'casual setting, harsh flash' },
    { id: 'artistic_nude', label: 'Artistic Nude', prompt: 'artistic nude portrait, classical fine art pose, painterly studio lighting, gallery quality', category: 'nsfw', group: '18+', positiveAnchors: 'classical pose, painterly lighting', negativeHints: 'casual setting, harsh flash' },
    { id: 'fantasy_outfit', label: 'Fantasy', prompt: 'exotic daring fantasy costume, mystical enchanted setting, magical lighting', category: 'nsfw', group: '18+', positiveAnchors: 'exotic costume, magical lighting', negativeHints: 'modern clothing, plain background' },
    { id: 'explicit', label: 'Explicit', prompt: 'explicit adult content, intimate setting, bold confident pose', category: 'nsfw', group: '18+', positiveAnchors: 'intimate setting, bold pose', negativeHints: 'formal clothing, public setting' },
    { id: 'latex_fetish', label: 'Latex & Fetish', prompt: 'latex outfit, dark studio, dramatic lighting, bold commanding pose', category: 'nsfw', group: '18+', positiveAnchors: 'latex fabric visible, dramatic lighting', negativeHints: 'casual clothing, soft lighting' },
    { id: 'bedroom_nude', label: 'Bedroom Nude', prompt: 'nude, luxury bedroom setting, warm intimate lighting, natural relaxed pose', category: 'nsfw', group: '18+', positiveAnchors: 'luxury bedroom, warm lighting', negativeHints: 'outdoor setting, harsh lighting' },
];
export const NUDITY_LEVELS = [
    { id: 'suggestive', label: 'Suggestive', prompt: 'clothed but revealing, suggestive pose' },
    { id: 'partial_nudity', label: 'Partial Nudity', prompt: 'partially nude, implied nudity, strategic coverage' },
    { id: 'topless', label: 'Topless', prompt: 'topless, nude upper body' },
    { id: 'full_nude', label: 'Full Nude', prompt: 'fully nude, tasteful nude portrait' },
    { id: 'explicit', label: 'Explicit', prompt: 'explicit adult content, fully nude, uninhibited' },
];
export const SENSUAL_POSES = [
    { id: 'subtle_tease', label: 'Subtle Tease', prompt: 'subtle teasing pose, coy glance' },
    { id: 'confident_display', label: 'Confident Display', prompt: 'confident bold pose, direct eye contact' },
    { id: 'intimate_close', label: 'Intimate Close', prompt: 'intimate close-up, tender expression' },
    { id: 'seductive_lean', label: 'Seductive Lean', prompt: 'seductive leaning pose, alluring gaze' },
    { id: 'lying_down', label: 'Lying Down', prompt: 'lying down pose, relaxed sensual' },
    { id: 'arched_back', label: 'Arched Back', prompt: 'arched back pose, elegant body line' },
    { id: 'kneeling', label: 'Kneeling', prompt: 'kneeling pose, graceful posture' },
    { id: 'over_shoulder', label: 'Over Shoulder', prompt: 'looking over shoulder, flirtatious glance' },
    { id: 'arms_up', label: 'Arms Up', prompt: 'arms raised pose, open confident body language' },
];
export const POWER_DYNAMICS = [
    { id: 'soft_romantic', label: 'Soft & Romantic', prompt: 'soft romantic mood, gentle tender expression, warm tones' },
    { id: 'balanced', label: 'Balanced', prompt: 'balanced confident pose, natural expression' },
    { id: 'dominant_bold', label: 'Dominant & Bold', prompt: 'dominant commanding presence, bold powerful stance, dark dramatic tones' },
];
export const FANTASY_TONES = [
    { id: 'romantic_tender', label: 'Romantic & Tender', prompt: 'romantic tender mood, warm soft lighting, dreamy atmosphere' },
    { id: 'seductive_alluring', label: 'Seductive & Alluring', prompt: 'seductive alluring mood, sultry lighting, mysterious atmosphere' },
    { id: 'dramatic_intense', label: 'Dramatic & Intense', prompt: 'dramatic intense mood, high contrast lighting, powerful atmosphere' },
];
export const SCENE_SETTINGS = [
    { id: 'luxury_bedroom', label: 'Luxury Bedroom', prompt: 'luxury bedroom, silk sheets, warm ambient lighting' },
    { id: 'penthouse', label: 'Penthouse Suite', prompt: 'penthouse suite, city skyline view, modern luxury interior' },
    { id: 'bathtub_spa', label: 'Bathtub / Spa', prompt: 'luxury bathtub, spa setting, steam and candlelight' },
    { id: 'poolside', label: 'Poolside', prompt: 'poolside setting, golden hour sunlight, tropical luxury' },
    { id: 'dark_studio', label: 'Dark Studio', prompt: 'dark photography studio, dramatic spotlight, moody shadows' },
    { id: 'mirror_room', label: 'Mirror Room', prompt: 'mirror room, reflective surfaces, artistic multiplied perspective' },
];
export const ACCESSORY_OPTIONS = [
    { id: 'glasses', label: 'Glasses', icon: '👓', prompt: 'wearing stylish glasses' },
    { id: 'necklace', label: 'Necklace', icon: '📿', prompt: 'wearing elegant necklace' },
    { id: 'watch', label: 'Watch', icon: '⌚', prompt: 'wearing luxury watch' },
    { id: 'earrings', label: 'Earrings', icon: '💎', prompt: 'wearing earrings' },
    { id: 'folder', label: 'Folder', icon: '📁', prompt: 'holding a professional folder' },
    { id: 'id_badge', label: 'ID Badge', icon: '🪪', prompt: 'wearing corporate ID badge lanyard' },
    { id: 'scarf', label: 'Scarf', icon: '🧣', prompt: 'wearing fashionable scarf' },
    { id: 'hat', label: 'Hat', icon: '🎩', prompt: 'wearing stylish hat' },
];
