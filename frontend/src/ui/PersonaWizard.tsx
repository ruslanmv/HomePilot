/**
 * PersonaWizard — Phase 2
 *
 * A 4-step wizard for creating Persona projects with class-based blueprints.
 *
 * Steps:
 *   0. Choose Class  — Secretary, Assistant, Companion, NSFW classes (if enabled), Custom
 *   1. Identity      — name, role, system prompt, tone, goal, skills (pre-filled from class)
 *   2. Appearance    — style preset, generate 4 looks, pick avatar (stores avatar_settings)
 *   3. Review        — summary card with class badge, skills, and create button
 *
 * NSFW classes and appearance options are shown dynamically based on global Spice Mode
 * setting — no explicit banner or callout.
 *
 * Avatar generation settings are stored for reproducibility and outfit variations.
 */

import React, { useMemo, useState } from 'react'
import { X, ChevronRight, ChevronLeft, Sparkles, Loader2, Shield, Star, Check } from 'lucide-react'
import type {
  PersonaAppearance,
  PersonaImageRef,
  PersonaWizardDraft,
  PersonaClassId,
  PersonaBlueprint,
  AvatarGenerationSettings,
} from './personaTypes'
import { PERSONA_BLUEPRINTS } from './personaTypes'
import { createPersonaProject, generatePersonaImages } from './personaApi'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type Props = {
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onCreated?: (project: any) => void
}

// ---------------------------------------------------------------------------
// Defaults & Helpers
// ---------------------------------------------------------------------------

function readNsfwMode(): boolean {
  try {
    return localStorage.getItem('homepilot_nsfw_mode') === 'true'
  } catch {
    return false
  }
}

let _imgCounter = 0
function nextImageId(): string {
  return `pimg_${Date.now()}_${++_imgCounter}`
}

