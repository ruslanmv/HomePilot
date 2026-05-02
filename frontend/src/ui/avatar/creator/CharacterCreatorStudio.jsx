/**
 * CharacterCreatorStudio — MMORPG-style three-panel character creator.
 *
 * Layout: grid-cols-[180px_1fr_320px]
 *   Left:   Step navigation + Identity Library
 *   Center: Character Stage (hero preview)
 *   Right:  Dynamic controls for current phase/step
 *   Bottom: Action bar (Generate / Save / Navigate)
 *
 * Two phases:
 *   Phase 1 — Identity Creation: generate faces, pick one, save identity
 *   Phase 2 — Style / Outfit: generate outfits/scenes for the saved identity
 *
 * Full NSFW/Spicy support when homepilot_nsfw_mode === 'true'.
 */
import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { ChevronLeft, Sparkles, Loader2, User, Lock, Shuffle, CheckCircle2, Star, Flame, X, Shirt, PenLine, ChevronDown, } from 'lucide-react';
import { useGenerateAvatars } from '../useGenerateAvatars';
import { useGenerateHybridBody } from '../useGenerateHybridBody';
import { AvatarSettingsPanel, loadAvatarSettings, resolveCheckpoint } from '../AvatarSettingsPanel';
import { resolveFileUrl } from '../../resolveFileUrl';
import { CHARACTER_STYLE_PRESETS, GENDER_OPTIONS, buildCharacterPrompt, SCENARIO_TAG_META, FRAMING_OPTIONS, } from '../galleryTypes';
import { DEFAULT_AVATAR_PREFS, buildGeneticsPromptFragment, mapEyeColor, SKIN_TONE_OPTIONS, FACE_BASE_OPTIONS, HAIR_TYPE_OPTIONS, HAIR_COLOR_OPTIONS, EYE_COLOR_OPTIONS, AGE_RANGE_OPTIONS, REALISM_OPTIONS, } from '../avatarPrompt';
import { OUTFIT_PRESETS, NUDITY_LEVELS, SENSUAL_POSES, POWER_DYNAMICS, FANTASY_TONES, SCENE_SETTINGS, ACCESSORY_OPTIONS, } from '../../personaTypes';
import { PROFESSIONS } from '../wizard/professionRegistry';
import { loadVibeTab, saveVibeTab } from '../vibeTabPersistence';
import { CharacterStage } from './CharacterStage';
import { FaceFilmstrip } from './FaceFilmstrip';
import { IdentityLibrary } from './IdentityLibrary';
import { OutfitLibrary } from './OutfitLibrary';
/** Body type options for the Body Anchor step. */
const BODY_TYPES = [
    { id: 'slim', label: 'Slim' },
    { id: 'average', label: 'Average' },
    { id: 'athletic', label: 'Athletic' },
    { id: 'curvy', label: 'Curvy' },
];
const POSTURE_OPTIONS = [
    { id: 'standing', label: 'Standing' },
    { id: 'relaxed', label: 'Relaxed' },
    { id: 'confident', label: 'Confident' },
    { id: 'three_quarter', label: '3/4 Turn' },
];
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function readNsfwMode() {
    try {
        return localStorage.getItem('homepilot_nsfw_mode') === 'true';
    }
    catch {
        return false;
    }
}
function resolveUrl(url, backendUrl) {
    return resolveFileUrl(url, backendUrl);
}
// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export function CharacterCreatorStudio({ backendUrl, apiKey, globalModelImages, enabledModes = [], gallery, onClose, onOpenLightbox, onSendToEdit, onSaveAsPersonaAvatar, onOpenViewer, }) {
    // ── Core state ──
    const gen = useGenerateAvatars(backendUrl, apiKey);
    const [avatarSettings, setAvatarSettings] = useState(loadAvatarSettings);
    const [nsfwMode, setNsfwMode] = useState(readNsfwMode);
    useEffect(() => {
        const sync = () => setNsfwMode(readNsfwMode());
        window.addEventListener('focus', sync);
        window.addEventListener('storage', sync);
        const interval = setInterval(sync, 1000);
        return () => {
            window.removeEventListener('focus', sync);
            window.removeEventListener('storage', sync);
            clearInterval(interval);
        };
    }, []);
    // Pick the face generation mode based on settings + availability
    // When useStyleGAN is on → studio_random (StyleGAN), otherwise creative (diffusion)
    const faceGenMode = avatarSettings.useStyleGAN
        ? (enabledModes.includes('studio_random') ? 'studio_random' : 'creative')
        : (enabledModes.includes('creative') ? 'creative' : 'studio_random');
    // ── Phase state ──
    const [phase, setPhase] = useState('identity');
    const [savedIdentity, setSavedIdentity] = useState(null);
    // Track identities created during this wizard session (for scoped display)
    const [sessionIdentityIds, setSessionIdentityIds] = useState(new Set());
    // Track imported identity IDs (brought from library, not created in session)
    const [importedIdentityIds, setImportedIdentityIds] = useState(new Set());
    // ── Phase 1: Identity ──
    const [selectedGender, setSelectedGender] = useState('female');
    const [selectedStyle, setSelectedStyle] = useState('executive');
    const [vibeTab, _setVibeTab] = useState(loadVibeTab);
    const setVibeTab = useCallback((tab) => { _setVibeTab(tab); saveVibeTab(tab); }, []);
    const [showGenetics, setShowGenetics] = useState(false);
    const [geneticsPrefs, setGeneticsPrefs] = useState(DEFAULT_AVATAR_PREFS);
    const [eyeColor, setEyeColor] = useState('brown');
    // Controls the collapsed "Advanced" section (face structure, realism, ethnicity, profession)
    const [showAdvancedIdentity, setShowAdvancedIdentity] = useState(false);
    const [faceCount, setFaceCount] = useState(4);
    const [selectedFaceIndex, setSelectedFaceIndex] = useState(null);
    const [showNsfw, setShowNsfw] = useState(nsfwMode);
    const [showFaceCountMenu, setShowFaceCountMenu] = useState(false);
    const [showBodyCountMenu, setShowBodyCountMenu] = useState(false);
    const [showOutfitCountMenu, setShowOutfitCountMenu] = useState(false);
    // ── Phase 1.5: Body Anchor (half-body or headshot) ──
    const [bodyFraming, setBodyFraming] = useState('half_body');
    const [bodyType, setBodyType] = useState('average');
    const [bodyPosture, setBodyPosture] = useState('standing');
    const [bodyCount, setBodyCount] = useState(1);
    const [selectedBodyIndex, setSelectedBodyIndex] = useState(null);
    const [savedBody, setSavedBody] = useState(null);
    const bodyGen = useGenerateHybridBody(backendUrl, apiKey);
    // Body step is needed when:
    // 1. User chose "Headshot" framing — face is a close-up, needs body expansion
    // 2. StyleGAN is ON — StyleGAN generates square face-only images regardless of framing
    // In both cases we need a half-body generation step before outfits can be applied.
    // The only exception: body workflow explicitly disabled in settings.
    const needsBodyStep = avatarSettings.bodyWorkflowMethod !== 'disabled'
        && (bodyFraming === 'headshot' || avatarSettings.useStyleGAN);
    // ── Profession ──
    const [selectedProfession, setSelectedProfession] = useState('executive_secretary');
    // ── Phase 2: Outfit ──
    const [selectedOutfitPreset, setSelectedOutfitPreset] = useState('corporate');
    const [customOutfitPrompt, setCustomOutfitPrompt] = useState('');
    const [outfitCount, setOutfitCount] = useState(1);
    const [selectedOutfitIndex, setSelectedOutfitIndex] = useState(null);
    const outfitGen = useGenerateAvatars(backendUrl, apiKey);
    // Accumulated outfits — persists across multiple generations so the user
    // can preview ALL outfits (not just the latest batch) in the filmstrip.
    const [allOutfits, setAllOutfits] = useState([]);
    // Outfit tab: standard vs romance vs 18+
    const [outfitTab, setOutfitTab] = useState('standard');
    // NSFW advanced controls (collapsible)
    const [showNsfwAdvanced, setShowNsfwAdvanced] = useState(false);
    const [nudityLevel, setNudityLevel] = useState(null);
    const [sensualPose, setSensualPose] = useState(null);
    const [powerDynamic, setPowerDynamic] = useState(null);
    const [fantasyTone, setFantasyTone] = useState(null);
    const [sceneSetting, setSceneSetting] = useState(null);
    const [selectedAccessories, setSelectedAccessories] = useState([]);
    const [explicitnessIntensity, setExplicitnessIntensity] = useState(5);
    const [outfitPrimaryColor, setOutfitPrimaryColor] = useState(null);
    const [outfitSecondaryColor, setOutfitSecondaryColor] = useState(null);
    const toggleAccessory = useCallback((id) => {
        setSelectedAccessories((prev) => prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]);
    }, []);
    // ── Undo stack for outfit deletion ──
    const [deletedOutfit, setDeletedOutfit] = useState(null);
    const undoTimer = useRef();
    // ── Phase 3: Finalize ──
    const [characterName, setCharacterName] = useState('');
    // Pending identity save — tracks the seed of a just-saved anchor so we can
    // pick it up from gallery.items once React processes the state update.
    const pendingIdentitySeedRef = useRef(null);
    // ── Toast ──
    const [toast, setToast] = useState(null);
    const toastTimer = useRef();
    const showToast = useCallback((message, type = 'info') => {
        setToast({ message, type });
        if (toastTimer.current)
            clearTimeout(toastTimer.current);
        toastTimer.current = setTimeout(() => setToast(null), 5000);
    }, []);
    // ── Derived ──
    const checkpoint = resolveCheckpoint(avatarSettings, globalModelImages);
    const charStyles = CHARACTER_STYLE_PRESETS.filter((s) => vibeTab === 'standard' ? s.category === 'standard' : s.category === 'spicy');
    // Filter outfits by tab + NSFW access
    const outfitPresets = OUTFIT_PRESETS.filter((p) => {
        if (p.category === 'nsfw' && !nsfwMode)
            return false;
        const group = p.group || (p.category === 'sfw' ? 'standard' : 'romance');
        return group === outfitTab;
    });
    // ── Build identity prompt ──
    // Both Half Body and Headshot use portrait ratio (512x768) by default for quality.
    // The 1:1 square ratio is only used when explicitly enabled in Advanced Settings.
    const identityFramingOption = FRAMING_OPTIONS.find((f) => f.id === bodyFraming) ?? FRAMING_OPTIONS[0];
    // Resolve effective dimensions: headshot uses portrait ratio by default,
    // but allows optional 1:1 square via Advanced Settings for specific use cases.
    const identityDims = useMemo(() => {
        if (bodyFraming === 'headshot' && avatarSettings.headshot1to1) {
            return { width: 512, height: 512 }; // Square 1:1 (optional)
        }
        return identityFramingOption.sd15; // Portrait 2:3 (default for both)
    }, [bodyFraming, avatarSettings.headshot1to1, identityFramingOption]);
    const activeCreatorStyle = CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle);
    const identityPrompt = useMemo(() => {
        const style = CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle);
        let base;
        if (selectedGender && style) {
            base = buildCharacterPrompt(selectedGender, style);
        }
        else if (selectedGender) {
            const word = selectedGender === 'neutral' ? 'an androgynous' : `a ${selectedGender}`;
            base = `Solo portrait photograph of ${word} person, front-facing, looking directly at camera, RAW photo, photorealistic, ultra realistic skin texture, pores visible, fine facial detail, DSLR, 85mm lens, f/1.8, professional studio lighting, 8k uhd`;
        }
        else {
            base = 'Solo portrait photograph of a female person, front-facing, looking directly at camera, RAW photo, photorealistic, ultra realistic skin texture, pores visible, fine facial detail, DSLR, 85mm lens, f/1.8, professional studio lighting, 8k uhd';
        }
        // Include profession context in prompt.
        // Use SD-safe aliases so words like "secretary" (NSFW trigger in many
        // checkpoints) never leak into the image-generation prompt.
        const PROFESSION_PROMPT_ALIAS = {
            executive_secretary: 'executive assistant',
            office_administrator: 'office administrator',
        };
        const prof = selectedProfession ? PROFESSIONS.find((p) => p.id === selectedProfession) : null;
        if (prof && prof.id !== 'custom') {
            const safeLabel = PROFESSION_PROMPT_ALIAS[prof.id] ?? prof.label.toLowerCase();
            base = `${base}, ${safeLabel} professional`;
        }
        // Always include core appearance tokens (skin tone, hair, eye color) so
        // they are baked into the prompt — View Pack reads wizardMeta for these but
        // having them in the prompt also anchors the diffusion model during face gen.
        const appearanceParts = [];
        const skinLabel = SKIN_TONE_OPTIONS.find((o) => o.key === geneticsPrefs.skinTone);
        if (skinLabel)
            appearanceParts.push(`${skinLabel.label.toLowerCase()} skin tone`);
        const hairColorLabel = HAIR_COLOR_OPTIONS.find((o) => o.key === geneticsPrefs.hairColor);
        if (hairColorLabel)
            appearanceParts.push(`${hairColorLabel.label.toLowerCase()} hair`);
        const hairTypeLabel = HAIR_TYPE_OPTIONS.find((o) => o.key === geneticsPrefs.hairType);
        if (hairTypeLabel)
            appearanceParts.push(`${hairTypeLabel.label.toLowerCase()} hair texture`);
        appearanceParts.push(mapEyeColor(eyeColor));
        base = `${base}, ${appearanceParts.join(', ')}`;
        if (showGenetics) {
            const frag = buildGeneticsPromptFragment(geneticsPrefs);
            base = `${base}, ${frag}`;
        }
        // Append style-specific positive anchors (e.g., "business suit visible, formal neckwear")
        if (style?.positiveAnchors) {
            base = `${base}, ${style.positiveAnchors}`;
        }
        // Only append framing keywords for body-showing framings (needs specific composition guidance).
        // Headshot relies on the high-quality preset prompt + portrait dimensions.
        if (bodyFraming === 'half_body' || bodyFraming === 'mid_body') {
            return `${base}, ${identityFramingOption.promptPrefix}`;
        }
        return base;
    }, [selectedGender, selectedStyle, selectedProfession, showGenetics, geneticsPrefs, eyeColor, bodyFraming, identityFramingOption]);
    // Build negative prompt from framing + style hints (max 4 tokens total)
    const identityNegativePrompt = useMemo(() => {
        return [identityFramingOption.negativeHints, activeCreatorStyle?.negativeHints].filter(Boolean).join(', ');
    }, [identityFramingOption, activeCreatorStyle]);
    // ── Build body prompt (for Body Anchor step) ──
    // Body step always generates half-body — this is the base for outfit generation.
    // When user chose "Headshot", the face step produces a headshot, then this body
    // step generates a half-body from that face so outfits can be applied.
    const bodyPrompt = useMemo(() => {
        const gender = selectedGender === 'neutral' ? 'androgynous person' : `${selectedGender} person`;
        const pose = bodyPosture === 'three_quarter' ? '3/4 turn pose' : `${bodyPosture} pose`;
        return `Half body portrait photograph of a single real ${gender}, ${bodyType} build, ${pose}, ` +
            'simple neutral attire, clean seamless background, professional studio lighting, visible from head to waist, upper body focus, ' +
            'RAW photo, photorealistic, ultra realistic skin texture, real person, DSLR, 50mm lens, f/2.8, 8k uhd';
    }, [selectedGender, bodyType, bodyPosture]);
    // Reset spicy tab if NSFW gets disabled
    useEffect(() => {
        if (!nsfwMode && vibeTab === 'spicy')
            setVibeTab('standard');
    }, [nsfwMode, vibeTab, setVibeTab]);
    // Reset style when tab switches
    useEffect(() => {
        if (selectedStyle) {
            const style = CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle);
            if (style && style.category !== vibeTab)
                setSelectedStyle(null);
        }
    }, [vibeTab, selectedStyle]);
    // ── Effective outfit prompt (composes base + NSFW modifiers + accessories + scene) ──
    const effectiveOutfitPrompt = useMemo(() => {
        let base = '';
        if (customOutfitPrompt.trim()) {
            base = customOutfitPrompt.trim();
        }
        else if (selectedOutfitPreset) {
            const preset = OUTFIT_PRESETS.find((p) => p.id === selectedOutfitPreset);
            base = preset?.prompt || '';
        }
        if (!base)
            return '';
        // Compose NSFW modifiers (additive — only appended when set)
        const parts = [base];
        if (nudityLevel) {
            const nl = NUDITY_LEVELS.find((l) => l.id === nudityLevel);
            if (nl)
                parts.push(nl.prompt);
        }
        if (sensualPose) {
            const sp = SENSUAL_POSES.find((p) => p.id === sensualPose);
            if (sp)
                parts.push(sp.prompt);
        }
        if (powerDynamic) {
            const pd = POWER_DYNAMICS.find((d) => d.id === powerDynamic);
            if (pd)
                parts.push(pd.prompt);
        }
        if (fantasyTone) {
            const ft = FANTASY_TONES.find((t) => t.id === fantasyTone);
            if (ft)
                parts.push(ft.prompt);
        }
        if (sceneSetting) {
            const ss = SCENE_SETTINGS.find((s) => s.id === sceneSetting);
            if (ss)
                parts.push(ss.prompt);
        }
        if (selectedAccessories.length > 0) {
            const accPrompts = selectedAccessories
                .map((id) => ACCESSORY_OPTIONS.find((a) => a.id === id)?.prompt)
                .filter(Boolean);
            if (accPrompts.length)
                parts.push(accPrompts.join(', '));
        }
        // Add color context
        if (outfitPrimaryColor)
            parts.push(`${outfitPrimaryColor} primary color`);
        if (outfitSecondaryColor)
            parts.push(`${outfitSecondaryColor} accent color`);
        // Add profession context to outfit
        const prof = selectedProfession ? PROFESSIONS.find((p) => p.id === selectedProfession) : null;
        if (prof && prof.id !== 'custom')
            parts.push(`${prof.label.toLowerCase()} role`);
        return parts.join(', ');
    }, [customOutfitPrompt, selectedOutfitPreset, nudityLevel, sensualPose, powerDynamic, fantasyTone, sceneSetting, selectedAccessories, outfitPrimaryColor, outfitSecondaryColor, selectedProfession]);
    // ── Phase 1: Generate Faces ──
    // Flag: when true, auto-save identity after next render (single-face auto-advance)
    const [autoSaveIdentity, setAutoSaveIdentity] = useState(false);
    const handleGenerateFaces = useCallback(async () => {
        setSelectedFaceIndex(null);
        setAutoSaveIdentity(false);
        try {
            const result = await gen.run({
                mode: faceGenMode,
                count: faceCount,
                prompt: identityPrompt || undefined,
                truncation: 0.7,
                checkpoint_override: checkpoint,
                width: identityDims.width,
                height: identityDims.height,
                negative_prompt: identityNegativePrompt || undefined,
            });
            if (result?.results?.length) {
                setSelectedFaceIndex(0);
                // Check if backend returned placeholder warning (no AI generators available)
                const isPlaceholder = result.warnings?.some((w) => w.toLowerCase().includes('placeholder'));
                if (isPlaceholder) {
                    showToast('No AI generator available — showing placeholder faces. Start ComfyUI for real AI faces.', 'info');
                }
                else if (result.results.length === 1) {
                    // Auto-advance: single face → auto-select and auto-save after state settles
                    showToast('Face generated — advancing to next step...', 'success');
                    setAutoSaveIdentity(true);
                }
                else {
                    showToast(`${result.results.length} faces generated — pick your character`, 'success');
                }
            }
        }
        catch {
            showToast('Generation failed. Click Generate to try again.', 'error');
        }
    }, [gen, faceGenMode, faceCount, identityPrompt, checkpoint, showToast, identityDims]);
    // ── Phase 1: Save Identity ──
    const handleSaveIdentity = useCallback(() => {
        if (!gen.result?.results?.length || selectedFaceIndex === null)
            return;
        const allResults = gen.result.results;
        const chosen = allResults[selectedFaceIndex];
        const portraits = allResults.filter((_, i) => i !== selectedFaceIndex);
        const isSpicy = (() => {
            const style = CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle);
            return style?.category === 'spicy';
        })();
        // Build WizardMeta so persona export can pre-populate role, tools, tone
        // Appearance fields are stored so View Pack can produce exact visual
        // descriptors without regex-guessing from the prompt text.
        const prof = selectedProfession ? PROFESSIONS.find((p) => p.id === selectedProfession) : null;
        const wizardMeta = {
            professionId: selectedProfession || undefined,
            professionLabel: prof?.label,
            professionDescription: prof?.description,
            tools: prof?.defaults.tools,
            memoryEngine: prof?.defaults.memoryEngine,
            autonomy: prof?.defaults.autonomy,
            tone: prof?.defaults.tone,
            systemPrompt: prof?.defaults.systemPrompt,
            responseStyle: prof?.defaults.responseStyle,
            gender: selectedGender || undefined,
            // Appearance — used by View Pack for drift-free 3D angle generation
            skinTone: geneticsPrefs.skinTone,
            hairColor: geneticsPrefs.hairColor,
            hairType: geneticsPrefs.hairType,
            eyeColor,
        };
        gallery.addAnchorWithPortraits(chosen, portraits, faceGenMode, identityPrompt || undefined, undefined, { vibeTag: selectedStyle || undefined, nsfw: isSpicy || undefined, wizardMeta, framingType: bodyFraming });
        // Track the pending anchor so the useEffect below can pick it up
        // once gallery.items has been updated by React.
        pendingIdentitySeedRef.current = { seed: chosen.seed, url: chosen.url };
        if (needsBodyStep) {
            setPhase('body');
            gen.reset();
            showToast('Face saved! Now generate a half-body for outfit generation.', 'success');
        }
        else {
            setPhase('outfit');
            gen.reset();
            showToast('Identity saved! Now pick an outfit for your character.', 'success');
        }
    }, [gen, selectedFaceIndex, gallery, identityPrompt, selectedStyle, selectedProfession, selectedGender, geneticsPrefs, eyeColor, bodyFraming, showToast, needsBodyStep]);
    // Auto-advance: when single face generated, auto-save identity and move on
    useEffect(() => {
        if (autoSaveIdentity && gen.result?.results?.length === 1 && selectedFaceIndex === 0) {
            setAutoSaveIdentity(false);
            handleSaveIdentity();
        }
    }, [autoSaveIdentity, gen.result, selectedFaceIndex, handleSaveIdentity]);
    // Resolve pending identity once gallery.items updates after addAnchorWithPortraits
    useEffect(() => {
        const pending = pendingIdentitySeedRef.current;
        if (!pending)
            return;
        const found = gallery.items.find((i) => i.role === 'anchor' && !i.parentId && i.url === pending.url);
        if (found) {
            pendingIdentitySeedRef.current = null;
            setSavedIdentity(found);
            setSessionIdentityIds((prev) => new Set(prev).add(found.id));
        }
    }, [gallery.items]);
    // ── Phase 1.5: Generate Body Base (hybrid pipeline: face → full body) ──
    const handleGenerateBody = useCallback(async () => {
        if (!savedIdentity)
            return;
        setSelectedBodyIndex(null);
        try {
            const result = await bodyGen.run({
                face_image_url: savedIdentity.url,
                count: bodyCount,
                body_type: bodyType,
                posture: bodyPosture,
                gender: selectedGender === 'neutral' ? 'neutral' : selectedGender ?? undefined,
                background: 'studio',
                lighting: 'studio',
                identity_strength: 0.75,
                workflow_method: avatarSettings.bodyWorkflowMethod || 'default',
            });
            if (result?.results?.length) {
                setSelectedBodyIndex(0);
                showToast(result.results.length === 1
                    ? 'Body generated — select and save to continue'
                    : `${result.results.length} body variations generated — pick the best one`, 'success');
            }
        }
        catch (err) {
            const msg = err?.message || 'Body generation failed';
            const hint = msg.includes('timeout') ? ' Try reducing the count.'
                : msg.includes('Unavailable') || msg.includes('offline') ? ' Check that ComfyUI is running.'
                    : ' Click Generate to try again.';
            showToast(msg + hint, 'error');
        }
    }, [bodyGen, bodyCount, bodyType, bodyPosture, selectedGender, savedIdentity, showToast, avatarSettings.bodyWorkflowMethod]);
    // ── Phase 1.5: Save Body Anchor ──
    const handleSaveBody = useCallback(() => {
        if (!bodyGen.result?.results?.length || selectedBodyIndex === null || !savedIdentity)
            return;
        const chosen = bodyGen.result.results[selectedBodyIndex];
        // Save body anchor to gallery linked to face identity
        gallery.addBatch([{ url: chosen.url, seed: chosen.seed, metadata: chosen.metadata }], 'studio_reference', bodyPrompt, savedIdentity.url, undefined, { parentId: savedIdentity.id });
        const bodyItem = {
            id: crypto.randomUUID ? crypto.randomUUID() : `body-${Date.now()}`,
            url: chosen.url,
            seed: chosen.seed,
            prompt: bodyPrompt,
            mode: 'studio_reference',
            createdAt: Date.now(),
            role: 'anchor',
            parentId: savedIdentity.id,
        };
        setSavedBody(bodyItem);
        setPhase('outfit');
        bodyGen.reset();
        showToast('Half-body saved! Now pick an outfit for your character.', 'success');
    }, [bodyGen, selectedBodyIndex, savedIdentity, gallery, bodyPrompt, showToast]);
    // ── Phase 2: Generate Outfits ──
    const handleGenerateOutfits = useCallback(async () => {
        if (!savedIdentity || !effectiveOutfitPrompt)
            return;
        setSelectedOutfitIndex(null);
        try {
            // Use body anchor as reference when available (StyleGAN path),
            // otherwise use face identity directly (diffusion path)
            const referenceUrl = savedBody?.url || savedIdentity.url;
            const result = await outfitGen.run({
                mode: 'studio_reference',
                count: outfitCount,
                prompt: effectiveOutfitPrompt,
                reference_image_url: referenceUrl,
                checkpoint_override: checkpoint,
            });
            if (result?.results?.length) {
                // Accumulate new outfits with previous ones so the filmstrip shows ALL
                const scenarioForResults = selectedOutfitPreset || 'custom';
                const taggedResults = result.results.map((r) => ({ ...r, scenarioTag: scenarioForResults }));
                setAllOutfits((prev) => {
                    const newIndex = prev.length; // select first newly added outfit
                    setSelectedOutfitIndex(newIndex);
                    return [...prev, ...taggedResults];
                });
                const scenarioTag = selectedOutfitPreset || 'custom';
                // Save to gallery linked to identity
                gallery.addBatch(result.results, 'studio_reference', effectiveOutfitPrompt, savedIdentity.url, scenarioTag, { parentId: savedIdentity.id, nsfw: (outfitTab !== 'standard') || undefined });
                showToast(`${result.results.length} outfit(s) generated!`, 'success');
            }
        }
        catch {
            showToast('Outfit generation failed. Try again.', 'error');
        }
    }, [outfitGen, savedIdentity, effectiveOutfitPrompt, outfitCount, checkpoint, selectedOutfitPreset, gallery, showToast, savedBody]);
    // ── Select existing identity from library ──
    const handleSelectIdentity = useCallback((item) => {
        setSavedIdentity(item);
        setSavedBody(null);
        gen.reset();
        outfitGen.reset();
        setAllOutfits([]);
        setSelectedOutfitIndex(null);
        // If body step is needed (headshot or StyleGAN), route to body first
        // so the user can generate a half-body before outfits.
        setPhase(needsBodyStep ? 'body' : 'outfit');
        // Track as imported if not created in this session
        if (!sessionIdentityIds.has(item.id)) {
            setImportedIdentityIds((prev) => new Set(prev).add(item.id));
        }
    }, [gen, outfitGen, sessionIdentityIds, needsBodyStep]);
    // ── Back to identity phase ──
    const handleBackToIdentity = useCallback(() => {
        setPhase('identity');
        bodyGen.reset();
        outfitGen.reset();
        setAllOutfits([]);
        setSavedBody(null);
        setSelectedBodyIndex(null);
        setSelectedOutfitIndex(null);
    }, [bodyGen, outfitGen]);
    const handleBackToBody = useCallback(() => {
        setPhase('body');
        outfitGen.reset();
        setAllOutfits([]);
        setSelectedOutfitIndex(null);
    }, [outfitGen]);
    // ── Delete face/body/outfit from filmstrip ──
    const handleDeleteFace = useCallback((index) => {
        gen.removeResult(index);
        setSelectedFaceIndex((prev) => {
            if (prev === null)
                return null;
            if (prev === index)
                return gen.result?.results && gen.result.results.length > 1 ? Math.max(0, index - 1) : null;
            if (prev > index)
                return prev - 1;
            return prev;
        });
    }, [gen]);
    const handleDeleteBody = useCallback((index) => {
        bodyGen.removeResult(index);
        setSelectedBodyIndex((prev) => {
            if (prev === null)
                return null;
            if (prev === index)
                return bodyGen.result?.results && bodyGen.result.results.length > 1 ? Math.max(0, index - 1) : null;
            if (prev > index)
                return prev - 1;
            return prev;
        });
    }, [bodyGen]);
    const handleDeleteOutfit = useCallback((index) => {
        // Stash deleted outfit for undo
        const removed = allOutfits[index];
        if (removed) {
            setDeletedOutfit({ item: removed, index });
            if (undoTimer.current)
                clearTimeout(undoTimer.current);
            undoTimer.current = setTimeout(() => setDeletedOutfit(null), 6000);
        }
        // Remove from accumulated list
        setAllOutfits((prev) => prev.filter((_, i) => i !== index));
        setSelectedOutfitIndex((prev) => {
            if (prev === null)
                return null;
            if (prev === index)
                return allOutfits.length > 1 ? Math.max(0, index - 1) : null;
            if (prev > index)
                return prev - 1;
            return prev;
        });
        showToast('Outfit removed — click Undo to restore', 'info');
    }, [allOutfits, showToast]);
    const handleUndoDeleteOutfit = useCallback(() => {
        if (!deletedOutfit)
            return;
        setAllOutfits((prev) => {
            const next = [...prev];
            next.splice(deletedOutfit.index, 0, deletedOutfit.item);
            return next;
        });
        setSelectedOutfitIndex(deletedOutfit.index);
        setDeletedOutfit(null);
        if (undoTimer.current)
            clearTimeout(undoTimer.current);
        showToast('Outfit restored', 'success');
    }, [deletedOutfit, showToast]);
    // ── Delete outfit from gallery (used by OutfitLibrary panel) ──
    const handleDeleteOutfitFromGallery = useCallback((item) => {
        gallery.removeItem(item.id);
    }, [gallery]);
    // ── Select outfit from library → show on stage ──
    const handleSelectOutfitFromLibrary = useCallback((item) => {
        // Check if this outfit is already in the accumulated list
        const existingIndex = allOutfits.findIndex((o) => o.url === item.url);
        if (existingIndex >= 0) {
            setSelectedOutfitIndex(existingIndex);
        }
        else {
            // Add it to the accumulated list and select it
            setAllOutfits((prev) => {
                setSelectedOutfitIndex(prev.length);
                return [...prev, { url: item.url, seed: item.seed, metadata: {} }];
            });
        }
        // Switch to outfit phase so it shows on stage
        if (phase !== 'outfit' && phase !== 'finalize') {
            setPhase('outfit');
        }
    }, [allOutfits, phase]);
    // ── Resolve URL helper ──
    const resolveUrlFn = useCallback((url) => resolveUrl(url, backendUrl), [backendUrl]);
    // ── Keyboard shortcut ──
    useEffect(() => {
        const handler = (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                if (phase === 'identity' && !gen.loading)
                    handleGenerateFaces();
                if (phase === 'body' && !bodyGen.loading)
                    handleGenerateBody();
                if (phase === 'outfit' && !outfitGen.loading && effectiveOutfitPrompt)
                    handleGenerateOutfits();
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [phase, gen.loading, bodyGen.loading, outfitGen.loading, handleGenerateFaces, handleGenerateBody, handleGenerateOutfits, effectiveOutfitPrompt]);
    // ── Stage content ──
    const stageContent = (() => {
        // Helper: show selected outfit from the accumulated list
        const outfitStage = () => {
            if (allOutfits.length > 0 && selectedOutfitIndex !== null && selectedOutfitIndex < allOutfits.length) {
                const r = allOutfits[selectedOutfitIndex];
                return {
                    kind: 'outfit',
                    url: resolveUrlFn(r.url),
                    seed: r.seed,
                    scenarioLabel: selectedOutfitPreset
                        ? SCENARIO_TAG_META.find((t) => t.id === selectedOutfitPreset)?.label
                        : undefined,
                };
            }
            return null;
        };
        // Phase 4: Finalize — show the selected outfit (or body/identity)
        if (phase === 'finalize') {
            const outfit = outfitStage();
            if (outfit)
                return outfit;
            const baseAnchor = savedBody || savedIdentity;
            if (baseAnchor)
                return { kind: 'face', url: resolveUrlFn(baseAnchor.url), seed: baseAnchor.seed };
            return { kind: 'empty' };
        }
        if (phase === 'outfit') {
            if (outfitGen.loading)
                return { kind: 'generating' };
            const outfit = outfitStage();
            if (outfit)
                return outfit;
            // Show body base (if available) as the starting reference for outfits
            const baseAnchor = savedBody || savedIdentity;
            if (baseAnchor) {
                return { kind: 'face', url: resolveUrlFn(baseAnchor.url), seed: baseAnchor.seed };
            }
            return { kind: 'empty' };
        }
        // Phase 1.5: body
        if (phase === 'body') {
            if (bodyGen.loading)
                return { kind: 'generating' };
            if (bodyGen.result?.results?.length && selectedBodyIndex !== null) {
                const r = bodyGen.result.results[selectedBodyIndex];
                return { kind: 'face', url: resolveUrlFn(r.url), seed: r.seed };
            }
            if (savedIdentity) {
                return { kind: 'face', url: resolveUrlFn(savedIdentity.url), seed: savedIdentity.seed };
            }
            return { kind: 'empty' };
        }
        // Phase 1: identity
        if (gen.loading)
            return { kind: 'generating' };
        if (gen.result?.results?.length && selectedFaceIndex !== null) {
            const r = gen.result.results[selectedFaceIndex];
            return { kind: 'face', url: resolveUrlFn(r.url), seed: r.seed };
        }
        return { kind: 'empty' };
    })();
    // ══════════════════════════════════════════════════════════════
    // RENDER
    // ══════════════════════════════════════════════════════════════
    return (<div className="flex flex-col h-full bg-[#0a0a0f] text-white overflow-hidden">

      {/* ═══════════ HEADER — AAA Progress Bar ═══════════ */}
      <div className="px-5 pt-4 pb-3 border-b border-white/[0.06] flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={onClose} className="flex items-center gap-2 text-white/40 hover:text-white/70 transition-colors text-sm" title="Back to Gallery">
            <ChevronLeft size={16}/>
          </button>
          <div className="flex items-center gap-2.5">
            <Sparkles size={18} className="text-purple-400"/>
            <h1 className="text-base font-semibold tracking-tight">New Avatar</h1>
          </div>

          {/* ── Wizard Step Progress (AAA-style) ── */}
          <div className="flex items-center gap-0.5 ml-4">
            {(() => {
            const steps = needsBodyStep
                ? [
                    { key: 'identity', num: 1, label: 'Face', done: !!savedIdentity },
                    { key: 'body', num: 2, label: 'Body', done: !!savedBody },
                    { key: 'outfit', num: 3, label: 'Style (optional)', done: phase === 'finalize' || !!outfitGen.result?.results?.length },
                    { key: 'finalize', num: 4, label: 'Finalize', done: false },
                ]
                : [
                    { key: 'identity', num: 1, label: 'Face', done: !!savedIdentity },
                    { key: 'outfit', num: 2, label: 'Style', done: phase === 'finalize' },
                    { key: 'finalize', num: 3, label: 'Finalize', done: false },
                ];
            return steps.map((s, i) => (<React.Fragment key={s.key}>
                  {i > 0 && (<div className={`w-5 h-px mx-0.5 ${s.done || phase === s.key ? 'bg-purple-500/40' : 'bg-white/10'}`}/>)}
                  <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium transition-all ${phase === s.key
                    ? 'bg-purple-500/15 text-purple-300 border border-purple-500/25'
                    : s.done
                        ? 'text-green-400/70 border border-green-500/20 bg-green-500/5'
                        : 'text-white/25 border border-transparent'}`}>
                    {s.done ? (<CheckCircle2 size={10} className="text-green-400/70"/>) : (<span className={`w-3.5 h-3.5 rounded-full text-[8px] flex items-center justify-center font-bold ${phase === s.key ? 'bg-purple-500/30 text-purple-200' : 'bg-white/10 text-white/30'}`}>{s.num}</span>)}
                    {s.label}
                  </div>
                </React.Fragment>));
        })()}
          </div>
        </div>
        <AvatarSettingsPanel globalModelImages={globalModelImages} settings={avatarSettings} onChange={setAvatarSettings} styleganStatus={null}/>
      </div>

      {/* ═══════════ THREE-PANEL BODY ═══════════ */}
      <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[180px_1fr_320px] overflow-hidden">

        {/* ──────── LEFT PANEL: Navigation + Identity Library ──────── */}
        <div className="hidden md:flex flex-col border-r border-white/[0.06] py-4 px-3 overflow-y-auto gap-4">

          {/* Identity Library — session-scoped */}
          <IdentityLibrary items={gallery.items} sessionIds={sessionIdentityIds} importedIds={importedIdentityIds} activeIdentityId={savedIdentity?.id ?? null} onSelectIdentity={handleSelectIdentity} onNewIdentity={handleBackToIdentity} onImportIdentity={handleSelectIdentity} resolveUrl={resolveUrlFn}/>

          <div className="border-t border-white/[0.06]"/>

          {/* Outfit Library — outfits created for the active identity */}
          <OutfitLibrary items={gallery.items} activeIdentityId={savedIdentity?.id ?? null} activeOutfitUrl={selectedOutfitIndex !== null && selectedOutfitIndex < allOutfits.length ? allOutfits[selectedOutfitIndex].url : null} onSelectOutfit={handleSelectOutfitFromLibrary} onDeleteOutfit={handleDeleteOutfitFromGallery} resolveUrl={resolveUrlFn}/>

          <div className="border-t border-white/[0.06]"/>

          {/* Phase navigation */}
          <div className="space-y-1">
            <button onClick={handleBackToIdentity} className={[
            'w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all',
            phase === 'identity'
                ? 'bg-purple-500/10 text-purple-300 border border-purple-500/20'
                : savedIdentity
                    ? 'text-white/50 hover:bg-white/[0.04] border border-transparent'
                    : 'text-white/25 border border-transparent',
        ].join(' ')}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0 ${phase === 'identity' ? 'bg-purple-500/25 text-purple-300'
            : savedIdentity ? 'bg-green-500/20 text-green-300' : 'bg-white/[0.05] text-white/20'}`}>
                {savedIdentity ? <CheckCircle2 size={10}/> : '1'}
              </span>
              {needsBodyStep ? 'Face Identity' : 'Create Identity'}
            </button>

            {needsBodyStep && (<button onClick={() => savedIdentity && setPhase('body')} disabled={!savedIdentity} className={[
                'w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all',
                phase === 'body'
                    ? 'bg-pink-500/10 text-pink-300 border border-pink-500/20'
                    : savedBody
                        ? 'text-white/50 hover:bg-white/[0.04] border border-transparent'
                        : savedIdentity
                            ? 'text-white/40 hover:bg-white/[0.04] border border-transparent'
                            : 'text-white/15 cursor-not-allowed border border-transparent',
            ].join(' ')}>
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0 ${phase === 'body' ? 'bg-pink-500/25 text-pink-300'
                : savedBody ? 'bg-green-500/20 text-green-300' : 'bg-white/[0.05] text-white/20'}`}>
                  {savedBody ? <CheckCircle2 size={10}/> : '2'}
                </span>
                {bodyFraming === 'headshot' ? 'Half Body' : 'Body Base'}
              </button>)}

            <button onClick={() => {
            if (needsBodyStep ? savedBody : savedIdentity)
                setPhase('outfit');
        }} disabled={needsBodyStep ? !savedBody : !savedIdentity} className={[
            'w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all',
            phase === 'outfit'
                ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20'
                : (needsBodyStep ? savedBody : savedIdentity)
                    ? 'text-white/50 hover:bg-white/[0.04] border border-transparent'
                    : 'text-white/15 cursor-not-allowed border border-transparent',
        ].join(' ')}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0 ${phase === 'outfit' ? 'bg-cyan-500/25 text-cyan-300' : 'bg-white/[0.05] text-white/20'}`}>
                {needsBodyStep ? '3' : '2'}
              </span>
              Style & Outfit
            </button>

            <button onClick={() => {
            if (savedBody || savedIdentity)
                setPhase('finalize');
        }} disabled={!(savedBody || savedIdentity)} className={[
            'w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all',
            phase === 'finalize'
                ? 'bg-green-500/10 text-green-300 border border-green-500/20'
                : (savedBody || savedIdentity)
                    ? 'text-white/50 hover:bg-white/[0.04] border border-transparent'
                    : 'text-white/15 cursor-not-allowed border border-transparent',
        ].join(' ')}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0 ${phase === 'finalize' ? 'bg-green-500/25 text-green-300' : 'bg-white/[0.05] text-white/20'}`}>
                {needsBodyStep ? '4' : '3'}
              </span>
              Finalize
            </button>
          </div>

          {/* Spacer */}
          <div className="flex-1"/>

          {/* Randomize (Phase 1 only) */}
          {phase === 'identity' && (<button onClick={() => {
                setSelectedGender(['female', 'male', 'neutral'][Math.floor(Math.random() * 3)]);
                const styles = charStyles;
                if (styles.length)
                    setSelectedStyle(styles[Math.floor(Math.random() * styles.length)].id);
            }} className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-xs font-medium text-white/35 hover:text-white/60 hover:bg-white/[0.04] border border-white/[0.06] transition-all">
              <Shuffle size={12}/> Randomize
            </button>)}
        </div>

        {/* ──────── CENTER PANEL: Character Stage ──────── */}
        <div className="flex flex-col min-h-0 px-4 py-4 gap-3 overflow-hidden">
          {/* Stage */}
          <div className="flex-1 min-h-0">
            <CharacterStage content={stageContent} faceLocked={phase === 'outfit' && !!(savedBody || savedIdentity)} lockedFaceUrl={(savedBody || savedIdentity) ? resolveUrlFn((savedBody || savedIdentity).url) : undefined} onOpenLightbox={onOpenLightbox} onDelete={phase === 'identity' && gen.result?.results?.length && selectedFaceIndex !== null
            ? () => handleDeleteFace(selectedFaceIndex)
            : phase === 'body' && bodyGen.result?.results?.length && selectedBodyIndex !== null
                ? () => handleDeleteBody(selectedBodyIndex)
                : phase === 'outfit' && outfitGen.result?.results?.length && selectedOutfitIndex !== null
                    ? () => handleDeleteOutfit(selectedOutfitIndex)
                    : undefined} className="h-full"/>
          </div>

          {/* Filmstrip — Phase 1 faces */}
          {phase === 'identity' && gen.result?.results && gen.result.results.length > 1 && (<FaceFilmstrip results={gen.result.results} selectedIndex={selectedFaceIndex ?? 0} onSelect={setSelectedFaceIndex} onDelete={handleDeleteFace} resolveUrl={resolveUrlFn} accent="purple"/>)}

          {/* Filmstrip — Phase 1.5 body bases */}
          {phase === 'body' && bodyGen.result?.results && bodyGen.result.results.length > 1 && (<FaceFilmstrip results={bodyGen.result.results} selectedIndex={selectedBodyIndex ?? 0} onSelect={setSelectedBodyIndex} onDelete={handleDeleteBody} resolveUrl={resolveUrlFn} accent="purple"/>)}

          {/* Filmstrip — outfits (visible in outfit + finalize phases) */}
          {(phase === 'outfit' || phase === 'finalize') && allOutfits.length > 0 && (<FaceFilmstrip results={allOutfits} selectedIndex={selectedOutfitIndex ?? 0} onSelect={setSelectedOutfitIndex} onDelete={phase === 'outfit' ? handleDeleteOutfit : undefined} resolveUrl={resolveUrlFn} accent="cyan" showScenarioTags/>)}
        </div>

        {/* ──────── RIGHT PANEL: Dynamic Controls ──────── */}
        <div className="hidden md:block border-l border-white/[0.06] overflow-y-auto scrollbar-hide">
          <div className="px-4 py-4 space-y-5">

            {phase === 'identity' ? (
        /* ═══════════ PHASE 1: IDENTITY CONTROLS (Face) ═══════════ */
        <>
                {/* Section: Gender */}
                <div>
                  <SectionLabel>Core Identity</SectionLabel>
                  <div className="flex gap-1.5">
                    {GENDER_OPTIONS.map((g) => {
                const active = selectedGender === g.id;
                return (<button key={g.id} onClick={() => setSelectedGender(g.id)} className={[
                        'flex-1 flex items-center justify-center gap-2 px-3 py-3 rounded-xl text-xs font-medium transition-all border',
                        active
                            ? 'bg-purple-500/15 text-purple-300 border-purple-500/30 shadow-[0_0_12px_rgba(168,85,247,0.15)]'
                            : 'bg-white/[0.03] text-white/45 border-white/[0.06] hover:bg-white/[0.06] hover:text-white/65',
                    ].join(' ')}>
                          <span className="text-sm">{g.icon}</span>
                          <span>{g.label}</span>
                        </button>);
            })}
                  </div>
                </div>

                {/* Section: Style & Role */}
                <div>
                  <SectionLabel>Style & Role</SectionLabel>
                  {/* Tabs: Standard / Spicy */}
                  <div className="flex items-center gap-1 mb-3 p-1 rounded-xl bg-white/[0.04] border border-white/[0.08]">
                    <button onClick={() => setVibeTab('standard')} className={[
                'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all',
                vibeTab === 'standard'
                    ? 'bg-purple-500/15 text-purple-300 border border-purple-500/25 shadow-sm'
                    : 'text-white/40 hover:text-white/60',
            ].join(' ')}>
                      <Star size={11}/> Standard
                    </button>
                    {nsfwMode && (<button onClick={() => setVibeTab('spicy')} className={[
                    'flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all',
                    vibeTab === 'spicy'
                        ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/25 shadow-[0_0_12px_rgba(244,63,94,0.15)]'
                        : 'text-white/40 hover:text-rose-300/60',
                ].join(' ')}>
                        <Flame size={11}/> Spicy
                        <span className="text-[8px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">18+</span>
                      </button>)}
                  </div>

                  {/* Style badges */}
                  <div className="grid grid-cols-2 gap-1.5">
                    {charStyles.map((s) => {
                const active = selectedStyle === s.id;
                return (<button key={s.id} onClick={() => setSelectedStyle(active ? null : s.id)} className={[
                        'flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-left transition-all border',
                        active
                            ? vibeTab === 'spicy'
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200 shadow-[0_0_12px_rgba(244,63,94,0.15)]'
                                : 'border-purple-500/30 bg-purple-500/15 text-purple-300 shadow-[0_0_12px_rgba(168,85,247,0.15)]'
                            : 'border-white/[0.06] bg-white/[0.03] text-white/50 hover:bg-white/[0.06] hover:text-white/70',
                    ].join(' ')}>
                          <span className="text-sm leading-none">{s.icon}</span>
                          <span className="text-[11px] font-medium">{s.label}</span>
                        </button>);
            })}
                  </div>
                </div>

                {/* ── Section: Appearance (always visible — critical for View Pack) ── */}
                <div>
                  <SectionLabel>Appearance</SectionLabel>
                  <div className="space-y-3">
                    {/* Skin Tone */}
                    <div>
                      <MiniLabel>Skin Tone</MiniLabel>
                      <div className="flex flex-wrap gap-2">
                        {SKIN_TONE_OPTIONS.map((o) => (<SkinSwatch key={o.key} tone={o.key} label={o.label} active={geneticsPrefs.skinTone === o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, skinTone: o.key }))}/>))}
                      </div>
                    </div>

                    {/* Hair Color + Type (side by side) */}
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <MiniLabel>Hair Color</MiniLabel>
                        <div className="flex flex-wrap gap-2">
                          {HAIR_COLOR_OPTIONS.map((o) => (<SkinSwatch key={o.key} tone={`hair_${o.key}`} label={o.label} active={geneticsPrefs.hairColor === o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, hairColor: o.key }))}/>))}
                        </div>
                      </div>
                      <div>
                        <MiniLabel>Hair Type</MiniLabel>
                        <div className="flex flex-col gap-1">
                          {HAIR_TYPE_OPTIONS.map((o) => (<OptionPill key={o.key} label={o.label} active={geneticsPrefs.hairType === o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, hairType: o.key }))}/>))}
                        </div>
                      </div>
                    </div>

                    {/* Eye Color */}
                    <div>
                      <MiniLabel>Eye Color</MiniLabel>
                      <div className="flex flex-wrap gap-2">
                        {EYE_COLOR_OPTIONS.map((o) => (<SkinSwatch key={o.key} tone={`eye_${o.key}`} label={o.label} active={eyeColor === o.key} onClick={() => setEyeColor(o.key)}/>))}
                      </div>
                    </div>
                  </div>
                </div>

                {/* ── Section: Advanced (collapsible — profession, face structure, realism, ethnicity) ── */}
                <div>
                  <button onClick={() => setShowAdvancedIdentity(!showAdvancedIdentity)} className={[
                'flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider transition-colors w-full',
                showAdvancedIdentity ? 'text-purple-300/60' : 'text-white/35 hover:text-purple-300/50',
            ].join(' ')}>
                    <ChevronLeft size={10} className={`transition-transform ${showAdvancedIdentity ? '-rotate-90' : 'rotate-180'}`}/>
                    Advanced
                    <span className="text-white/15 normal-case tracking-normal font-normal">(optional)</span>
                  </button>

                  {showAdvancedIdentity && (<div className="mt-3 space-y-3 animate-fadeSlideIn">
                      {/* Age Range */}
                      <div>
                        <MiniLabel>Age Range</MiniLabel>
                        <div className="flex gap-1">
                          {AGE_RANGE_OPTIONS.map((o) => (<OptionPill key={o.key} label={o.label} active={geneticsPrefs.ageRange === o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, ageRange: o.key }))}/>))}
                        </div>
                      </div>

                      {/* Face Structure */}
                      <div>
                        <MiniLabel>Face Structure</MiniLabel>
                        <div className="flex gap-1">
                          {FACE_BASE_OPTIONS.map((o) => (<OptionPill key={o.key} label={o.label} active={geneticsPrefs.faceBase === o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, faceBase: o.key }))}/>))}
                        </div>
                      </div>

                      {/* Realism */}
                      <div>
                        <MiniLabel>Realism</MiniLabel>
                        <div className="flex gap-1">
                          {REALISM_OPTIONS.map((o) => (<OptionPill key={o.key} label={o.label} active={String(geneticsPrefs.realism) === o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, realism: Number(o.key) }))}/>))}
                        </div>
                      </div>

                      {/* Ethnicity — dropdown */}
                      <div>
                        <MiniLabel>Ethnicity Baseline</MiniLabel>
                        <select value={geneticsPrefs.baseEthnicityPreset === 'custom' ? (geneticsPrefs.customEthnicityHint || '__custom__') : geneticsPrefs.baseEthnicityPreset} onChange={(e) => {
                    const val = e.target.value;
                    if (val === 'european_standard' || val === 'global_mixed') {
                        setGeneticsPrefs((p) => ({ ...p, baseEthnicityPreset: val, customEthnicityHint: '' }));
                    }
                    else if (val === '__custom__') {
                        setGeneticsPrefs((p) => ({ ...p, baseEthnicityPreset: 'custom', customEthnicityHint: '' }));
                    }
                    else {
                        setGeneticsPrefs((p) => ({ ...p, baseEthnicityPreset: 'custom', customEthnicityHint: val }));
                    }
                }} className="w-full px-2.5 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-[11px] text-white/70 focus:outline-none focus:border-purple-500/40 appearance-none cursor-pointer" style={{ colorScheme: 'dark', backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.3)' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 8px center' }}>
                          <option value="european_standard" className="bg-[#1a1a2e] text-white">European Standard</option>
                          <option value="global_mixed" className="bg-[#1a1a2e] text-white">Global Mixed</option>
                          <option disabled className="bg-[#1a1a2e] text-white/40">───────────</option>
                          {['Mediterranean', 'Nordic', 'South Asian', 'Southeast Asian', 'Middle Eastern', 'East Asian', 'Indigenous American', 'Pacific Islander', 'Sub-Saharan African', 'Caribbean', 'Slavic', 'Celtic', 'Iberian', 'Polynesian', 'Andean', 'Amazigh'].map((s) => (<option key={s} value={s} className="bg-[#1a1a2e] text-white">{s}</option>))}
                          <option disabled className="bg-[#1a1a2e] text-white/40">───────────</option>
                          <option value="__custom__" className="bg-[#1a1a2e] text-white">Custom...</option>
                        </select>
                        {geneticsPrefs.baseEthnicityPreset === 'custom' && !['Mediterranean', 'Nordic', 'South Asian', 'Southeast Asian', 'Middle Eastern', 'East Asian', 'Indigenous American', 'Pacific Islander', 'Sub-Saharan African', 'Caribbean', 'Slavic', 'Celtic', 'Iberian', 'Polynesian', 'Andean', 'Amazigh'].includes(geneticsPrefs.customEthnicityHint || '') && (<input value={geneticsPrefs.customEthnicityHint || ''} onChange={(e) => setGeneticsPrefs((p) => ({ ...p, customEthnicityHint: e.target.value }))} className="mt-2 w-full px-2.5 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-[11px] text-white/70 placeholder:text-white/20 focus:outline-none focus:border-purple-500/40" placeholder="e.g., Afro-Caribbean, Eurasian..." autoFocus/>)}
                      </div>

                      {/* Profession */}
                      <div>
                        <MiniLabel>Profession</MiniLabel>
                        <div className="grid grid-cols-2 gap-1.5 max-h-[140px] overflow-y-auto scrollbar-hide pr-0.5">
                          {PROFESSIONS.map((prof) => {
                    const active = selectedProfession === prof.id;
                    return (<button key={prof.id} onClick={() => setSelectedProfession(active ? null : prof.id)} className={[
                            'flex items-center gap-2 px-3 py-2 rounded-xl text-left transition-all border',
                            active
                                ? 'border-purple-500/30 bg-purple-500/10 text-purple-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.04] hover:text-white/70',
                        ].join(' ')} title={prof.description}>
                                <span className="text-sm leading-none">{prof.icon}</span>
                                <div className="flex-1 min-w-0">
                                  <span className="text-[11px] font-medium block truncate">{prof.label}</span>
                                  {prof.recommended && (<span className="text-[8px] text-yellow-400/70 font-bold uppercase">Rec</span>)}
                                </div>
                              </button>);
                })}
                        </div>
                      </div>
                    </div>)}
                </div>

                {/* Portrait Type — Half Body or Headshot */}
                <div className="border-t border-white/[0.06] pt-4">
                  <SectionLabel>Portrait Type</SectionLabel>
                  <div className="grid grid-cols-3 gap-1.5 mb-4">
                    {FRAMING_OPTIONS.map((f) => (<button key={f.id} onClick={() => setBodyFraming(f.id)} className={[
                    'flex flex-col items-center gap-1 px-2 py-2.5 rounded-xl border text-center transition-all',
                    bodyFraming === f.id
                        ? 'border-purple-500/40 bg-purple-500/15 text-purple-200 shadow-[0_0_12px_rgba(168,85,247,0.15)]'
                        : 'border-white/[0.06] bg-white/[0.03] text-white/50 hover:bg-white/[0.06] hover:text-white/70',
                ].join(' ')} title={f.description}>
                        <span className="text-base">{f.icon}</span>
                        <span className="text-[10px] font-semibold leading-tight">{f.label}</span>
                      </button>))}
                  </div>
                </div>

                {/* Count picker moved to Generate Faces split-button dropdown */}
              </>) : phase === 'body' ? (
        /* ═══════════ PHASE 1.5: BODY BASE CONTROLS ═══════════ */
        <>
                {/* Face anchor preview */}
                {savedIdentity && (<div className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                    <div className="w-10 h-10 rounded-lg overflow-hidden border border-purple-500/25 flex-shrink-0">
                      <img src={resolveUrlFn(savedIdentity.url)} alt="Face" className="w-full h-full object-cover"/>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[10px] text-purple-300/60 font-medium flex items-center gap-1">
                        <Lock size={9}/> Face Locked
                      </div>
                    </div>
                  </div>)}

                {/* Body Type */}
                <div>
                  <SectionLabel>Body Type</SectionLabel>
                  <div className="grid grid-cols-2 gap-1.5">
                    {BODY_TYPES.map((b) => (<OptionPill key={b.id} label={b.label} active={bodyType === b.id} onClick={() => setBodyType(b.id)} accent="purple"/>))}
                  </div>
                </div>

                {/* Posture / Pose */}
                <div>
                  <SectionLabel>Pose</SectionLabel>
                  <div className="grid grid-cols-2 gap-1.5">
                    {POSTURE_OPTIONS.map((p) => (<OptionPill key={p.id} label={p.label} active={bodyPosture === p.id} onClick={() => setBodyPosture(p.id)} accent="purple"/>))}
                  </div>
                </div>

                {/* Count picker moved to Generate Body split-button dropdown */}
              </>) : phase === 'outfit' ? (
        /* ═══════════ PHASE 2: OUTFIT CONTROLS ═══════════ */
        <>
                {/* Anchor preview — show body base when available (StyleGAN path), otherwise face */}
                {(savedBody || savedIdentity) && (() => {
                const anchor = savedBody || savedIdentity;
                const isBody = !!savedBody;
                return (<div className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                      <div className={`w-10 h-10 rounded-lg overflow-hidden border flex-shrink-0 ${isBody ? 'border-pink-500/25' : 'border-purple-500/25'}`}>
                        <img src={resolveUrlFn(anchor.url)} alt={isBody ? 'Body' : 'Identity'} className="w-full h-full object-cover"/>
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className={`text-[10px] font-medium flex items-center gap-1 ${isBody ? 'text-pink-300/60' : 'text-purple-300/60'}`}>
                          <Lock size={9}/> {isBody ? 'Body Anchor' : 'Identity Anchor'}
                        </div>
                      </div>
                      <button onClick={isBody ? handleBackToBody : handleBackToIdentity} className="text-[10px] text-white/25 hover:text-white/50 transition-colors" title={isBody ? 'Change body' : 'Change identity'}>
                        Change
                      </button>
                    </div>);
            })()}

                {/* ── Outfit Tab Selector: Standard / Romance & Roleplay / 18+ ── */}
                <div>
                  <SectionLabel>Outfit</SectionLabel>
                  <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.04] border border-white/[0.08] mb-3">
                    <button onClick={() => {
                setOutfitTab('standard');
                const first = OUTFIT_PRESETS.find((p) => (p.group || 'standard') === 'standard');
                setSelectedOutfitPreset(first?.id ?? 'corporate');
            }} className={[
                'flex-1 flex items-center justify-center gap-1 px-2 py-2 rounded-lg text-[10px] font-medium transition-all',
                outfitTab === 'standard'
                    ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/25 shadow-sm'
                    : 'text-white/40 hover:text-white/60',
            ].join(' ')}>
                      Standard
                    </button>
                    {nsfwMode && (<>
                        <button onClick={() => {
                    setOutfitTab('romance');
                    const first = OUTFIT_PRESETS.find((p) => p.group === 'romance');
                    setSelectedOutfitPreset(first?.id ?? null);
                }} className={[
                    'flex-1 flex items-center justify-center gap-1 px-2 py-2 rounded-lg text-[10px] font-medium transition-all',
                    outfitTab === 'romance'
                        ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/25 shadow-sm'
                        : 'text-white/40 hover:text-rose-300/60',
                ].join(' ')}>
                          Romance &amp; Roleplay
                        </button>
                        <button onClick={() => {
                    setOutfitTab('18+');
                    const first = OUTFIT_PRESETS.find((p) => p.group === '18+');
                    setSelectedOutfitPreset(first?.id ?? null);
                }} className={[
                    'flex-1 flex items-center justify-center gap-1 px-2 py-2 rounded-lg text-[10px] font-medium transition-all',
                    outfitTab === '18+'
                        ? 'bg-gradient-to-r from-red-500/20 to-rose-500/20 text-red-300 border border-red-500/25 shadow-sm'
                        : 'text-white/40 hover:text-red-300/60',
                ].join(' ')}>
                          18+
                        </button>
                      </>)}
                  </div>
                </div>

                {/* Outfit Style presets (filtered by tab) */}
                <div>
                  <SectionLabel>Outfit Style</SectionLabel>
                  <div className="grid grid-cols-2 gap-1.5">
                    {outfitPresets.map((p) => {
                const tagMeta = SCENARIO_TAG_META.find((t) => t.id === p.id);
                const active = selectedOutfitPreset === p.id;
                const isNsfw = p.category === 'nsfw';
                return (<button key={p.id} onClick={() => {
                        setSelectedOutfitPreset(active ? null : p.id);
                        if (!active)
                            setCustomOutfitPrompt('');
                    }} className={[
                        'flex items-center gap-2 px-3 py-2.5 rounded-xl text-left transition-all border',
                        active
                            ? isNsfw
                                ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                                : 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
                            : 'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.04] hover:text-white/70',
                    ].join(' ')} title={p.prompt}>
                          <span className="text-sm leading-none">{tagMeta?.icon || '\u2728'}</span>
                          <span className="text-[11px] font-medium">{p.label}</span>
                        </button>);
            })}
                  </div>
                  {/* Selected preset description */}
                  {selectedOutfitPreset && (() => {
                const sel = outfitPresets.find((p) => p.id === selectedOutfitPreset);
                if (!sel)
                    return null;
                const tagMeta = SCENARIO_TAG_META.find((t) => t.id === sel.id);
                return (<div className="mt-2 px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.06] animate-fadeIn">
                        <div className="flex items-center gap-1.5 mb-1">
                          <span className="text-sm">{tagMeta?.icon || '\u2728'}</span>
                          <span className="text-[10px] font-semibold text-white/60">{sel.label}</span>
                        </div>
                        <p className="text-[10px] text-white/30 italic leading-relaxed">{sel.prompt}</p>
                      </div>);
            })()}
                </div>

                {/* Primary / Secondary Colors */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <MiniLabel>Primary Color</MiniLabel>
                    <div className="flex flex-wrap gap-1.5">
                      {['black', 'white', 'navy', 'red', 'burgundy', 'grey', 'blush', 'emerald'].map((c) => (<button key={c} onClick={() => setOutfitPrimaryColor(outfitPrimaryColor === c ? null : c)} className={[
                    'w-6 h-6 rounded-full border-2 transition-all',
                    outfitPrimaryColor === c ? 'border-cyan-400 scale-110 ring-2 ring-cyan-400/30' : 'border-white/10 hover:border-white/30',
                ].join(' ')} style={{ backgroundColor: { black: '#1a1a1a', white: '#f0f0f0', navy: '#1e3a5f', red: '#dc2626', burgundy: '#7f1d1d', grey: '#6b7280', blush: '#fbcfe8', emerald: '#059669' }[c] }} title={c}/>))}
                    </div>
                  </div>
                  <div>
                    <MiniLabel>Secondary Color</MiniLabel>
                    <div className="flex flex-wrap gap-1.5">
                      {['black', 'white', 'navy', 'red', 'burgundy', 'grey', 'blush', 'emerald'].map((c) => (<button key={c} onClick={() => setOutfitSecondaryColor(outfitSecondaryColor === c ? null : c)} className={[
                    'w-6 h-6 rounded-full border-2 transition-all',
                    outfitSecondaryColor === c ? 'border-cyan-400 scale-110 ring-2 ring-cyan-400/30' : 'border-white/10 hover:border-white/30',
                ].join(' ')} style={{ backgroundColor: { black: '#1a1a1a', white: '#f0f0f0', navy: '#1e3a5f', red: '#dc2626', burgundy: '#7f1d1d', grey: '#6b7280', blush: '#fbcfe8', emerald: '#059669' }[c] }} title={c}/>))}
                    </div>
                  </div>
                </div>

                {/* Accessories */}
                <div>
                  <MiniLabel>Accessories</MiniLabel>
                  <div className="flex flex-wrap gap-1.5">
                    {ACCESSORY_OPTIONS.map((a) => {
                const active = selectedAccessories.includes(a.id);
                return (<button key={a.id} onClick={() => toggleAccessory(a.id)} className={[
                        'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all',
                        active
                            ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
                            : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.04]',
                    ].join(' ')}>
                          <span>{a.icon}</span> {a.label}
                        </button>);
            })}
                  </div>
                </div>

                {/* ── NSFW Advanced Controls (18+ gated, collapsible) ── */}
                {nsfwMode && (outfitTab === 'romance' || outfitTab === '18+') && (<div className="border-t border-rose-500/20 pt-3">
                    <button onClick={() => setShowNsfwAdvanced(!showNsfwAdvanced)} className="flex items-center gap-2 text-[10px] text-rose-400 font-bold uppercase tracking-wider w-full">
                      <ChevronLeft size={10} className={`transition-transform ${showNsfwAdvanced ? '-rotate-90' : 'rotate-180'}`}/>
                      Adult Content Controls
                      <span className="text-[8px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold ml-1">18+</span>
                    </button>

                    {showNsfwAdvanced && (<div className="mt-3 space-y-4 animate-fadeSlideIn">
                        {/* Nudity / Exposure Level */}
                        <div>
                          <MiniLabel>Nudity / Exposure Level</MiniLabel>
                          <div className="grid grid-cols-2 gap-1.5">
                            {NUDITY_LEVELS.map((nl) => (<button key={nl.id} onClick={() => setNudityLevel(nudityLevel === nl.id ? null : nl.id)} className={[
                            'px-2.5 py-2 rounded-lg text-[10px] font-medium border transition-all text-center',
                            nudityLevel === nl.id
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.05]',
                        ].join(' ')}>
                                {nl.label}
                              </button>))}
                          </div>
                        </div>

                        {/* Explicitness Intensity Slider */}
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <MiniLabel className="mb-0">Explicitness Intensity</MiniLabel>
                            <span className="text-[10px] text-rose-300/60 font-mono">{explicitnessIntensity}</span>
                          </div>
                          <input type="range" min={0} max={10} value={explicitnessIntensity} onChange={(e) => setExplicitnessIntensity(Number(e.target.value))} className="w-full accent-rose-500 h-1.5"/>
                        </div>

                        {/* Sensual Pose */}
                        <div>
                          <MiniLabel>Sensual Pose</MiniLabel>
                          <div className="grid grid-cols-3 gap-1.5">
                            {SENSUAL_POSES.map((sp) => (<button key={sp.id} onClick={() => setSensualPose(sensualPose === sp.id ? null : sp.id)} className={[
                            'px-2 py-2 rounded-lg text-[10px] font-medium border transition-all text-center',
                            sensualPose === sp.id
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.05]',
                        ].join(' ')}>
                                {sp.label}
                              </button>))}
                          </div>
                        </div>

                        {/* Power Dynamic */}
                        <div>
                          <MiniLabel>Power Dynamic</MiniLabel>
                          <div className="flex gap-1.5">
                            {POWER_DYNAMICS.map((pd) => (<button key={pd.id} onClick={() => setPowerDynamic(powerDynamic === pd.id ? null : pd.id)} className={[
                            'flex-1 px-2 py-2 rounded-lg text-[10px] font-medium border transition-all text-center',
                            powerDynamic === pd.id
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.05]',
                        ].join(' ')}>
                                {pd.label}
                              </button>))}
                          </div>
                        </div>

                        {/* Fantasy Tone */}
                        <div>
                          <MiniLabel>Fantasy Tone</MiniLabel>
                          <div className="flex gap-1.5">
                            {FANTASY_TONES.map((ft) => (<button key={ft.id} onClick={() => setFantasyTone(fantasyTone === ft.id ? null : ft.id)} className={[
                            'flex-1 px-2 py-2 rounded-lg text-[10px] font-medium border transition-all text-center',
                            fantasyTone === ft.id
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.05]',
                        ].join(' ')}>
                                {ft.label}
                              </button>))}
                          </div>
                        </div>

                        {/* Scene / Setting */}
                        <div>
                          <MiniLabel>Scene / Setting</MiniLabel>
                          <div className="grid grid-cols-2 gap-1.5">
                            {SCENE_SETTINGS.map((ss) => (<button key={ss.id} onClick={() => setSceneSetting(sceneSetting === ss.id ? null : ss.id)} className={[
                            'px-2.5 py-2 rounded-lg text-[10px] font-medium border transition-all text-center',
                            sceneSetting === ss.id
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.05]',
                        ].join(' ')}>
                                {ss.label}
                              </button>))}
                          </div>
                        </div>
                      </div>)}
                  </div>)}

                {/* Custom outfit prompt */}
                <div>
                  <SectionLabel>Or Custom Outfit</SectionLabel>
                  <div className={[
                'flex items-center gap-2 px-3 py-2.5 rounded-xl border transition-all',
                'bg-white/[0.03] focus-within:bg-white/[0.05]',
                'border-white/[0.08] focus-within:border-cyan-500/30 focus-within:ring-1 focus-within:ring-cyan-500/15',
            ].join(' ')}>
                    <PenLine size={13} className="text-white/20 flex-shrink-0"/>
                    <input value={customOutfitPrompt} onChange={(e) => {
                setCustomOutfitPrompt(e.target.value);
                if (e.target.value.trim())
                    setSelectedOutfitPreset(null);
            }} placeholder="Describe custom clothing..." className="flex-1 bg-transparent text-white text-xs placeholder:text-white/20 focus:outline-none" onKeyDown={(e) => {
                if (e.key === 'Enter' && effectiveOutfitPrompt) {
                    e.preventDefault();
                    handleGenerateOutfits();
                }
            }}/>
                  </div>
                </div>

                {/* Count picker moved to Generate Outfit split-button dropdown */}
              </>) : phase === 'finalize' ? (
        /* ═══════════ PHASE 4: FINALIZE ═══════════ */
        <>
                {/* Avatar hero card — MMORPG completion screen */}
                <div className="rounded-xl border border-purple-500/20 bg-gradient-to-b from-purple-500/8 to-transparent overflow-hidden">
                  {/* Header */}
                  <div className="px-4 py-2.5 border-b border-purple-500/15 flex items-center gap-2">
                    <CheckCircle2 size={14} className="text-purple-400"/>
                    <span className="text-xs font-semibold text-purple-300/80 uppercase tracking-wider">Avatar Complete</span>
                    {allOutfits.length > 0 && (<span className="ml-auto text-[9px] px-2 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300/70 font-medium">
                        {allOutfits.length} outfit{allOutfits.length !== 1 ? 's' : ''}
                      </span>)}
                  </div>
                  {/* Hero preview */}
                  {(() => {
                const outfitResult = allOutfits.length && selectedOutfitIndex !== null
                    ? allOutfits[selectedOutfitIndex] : null;
                const displayAnchor = outfitResult
                    ? { url: outfitResult.url, label: selectedOutfitPreset ? (SCENARIO_TAG_META.find((t) => t.id === selectedOutfitPreset)?.label || 'Custom outfit') : 'Custom outfit' }
                    : savedBody
                        ? { url: savedBody.url, label: 'Half-body base' }
                        : savedIdentity
                            ? { url: savedIdentity.url, label: 'Face identity' }
                            : null;
                return displayAnchor ? (<div className="p-3">
                        <div className="relative aspect-[3/4] max-h-[200px] w-full rounded-lg overflow-hidden border border-purple-500/15 bg-black/30 mx-auto">
                          <img src={resolveUrlFn(displayAnchor.url)} alt="Avatar" className="w-full h-full object-cover"/>
                          {/* Label overlay */}
                          <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 via-black/30 to-transparent px-3 py-2">
                            <span className="text-[10px] text-white/70 font-medium">{displayAnchor.label}</span>
                          </div>
                        </div>
                        {/* Face + body mini anchors */}
                        <div className="flex items-center justify-center gap-2 mt-2">
                          {savedIdentity && (<div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-white/[0.03] border border-white/[0.06]">
                              <div className="w-5 h-5 rounded-full overflow-hidden border border-purple-500/30">
                                <img src={resolveUrlFn(savedIdentity.url)} alt="Face" className="w-full h-full object-cover"/>
                              </div>
                              <span className="text-[9px] text-white/35">Face</span>
                            </div>)}
                          {savedBody && (<div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-white/[0.03] border border-white/[0.06]">
                              <div className="w-5 h-5 rounded-full overflow-hidden border border-pink-500/30">
                                <img src={resolveUrlFn(savedBody.url)} alt="Body" className="w-full h-full object-cover"/>
                              </div>
                              <span className="text-[9px] text-white/35">Body</span>
                            </div>)}
                        </div>
                      </div>) : null;
            })()}
                </div>

                {/* Character Sheet Summary */}
                <div className="rounded-xl border border-white/[0.08] bg-white/[0.02] overflow-hidden">
                  {/* Sheet header */}
                  <div className="px-3.5 py-2 border-b border-white/[0.06] bg-white/[0.02]">
                    <div className="text-[9px] font-bold text-white/30 uppercase tracking-wider">Character Sheet</div>
                  </div>
                  <div className="px-3.5 py-3 space-y-2 text-[11px]">
                    {/* Stats rows */}
                    {[
                { label: 'Gender', value: selectedGender || 'Not set', icon: selectedGender === 'female' ? '\uD83D\uDC69' : selectedGender === 'male' ? '\uD83D\uDC68' : '\uD83E\uDDD1' },
                { label: 'Style', value: selectedStyle ? (CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle)?.label || selectedStyle) : 'Default', icon: CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle)?.icon || '\u2728' },
                { label: 'Class', value: selectedProfession ? (PROFESSIONS.find((p) => p.id === selectedProfession)?.label || 'Custom') : 'Not set', icon: PROFESSIONS.find((p) => p.id === selectedProfession)?.icon || '\u2753' },
                ...(needsBodyStep ? [{ label: 'Build', value: `${bodyType} / ${bodyPosture}`, icon: '\uD83C\uDFCB\uFE0F' }] : []),
                { label: 'Outfit', value: outfitGen.result?.results?.length ? (selectedOutfitPreset ? (SCENARIO_TAG_META.find((t) => t.id === selectedOutfitPreset)?.label || 'Custom') : (customOutfitPrompt || 'Custom')) : 'None', icon: outfitGen.result?.results?.length ? (SCENARIO_TAG_META.find((t) => t.id === selectedOutfitPreset)?.icon || '\uD83D\uDC55') : '\u2796' },
                { label: 'Outfits', value: `${allOutfits.length} generated`, icon: '\uD83D\uDC57' },
            ].map((row) => (<div key={row.label} className="flex items-center gap-2.5">
                        <span className="text-sm w-5 text-center leading-none">{row.icon}</span>
                        <span className="text-white/30 w-14 flex-shrink-0">{row.label}</span>
                        <span className="text-white/60 capitalize flex-1 truncate">{row.value}</span>
                      </div>))}
                  </div>
                </div>

                {/* Next steps hint */}
                <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg bg-purple-500/5 border border-purple-500/10">
                  <Sparkles size={12} className="text-purple-400/50 mt-0.5 flex-shrink-0"/>
                  <p className="text-[10px] text-white/30 leading-relaxed">
                    Save to open the <span className="text-purple-300/60 font-medium">Character Sheet</span> where you can generate more outfits and manage your wardrobe.
                  </p>
                </div>
              </>) : null}
          </div>
        </div>
      </div>

      {/* ═══════════ BOTTOM ACTION BAR ═══════════ */}
      <div className="flex-shrink-0 border-t border-white/[0.06] px-5 py-3 flex items-center justify-between">
        {phase === 'identity' ? (<>
            <div className="flex items-center gap-2 text-[10px] text-white/20">
              <span>Ctrl+Enter to generate</span>
            </div>
            <div className="flex items-center gap-3">
              {/* Generate Faces — split button with count dropdown */}
              <div className="relative flex items-stretch">
                <button onClick={handleGenerateFaces} disabled={gen.loading} className={[
                'flex items-center gap-2 pl-5 pr-3 py-2.5 rounded-l-xl text-sm font-semibold transition-all',
                !gen.loading
                    ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:brightness-110 active:scale-[0.98]'
                    : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
            ].join(' ')}>
                  {gen.loading ? (<><Loader2 size={16} className="animate-spin"/> Generating...</>) : (<><Sparkles size={16}/> Generate Faces ({faceCount})</>)}
                </button>
                <div className="relative">
                  <button onClick={() => setShowFaceCountMenu(!showFaceCountMenu)} className={[
                'h-full px-2.5 rounded-r-xl border-l transition-all flex items-center',
                !gen.loading
                    ? 'bg-gradient-to-r from-pink-600 to-pink-700 border-white/10 text-white/80 hover:text-white'
                    : 'bg-white/[0.06] border-white/5 text-white/15 cursor-not-allowed',
            ].join(' ')} disabled={gen.loading}>
                    <ChevronDown size={14}/>
                  </button>
                  {showFaceCountMenu && (<>
                      <div className="fixed inset-0 z-30" onClick={() => setShowFaceCountMenu(false)}/>
                      <div className="absolute right-0 bottom-full mb-1 bg-[#1a1a1a] border border-white/10 rounded-lg shadow-2xl z-40 overflow-hidden min-w-[80px]">
                        {[1, 4, 8].map((n) => (<button key={n} onClick={() => { setFaceCount(n); setShowFaceCountMenu(false); }} className={[
                        'w-full px-4 py-2 text-left text-sm transition-colors',
                        faceCount === n ? 'bg-purple-500/15 text-purple-300 font-medium' : 'text-white/60 hover:bg-white/5 hover:text-white/80',
                    ].join(' ')}>
                            {n} image{n > 1 ? 's' : ''}
                          </button>))}
                      </div>
                    </>)}
                </div>
              </div>

              {/* Save Identity (only when face selected) */}
              {gen.result?.results?.length && selectedFaceIndex !== null ? (<button onClick={handleSaveIdentity} className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-green-600 to-emerald-600 text-white shadow-lg shadow-green-500/20 hover:shadow-green-500/30 hover:brightness-110 active:scale-[0.98] transition-all">
                  <CheckCircle2 size={16}/> {needsBodyStep ? 'Save Face & Continue' : 'Save Identity & Continue'}
                </button>) : null}

              {gen.loading && (<button onClick={gen.cancel} className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl text-sm font-medium border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all">
                  <X size={14}/> Cancel
                </button>)}
            </div>
          </>) : phase === 'body' ? (
        /* ═══════════ BODY PHASE ACTION BAR ═══════════ */
        <>
            <button onClick={handleBackToIdentity} className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium text-white/50 hover:text-white/70 hover:bg-white/[0.04] transition-all">
              <ChevronLeft size={14}/> Change Face
            </button>
            <div className="flex items-center gap-3">
              {/* Generate Body — split button with count dropdown */}
              <div className="relative flex items-stretch">
                <button onClick={handleGenerateBody} disabled={bodyGen.loading} className={[
                'flex items-center gap-2 pl-5 pr-3 py-2.5 rounded-l-xl text-sm font-semibold transition-all',
                !bodyGen.loading
                    ? 'bg-gradient-to-r from-pink-600 to-purple-600 text-white shadow-lg shadow-pink-500/20 hover:shadow-pink-500/30 hover:brightness-110 active:scale-[0.98]'
                    : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
            ].join(' ')}>
                  {bodyGen.loading ? (<><Loader2 size={16} className="animate-spin"/> Generating...</>) : (<><User size={16}/> {bodyFraming === 'headshot' ? 'Generate Half Body' : 'Generate Body'} ({bodyCount})</>)}
                </button>
                <div className="relative">
                  <button onClick={() => setShowBodyCountMenu(!showBodyCountMenu)} className={[
                'h-full px-2.5 rounded-r-xl border-l transition-all flex items-center',
                !bodyGen.loading
                    ? 'bg-gradient-to-r from-purple-600 to-purple-700 border-white/10 text-white/80 hover:text-white'
                    : 'bg-white/[0.06] border-white/5 text-white/15 cursor-not-allowed',
            ].join(' ')} disabled={bodyGen.loading}>
                    <ChevronDown size={14}/>
                  </button>
                  {showBodyCountMenu && (<>
                      <div className="fixed inset-0 z-30" onClick={() => setShowBodyCountMenu(false)}/>
                      <div className="absolute right-0 bottom-full mb-1 bg-[#1a1a1a] border border-white/10 rounded-lg shadow-2xl z-40 overflow-hidden min-w-[80px]">
                        {[1, 4, 8].map((n) => (<button key={n} onClick={() => { setBodyCount(n); setShowBodyCountMenu(false); }} className={[
                        'w-full px-4 py-2 text-left text-sm transition-colors',
                        bodyCount === n ? 'bg-pink-500/15 text-pink-300 font-medium' : 'text-white/60 hover:bg-white/5 hover:text-white/80',
                    ].join(' ')}>
                            {n} image{n > 1 ? 's' : ''}
                          </button>))}
                      </div>
                    </>)}
                </div>
              </div>

              {bodyGen.result?.results?.length && selectedBodyIndex !== null ? (<button onClick={handleSaveBody} className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-green-600 to-emerald-600 text-white shadow-lg shadow-green-500/20 hover:shadow-green-500/30 hover:brightness-110 active:scale-[0.98] transition-all">
                  <CheckCircle2 size={16}/> Save Body & Continue
                </button>) : null}

              {bodyGen.loading && (<button onClick={bodyGen.cancel} className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl text-sm font-medium border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all">
                  <X size={14}/> Cancel
                </button>)}
            </div>
          </>) : phase === 'outfit' ? (
        /* ═══════════ OUTFIT PHASE ACTION BAR ═══════════ */
        <>
            <button onClick={needsBodyStep ? handleBackToBody : handleBackToIdentity} className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium text-white/50 hover:text-white/70 hover:bg-white/[0.04] transition-all">
              <ChevronLeft size={14}/> {needsBodyStep ? 'Change Body' : 'Change Face'}
            </button>
            <div className="flex items-center gap-3">
              {/* Generate Outfit — split button with count dropdown */}
              <div className="relative flex items-stretch">
                <button onClick={handleGenerateOutfits} disabled={outfitGen.loading || !effectiveOutfitPrompt} className={[
                'flex items-center gap-2 pl-5 pr-3 py-2.5 rounded-l-xl text-sm font-semibold transition-all',
                !outfitGen.loading && effectiveOutfitPrompt
                    ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-lg shadow-cyan-500/20 hover:shadow-cyan-500/25 hover:brightness-110 active:scale-[0.98]'
                    : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
            ].join(' ')}>
                  {outfitGen.loading ? (<><Loader2 size={16} className="animate-spin"/> Generating...</>) : (<><Shirt size={16}/> Generate Outfit ({outfitCount})</>)}
                </button>
                <div className="relative">
                  <button onClick={() => setShowOutfitCountMenu(!showOutfitCountMenu)} className={[
                'h-full px-2.5 rounded-r-xl border-l transition-all flex items-center',
                !outfitGen.loading && effectiveOutfitPrompt
                    ? 'bg-gradient-to-r from-blue-600 to-blue-700 border-white/10 text-white/80 hover:text-white'
                    : 'bg-white/[0.06] border-white/5 text-white/15 cursor-not-allowed',
            ].join(' ')} disabled={outfitGen.loading || !effectiveOutfitPrompt}>
                    <ChevronDown size={14}/>
                  </button>
                  {showOutfitCountMenu && (<>
                      <div className="fixed inset-0 z-30" onClick={() => setShowOutfitCountMenu(false)}/>
                      <div className="absolute right-0 bottom-full mb-1 bg-[#1a1a1a] border border-white/10 rounded-lg shadow-2xl z-40 overflow-hidden min-w-[80px]">
                        {[1, 4, 8].map((n) => (<button key={n} onClick={() => { setOutfitCount(n); setShowOutfitCountMenu(false); }} className={[
                        'w-full px-4 py-2 text-left text-sm transition-colors',
                        outfitCount === n ? 'bg-cyan-500/15 text-cyan-300 font-medium' : 'text-white/60 hover:bg-white/5 hover:text-white/80',
                    ].join(' ')}>
                            {n} image{n > 1 ? 's' : ''}
                          </button>))}
                      </div>
                    </>)}
                </div>
              </div>

              {/* Continue to Finalize */}
              {outfitGen.result?.results?.length && selectedOutfitIndex !== null ? (<button onClick={() => setPhase('finalize')} className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-green-600 to-emerald-600 text-white shadow-lg shadow-green-500/20 hover:shadow-green-500/30 hover:brightness-110 active:scale-[0.98] transition-all">
                  <CheckCircle2 size={16}/> Continue
                </button>) : null}

              {outfitGen.loading && (<button onClick={outfitGen.cancel} className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl text-sm font-medium border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all">
                  <X size={14}/> Cancel
                </button>)}
            </div>
          </>) : phase === 'finalize' ? (
        /* ═══════════ FINALIZE PHASE ACTION BAR ═══════════ */
        <>
            <div className="flex items-center gap-2">
              <button onClick={() => setPhase(savedBody ? 'body' : 'identity')} className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium text-white/50 hover:text-white/70 hover:bg-white/[0.04] transition-all">
                <ChevronLeft size={14}/> Back
              </button>
              {(savedBody || savedIdentity) && (<button onClick={() => setPhase('outfit')} className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-cyan-500/25 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 transition-all">
                  <Shirt size={14}/> {outfitGen.result?.results?.length ? 'Change Outfit' : 'Add Outfit'}
                </button>)}
            </div>
            <div className="flex items-center gap-2">
              {/* Export to Persona — quick path from avatar to character */}
              {onSaveAsPersonaAvatar && savedIdentity && (<button onClick={() => {
                    const outfitItems = gallery.items.filter((i) => i.parentId === savedIdentity.id && i.scenarioTag);
                    const batchSiblings = gallery.items.filter((i) => i.batchId === savedIdentity.batchId && i.id !== savedIdentity.id && i.role === 'portrait');
                    onSaveAsPersonaAvatar(savedIdentity, outfitItems, batchSiblings);
                }} className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-emerald-500/25 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-all">
                  <Star size={14}/> Export to Persona
                </button>)}
              <button onClick={() => {
                showToast('Avatar saved!', 'success');
                if (onOpenViewer && savedIdentity) {
                    // Navigate to the avatar viewer to view/manage outfits
                    setTimeout(() => onOpenViewer(savedIdentity), 400);
                }
                else {
                    setTimeout(() => onClose(), 800);
                }
            }} className="flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-purple-600 to-violet-600 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:brightness-110 active:scale-[0.98] transition-all">
                <CheckCircle2 size={16}/> {onOpenViewer ? 'Save & Open Wardrobe' : 'Save Avatar'}
              </button>
            </div>
          </>) : null}
      </div>

      {/* ═══════════ TOAST ═══════════ */}
      {toast && (<div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-toastSlideUp">
          <div className={[
                'flex items-center gap-2.5 px-5 py-3 rounded-xl shadow-2xl backdrop-blur-md border text-sm font-medium',
                toast.type === 'error' ? 'bg-red-500/15 border-red-500/20 text-red-300'
                    : toast.type === 'success' ? 'bg-green-500/15 border-green-500/20 text-green-300'
                        : 'bg-white/10 border-white/10 text-white/70',
            ].join(' ')}>
            {toast.type === 'success' && <Sparkles size={16}/>}
            <span>{toast.message}</span>
            {deletedOutfit && (<button onClick={handleUndoDeleteOutfit} className="ml-1 px-2.5 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-xs font-semibold text-white/80 transition-all">
                Undo
              </button>)}
            <button onClick={() => setToast(null)} className="ml-2 text-white/30 hover:text-white/60"><X size={14}/></button>
          </div>
        </div>)}

      <style>{`
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        .animate-fadeSlideIn { animation: fadeSlideIn 0.35s ease-out; }
        @keyframes toastSlideUp { from { opacity: 0; transform: translate(-50%, 16px); } to { opacity: 1; transform: translate(-50%, 0); } }
        .animate-toastSlideUp { animation: toastSlideUp 0.25s ease-out; }
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>);
}
// ---------------------------------------------------------------------------
// Shared UI primitives
// ---------------------------------------------------------------------------
function SectionLabel({ children }) {
    return <div className="text-[10px] text-purple-300/50 font-semibold uppercase tracking-wider mb-2.5">{children}</div>;
}
function MiniLabel({ children, className = '' }) {
    return <div className={`text-[10px] text-white/35 font-medium mb-1.5 ${className}`}>{children}</div>;
}
function OptionPill({ label, active, onClick, accent = 'purple' }) {
    const colors = {
        purple: active ? 'bg-purple-500/15 text-purple-300 border-purple-500/30 shadow-[0_0_8px_rgba(168,85,247,0.1)]' : '',
        rose: active ? 'bg-rose-500/15 text-rose-300 border-rose-500/30 shadow-[0_0_8px_rgba(244,63,94,0.1)]' : '',
        cyan: active ? 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30 shadow-[0_0_8px_rgba(6,182,212,0.1)]' : '',
    };
    return (<button onClick={onClick} className={[
            'flex-1 px-3 py-2.5 rounded-xl text-[11px] font-medium border transition-all min-w-0',
            active ? colors[accent]
                : 'bg-white/[0.03] border-white/[0.06] text-white/45 hover:bg-white/[0.06] hover:text-white/65',
        ].join(' ')}>
      {label}
    </button>);
}
/** Skin tone swatch — renders a colored circle instead of text. */
const SKIN_TONE_COLORS = {
    espresso: '#3B1E0A', mocha: '#5C3A1E', umber: '#7A5230',
    sienna: '#A07040', olive: '#B8A060', sand: '#D2B88C',
    ivory: '#F0DCC0', cream: '#FFF0DC',
    // Hair colors
    hair_black: '#1a1a1a', hair_brown: '#5C3317', hair_blonde: '#D4A84B',
    hair_auburn: '#922724', hair_neon_blue: '#00BFFF', hair_fuchsia: '#FF00FF',
    // Eye colors
    eye_brown: '#634E34', eye_blue: '#2E86C1', eye_green: '#2E8B57',
    eye_hazel: '#8E7618', eye_amber: '#BF8A30', eye_grey: '#8E9196',
};
function SkinSwatch({ tone, active, onClick, label }) {
    return (<button onClick={onClick} title={label} className={[
            'w-8 h-8 rounded-full border-2 transition-all flex-shrink-0',
            active
                ? 'border-purple-400 scale-110 shadow-[0_0_10px_rgba(168,85,247,0.4)]'
                : 'border-white/10 hover:border-white/30 hover:scale-105',
        ].join(' ')} style={{ backgroundColor: SKIN_TONE_COLORS[tone] || '#888' }}/>);
}
