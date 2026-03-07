/**
 * CharacterWizard — 7-step professional character creation wizard.
 *
 * Steps: Identity, Body, Face, Hair, Profession, Outfit, Generate
 *
 * Features:
 *   - Quick Create mode (name + gender + profession → generate)
 *   - Full Studio mode (all 7 steps with presets + advanced)
 *   - NSFW gated by global setting (Romance & Roleplay 18+)
 *   - Keeps 3 generation modes: Design Character, From Reference, Face + Style
 *   - Live character card preview (right panel)
 *   - Prompt builder assembles all choices into diffusion-friendly prompt
 */

import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import {
  X,
  ChevronRight,
  ChevronLeft,
  Sparkles,
  Loader2,
  User,
  Palette,
  Camera,
  CheckCircle2,
  EyeOff,
  Shuffle,
  Zap,
  Layers,
  Check,
  ChevronDown,
  Star,
  Flame,
  Plus,
  Settings,
  RotateCcw,
} from 'lucide-react'

import type { CharacterDraft, PresetOption } from './wizardTypes'
import {
  DEFAULT_DRAFT,
  WIZARD_STEPS,
  SKIN_TONES,
  EYE_COLORS,
  EYE_SHAPES,
  FACE_PRESETS,
  HAIR_STYLES,
  HAIR_COLORS,
  OUTFIT_STYLES_SFW,
  OUTFIT_STYLES_NSFW,
  COLOR_PALETTE,
  ACCESSORIES,
  POSES,
  BACKGROUNDS,
  LIGHTING_OPTIONS,
  EXPRESSIONS,
  NSFW_POSES,
  NSFW_BACKGROUNDS,
  findPreset,
} from './wizardTypes'
import { PROFESSIONS, getProfession } from './professionRegistry'
import { loadVibeTab, saveVibeTab } from '../vibeTabPersistence'
import type { VibeTab } from '../vibeTabPersistence'
import { useGenerateAvatars } from '../useGenerateAvatars'
import { useAvatarGallery } from '../useAvatarGallery'
import { loadAvatarSettings, resolveCheckpoint } from '../AvatarSettingsPanel'
import { resolveFileUrl } from '../../resolveFileUrl'
import type { AvatarMode, AvatarResult } from '../types'

import {
  AVATAR_VIBE_PRESETS,
  CHARACTER_STYLE_PRESETS,
  GENDER_OPTIONS,
  buildCharacterPrompt,
} from '../galleryTypes'
import type { CharacterGender } from '../galleryTypes'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface CharacterWizardProps {
  backendUrl: string
  apiKey?: string
  globalModelImages?: string
  /** @deprecated — no longer used; the wizard reads localStorage directly for reactivity. */
  nsfwEnabled?: boolean
  onClose: () => void
  /** Callback: save selected anchor + non-selected portraits atomically */
  onSaveGeneration?: (anchor: AvatarResult, portraits: AvatarResult[], mode: AvatarMode, prompt?: string, referenceUrl?: string, nsfw?: boolean, wizardMeta?: import('../galleryTypes').WizardMeta) => void
}

// ---------------------------------------------------------------------------
// Shared UI helpers
// ---------------------------------------------------------------------------

function PillButton({ label, selected, onClick, icon, accent = 'purple' }: {
  label: string; selected: boolean; onClick: () => void; icon?: string; accent?: 'purple' | 'rose'
}) {
  const colors = {
    purple: selected ? 'bg-purple-500/15 text-purple-300 border-purple-500/30' : '',
    rose: selected ? 'bg-rose-500/15 text-rose-300 border-rose-500/30' : '',
  }
  return (
    <button onClick={onClick}
      className={[
        'px-3.5 py-2.5 rounded-xl text-xs font-medium transition-all border',
        selected ? colors[accent]
          : 'bg-white/[0.03] text-white/45 border-white/[0.06] hover:bg-white/[0.06] hover:text-white/65',
      ].join(' ')}
    >
      {icon && <span className="mr-1.5">{icon}</span>}{label}
    </button>
  )
}

function ColorSwatch({ color, selected, onClick, label }: {
  color: string; selected: boolean; onClick: () => void; label?: string
}) {
  return (
    <button onClick={onClick} title={label}
      className={[
        'w-7 h-7 rounded-full border-2 transition-all flex-shrink-0',
        selected
          ? 'border-purple-400 scale-110 shadow-[0_0_8px_rgba(168,85,247,0.4)]'
          : 'border-white/10 hover:border-white/30 hover:scale-105',
      ].join(' ')}
      style={{ backgroundColor: color }}
    />
  )
}

function SliderField({ label, value, min, max, step, onChange, unit }: {
  label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; unit?: string
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between">
        <span className="text-[10px] text-white/40 font-medium">{label}</span>
        <span className="text-[10px] text-white/25 tabular-nums">{value}{unit}</span>
      </div>
      <input type="range" min={min} max={max} step={step ?? 1} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-purple-500 h-1.5 rounded-full bg-white/[0.06]" />
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] text-white/35 font-semibold uppercase tracking-wider mb-3">{children}</div>
}

function AdvancedToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle}
      className="flex items-center gap-1.5 text-[10px] text-white/25 hover:text-white/45 font-medium uppercase tracking-wider transition-colors mt-4 mb-2"
    >
      <ChevronRight size={10} className={`transition-transform ${open ? 'rotate-90' : ''}`} />
      Advanced
    </button>
  )
}

// ---------------------------------------------------------------------------
// Prompt builder
// ---------------------------------------------------------------------------