function defaultAppearance(): PersonaAppearance {
  return {
    style_preset: 'Executive',
    aspect_ratio: '2:3',
    img_preset: 'med',
    img_model: 'dreamshaper_8.safetensors',
    nsfwMode: false,
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
// Style presets — SFW
// ---------------------------------------------------------------------------

const STYLE_PRESETS = ['Executive', 'Elegant', 'Romantic', 'Casual'] as const

const STYLE_HINTS: Record<string, string> = {
  Executive: 'professional, composed, business attire, confident',
  Elegant: 'graceful, refined, evening wear, sophisticated',
  Romantic: 'warm, inviting, soft lighting, natural beauty',
  Casual: 'relaxed, approachable, everyday style, friendly',
}

// ---------------------------------------------------------------------------
// Style presets — NSFW (shown dynamically when spice mode is on)
// ---------------------------------------------------------------------------

const NSFW_STYLE_PRESETS = ['Seductive', 'Lingerie', 'Pin-Up', 'Fantasy'] as const
type NsfwStylePreset = (typeof NSFW_STYLE_PRESETS)[number]

const NSFW_STYLE_HINTS: Record<string, string> = {
  Seductive: 'seductive pose, alluring, sultry expression, form-fitting outfit, provocative',
  Lingerie: 'lace lingerie, boudoir photography, intimate setting, sensual, bedroom eyes',
  'Pin-Up': 'retro pin-up style, playful, vintage glamour, suggestive pose, confident smile',
  Fantasy: 'fantasy costume, exotic, mystical setting, enchanting, bold and daring',
}

const BODY_TYPES = ['Slim', 'Athletic', 'Curvy', 'Voluptuous', 'Petite'] as const
const OUTFIT_HINTS: Record<string, string> = {
  'Cocktail dress': 'tight cocktail dress, showing cleavage',
  'Lingerie set': 'lace lingerie set, stockings',
  Bikini: 'bikini, beach setting',
  'Evening gown': 'revealing evening gown, low neckline, thigh slit',
  'Crop top': 'crop top, tight shorts, midriff showing',
  'None specified': '',
}

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

const BUILTIN_CAPABILITIES: Array<{ id: string; label: string; desc: string }> = [
  { id: 'generate_images', label: 'Image Generation', desc: 'Create and edit images' },
  { id: 'generate_videos', label: 'Video Generation', desc: 'Create short video clips' },
  { id: 'analyze_documents', label: 'Document Analysis', desc: 'Read and analyze uploaded files' },
  { id: 'automate_external', label: 'Automation', desc: 'Connect to external services' },
]

// ---------------------------------------------------------------------------
// Color maps for class cards
// ---------------------------------------------------------------------------

const CLASS_COLORS: Record<string, { bg: string; border: string; text: string; ring: string }> = {
  blue: { bg: 'bg-blue-500/15', border: 'border-blue-500/30', text: 'text-blue-300', ring: 'ring-blue-500/20' },
  purple: { bg: 'bg-purple-500/15', border: 'border-purple-500/30', text: 'text-purple-300', ring: 'ring-purple-500/20' },
  rose: { bg: 'bg-rose-500/15', border: 'border-rose-500/30', text: 'text-rose-300', ring: 'ring-rose-500/20' },
  pink: { bg: 'bg-pink-500/15', border: 'border-pink-500/30', text: 'text-pink-300', ring: 'ring-pink-500/20' },
  red: { bg: 'bg-red-500/15', border: 'border-red-500/30', text: 'text-red-300', ring: 'ring-red-500/20' },
  emerald: { bg: 'bg-emerald-500/15', border: 'border-emerald-500/30', text: 'text-emerald-300', ring: 'ring-emerald-500/20' },
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PersonaWizard({ backendUrl, apiKey, onClose, onCreated }: Props) {
  const [step, setStep] = useState<0 | 1 | 2 | 3>(0)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)

  // Global NSFW mode — determines which classes and options are visible
  const isSpicy = readNsfwMode()

  // NSFW appearance options
  const [nsfwStylePreset, setNsfwStylePreset] = useState<NsfwStylePreset>('Seductive')
  const [bodyType, setBodyType] = useState<string>('Curvy')
  const [outfit, setOutfit] = useState<string>('None specified')
  const [customPromptExtra, setCustomPromptExtra] = useState('')

  // Character description (for outfit system — editable in step 2)
  const [characterDesc, setCharacterDesc] = useState('')

  const [draft, setDraft] = useState<PersonaWizardDraft>(() => ({
    persona_class: 'custom',
    persona_agent: defaultPersonaAgent(),
    persona_appearance: { ...defaultAppearance(), nsfwMode: readNsfwMode() },
    agentic: { goal: '', capabilities: [] },
  }))

  // -------------------------------------------------------------------------
  // Available blueprints: SFW always + NSFW only when enabled + Custom always
  // -------------------------------------------------------------------------

  const availableBlueprints = useMemo(() => {
    return PERSONA_BLUEPRINTS.filter((bp) => bp.category === 'sfw' || isSpicy)
  }, [isSpicy])

  // -------------------------------------------------------------------------
  // Navigation guard
  // -------------------------------------------------------------------------

  const canNext = useMemo(() => {
    if (step === 0) return draft.persona_class !== undefined
    if (step === 1) return (draft.persona_agent?.label ?? '').trim().length > 0
    if (step === 2) return !!draft.persona_appearance.selected?.image_id
    return true
  }, [step, draft])

  // -------------------------------------------------------------------------
  // Step 0: Select class
  // -------------------------------------------------------------------------

  function onSelectClass(bp: PersonaBlueprint) {
    const isNsfw = bp.category === 'nsfw'
    const newAgent = {
      ...defaultPersonaAgent(),
      label: bp.id === 'custom' ? '' : bp.label,
      role: bp.defaults.role,
      system_prompt: bp.defaults.system_prompt,
      category: bp.id,
      response_style: { max_length: 500, tone: bp.defaults.tone, use_emoji: false },
      image_style_hint: bp.defaults.image_style_hint,
      safety: { ...bp.defaults.safety },
    }

    const stylePreset = bp.defaults.style_preset as any

    setDraft({
      persona_class: bp.id,
      persona_agent: newAgent,
      persona_appearance: {
        ...defaultAppearance(),
        style_preset: stylePreset,
        nsfwMode: isNsfw || isSpicy,
      },
      agentic: {
        goal: bp.defaults.goal,
        capabilities: [...bp.defaults.capabilities],
      },
    })

    // For NSFW classes, pre-set the NSFW style to match
    if (isNsfw && NSFW_STYLE_PRESETS.includes(stylePreset as any)) {
      setNsfwStylePreset(stylePreset as NsfwStylePreset)
    }

    setCharacterDesc('')
    setStep(1)
  }

  // -------------------------------------------------------------------------
  // Build the generation prompt
  // -------------------------------------------------------------------------

  function buildPrompt(): { characterPrompt: string; outfitPrompt: string; fullPrompt: string } {
    const personaName = (draft.persona_agent?.label ?? 'persona').trim()
    const role = draft.persona_agent?.role ?? ''
    const isNsfw = isSpicy && draft.persona_appearance.nsfwMode

    let characterPrompt: string
    let outfitPrompt: string

    if (characterDesc.trim()) {
      // User-edited character description
      characterPrompt = characterDesc.trim()
    } else {
      characterPrompt = `high quality studio portrait, beautiful adult woman, ${personaName}${role ? `, ${role}` : ''}`
    }

    if (isNsfw) {
      const nsfwHint = NSFW_STYLE_HINTS[nsfwStylePreset] ?? ''
      const bodyHint = bodyType && bodyType !== 'Slim' ? `, ${bodyType.toLowerCase()} body type` : ''
      const outfitHint = OUTFIT_HINTS[outfit] ?? ''
      const customHint = customPromptExtra ? `, ${customPromptExtra}` : ''
      outfitPrompt = `${nsfwStylePreset.toLowerCase()} style, ${nsfwHint}${bodyHint}${outfitHint ? `, ${outfitHint}` : ''}${customHint}`
    } else {
      const preset = draft.persona_appearance.style_preset
      const hint = STYLE_HINTS[preset] ?? ''
      outfitPrompt = `${preset.toLowerCase()} style, ${hint}`
    }

    const fullPrompt = `${characterPrompt}, ${outfitPrompt}, elegant lighting, realistic, sharp focus`
    return { characterPrompt, outfitPrompt, fullPrompt }
  }

  // -------------------------------------------------------------------------
  // Image generation
  // -------------------------------------------------------------------------

  async function onGenerateSet() {
    setGenerating(true)
    setGenError(null)
    try {
      const { characterPrompt, outfitPrompt, fullPrompt } = buildPrompt()
      const isNsfw = isSpicy && draft.persona_appearance.nsfwMode

      const out = await generatePersonaImages({
        backendUrl,
        apiKey,
        prompt: fullPrompt,
        imgModel: draft.persona_appearance.img_model,
        imgBatchSize: 4,
        imgAspectRatio: draft.persona_appearance.aspect_ratio,
        imgPreset: draft.persona_appearance.img_preset,
        promptRefinement: true,
        nsfwMode: isNsfw,
      })

      if (out.urls.length === 0) {
        setGenError('No images returned. Check that your image backend is running.')
        return
      }

      const set_id = `set_${String(draft.persona_appearance.sets.length + 1).padStart(3, '0')}`
      const created_at = new Date().toISOString()
      const images: PersonaImageRef[] = out.urls.map((url, i) => ({
        id: nextImageId(),
        url,
        created_at,
        set_id,
        seed: out.seeds?.[i],
      }))

      const nextSets = [...draft.persona_appearance.sets, { set_id, images }]
      const selected =
        draft.persona_appearance.selected ?? (images[0] ? { set_id, image_id: images[0].id } : undefined)

      // Store avatar generation settings for reproducibility
      const avatarSettings: AvatarGenerationSettings = {
        character_prompt: characterPrompt,
        outfit_prompt: outfitPrompt,
        full_prompt: out.final_prompt ?? fullPrompt,
        style_preset: isNsfw ? nsfwStylePreset : draft.persona_appearance.style_preset,
        body_type: isNsfw ? bodyType : undefined,
        custom_extras: customPromptExtra || undefined,
        img_model: out.model ?? draft.persona_appearance.img_model ?? 'dreamshaper_8.safetensors',
        img_preset: draft.persona_appearance.img_preset,
        aspect_ratio: draft.persona_appearance.aspect_ratio,
        nsfw_mode: !!isNsfw,
      }

      // Auto-fill character description for user to see / edit
      if (!characterDesc.trim()) {
        setCharacterDesc(characterPrompt)
      }

      setDraft({
        ...draft,
        persona_appearance: {
          ...draft.persona_appearance,
          sets: nextSets,
          selected,
          final_prompt: out.final_prompt ?? draft.persona_appearance.final_prompt,
          img_model: out.model ?? draft.persona_appearance.img_model,
          avatar_settings: avatarSettings,
        },
      })
    } catch (err: any) {
      setGenError(err?.message || 'Image generation failed.')
    } finally {
      setGenerating(false)
    }
  }

  // -------------------------------------------------------------------------
  // Create project
  // -------------------------------------------------------------------------

  async function onCreate() {
    setSaving(true)
    try {
      const name = draft.persona_agent.label
      const description = draft.persona_agent.role ?? ''

      const result = await createPersonaProject({
        backendUrl,
        apiKey,
        name,
        description,
        persona_agent: { ...draft.persona_agent, persona_class: draft.persona_class },
        persona_appearance: draft.persona_appearance,
        agentic: {
          goal: draft.agentic.goal,
          capabilities: draft.agentic.capabilities,
          execution_profile: 'balanced',
          ask_before_acting: true,
        },
      })

      onCreated?.(result.project ?? result)
      onClose()
    } catch (err: any) {
      alert(`Failed to create persona project: ${err?.message || 'Unknown error'}`)
    } finally {
      setSaving(false)
    }
  }

  // -------------------------------------------------------------------------
  // Image helpers
  // -------------------------------------------------------------------------

  const allImages = draft.persona_appearance.sets.flatMap((s) => s.images.map((img) => ({ ...img })))

  const selectedImageUrl = useMemo(() => {
    const sel = draft.persona_appearance.selected
    if (!sel) return null
    for (const s of draft.persona_appearance.sets) {
      for (const img of s.images) {
        if (img.id === sel.image_id && img.set_id === sel.set_id) return img.url
      }
    }
    return null
  }, [draft.persona_appearance.selected, draft.persona_appearance.sets])

  const currentBlueprint = PERSONA_BLUEPRINTS.find((bp) => bp.id === draft.persona_class)

  // -------------------------------------------------------------------------
  // Step labels
  // -------------------------------------------------------------------------

  const STEP_LABELS = ['Choose Class', 'Identity & Skills', 'Appearance', 'Review'] as const

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-4xl bg-[#1a1a2e] rounded-2xl border border-white/10 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Sparkles size={18} className="text-pink-400" />
              Create Persona
            </h2>
            <div className="flex items-center gap-2 mt-1">
              {STEP_LABELS.map((label, i) => (
                <React.Fragment key={i}>
                  {i > 0 && <span className="text-white/20 text-xs">&rsaquo;</span>}
                  <span
                    className={`text-xs ${
                      i === step
                        ? 'text-purple-300 font-semibold'
                        : i < step
                          ? 'text-white/50'
                          : 'text-white/25'
                    }`}
                  >
                    {label}
                  </span>
                </React.Fragment>
              ))}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
          {/* ===== STEP 0: Choose Class ===== */}
          {step === 0 && (
            <div className="space-y-4">
              <div className="text-center mb-6">
                <h3 className="text-xl font-bold text-white mb-1">Choose your persona class</h3>
                <p className="text-sm text-white/50">
                  Pick a template to get started quickly, or go fully custom.
                </p>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {availableBlueprints.map((bp) => {
                  const colors = CLASS_COLORS[bp.color] || CLASS_COLORS.purple
                  const isSelected = draft.persona_class === bp.id

                  return (
                    <button
                      key={bp.id}
                      type="button"
                      onClick={() => onSelectClass(bp)}
                      className={`relative flex flex-col items-start p-4 rounded-xl border-2 transition-all text-left group hover:scale-[1.02] ${
                        isSelected
                          ? `${colors.bg} ${colors.border} ring-2 ${colors.ring}`
                          : 'bg-white/5 border-white/10 hover:border-white/25 hover:bg-white/8'
                      }`}
                    >
                      {/* Icon */}
                      <div className="text-3xl mb-2">{bp.icon}</div>

                      {/* Name */}
                      <div className={`text-sm font-bold ${isSelected ? colors.text : 'text-white'}`}>
                        {bp.label}
                      </div>

                      {/* Description */}
                      <div className="text-[11px] text-white/50 mt-1 leading-relaxed">{bp.description}</div>

                      {/* Pre-filled skills count */}
                      {bp.defaults.capabilities.length > 0 && (
                        <div className="flex items-center gap-1 mt-2">
                          <Shield size={10} className="text-emerald-400" />
                          <span className="text-[10px] text-emerald-300/80">
                            {bp.defaults.capabilities.length} skill
                            {bp.defaults.capabilities.length !== 1 ? 's' : ''} included
                          </span>
                        </div>
                      )}

                      {/* Category tag */}
                      {bp.category === 'nsfw' && (
                        <span className="absolute top-2 right-2 text-[9px] px-1.5 py-0.5 rounded-full bg-orange-500/20 border border-orange-500/30 text-orange-300 font-medium">
                          18+
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* ===== STEP 1: Identity & Skills ===== */}
          {step === 1 && (
            <div className="space-y-5">
              {/* Class badge */}
              {currentBlueprint && currentBlueprint.id !== 'custom' && (
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-lg">{currentBlueprint.icon}</span>
                  <span
                    className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      CLASS_COLORS[currentBlueprint.color]?.bg ?? 'bg-white/10'
                    } ${CLASS_COLORS[currentBlueprint.color]?.text ?? 'text-white/60'} border ${
                      CLASS_COLORS[currentBlueprint.color]?.border ?? 'border-white/10'
                    }`}
                  >
                    {currentBlueprint.label} Class
                  </span>
                  <span className="text-[11px] text-white/40 ml-1">
                    All fields are pre-filled &mdash; customize anything you like.
                  </span>
                </div>
              )}

              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80">Name</label>
                <input
                  type="text"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all"
                  value={draft.persona_agent.label}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      persona_agent: { ...draft.persona_agent, label: e.target.value },
                    })
                  }
                  placeholder="e.g., Scarlett"
                />
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80">Role</label>
                <input
                  type="text"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all"
                  value={draft.persona_agent.role ?? ''}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      persona_agent: { ...draft.persona_agent, role: e.target.value },
                    })
                  }
                  placeholder="e.g., Executive Secretary"
                />
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80">Personality (system prompt)</label>
                <textarea
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all min-h-[100px] resize-y"
                  value={draft.persona_agent.system_prompt ?? ''}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      persona_agent: { ...draft.persona_agent, system_prompt: e.target.value },
                    })
                  }
                  placeholder="Describe how this persona should behave, their personality traits, background..."
                />
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80">Tone</label>
                <div className="flex flex-wrap gap-2">
                  {(['warm', 'professional', 'playful', 'assertive', ...(isSpicy ? ['flirty'] : [])] as const).map((tone) => (
                    <button
                      key={tone}
                      type="button"
                      onClick={() =>
                        setDraft({
                          ...draft,
                          persona_agent: {
                            ...draft.persona_agent,
                            response_style: { ...draft.persona_agent.response_style, tone },
                          },
                        })
                      }
                      className={`px-4 py-2 rounded-full border text-sm capitalize transition-all ${
                        draft.persona_agent.response_style?.tone === tone
                          ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
                          : 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10 hover:text-white/80'
                      }`}
                    >
                      {tone}
                    </button>
                  ))}
                </div>
              </div>

              {/* Goal */}
              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80 flex items-center gap-2">
                  <Star size={14} className="text-amber-400" />
                  Goal
                </label>
                <input
                  type="text"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500 transition-all text-sm"
                  value={draft.agentic.goal}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      agentic: { ...draft.agentic, goal: e.target.value },
                    })
                  }
                  placeholder="e.g., Help me plan my week and manage my schedule"
                />
              </div>

              {/* Skills */}
              <div className="space-y-3">
                <label className="block text-sm font-medium text-white/80 flex items-center gap-2">
                  <Shield size={14} className="text-emerald-400" />
                  Skills
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {BUILTIN_CAPABILITIES.map((cap) => {
                    const active = draft.agentic.capabilities.includes(cap.id)
                    return (
                      <button
                        key={cap.id}
                        type="button"
                        onClick={() => {
                          const next = active
                            ? draft.agentic.capabilities.filter((c) => c !== cap.id)
                            : [...draft.agentic.capabilities, cap.id]
                          setDraft({ ...draft, agentic: { ...draft.agentic, capabilities: next } })
                        }}
                        className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl border text-left transition-all ${
                          active
                            ? 'bg-emerald-500/15 border-emerald-500/30'
                            : 'bg-white/5 border-white/10 hover:bg-white/8'
                        }`}
                      >
                        <div
                          className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors ${
                            active ? 'bg-emerald-500 border-emerald-500' : 'border-white/20'
                          }`}
                        >
                          {active && <Check size={10} className="text-white" />}
                        </div>
                        <div>
                          <span className={`text-sm ${active ? 'text-white' : 'text-white/60'}`}>
                            {cap.label}
                          </span>
                          <div className="text-[10px] text-white/35">{cap.desc}</div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ===== STEP 2: Appearance ===== */}
          {step === 2 && (
            <div className="space-y-5">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {/* Left: Generation controls */}
                <div className="space-y-4">
                  {/* Style presets — SFW or NSFW shown dynamically based on global setting */}
                  {isSpicy ? (
                    <>
                      <div className="space-y-3">
                        <label className="block text-sm font-medium text-white/80">Style</label>
                        <div className="flex flex-wrap gap-2">
                          {NSFW_STYLE_PRESETS.map((p) => (
                            <button
                              key={p}
                              type="button"
                              onClick={() => setNsfwStylePreset(p)}
                              className={`px-4 py-2 rounded-full border text-sm transition-all ${
                                nsfwStylePreset === p
                                  ? 'bg-pink-500/20 border-pink-500/50 text-pink-300'
                                  : 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10 hover:text-white/80'
                              }`}
                            >
                              {p}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <label className="block text-sm font-medium text-white/80">Body type</label>
                        <div className="flex flex-wrap gap-2">
                          {BODY_TYPES.map((bt) => (
                            <button
                              key={bt}
                              type="button"
                              onClick={() => setBodyType(bt)}
                              className={`px-4 py-2 rounded-full border text-sm transition-all ${
                                bodyType === bt
                                  ? 'bg-pink-500/20 border-pink-500/50 text-pink-300'
                                  : 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10 hover:text-white/80'
                              }`}
                            >
                              {bt}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <label className="block text-sm font-medium text-white/80">Outfit</label>
                        <div className="flex flex-wrap gap-2">
                          {Object.keys(OUTFIT_HINTS).map((o) => (
                            <button
                              key={o}
                              type="button"
                              onClick={() => setOutfit(o)}
                              className={`px-4 py-2 rounded-full border text-sm transition-all ${
                                outfit === o
                                  ? 'bg-pink-500/20 border-pink-500/50 text-pink-300'
                                  : 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10 hover:text-white/80'
                              }`}
                            >
                              {o}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <label className="block text-sm font-medium text-white/80">
                          Custom prompt extras (optional)
                        </label>
                        <input
                          type="text"
                          className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-pink-500 focus:ring-1 focus:ring-pink-500 transition-all text-sm"
                          value={customPromptExtra}
                          onChange={(e) => setCustomPromptExtra(e.target.value)}
                          placeholder="e.g., long red hair, green eyes, tattoo on shoulder"
                        />
                      </div>
                    </>
                  ) : (
                    <div className="space-y-3">
                      <label className="block text-sm font-medium text-white/80">Style preset</label>
                      <div className="flex flex-wrap gap-2">
                        {STYLE_PRESETS.map((p) => (
                          <button
                            key={p}
                            type="button"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                persona_appearance: { ...draft.persona_appearance, style_preset: p },
                              })
                            }
                            className={`px-4 py-2 rounded-full border text-sm transition-all ${
                              draft.persona_appearance.style_preset === p
                                ? 'bg-pink-500/20 border-pink-500/50 text-pink-300'
                                : 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10 hover:text-white/80'
                            }`}
                          >
                            {p}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Character description — auto-generated, editable for reproducibility */}
                  <div className="space-y-3">
                    <label className="block text-sm font-medium text-white/80">
                      Character description
                      <span className="text-[10px] text-white/40 ml-2 font-normal">
                        (auto-filled, edit to customize your character's look)
                      </span>
                    </label>
                    <textarea
                      className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-white/40 focus:outline-none focus:border-purple-500 focus:ring-1 focus:ring-purple-500 transition-all min-h-[60px] resize-y text-sm"
                      value={characterDesc}
                      onChange={(e) => setCharacterDesc(e.target.value)}
                      placeholder="e.g., beautiful woman, long brown hair, green eyes, fair skin, elegant face..."
                    />
                    <p className="text-[10px] text-white/30 px-1">
                      This description defines your character's physical appearance and stays constant across
                      outfit variations. Edit it to lock in the exact look you want.
                    </p>
                  </div>

                  {/* Quality */}
                  <div className="space-y-3">
                    <label className="block text-sm font-medium text-white/80">Quality</label>
                    <div className="flex flex-wrap gap-2">
                      {(['low', 'med', 'high'] as const).map((q) => (
                        <button
                          key={q}
                          type="button"
                          onClick={() =>
                            setDraft({
                              ...draft,
                              persona_appearance: { ...draft.persona_appearance, img_preset: q },
                            })
                          }
                          className={`px-4 py-2 rounded-full border text-sm capitalize transition-all ${
                            draft.persona_appearance.img_preset === q
                              ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
                              : 'bg-white/5 border-white/10 text-white/60 hover:bg-white/10 hover:text-white/80'
                          }`}
                        >
                          {q === 'med' ? 'Medium' : q === 'low' ? 'Fast' : 'High'}
                        </button>
                      ))}
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={onGenerateSet}
                    disabled={generating}
                    className="w-full px-6 py-3 bg-purple-500 hover:bg-purple-600 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-all flex items-center justify-center gap-2"
                  >
                    {generating ? (
                      <>
                        <Loader2 size={16} className="animate-spin" />
                        Generating 4 looks...
                      </>
                    ) : (
                      <>
                        <Sparkles size={16} />
                        {allImages.length > 0 ? 'Generate 4 more' : 'Generate 4 looks'}
                      </>
                    )}
                  </button>

                  {genError && (
                    <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
                      {genError}
                    </div>
                  )}

                  {allImages.length > 0 && (
                    <div className="text-xs text-white/40">
                      {allImages.length} image{allImages.length !== 1 ? 's' : ''} generated
                    </div>
                  )}
                </div>

                {/* Right: Avatar picker */}
                <div className="space-y-3">
                  <label className="block text-sm font-medium text-white/80">Pick your avatar</label>

                  {allImages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-64 bg-white/5 border border-white/10 rounded-xl text-white/40 text-sm">
                      <Sparkles size={32} className="mb-3 opacity-40" />
                      Generate a set to view options
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-3 max-h-[440px] overflow-y-auto custom-scrollbar pr-1">
                      {allImages.map((img) => {
                        const isSel =
                          draft.persona_appearance.selected?.set_id === img.set_id &&
                          draft.persona_appearance.selected?.image_id === img.id

                        return (
                          <button
                            key={img.id}
                            type="button"
                            onClick={() =>
                              setDraft({
                                ...draft,
                                persona_appearance: {
                                  ...draft.persona_appearance,
                                  selected: { set_id: img.set_id, image_id: img.id },
                                },
                              })
                            }
                            className={`relative overflow-hidden rounded-xl border-2 transition-all ${
                              isSel
                                ? 'border-purple-500 ring-2 ring-purple-500/30'
                                : 'border-white/10 hover:border-white/30'
                            }`}
                          >
                            <img src={img.url} className="w-full h-48 object-cover" alt="" loading="lazy" />
                            {isSel && (
                              <div className="absolute top-2 right-2 text-xs bg-purple-500 px-2 py-1 rounded-full font-medium shadow-lg">
                                Selected
                              </div>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ===== STEP 3: Review ===== */}
          {step === 3 && (
            <div className="space-y-5">
              <div className="bg-white/5 border border-white/10 rounded-xl p-5 space-y-4">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-2xl">{currentBlueprint?.icon}</span>
                  <div>
                    <div className="text-lg font-semibold text-white">Review</div>
                    {currentBlueprint && currentBlueprint.id !== 'custom' && (
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                          CLASS_COLORS[currentBlueprint.color]?.bg ?? 'bg-white/10'
                        } ${CLASS_COLORS[currentBlueprint.color]?.text ?? 'text-white/60'} border ${
                          CLASS_COLORS[currentBlueprint.color]?.border ?? 'border-white/10'
                        }`}
                      >
                        {currentBlueprint.label} Class
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Left: avatar preview */}
                  <div>
                    {selectedImageUrl ? (
                      <img
                        src={selectedImageUrl}
                        className="w-full max-w-[280px] rounded-xl border border-white/10"
                        alt="Selected avatar"
                      />
                    ) : (
                      <div className="w-full h-64 bg-white/5 border border-white/10 rounded-xl flex items-center justify-center text-white/40 text-sm">
                        No avatar selected
                      </div>
                    )}
                  </div>

                  {/* Right: identity summary */}
                  <div className="space-y-3">
                    <div>
                      <span className="text-xs text-white/50">Name</span>
                      <div className="text-white font-medium">{draft.persona_agent.label}</div>
                    </div>
                    {draft.persona_agent.role && (
                      <div>
                        <span className="text-xs text-white/50">Role</span>
                        <div className="text-white/80 text-sm">{draft.persona_agent.role}</div>
                      </div>
                    )}
                    <div>
                      <span className="text-xs text-white/50">Style</span>
                      <div className="text-white/80 text-sm">
                        {isSpicy ? nsfwStylePreset : draft.persona_appearance.style_preset}
                      </div>
                    </div>
                    <div>
                      <span className="text-xs text-white/50">Tone</span>
                      <div className="text-white/80 text-sm capitalize">
                        {draft.persona_agent.response_style?.tone ?? 'warm'}
                      </div>
                    </div>

                    {/* Goal */}
                    {draft.agentic.goal && (
                      <div>
                        <span className="text-xs text-white/50">Goal</span>
                        <div className="text-white/80 text-sm">{draft.agentic.goal}</div>
                      </div>
                    )}

                    {/* Skills */}
                    {draft.agentic.capabilities.length > 0 && (
                      <div>
                        <span className="text-xs text-white/50">Skills</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {draft.agentic.capabilities.map((capId) => {
                            const cap = BUILTIN_CAPABILITIES.find((c) => c.id === capId)
                            return (
                              <span
                                key={capId}
                                className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/20 text-emerald-300"
                              >
                                {cap?.label ?? capId}
                              </span>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {draft.persona_agent.system_prompt && (
                      <div>
                        <span className="text-xs text-white/50">Personality</span>
                        <div className="text-white/60 text-xs mt-1 bg-white/5 border border-white/10 rounded-lg p-3 max-h-[100px] overflow-y-auto">
                          {draft.persona_agent.system_prompt}
                        </div>
                      </div>
                    )}

                    <div className="text-xs text-white/40 mt-2">
                      {allImages.length} image{allImages.length !== 1 ? 's' : ''} generated &middot;
                      Quality: {draft.persona_appearance.img_preset}
                    </div>

                    {/* Avatar settings note */}
                    {draft.persona_appearance.avatar_settings && (
                      <div className="text-[10px] text-white/30 bg-white/[0.03] border border-white/5 rounded-lg p-2">
                        Generation settings saved &mdash; you can reproduce this look or create
                        outfit variations later from the persona settings panel.
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="bg-white/5 border border-white/10 rounded-xl p-4 text-sm text-white/60">
                Tools, Knowledge Base, and Outfit Variations can be configured later by editing this persona
                project.
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-white/10 bg-[#1a1a2e] flex justify-between">
          <button
            onClick={() => (step === 0 ? onClose() : setStep((step - 1) as any))}
            className="px-4 py-2 text-sm font-medium text-white/60 hover:text-white transition-colors flex items-center gap-1"
          >
            {step === 0 ? (
              'Cancel'
            ) : (
              <>
                <ChevronLeft size={16} />
                Back
              </>
            )}
          </button>

          <div className="flex gap-2">
            {step > 0 && step < 3 && (
              <button
                disabled={!canNext}
                onClick={() => setStep((step + 1) as any)}
                className="px-6 py-2 bg-purple-500 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-full transition-colors flex items-center gap-2"
              >
                Next <ChevronRight size={16} />
              </button>
            )}

            {step === 3 && (
              <button
                disabled={saving || !draft.persona_appearance.selected?.image_id}
                onClick={onCreate}
                className="px-6 py-2 bg-purple-500 hover:bg-purple-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-full transition-colors"
              >
                {saving ? 'Creating...' : 'Create Persona Project'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