function buildPrompt(d: CharacterDraft, nsfwEnabled: boolean): string {
  const parts: string[] = []

  // Portrait framing
  const framing: Record<string, string> = {
    headshot: 'headshot portrait, face closeup',
    half_body: 'upper body portrait, from waist up',
    full_body: 'full body portrait',
  }
  parts.push(framing[d.portraitType] || framing.headshot)

  // Single subject + camera
  parts.push('single person, front-facing, looking at camera')

  // Gender + age
  const genderWord = d.gender === 'neutral' ? 'androgynous person' : d.gender === 'female' ? 'woman' : 'man'
  const ageWord = d.ageRange === 'young_adult' ? 'young adult' : d.ageRange === 'mature' ? 'mature' : 'adult'
  parts.push(`${ageWord} ${genderWord}`)

  // Body
  parts.push(`${d.bodyType} build`)
  parts.push(`${d.posture} posture`)

  // Skin
  const skin = findPreset(SKIN_TONES, d.skinTone)
  if (skin) parts.push(skin.prompt)

  // Face
  const face = findPreset(FACE_PRESETS, d.facePreset)
  if (face) parts.push(face.prompt)

  // Eyes
  const eyeC = findPreset(EYE_COLORS, d.eyeColor)
  if (eyeC) parts.push(eyeC.prompt)
  const eyeS = findPreset(EYE_SHAPES, d.eyeShape)
  if (eyeS) parts.push(eyeS.prompt)

  // Expression
  const expr = findPreset(EXPRESSIONS, d.expression)
  if (expr) parts.push(expr.prompt)

  // Hair
  const hairS = findPreset(HAIR_STYLES, d.hairStyle)
  if (hairS) parts.push(hairS.prompt)
  const hairC = findPreset(HAIR_COLORS, d.hairColor)
  if (hairC) parts.push(hairC.prompt)

  // Outfit
  const outfit = findPreset([...OUTFIT_STYLES_SFW, ...OUTFIT_STYLES_NSFW], d.outfitStyle)
  if (outfit) parts.push(outfit.prompt)

  // Profession context (influences scene/outfit/pose)
  const prof = getProfession(d.professionId)
  if (prof && prof.id !== 'custom') parts.push(prof.label)

  // Colors
  const primC = findPreset(COLOR_PALETTE, d.outfitPrimaryColor)
  const secC = findPreset(COLOR_PALETTE, d.outfitSecondaryColor)
  if (primC && secC) parts.push(`${primC.prompt} and ${secC.prompt} color scheme`)

  // Accessories
  for (const accId of d.accessories) {
    const acc = findPreset(ACCESSORIES, accId)
    if (acc) parts.push(acc.prompt)
  }

  // Polish / makeup
  const polishMap: Record<string, string> = {
    natural: 'natural look',
    light_makeup: 'light professional makeup',
    formal: 'formal polished appearance, refined makeup',
  }
  parts.push(polishMap[d.polish] || '')

  // Pose + background (check NSFW-specific poses/backgrounds first, then standard)
  const pose = findPreset(NSFW_POSES, d.pose) || findPreset(POSES, d.pose)
  if (pose) parts.push(pose.prompt)
  const bg = findPreset(NSFW_BACKGROUNDS, d.background) || findPreset(BACKGROUNDS, d.background)
  if (bg) parts.push(bg.prompt)

  // Lighting
  const light = findPreset(LIGHTING_OPTIONS, d.lighting)
  if (light) parts.push(light.prompt)

  // NSFW modifiers (gated)
  if (nsfwEnabled && d.nsfwExposure) {
    const nsfwMap: Record<string, string> = {
      suggestive: 'suggestive pose, revealing outfit, tastefully showing skin, sensual',
      clothed_revealing: 'clothed but revealing, deep neckline, exposed skin, alluring',
      partial_nudity: 'partial nudity, exposed skin, provocative sensual pose, alluring',
      topless: 'topless, implied nude, exposed upper body, sensual artistic pose',
      full_nude: 'fully nude, naked body, sensual erotic pose, artistic nude',
      explicit: 'fully nude, explicit adult content, naked body, sensual erotic pose, anatomically detailed',
    }
    parts.push(nsfwMap[d.nsfwExposure] || '')

    // Intensity amplifier
    const intensity = d.nsfwIntensity ?? 5
    if (intensity >= 8) parts.push('extremely sensual, raw, uninhibited')
    else if (intensity >= 5) parts.push('sensual, inviting')

    // Pose — unified: quick-pick categories or specific NSFW pose presets
    if (d.nsfwPose === 'subtle') parts.push('subtle teasing pose, coy expression')
    else if (d.nsfwPose === 'confident') parts.push('confident provocative display, bold body language')
    else if (d.nsfwPose === 'intimate') parts.push('intimate close pose, bedroom eyes, inviting')
    else if (d.nsfwPose) {
      const posePreset = findPreset(NSFW_POSES, d.nsfwPose)
      if (posePreset) parts.push(posePreset.prompt)
    }

    // Fantasy tone
    if (d.nsfwFantasyTone === 'romantic') parts.push('romantic tender mood, soft warm tones')
    if (d.nsfwFantasyTone === 'seductive') parts.push('seductive alluring expression, smoldering gaze')
    if (d.nsfwFantasyTone === 'dramatic') parts.push('dramatic intense mood, powerful commanding presence')

    // Dominance
    if (d.nsfwDominanceStyle === 'soft') parts.push('gentle submissive energy, yielding')
    if (d.nsfwDominanceStyle === 'balanced') parts.push('balanced confident energy, natural relaxed poise')
    if (d.nsfwDominanceStyle === 'strong') parts.push('dominant commanding presence, powerful stance, in control')
  }

  // Quality
  const realismWord = d.realism > 70 ? 'photorealistic' : d.realism > 40 ? 'semi-realistic' : 'stylized'
  parts.push(`${realismWord}, highly detailed, 8k resolution`)

  return parts.filter(Boolean).join(', ')
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CharacterWizard({ backendUrl, apiKey, globalModelImages, onClose, onSaveGeneration }: CharacterWizardProps) {
  const [wizardMode, setWizardMode] = useState<'quick' | 'studio'>('studio')
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState<CharacterDraft>({ ...DEFAULT_DRAFT })
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [selectedResultIndex, setSelectedResultIndex] = useState<number | null>(null)
  const [showNsfw, setShowNsfw] = useState(false)
  const [showCountMenu, setShowCountMenu] = useState(false)
  const [count, setCount] = useState(4)

  // Toast
  const [toast, setToast] = useState<{ message: string; type: 'error' | 'success' | 'info' } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()
  const showToast = useCallback((message: string, type: 'error' | 'success' | 'info' = 'info') => {
    clearTimeout(toastTimer.current)
    setToast({ message, type })
    toastTimer.current = setTimeout(() => setToast(null), 4000)
  }, [])

  // File input for reference upload
  const fileInputRef = useRef<HTMLInputElement>(null)

  // NSFW mode — read directly from localStorage so it stays reactive.
  // The prop from the parent is stale (captured at mount time), so we ignore it
  // and poll localStorage to pick up changes made in the Settings panel.
  const readNsfw = useCallback(() => {
    try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false }
  }, [])
  const [nsfwEnabled, setNsfwEnabled] = useState(readNsfw)
  useEffect(() => {
    const sync = () => setNsfwEnabled(readNsfw())
    // Re-read on window focus (e.g. switching tabs/windows)
    window.addEventListener('focus', sync)
    // Listen for cross-tab localStorage changes
    window.addEventListener('storage', sync)
    // Poll every 1s to catch same-tab settings changes (localStorage
    // writes within the same tab do NOT fire the 'storage' event)
    const interval = setInterval(sync, 1000)
    return () => {
      window.removeEventListener('focus', sync)
      window.removeEventListener('storage', sync)
      clearInterval(interval)
    }
  }, [readNsfw])

  // Standard / Spicy tab (for Step 6 outfit + Step 7 vibe selection) — persisted
  const [vibeTab, _setVibeTab] = useState<VibeTab>(loadVibeTab)
  const setVibeTab = useCallback((tab: VibeTab) => { _setVibeTab(tab); saveVibeTab(tab) }, [])

  // Reset to standard tab if NSFW gets disabled mid-session
  useEffect(() => {
    if (!nsfwEnabled && vibeTab === 'spicy') setVibeTab('standard')
  }, [nsfwEnabled, vibeTab, setVibeTab])

  // Hooks
  const gen = useGenerateAvatars(backendUrl, apiKey)
  const gallery = useAvatarGallery()

  // Update draft
  const update = useCallback((changes: Partial<CharacterDraft>) => {
    setDraft((prev) => ({ ...prev, ...changes }))
  }, [])

  // Randomize appearance settings (body, face, hair, outfit)
  // When spicy mode is active, also randomize NSFW-specific parameters
  const randomizeAppearance = useCallback(() => {
    const pick = <T,>(arr: T[]): T => arr[Math.floor(Math.random() * arr.length)]
    const isSpicyMode = nsfwEnabled && vibeTab === 'spicy'
    // Outfit presets for Step 5 (Outfit)
    const outfitPool = isSpicyMode ? [...OUTFIT_STYLES_SFW, ...OUTFIT_STYLES_NSFW] : OUTFIT_STYLES_SFW
    // Character style presets for Step 6 (Generate) and Quick Create style vibes
    const stylePool = CHARACTER_STYLE_PRESETS.filter((s) =>
      isSpicyMode ? s.category === 'spicy' : s.category === 'standard',
    )
    const posePool = isSpicyMode ? NSFW_POSES : POSES
    const bgPool = isSpicyMode ? NSFW_BACKGROUNDS : BACKGROUNDS
    // Pick from both pools so outfitStyle works on both Step 5 and Step 6
    const combinedOutfitPool = [...outfitPool.map((o) => o.id), ...stylePool.map((s) => s.id)]

    setDraft((prev) => ({
      ...prev,
      gender: pick(['female', 'male', 'neutral'] as const),
      ageRange: pick(['young_adult', 'adult', 'mature'] as const),
      bodyType: pick(['slim', 'average', 'athletic', 'curvy'] as const),
      heightCm: 155 + Math.floor(Math.random() * 40),
      posture: pick(['upright', 'relaxed', 'confident'] as const),
      skinTone: pick(SKIN_TONES).id,
      polish: pick(['natural', 'light_makeup', 'formal'] as const),
      facePreset: pick(FACE_PRESETS).id,
      eyeColor: pick(EYE_COLORS).id,
      eyeShape: pick(EYE_SHAPES).id,
      expression: pick(EXPRESSIONS).id as any,
      jawline: 20 + Math.floor(Math.random() * 60),
      lips: 20 + Math.floor(Math.random() * 60),
      browDefinition: 20 + Math.floor(Math.random() * 60),
      hairStyle: pick(HAIR_STYLES).id,
      hairColor: pick(HAIR_COLORS).id,
      hairShine: 10 + Math.floor(Math.random() * 70),
      outfitStyle: pick(combinedOutfitPool),
      outfitPrimaryColor: pick(COLOR_PALETTE).id,
      outfitSecondaryColor: pick(COLOR_PALETTE).id,
      accessories: ACCESSORIES.filter(() => Math.random() > 0.7).map((a) => a.id),
      portraitType: pick(['headshot', 'half_body', 'full_body'] as const),
      pose: pick(posePool).id,
      background: pick(bgPool).id,
      lighting: pick(LIGHTING_OPTIONS).id,
      realism: 40 + Math.floor(Math.random() * 50),
      // NSFW-specific parameters (only meaningful when spicy)
      ...(isSpicyMode ? {
        nsfwExposure: pick(['suggestive', 'clothed_revealing', 'partial_nudity', 'topless', 'full_nude', 'explicit'] as const),
        nsfwIntensity: 2 + Math.floor(Math.random() * 8),
        nsfwPose: pick(['subtle', 'confident', 'intimate', 'seductive_lean', 'lying_down', 'back_arch', 'kneeling', 'over_shoulder', 'hands_above_head'] as const),
        nsfwDominanceStyle: pick(['soft', 'balanced', 'strong'] as const),
        nsfwFantasyTone: pick(['romantic', 'seductive', 'dramatic'] as const),
      } : {
        nsfwExposure: undefined,
        nsfwIntensity: undefined,
        nsfwPose: undefined,
        nsfwDominanceStyle: undefined,
        nsfwFantasyTone: undefined,
      }),
    }))
  }, [nsfwEnabled, vibeTab])

  // Reset all appearance settings back to defaults
  const resetToDefaults = useCallback(() => {
    setDraft({ ...DEFAULT_DRAFT })
    setVibeTab('standard')
  }, [])

  // Build prompt from all wizard choices
  const prompt = useMemo(() => buildPrompt(draft, nsfwEnabled), [draft, nsfwEnabled])

  // Is spicy content
  const isSpicy = vibeTab === 'spicy' || !!draft.nsfwExposure

  // Filtered vibes for Step 7 reference/faceswap modes
  const vibes = AVATAR_VIBE_PRESETS.filter((v) =>
    vibeTab === 'standard' ? v.category === 'standard' : v.category === 'spicy',
  )
  const charStyles = CHARACTER_STYLE_PRESETS.filter((s) =>
    vibeTab === 'standard' ? s.category === 'standard' : s.category === 'spicy',
  )

  // ---------------------------------------------------------------------------
  // Step navigation
  // ---------------------------------------------------------------------------

  const canProceed = true // All steps are optional — user can skip ahead

  const goNext = () => { if (canProceed && step < 6) setStep((s) => (s + 1) as any) }
  const goBack = () => { if (step > 0) setStep((s) => (s - 1) as any) }

  // ---------------------------------------------------------------------------
  // Apply profession defaults
  // ---------------------------------------------------------------------------

  const applyProfession = useCallback((profId: string) => {
    const prof = getProfession(profId)
    if (!prof) return
    update({
      professionId: profId,
      tools: [...prof.defaults.tools],
      memoryEngine: prof.defaults.memoryEngine,
      autonomy: prof.defaults.autonomy,
      tone: prof.defaults.tone,
      systemPrompt: prof.defaults.systemPrompt,
      responseStyle: prof.defaults.responseStyle,
    })
  }, [update])

  // ---------------------------------------------------------------------------
  // File upload (for reference/faceswap)
  // ---------------------------------------------------------------------------

  const handleFileUpload = useCallback(async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`${backendUrl}/upload`, {
        method: 'POST',
        headers: apiKey ? { 'x-api-key': apiKey } : undefined,
        body: formData,
      })
      if (!res.ok) throw new Error('Upload failed')
      const data = await res.json()
      const url = data.url || data.file_url || ''
      update({ referenceUrl: url, referencePreview: URL.createObjectURL(file) })
    } catch {
      showToast('Failed to upload reference photo', 'error')
    }
  }, [backendUrl, apiKey, update, showToast])

  // ---------------------------------------------------------------------------
  // Generate
  // ---------------------------------------------------------------------------

  const avatarSettings = loadAvatarSettings()
  const checkpoint = resolveCheckpoint(avatarSettings, globalModelImages)

  const onGenerate = useCallback(async () => {
    // Send the real mode to the backend — it routes studio_random to the
    // avatar-service (StyleGAN) and other modes to ComfyUI automatically.
    const apiMode = draft.generationMode
    try {
      const result = await gen.run({
        mode: apiMode as AvatarMode,
        count,
        prompt: prompt || undefined,
        reference_image_url:
          draft.generationMode !== 'studio_random'
            ? draft.referenceUrl || undefined
            : undefined,
        truncation: 0.7,
        checkpoint_override: checkpoint,
      })
      if (result?.results?.length) {
        setSelectedResultIndex(null)
        if (result.results.length === 1) {
          showToast('Avatar generated — click to select, then Create Avatar', 'success')
        } else {
          showToast(`${result.results.length} avatars generated — pick your favourite`, 'success')
        }
      }
    } catch {
      showToast('Generation failed. Click Generate to try again.', 'error')
    }
  }, [gen, draft.generationMode, draft.referenceUrl, count, prompt, checkpoint, showToast])

  // Keyboard shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && step === 6 && !gen.loading) {
        e.preventDefault()
        onGenerate()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onGenerate, step, gen.loading])

  // ---------------------------------------------------------------------------
  // Create avatar (gallery only)
  // ---------------------------------------------------------------------------

  const handleCreateAvatar = useCallback(() => {
    if (selectedResultIndex === null || !gen.result?.results?.[selectedResultIndex]) return
    const allResults = gen.result.results
    const chosen = allResults[selectedResultIndex]

    // Save selected as anchor + non-selected as linked portraits (one atomic op)
    const portraits = allResults.filter((_, i) => i !== selectedResultIndex)

    // Build wizard metadata so persona export can access profession/tools/tone
    const prof = getProfession(draft.professionId)
    const wizardMeta = {
      professionId: draft.professionId,
      professionLabel: prof?.label,
      professionDescription: prof?.description,
      tools: draft.tools,
      memoryEngine: draft.memoryEngine,
      autonomy: draft.autonomy,
      tone: draft.tone,
      systemPrompt: draft.systemPrompt || prof?.defaults.systemPrompt,
      responseStyle: draft.responseStyle,
      gender: draft.gender,
      ageRange: draft.ageRange,
    }

    if (onSaveGeneration) {
      onSaveGeneration(chosen, portraits, draft.generationMode as AvatarMode, prompt, draft.referenceUrl, isSpicy, wizardMeta)
    } else {
      gallery.addAnchorWithPortraits(chosen, portraits, draft.generationMode as AvatarMode, prompt, draft.referenceUrl, { nsfw: isSpicy || undefined, wizardMeta })
    }

    const portraitCount = portraits.length
    showToast(
      portraitCount > 0
        ? `Avatar created! ${portraitCount} alternative${portraitCount > 1 ? 's' : ''} saved as portraits`
        : 'Avatar created!',
      'success',
    )
    onClose()
  }, [selectedResultIndex, gen.result, draft, prompt, isSpicy, gallery, onSaveGeneration, onClose, showToast])

  // ---------------------------------------------------------------------------
  // Render: Step content
  // ---------------------------------------------------------------------------

  function renderStep() {
    switch (step) {

      // =====================================================================
      // STEP 0 — IDENTITY
      // =====================================================================
      case 0:
        return (
          <div className="space-y-6">
            <SectionLabel>Gender</SectionLabel>
            <div className="flex gap-2">
              {GENDER_OPTIONS.map((g) => (
                <PillButton key={g.id} label={g.label} icon={g.icon}
                  selected={draft.gender === g.id}
                  onClick={() => update({ gender: g.id })} />
              ))}
            </div>

            <SectionLabel>Age Range</SectionLabel>
            <div className="flex gap-2">
              {(['young_adult', 'adult', 'mature'] as const).map((a) => (
                <PillButton key={a} label={a === 'young_adult' ? 'Young Adult' : a === 'adult' ? 'Adult' : 'Mature'}
                  selected={draft.ageRange === a}
                  onClick={() => update({ ageRange: a })} />
              ))}
            </div>
          </div>
        )

      // =====================================================================
      // STEP 1 — BODY
      // =====================================================================
      case 1:
        return (
          <div className="space-y-6">
            <SectionLabel>Body Type</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {(['slim', 'average', 'athletic', 'curvy'] as const).map((b) => (
                <PillButton key={b} label={b.charAt(0).toUpperCase() + b.slice(1)}
                  selected={draft.bodyType === b}
                  onClick={() => update({ bodyType: b })} />
              ))}
            </div>

            <SliderField label="Height" value={draft.heightCm} min={150} max={200} unit=" cm"
              onChange={(v) => update({ heightCm: v })} />

            <SectionLabel>Posture</SectionLabel>
            <div className="flex gap-2">
              {(['upright', 'relaxed', 'confident'] as const).map((p) => (
                <PillButton key={p} label={p.charAt(0).toUpperCase() + p.slice(1)}
                  selected={draft.posture === p}
                  onClick={() => update({ posture: p })} />
              ))}
            </div>

            <SectionLabel>Skin Tone</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {SKIN_TONES.map((t) => (
                <ColorSwatch key={t.id} color={t.color!} label={t.label}
                  selected={draft.skinTone === t.id}
                  onClick={() => update({ skinTone: t.id })} />
              ))}
            </div>

            <SectionLabel>Polish</SectionLabel>
            <div className="flex gap-2">
              {(['natural', 'light_makeup', 'formal'] as const).map((p) => (
                <PillButton key={p}
                  label={p === 'light_makeup' ? 'Light Makeup' : p.charAt(0).toUpperCase() + p.slice(1)}
                  selected={draft.polish === p}
                  onClick={() => update({ polish: p })} />
              ))}
            </div>
          </div>
        )

      // =====================================================================
      // STEP 2 — FACE
      // =====================================================================
      case 2:
        return (
          <div className="space-y-6">
            <SectionLabel>Face Shape</SectionLabel>
            <div className="grid grid-cols-4 gap-2">
              {FACE_PRESETS.map((f) => (
                <PillButton key={f.id} label={f.label}
                  selected={draft.facePreset === f.id}
                  onClick={() => update({ facePreset: f.id })} />
              ))}
            </div>

            <SectionLabel>Eye Color</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {EYE_COLORS.map((c) => (
                <ColorSwatch key={c.id} color={c.color!} label={c.label}
                  selected={draft.eyeColor === c.id}
                  onClick={() => update({ eyeColor: c.id })} />
              ))}
            </div>

            <SectionLabel>Eye Shape</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {EYE_SHAPES.map((s) => (
                <PillButton key={s.id} label={s.label}
                  selected={draft.eyeShape === s.id}
                  onClick={() => update({ eyeShape: s.id })} />
              ))}
            </div>

            <SectionLabel>Default Expression</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {EXPRESSIONS.map((e) => (
                <PillButton key={e.id} label={e.label}
                  selected={draft.expression === e.id}
                  onClick={() => update({ expression: e.id as any })} />
              ))}
            </div>

            <AdvancedToggle open={advancedOpen} onToggle={() => setAdvancedOpen(!advancedOpen)} />
            {advancedOpen && (
              <div className="space-y-4 animate-fadeSlideIn">
                <SliderField label="Jawline" value={draft.jawline} min={0} max={100}
                  onChange={(v) => update({ jawline: v })} />
                <SliderField label="Lips" value={draft.lips} min={0} max={100}
                  onChange={(v) => update({ lips: v })} />
                <SliderField label="Brow Definition" value={draft.browDefinition} min={0} max={100}
                  onChange={(v) => update({ browDefinition: v })} />
              </div>
            )}
          </div>
        )

      // =====================================================================
      // STEP 3 — HAIR
      // =====================================================================
      case 3:
        return (
          <div className="space-y-6">
            <SectionLabel>Hairstyle</SectionLabel>
            <div className="grid grid-cols-3 gap-2">
              {HAIR_STYLES.map((h) => (
                <PillButton key={h.id} label={h.label}
                  selected={draft.hairStyle === h.id}
                  onClick={() => update({ hairStyle: h.id })} />
              ))}
            </div>

            <SectionLabel>Hair Color</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {HAIR_COLORS.map((c) => (
                <ColorSwatch key={c.id} color={c.color!} label={c.label}
                  selected={draft.hairColor === c.id}
                  onClick={() => update({ hairColor: c.id })} />
              ))}
            </div>

            <SliderField label="Shine" value={draft.hairShine} min={0} max={100}
              onChange={(v) => update({ hairShine: v })} />
          </div>
        )

      // =====================================================================
      // STEP 4 — PROFESSION
      // =====================================================================
      case 4: {
        return (
          <div className="space-y-6">
            <SectionLabel>Choose a Profession</SectionLabel>
            <p className="text-[10px] text-white/25 -mt-3">Profession influences outfit style, pose, and scene context</p>
            <div className="space-y-2">
              {PROFESSIONS.map((p) => {
                const active = draft.professionId === p.id
                return (
                  <button key={p.id}
                    onClick={() => applyProfession(p.id)}
                    className={[
                      'w-full flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all',
                      active
                        ? 'border-purple-500/30 bg-purple-500/10 text-purple-200'
                        : 'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.05] hover:text-white/70',
                    ].join(' ')}
                  >
                    <span className="text-lg">{p.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold">{p.label}</span>
                        {p.recommended && <span className="text-[8px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 font-bold">Recommended</span>}
                      </div>
                      <p className="text-[10px] text-white/30 mt-0.5 truncate">{p.description}</p>
                    </div>
                    {active && <Check size={16} className="text-purple-400 flex-shrink-0" />}
                  </button>
                )
              })}
            </div>
          </div>
        )
      }

      // =====================================================================
      // STEP 5 — OUTFIT
      // =====================================================================
      case 5: {
        const outfits = vibeTab === 'spicy' && nsfwEnabled
          ? [...OUTFIT_STYLES_SFW, ...OUTFIT_STYLES_NSFW]
          : OUTFIT_STYLES_SFW
        return (
          <div className="space-y-6">
            {/* SFW / NSFW tabs — only show when NSFW is globally enabled */}
            {nsfwEnabled && (
              <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06] w-fit">
                <button onClick={() => setVibeTab('standard')}
                  className={[
                    'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                    vibeTab === 'standard' ? 'bg-white/10 text-white shadow-sm' : 'text-white/40 hover:text-white/60',
                  ].join(' ')}
                >
                  <Star size={12} /> Standard
                </button>
                <button onClick={() => setVibeTab('spicy')}
                  className={[
                    'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                    vibeTab === 'spicy'
                      ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/20 shadow-sm'
                      : 'text-white/40 hover:text-rose-300/60',
                  ].join(' ')}
                >
                  <Flame size={12} /> Romance &amp; Roleplay
                  <span className="text-[8px] px-1 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">18+</span>
                </button>
              </div>
            )}

            <SectionLabel>Outfit Style</SectionLabel>
            <div className="grid grid-cols-2 gap-2">
              {outfits.map((o) => (
                <PillButton key={o.id} label={o.label}
                  selected={draft.outfitStyle === o.id}
                  accent={OUTFIT_STYLES_NSFW.some((n) => n.id === o.id) ? 'rose' : 'purple'}
                  onClick={() => update({ outfitStyle: o.id })} />
              ))}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <SectionLabel>Primary Color</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {COLOR_PALETTE.map((c) => (
                    <ColorSwatch key={c.id} color={c.color!} label={c.label}
                      selected={draft.outfitPrimaryColor === c.id}
                      onClick={() => update({ outfitPrimaryColor: c.id })} />
                  ))}
                </div>
              </div>
              <div>
                <SectionLabel>Secondary Color</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {COLOR_PALETTE.map((c) => (
                    <ColorSwatch key={c.id} color={c.color!} label={c.label}
                      selected={draft.outfitSecondaryColor === c.id}
                      onClick={() => update({ outfitSecondaryColor: c.id })} />
                  ))}
                </div>
              </div>
            </div>

            <SectionLabel>Accessories</SectionLabel>
            <div className="flex flex-wrap gap-2">
              {ACCESSORIES.map((a) => {
                const active = draft.accessories.includes(a.id)
                return (
                  <PillButton key={a.id} label={a.label}
                    selected={active}
                    onClick={() => {
                      const next = active ? draft.accessories.filter((x) => x !== a.id) : [...draft.accessories, a.id]
                      update({ accessories: next })
                    }} />
                )
              })}
            </div>

            {/* ── NSFW customization (18+ gated) ── */}
            {nsfwEnabled && vibeTab === 'spicy' && (
              <div className="mt-6 pt-5 border-t border-rose-500/20">
                <div className="text-xs text-rose-400 font-bold uppercase tracking-wider mb-5 flex items-center gap-2">
                  <Flame size={14} /> Adult Content Controls
                  <span className="text-[8px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold ml-1">18+</span>
                </div>

                <div className="space-y-6">
                  {/* Exposure Level — 6-tier granular selector */}
                  <div>
                    <div className="text-[10px] text-rose-400/70 font-semibold uppercase tracking-wider mb-3">Nudity / Exposure Level</div>
                    <div className="grid grid-cols-3 gap-2">
                      {([
                        { id: 'suggestive' as const, label: 'Suggestive', desc: 'Tasteful hints' },
                        { id: 'clothed_revealing' as const, label: 'Clothed Revealing', desc: 'Clothed but revealing' },
                        { id: 'partial_nudity' as const, label: 'Partial Nudity', desc: 'Some exposed skin' },
                        { id: 'topless' as const, label: 'Topless', desc: 'Topless / implied nude' },
                        { id: 'full_nude' as const, label: 'Full Nude', desc: 'Artistic full nude' },
                        { id: 'explicit' as const, label: 'Explicit', desc: 'Explicit adult content' },
                      ]).map((e) => (
                        <button key={e.id}
                          onClick={() => update({ nsfwExposure: e.id })}
                          className={[
                            'flex flex-col items-center gap-1 px-3 py-3 rounded-xl border text-center transition-all',
                            draft.nsfwExposure === e.id
                              ? 'border-rose-500/40 bg-rose-500/15 text-rose-200 shadow-[0_0_12px_rgba(244,63,94,0.15)]'
                              : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.05] hover:text-white/60',
                          ].join(' ')}
                        >
                          <span className="text-xs font-semibold">{e.label}</span>
                          <span className="text-[9px] text-white/30">{e.desc}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Intensity slider */}
                  <SliderField label="Explicitness Intensity" value={draft.nsfwIntensity ?? 5} min={0} max={10}
                    onChange={(v) => update({ nsfwIntensity: v })} />

                  {/* Sensual Pose — unified flat grid of all 9 poses */}
                  <div>
                    <div className="text-[10px] text-rose-400/70 font-semibold uppercase tracking-wider mb-3">Sensual Pose</div>
                    <div className="grid grid-cols-3 gap-2">
                      {([
                        { id: 'subtle' as const, label: 'Subtle Tease' },
                        { id: 'confident' as const, label: 'Confident Display' },
                        { id: 'intimate' as const, label: 'Intimate Close' },
                        ...NSFW_POSES.map((p) => ({ id: p.id as typeof draft.nsfwPose & string, label: p.label })),
                      ]).map((p) => (
                        <PillButton key={p.id} label={p.label}
                          selected={draft.nsfwPose === p.id} accent="rose"
                          onClick={() => update({ nsfwPose: p.id as typeof draft.nsfwPose })} />
                      ))}
                    </div>
                  </div>

                  {/* Dominance / Power dynamic */}
                  <div>
                    <div className="text-[10px] text-rose-400/70 font-semibold uppercase tracking-wider mb-3">Power Dynamic</div>
                    <div className="flex gap-2">
                      {([
                        { id: 'soft' as const, label: 'Soft & Romantic' },
                        { id: 'balanced' as const, label: 'Balanced' },
                        { id: 'strong' as const, label: 'Dominant & Bold' },
                      ]).map((d) => (
                        <PillButton key={d.id} label={d.label}
                          selected={draft.nsfwDominanceStyle === d.id} accent="rose"
                          onClick={() => update({ nsfwDominanceStyle: d.id })} />
                      ))}
                    </div>
                  </div>

                  {/* Fantasy Tone */}
                  <div>
                    <div className="text-[10px] text-rose-400/70 font-semibold uppercase tracking-wider mb-3">Fantasy Tone</div>
                    <div className="flex gap-2">
                      {([
                        { id: 'romantic' as const, label: 'Romantic & Tender' },
                        { id: 'seductive' as const, label: 'Seductive & Alluring' },
                        { id: 'dramatic' as const, label: 'Dramatic & Intense' },
                      ]).map((t) => (
                        <PillButton key={t.id} label={t.label}
                          selected={draft.nsfwFantasyTone === t.id} accent="rose"
                          onClick={() => update({ nsfwFantasyTone: t.id })} />
                      ))}
                    </div>
                  </div>

                  {/* NSFW Scene / Background */}
                  <div>
                    <div className="text-[10px] text-rose-400/70 font-semibold uppercase tracking-wider mb-3">Scene / Setting</div>
                    <div className="grid grid-cols-3 gap-1.5">
                      {NSFW_BACKGROUNDS.map((b) => (
                        <PillButton key={b.id} label={b.label}
                          selected={draft.background === b.id} accent="rose"
                          onClick={() => update({ background: b.id })} />
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )
      }

      // =====================================================================
      // STEP 6 — GENERATE
      // =====================================================================
      case 6: {
        const needsRef = draft.generationMode === 'studio_reference' || draft.generationMode === 'studio_faceswap'
        const canGen = !gen.loading && (!needsRef || !!draft.referenceUrl)

        return (
          <div className="space-y-6">
            {/* ── Generation Mode tabs ── */}
            <SectionLabel>Generation Mode</SectionLabel>
            <div className="flex items-center gap-2" role="radiogroup">
              {[
                { mode: 'studio_random' as const,    label: 'Design Character', icon: <Sparkles size={13} /> },
                { mode: 'studio_reference' as const, label: 'From Reference',   icon: <User size={13} /> },
                { mode: 'studio_faceswap' as const,  label: 'Face + Style',     icon: <Palette size={13} /> },
              ].map((m) => (
                <button key={m.mode}
                  onClick={() => update({ generationMode: m.mode })}
                  className={[
                    'flex items-center gap-2 px-4 py-2 rounded-full text-xs font-medium transition-all border',
                    draft.generationMode === m.mode
                      ? 'bg-white/10 text-white border-white/20 shadow-[0_0_12px_rgba(255,255,255,0.05)]'
                      : 'text-white/40 hover:text-white/60 hover:bg-white/[0.04] border-transparent',
                  ].join(' ')}
                >
                  {m.icon} {m.label}
                </button>
              ))}
            </div>

            {/* ── Reference upload (for ref/faceswap) ── */}
            {needsRef && (
              <div>
                <SectionLabel>Upload a Face</SectionLabel>
                <div className={[
                  'flex items-center gap-3 px-4 py-3 rounded-2xl border transition-all',
                  'bg-white/[0.04] border-white/10',
                  draft.referencePreview ? 'border-purple-500/30' : 'hover:border-white/15',
                ].join(' ')}>
                  {draft.referencePreview ? (
                    <div className="relative flex-shrink-0">
                      <div className="w-10 h-10 rounded-full overflow-hidden border-2 border-purple-500/40">
                        <img src={draft.referencePreview} alt="Reference" className="w-full h-full object-cover" />
                      </div>
                      <button onClick={() => update({ referenceUrl: undefined, referencePreview: undefined })}
                        className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500/80 flex items-center justify-center text-white hover:bg-red-500 transition-colors">
                        <X size={8} />
                      </button>
                    </div>
                  ) : (
                    <button onClick={() => fileInputRef.current?.click()}
                      className="flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-white/20 hover:text-white/50 hover:bg-white/5 transition-all border border-dashed border-white/10">
                      <Camera size={18} />
                    </button>
                  )}
                  <input ref={fileInputRef} type="file" accept="image/*" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); e.target.value = '' }} />
                  <div className="flex-1 min-w-0">
                    {draft.referencePreview ? (
                      <span className="text-sm text-white/60">Reference photo attached</span>
                    ) : (
                      <button onClick={() => fileInputRef.current?.click()}
                        className="text-sm text-white/25 hover:text-white/40 transition-colors cursor-pointer text-left">
                        Click to upload a reference photo
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ── Style / Vibe selection (for reference/faceswap OR design character) ── */}
            {draft.generationMode === 'studio_random' ? (
              <>
                {/* Standard / Spicy tabs — only when NSFW globally enabled */}
                {nsfwEnabled && (
                  <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06] w-fit">
                    <button onClick={() => setVibeTab('standard')}
                      className={[
                        'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                        vibeTab === 'standard' ? 'bg-white/10 text-white shadow-sm' : 'text-white/40 hover:text-white/60',
                      ].join(' ')}
                    >
                      <Star size={12} /> Standard
                    </button>
                    <button onClick={() => setVibeTab('spicy')}
                      className={[
                        'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                        vibeTab === 'spicy'
                          ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/20 shadow-sm'
                          : 'text-white/40 hover:text-rose-300/60',
                      ].join(' ')}
                    >
                      <Flame size={12} /> Romance &amp; Roleplay
                      <span className="text-[8px] px-1 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">18+</span>
                    </button>
                  </div>
                )}

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {charStyles.map((s) => {
                    const active = draft.outfitStyle === s.id || false
                    return (
                      <button key={s.id}
                        onClick={() => update({ outfitStyle: s.id })}
                        className={[
                          'flex items-center gap-2.5 px-3.5 py-3 rounded-xl text-left transition-all border',
                          active
                            ? vibeTab === 'spicy'
                              ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                              : 'border-purple-500/30 bg-purple-500/10 text-purple-200'
                            : 'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.04]',
                        ].join(' ')}
                      >
                        <span className="text-base leading-none">{s.icon}</span>
                        <span className="text-xs font-medium">{s.label}</span>
                      </button>
                    )
                  })}
                </div>
              </>
            ) : (
              <>
                {/* Vibe grid for reference/faceswap — tab bar only when NSFW enabled */}
                {nsfwEnabled && (
                  <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06] w-fit">
                    <button onClick={() => setVibeTab('standard')}
                      className={[
                        'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                        vibeTab === 'standard' ? 'bg-white/10 text-white shadow-sm' : 'text-white/40 hover:text-white/60',
                      ].join(' ')}
                    >
                      <Star size={12} /> Standard
                    </button>
                    <button onClick={() => setVibeTab('spicy')}
                      className={[
                        'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                        vibeTab === 'spicy'
                          ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/20 shadow-sm'
                          : 'text-white/40 hover:text-rose-300/60',
                      ].join(' ')}
                    >
                      <Flame size={12} /> Romance &amp; Roleplay
                      <span className="text-[8px] px-1 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">18+</span>
                    </button>
                  </div>
                )}

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {vibes.map((v) => (
                    <button key={v.id}
                      onClick={() => {/* vibe selection for reference modes */}}
                      className={[
                        'flex items-center gap-2.5 px-3.5 py-3 rounded-xl text-left transition-all border',
                        'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.04]',
                      ].join(' ')}
                    >
                      <span className="text-base leading-none">{v.icon}</span>
                      <span className="text-xs font-medium">{v.label}</span>
                    </button>
                  ))}
                </div>
              </>
            )}

            {/* ── Portrait / Pose / Background controls ── */}
            <SectionLabel>Portrait Type</SectionLabel>
            <div className="flex gap-2">
              {(['headshot', 'half_body', 'full_body'] as const).map((t) => (
                <PillButton key={t}
                  label={t === 'half_body' ? 'Half Body' : t === 'full_body' ? 'Full Body' : 'Headshot'}
                  selected={draft.portraitType === t}
                  onClick={() => update({ portraitType: t })} />
              ))}
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <SectionLabel>Pose</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {POSES.map((p) => (
                    <PillButton key={p.id} label={p.label}
                      selected={draft.pose === p.id}
                      onClick={() => update({ pose: p.id })} />
                  ))}
                </div>
              </div>
              <div>
                <SectionLabel>Background</SectionLabel>
                <div className="flex flex-wrap gap-1.5">
                  {BACKGROUNDS.map((b) => (
                    <PillButton key={b.id} label={b.label}
                      selected={draft.background === b.id}
                      onClick={() => update({ background: b.id })} />
                  ))}
                </div>
              </div>
            </div>

            {/* ── Advanced ── */}
            <AdvancedToggle open={advancedOpen} onToggle={() => setAdvancedOpen(!advancedOpen)} />
            {advancedOpen && (
              <div className="space-y-4 animate-fadeSlideIn">
                <SliderField label="Realism" value={draft.realism} min={0} max={100}
                  onChange={(v) => update({ realism: v })} />
                <SliderField label="Detail Level" value={draft.detailLevel} min={0} max={100}
                  onChange={(v) => update({ detailLevel: v })} />
                <SectionLabel>Lighting</SectionLabel>
                <div className="flex flex-wrap gap-2">
                  {LIGHTING_OPTIONS.map((l) => (
                    <PillButton key={l.id} label={l.label}
                      selected={draft.lighting === l.id}
                      onClick={() => update({ lighting: l.id })} />
                  ))}
                </div>
              </div>
            )}

            {/* ── Generate Button + Count Selector ── */}
            <div className="flex items-center justify-center gap-3 pt-4">
              <div className="relative flex items-stretch">
                <button onClick={onGenerate} disabled={!canGen}
                  className={[
                    'flex items-center gap-2 pl-5 pr-3 py-2.5 rounded-l-xl text-sm font-semibold transition-all',
                    canGen
                      ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:brightness-110 active:scale-[0.98]'
                      : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
                  ].join(' ')}
                >
                  {gen.loading ? (
                    <><Loader2 size={16} className="animate-spin" /> Generating...</>
                  ) : (
                    <><Sparkles size={16} /> Generate ({count})</>
                  )}
                </button>
                <div className="relative">
                  <button onClick={() => setShowCountMenu(!showCountMenu)}
                    className={[
                      'h-full px-2.5 rounded-r-xl border-l transition-all flex items-center',
                      canGen
                        ? 'bg-gradient-to-r from-pink-600 to-pink-700 border-white/10 text-white/80 hover:text-white'
                        : 'bg-white/[0.06] border-white/5 text-white/15 cursor-not-allowed',
                    ].join(' ')}
                    disabled={!canGen && !gen.loading}
                  >
                    <ChevronDown size={14} />
                  </button>
                  {showCountMenu && (
                    <>
                      <div className="fixed inset-0 z-30" onClick={() => setShowCountMenu(false)} />
                      <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-white/10 rounded-lg shadow-2xl z-40 overflow-hidden min-w-[80px]">
                        {[1, 4, 8].map((n) => (
                          <button key={n} onClick={() => { setCount(n); setShowCountMenu(false) }}
                            className={[
                              'w-full px-4 py-2 text-left text-sm transition-colors',
                              count === n ? 'bg-purple-500/15 text-purple-300 font-medium' : 'text-white/60 hover:bg-white/5',
                            ].join(' ')}
                          >{n} image{n > 1 ? 's' : ''}</button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </div>

              {gen.loading && (
                <button onClick={gen.cancel}
                  className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl text-sm font-medium border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all">
                  <X size={14} /> Cancel
                </button>
              )}

              {canGen && !gen.loading && (
                <span className="text-[10px] text-white/20 hidden sm:inline ml-1">Ctrl+Enter</span>
              )}
            </div>

            {/* ── Loading skeleton ── */}
            {gen.loading && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
                {Array.from({ length: count }).map((_, i) => (
                  <div key={i} className="rounded-xl overflow-hidden border border-white/[0.06] bg-white/[0.02]">
                    <div className="aspect-square bg-white/[0.03] animate-pulse flex items-center justify-center">
                      <Loader2 size={20} className="animate-spin text-white/10" />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ── Results grid ── */}
            {gen.result?.results?.length ? (
              <div className="mt-4 animate-fadeSlideIn">
                <div className="text-xs text-white/30 mb-2 font-medium uppercase tracking-wider text-center">
                  {gen.result.results.length === 1 ? 'Your Avatar' : 'Choose Your Avatar'}
                </div>
                <div className={`grid gap-3 ${gen.result.results.length === 1 ? 'grid-cols-1 max-w-xs mx-auto' : 'grid-cols-2 sm:grid-cols-4'}`}>
                  {gen.result.results.map((item, i) => {
                    const imgUrl = resolveFileUrl(item.url, backendUrl)
                    const blurred = isSpicy && !showNsfw
                    const isSelected = selectedResultIndex === i
                    const hasSelection = selectedResultIndex !== null
                    return (
                      <div key={i}
                        className={[
                          'group relative rounded-xl overflow-hidden border-2 bg-white/[0.02] transition-all duration-300 cursor-pointer',
                          isSelected
                            ? 'border-purple-400 shadow-[0_0_20px_rgba(168,85,247,0.3)] scale-[1.02] z-10'
                            : hasSelection
                              ? 'border-white/[0.04] opacity-50 grayscale-[30%] hover:opacity-70 hover:grayscale-0'
                              : 'border-white/[0.06] hover:border-white/20 hover:shadow-lg',
                        ].join(' ')}
                        onClick={() => {
                          if (blurred) { setShowNsfw(true); return }
                          setSelectedResultIndex(isSelected ? null : i)
                        }}
                      >
                        <div className="aspect-square bg-white/[0.03] relative">
                          <img src={imgUrl} alt={`Avatar ${i + 1}`}
                            className={`w-full h-full object-cover transition-all duration-300 ${blurred ? 'blur-xl scale-110' : ''}`}
                            loading="lazy" />
                          {blurred && (
                            <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/30">
                              <EyeOff size={20} className="text-white/40 mb-1" />
                              <span className="text-[10px] text-white/40 font-medium">Click to reveal</span>
                            </div>
                          )}
                          {isSelected && !blurred && (
                            <div className="absolute top-2 right-2 w-7 h-7 rounded-full bg-purple-500 flex items-center justify-center shadow-lg animate-scaleIn">
                              <CheckCircle2 size={16} className="text-white" />
                            </div>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* ── Create Avatar button ── */}
                {selectedResultIndex !== null && gen.result.results[selectedResultIndex] && (
                  <div className="flex flex-col items-center mt-6 animate-fadeSlideIn">
                    <button onClick={handleCreateAvatar}
                      className="flex items-center gap-3 px-8 py-3.5 rounded-2xl bg-gradient-to-r from-purple-600 to-pink-600 text-white font-semibold text-sm shadow-[0_0_30px_rgba(168,85,247,0.25)] hover:shadow-[0_0_40px_rgba(168,85,247,0.4)] hover:scale-[1.03] active:scale-[0.98] transition-all duration-200"
                    >
                      <User size={18} />
                      Create Avatar
                    </button>
                    <p className="text-[10px] text-white/20 mt-2">
                      Saves avatar to your gallery — export as persona later
                    </p>
                  </div>
                )}
              </div>
            ) : !gen.loading && !gen.result ? (
              <div className="flex flex-col items-center justify-center py-12 text-white/15">
                <Sparkles size={36} strokeWidth={1} />
                <p className="mt-3 text-sm text-white/25">Your avatars will appear here</p>
                <p className="mt-1 text-[10px] text-white/15">Configure your character above, then click Generate</p>
              </div>
            ) : null}
          </div>
        )
      }

      default:
        return null
    }
  }

  // ---------------------------------------------------------------------------
  // Render: Quick Create mode
  // ---------------------------------------------------------------------------

  function renderQuickCreate() {
    const canGen = !gen.loading
    return (
      <div className="max-w-md mx-auto space-y-6">
        <div className="text-center mb-2">
          <h3 className="text-lg font-semibold text-white/90">Quick Create</h3>
          <p className="text-xs text-white/30 mt-1">Gender, profession, style — done in 60 seconds</p>
        </div>

        <SectionLabel>Gender</SectionLabel>
        <div className="flex gap-2">
          {GENDER_OPTIONS.map((g) => (
            <PillButton key={g.id} label={g.label} icon={g.icon}
              selected={draft.gender === g.id}
              onClick={() => update({ gender: g.id })} />
          ))}
        </div>

        <SectionLabel>Profession</SectionLabel>
        <div className="space-y-1.5">
          {PROFESSIONS.filter((p) => p.id !== 'custom').slice(0, 5).map((p) => (
            <button key={p.id}
              onClick={() => applyProfession(p.id)}
              className={[
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl border text-left transition-all text-xs',
                draft.professionId === p.id
                  ? 'border-purple-500/30 bg-purple-500/10 text-purple-200'
                  : 'border-white/[0.06] bg-white/[0.02] text-white/45 hover:bg-white/[0.05]',
              ].join(' ')}
            >
              <span>{p.icon}</span>
              <span className="font-medium">{p.label}</span>
              {p.recommended && <span className="text-[7px] px-1 py-0.5 rounded bg-purple-500/20 text-purple-300 font-bold ml-auto">Recommended</span>}
            </button>
          ))}
        </div>

        {/* Standard / Romance & Roleplay / 18+ tabs — only when NSFW globally enabled */}
        {nsfwEnabled && (
          <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06] w-fit">
            <button onClick={() => setVibeTab('standard')}
              className={[
                'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                vibeTab === 'standard' ? 'bg-white/10 text-white shadow-sm' : 'text-white/40 hover:text-white/60',
              ].join(' ')}
            >
              Standard
            </button>
            <button onClick={() => setVibeTab('spicy')}
              className={[
                'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                vibeTab === 'spicy'
                  ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/20 shadow-sm'
                  : 'text-white/40 hover:text-rose-300/60',
              ].join(' ')}
            >
              <Flame size={12} /> Romance &amp; Roleplay
            </button>
            <button onClick={() => setVibeTab('spicy')}
              className={[
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                vibeTab === 'spicy'
                  ? 'bg-gradient-to-r from-red-500/20 to-rose-500/20 text-red-300 border border-red-500/20 shadow-sm'
                  : 'text-white/40 hover:text-red-300/60',
              ].join(' ')}
            >
              18+
            </button>
          </div>
        )}

        {/* Style vibe — switches between standard & spicy presets */}
        <SectionLabel>Style Vibe</SectionLabel>
        <div className={`grid gap-1.5 ${vibeTab === 'spicy' && nsfwEnabled ? 'grid-cols-4' : 'grid-cols-4'}`}>
          {CHARACTER_STYLE_PRESETS
            .filter((s) => vibeTab === 'spicy' && nsfwEnabled ? s.category === 'spicy' : s.category === 'standard')
            .slice(0, vibeTab === 'spicy' && nsfwEnabled ? 8 : 4)
            .map((s) => (
            <button key={s.id}
              onClick={() => update({ outfitStyle: s.id })}
              className={[
                'flex items-center gap-1.5 px-2.5 py-2 rounded-lg text-[11px] font-medium border transition-all',
                draft.outfitStyle === s.id
                  ? vibeTab === 'spicy' && nsfwEnabled
                    ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                    : 'border-purple-500/30 bg-purple-500/10 text-purple-200'
                  : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:bg-white/[0.04]',
              ].join(' ')}
            >
              <span>{s.icon}</span> {s.label}
            </button>
          ))}
        </div>

        {/* Randomize + Reset + Generate */}
        <div className="flex justify-center gap-3 pt-4">
          <button onClick={resetToDefaults}
            className="flex items-center gap-2 px-4 py-3 rounded-2xl text-sm font-medium text-white/30 hover:text-white/55 hover:bg-white/[0.04] border border-white/[0.06] transition-all"
          >
            <RotateCcw size={14} /> Reset
          </button>
          <button onClick={randomizeAppearance}
            className="flex items-center gap-2 px-5 py-3 rounded-2xl text-sm font-medium text-white/45 hover:text-white/70 hover:bg-white/[0.06] border border-white/[0.08] transition-all"
          >
            <Shuffle size={14} /> Randomize
          </button>
          <button onClick={async () => {
            try {
              const result = await gen.run({
                mode: 'creative',
                count: 4,
                prompt: prompt || undefined,
                truncation: 0.7,
                checkpoint_override: checkpoint,
              })
              if (result?.results?.length) {
                setWizardMode('studio')
                setStep(6)
                showToast(`${result.results.length} avatars generated — pick your favourite`, 'success')
              }
            } catch {
              showToast('Generation failed. Try again.', 'error')
            }
          }}
            disabled={gen.loading}
            className={[
              'flex items-center gap-2.5 px-8 py-3 rounded-2xl text-sm font-semibold transition-all',
              !gen.loading
                ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:brightness-110 active:scale-[0.98]'
                : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
            ].join(' ')}
          >
            {gen.loading ? <Loader2 size={16} className="animate-spin" /> : <Zap size={16} />}
            {gen.loading ? 'Generating...' : 'Generate & Choose'}
          </button>
        </div>
      </div>
    )
  }

  // (Character Preview sidebar removed — not needed for avatar-only flow)

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full bg-[#0a0a0f] text-white">
      {/* ═══════════ HEADER ═══════════ */}
      <div className="px-6 pt-5 pb-4 border-b border-white/[0.06] flex-shrink-0">
        <div className="flex items-center justify-between max-w-6xl mx-auto">
          <div className="flex items-center gap-3">
            <button onClick={onClose}
              className="flex items-center gap-2 text-white/40 hover:text-white/70 transition-colors text-sm" title="Back to Gallery">
              <ChevronLeft size={16} />
            </button>
            <div className="flex items-center gap-2.5">
              <Sparkles size={18} className="text-purple-400" />
              <h1 className="text-base font-semibold tracking-tight">Avatar Studio</h1>
            </div>
          </div>

          {/* Quick / Studio toggle */}
          <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06]">
            <button onClick={() => setWizardMode('quick')}
              className={[
                'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                wizardMode === 'quick' ? 'bg-white/10 text-white shadow-sm' : 'text-white/40 hover:text-white/60',
              ].join(' ')}
            >
              <Zap size={12} /> Quick Create
            </button>
            <button onClick={() => setWizardMode('studio')}
              className={[
                'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                wizardMode === 'studio' ? 'bg-white/10 text-white shadow-sm' : 'text-white/40 hover:text-white/60',
              ].join(' ')}
            >
              <Layers size={12} /> Studio
            </button>
          </div>
        </div>
      </div>

      {/* ═══════════ BODY ═══════════ */}
      {wizardMode === 'quick' ? (
        <div className="flex-1 overflow-y-auto min-h-0 px-6 py-8">
          {renderQuickCreate()}
        </div>
      ) : (
        <div className="flex-1 flex min-h-0">
          {/* ── Sidebar ── */}
          <div className="w-48 flex-shrink-0 border-r border-white/[0.06] py-6 px-3 overflow-y-auto">
            {WIZARD_STEPS.map((s, i) => {
              const active = step === i
              const completed = i < step
              return (
                <button key={s.key}
                  onClick={() => setStep(i as any)}
                  className={[
                    'w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all mb-1',
                    active
                      ? 'bg-purple-500/10 text-purple-300 border border-purple-500/20'
                      : completed
                        ? 'text-white/50 hover:bg-white/[0.04] border border-transparent'
                        : 'text-white/25 hover:bg-white/[0.03] border border-transparent',
                  ].join(' ')}
                >
                  <span className={[
                    'w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0',
                    active ? 'bg-purple-500/25 text-purple-300'
                      : completed ? 'bg-white/10 text-white/50' : 'bg-white/[0.05] text-white/20',
                  ].join(' ')}>
                    {completed ? <Check size={10} /> : i + 1}
                  </span>
                  <span>{s.label}</span>
                </button>
              )
            })}

            {/* Randomize / Reset buttons */}
            <div className="mt-4 pt-4 border-t border-white/[0.06] space-y-1.5">
              <button onClick={randomizeAppearance}
                className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-xs font-medium text-white/35 hover:text-white/60 hover:bg-white/[0.04] border border-white/[0.06] transition-all"
              >
                <Shuffle size={12} /> Randomize Look
              </button>
              <button onClick={resetToDefaults}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-[10px] font-medium text-white/20 hover:text-white/45 hover:bg-white/[0.03] transition-all"
              >
                <RotateCcw size={10} /> Reset Defaults
              </button>
            </div>
          </div>

          {/* ── Main step content ── */}
          <div className="flex-1 overflow-y-auto min-h-0 px-8 py-6">
            <div className="max-w-2xl">
              {/* Step header */}
              <div className="mb-6">
                <div className="text-xs text-white/20 mb-1">Step {step + 1} of 7</div>
                <h2 className="text-lg font-semibold text-white/90">{WIZARD_STEPS[step].label}</h2>
              </div>

              {renderStep()}

              {/* Navigation (not on Generate step — it has its own buttons) */}
              {step < 6 && (
                <div className="flex items-center justify-between mt-8 pt-6 border-t border-white/[0.06]">
                  <button onClick={goBack} disabled={step === 0}
                    className={[
                      'flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all',
                      step > 0 ? 'text-white/50 hover:text-white/70 hover:bg-white/[0.04]' : 'text-white/15 cursor-not-allowed',
                    ].join(' ')}
                  >
                    <ChevronLeft size={14} /> Back
                  </button>
                  <button onClick={goNext} disabled={!canProceed}
                    className={[
                      'flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all',
                      canProceed
                        ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-md hover:shadow-lg hover:brightness-110 active:scale-[0.98]'
                        : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
                    ].join(' ')}
                  >
                    Next <ChevronRight size={14} />
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Preview sidebar removed — avatar-only flow */}
        </div>
      )}

      {/* ═══════════ TOAST ═══════════ */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-toastSlideUp">
          <div className={[
            'flex items-center gap-2.5 px-5 py-3 rounded-xl shadow-2xl backdrop-blur-md border text-sm font-medium',
            toast.type === 'error' ? 'bg-red-500/15 border-red-500/20 text-red-300'
              : toast.type === 'success' ? 'bg-green-500/15 border-green-500/20 text-green-300'
                : 'bg-white/10 border-white/10 text-white/70',
          ].join(' ')}>
            {toast.type === 'success' && <Sparkles size={16} />}
            <span>{toast.message}</span>
            <button onClick={() => setToast(null)} className="ml-2 text-white/30 hover:text-white/60"><X size={14} /></button>
          </div>
        </div>
      )}

      <style>{`
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        .animate-fadeSlideIn { animation: fadeSlideIn 0.35s ease-out; }
        @keyframes toastSlideUp { from { opacity: 0; transform: translate(-50%, 16px); } to { opacity: 1; transform: translate(-50%, 0); } }
        .animate-toastSlideUp { animation: toastSlideUp 0.25s ease-out; }
        @keyframes scaleIn { from { opacity: 0; transform: scale(0.5); } to { opacity: 1; transform: scale(1); } }
        .animate-scaleIn { animation: scaleIn 0.2s ease-out; }
      `}</style>
    </div>
  )
}
