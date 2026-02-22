/**
 * PersonaSettingsPanel — RPG-style character sheet for persona projects
 *
 * Replaces the AgentSettingsPanel when editing persona projects.
 * Displays the avatar gallery, identity details, appearance settings,
 * and agentic capabilities (goal, tools, agents, execution profile).
 *
 * Phase 2 additions:
 *   - Wardrobe system — generate outfit variations using stored character prompt
 *   - Avatar generation settings display — shows reproducibility info
 *   - Class badge from persona_class stored in persona_agent
 *
 * Designed like an MMORPG character profile card.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  X,
  Sparkles,
  User,
  Heart,
  Star,
  Shield,
  Palette,
  FileText,
  Trash2,
  Loader2,
  Camera,
  Zap,
  Wrench,
  Users,
  Server,
  Settings,
  Check,
  ChevronDown,
  ChevronUp,
  Shirt,
  Plus,
  Copy,
  Upload,
  RefreshCw,
} from 'lucide-react'
import { ImageViewer } from '../ImageViewer'
import type { PersonaImageRef, PersonaOutfit, AvatarGenerationSettings, GenerationMode } from '../personaTypes'
import { OUTFIT_PRESETS, PERSONA_BLUEPRINTS } from '../personaTypes'
import { generateOutfitImages, generatePersonaImages } from '../personaApi'
import { commitPersonaAvatar } from '../personaPortability'
import { useAvatarCapabilities } from '../useAvatarCapabilities'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PersonaProjectData = {
  id: string
  name: string
  description?: string
  instructions?: string
  project_type?: string
  created_at?: number
  files?: Array<{ name: string; size?: string; chunks?: number }>
  persona_agent?: Record<string, any>
  persona_appearance?: Record<string, any>
  agentic?: {
    goal?: string
    capabilities?: string[]
    tool_ids?: string[]
    a2a_agent_ids?: string[]
    tool_details?: Array<{ id: string; name: string; description?: string }>
    agent_details?: Array<{ id: string; name: string; description?: string }>
    tool_source?: string
    ask_before_acting?: boolean
    execution_profile?: 'fast' | 'balanced' | 'quality'
  }
}

type CatalogItem = { id: string; name: string; description?: string; enabled?: boolean }
type CatalogServer = { id: string; name: string; description?: string; enabled?: boolean; tool_ids?: string[] }

type Props = {
  project: PersonaProjectData
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onSaved: (updated: PersonaProjectData) => void
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PROFILE_OPTIONS: Array<{
  value: 'fast' | 'balanced' | 'quality'
  label: string
  hint: string
  icon: string
}> = [
  { value: 'fast', label: 'Swift', hint: 'Low latency, fewer tool calls', icon: '\u26A1' },
  { value: 'balanced', label: 'Balanced', hint: 'Good mix of speed and depth', icon: '\u2696\uFE0F' },
  { value: 'quality', label: 'Thorough', hint: 'Multi-step reasoning', icon: '\uD83C\uDFAF' },
]

const BUILTIN_CAPABILITIES: Array<{ id: string; label: string }> = [
  { id: 'generate_images', label: 'Generate images' },
  { id: 'generate_videos', label: 'Generate short videos' },
  { id: 'analyze_documents', label: 'Analyze documents' },
  { id: 'automate_external', label: 'Automate external services' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readNsfwMode(): boolean {
  try {
    return localStorage.getItem('homepilot_nsfw_mode') === 'true'
  } catch {
    return false
  }
}

/** Build a displayable /files/ URL from a DB-stored relative path.
 *  Appends auth token for <img> tags that can't set Authorization headers. */
function fileUrl(backendUrl: string, rel?: string | null): string | null {
  if (!rel) return null
  const clean = rel.replace(/^\/+/, '')
  const tok = localStorage.getItem('homepilot_auth_token') || ''
  return `${backendUrl}/files/${clean}${tok ? `?token=${encodeURIComponent(tok)}` : ''}`
}

/** Resolve an image URL — prepend backendUrl for backend-relative paths
 *  like `/comfy/view/...` that come from Avatar Studio exports.
 *  Appends auth token for /files/ paths (needed for <img> tags). */
function resolveImgUrl(url: string, backendUrl: string): string {
  if (!url) return url
  if (url.startsWith('data:') || url.startsWith('blob:')) return url

  let full = url
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    const base = backendUrl.replace(/\/+$/, '')
    const path = url.startsWith('/') ? url : `/${url}`
    full = `${base}${path}`
  }

  // Append auth token for /files/ paths so <img> tags can access them
  if (full.includes('/files/')) {
    const tok = localStorage.getItem('homepilot_auth_token') || ''
    if (tok) {
      const sep = full.includes('?') ? '&' : '?'
      return `${full}${sep}token=${encodeURIComponent(tok)}`
    }
  }
  return full
}

let _imgCounter = 0
function nextImageId(): string {
  return `pimg_${Date.now()}_${++_imgCounter}`
}

function SectionHeader({
  icon: Icon,
  title,
  badge,
  color = 'text-white/50',
}: {
  icon: React.ElementType
  title: string
  badge?: string | number
  color?: string
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon size={14} className={color} />
      <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">{title}</span>
      {badge !== undefined && (
        <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded-full bg-white/10 text-white/50 font-medium">
          {badge}
        </span>
      )}
    </div>
  )
}

function StatBar({ label, value, color = 'bg-purple-500' }: { label: string; value: number; color?: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-[11px] text-white/50 w-20 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-[10px] text-white/40 w-8 text-right">{value}</span>
    </div>
  )
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex items-center justify-between w-full group">
      <span className="text-sm text-white/80 group-hover:text-white transition-colors">{label}</span>
      <div
        className={[
          'relative w-10 h-5 rounded-full transition-colors',
          checked ? 'bg-pink-500' : 'bg-white/15',
        ].join(' ')}
      >
        <div
          className={[
            'absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform',
            checked ? 'translate-x-5' : 'translate-x-0.5',
          ].join(' ')}
        />
      </div>
    </button>
  )
}

function StatusDot({ ok }: { ok: boolean }) {
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${ok ? 'bg-green-400' : 'bg-white/20'}`} />
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PersonaSettingsPanel({ project, backendUrl, apiKey, onClose, onSaved }: Props) {
  const pa = project.persona_agent || {}
  const pap = project.persona_appearance || {}
  const ag = project.agentic || {}
  const isSpicy = readNsfwMode()

  // Avatar model capabilities — purely informational, never blocks existing flows
  const { capabilities: avatarCaps } = useAvatarCapabilities(backendUrl, apiKey)

  // --- Persona identity state ---
  const [name, setName] = useState(pa.label || project.name || '')
  const [role, setRole] = useState(pa.role || project.description || '')
  const [systemPrompt, setSystemPrompt] = useState(pa.system_prompt || project.instructions || '')
  const [tone, setTone] = useState(pa.response_style?.tone || 'warm')
  const [stylePreset, setStylePreset] = useState(pap.style_preset || 'Executive')

  // --- Agentic state ---
  const [goal, setGoal] = useState(ag.goal || '')
  const [capabilities, setCapabilities] = useState<string[]>(ag.capabilities || [])
  const [profile, setProfile] = useState<'fast' | 'balanced' | 'quality'>(ag.execution_profile || 'balanced')
  const [askFirst, setAskFirst] = useState(ag.ask_before_acting !== false)
  const [toolIds, setToolIds] = useState<string[]>(ag.tool_ids || [])
  const [agentIds, setAgentIds] = useState<string[]>(ag.a2a_agent_ids || [])
  const [toolSource, setToolSource] = useState(ag.tool_source || 'all')

  // --- Catalog data ---
  const [catalogTools, setCatalogTools] = useState<CatalogItem[]>([])
  const [catalogAgents, setCatalogAgents] = useState<CatalogItem[]>([])
  const [catalogServers, setCatalogServers] = useState<CatalogServer[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)

  // Avatar state (sets is stateful so individual image deletions trigger re-render)
  // For imported personas: sets may be empty but selected_filename exists on disk.
  // Synthesize a fallback set so the portrait renders immediately.
  const initialSets = (() => {
    const raw = Array.isArray(pap.sets) ? pap.sets : []
    if (raw.length > 0) return raw

    const thumb = pap.selected_thumb_filename as string | undefined
    const full = pap.selected_filename as string | undefined
    const url = fileUrl(backendUrl, thumb || full)
    if (!url) return []

    return [
      {
        set_id: 'set_imported_001',
        images: [{ id: 'pimg_imported_001', url, set_id: 'set_imported_001' }],
      },
    ]
  })()

  const [sets, setSets] = useState<Array<{ set_id: string; images: Array<{ id: string; url: string; set_id: string }> }>>(initialSets)
  const allImages = sets.flatMap((s) => (s.images || []).map((img) => ({ ...img, set_id: s.set_id })))
  const [selectedImage, setSelectedImage] = useState<{ set_id: string; image_id: string } | null>(
    pap.selected
      || (initialSets.length > 0
        ? { set_id: initialSets[0].set_id, image_id: initialSets[0].images[0].id }
        : null),
  )

  // Outfit / wardrobe state
  const [outfits, setOutfits] = useState<PersonaOutfit[]>(pap.outfits || [])
  const [generatingOutfit, setGeneratingOutfit] = useState(false)
  const [outfitGenError, setOutfitGenError] = useState<string | null>(null)
  const [selectedOutfitPreset, setSelectedOutfitPreset] = useState<string>('')
  const [customOutfitPrompt, setCustomOutfitPrompt] = useState('')
  const [customOutfitLabel, setCustomOutfitLabel] = useState('')

  // Generation mode: 'standard' (default text-to-image) or 'identity' (face-preserving)
  const [generationMode, setGenerationModeRaw] = useState<GenerationMode>(
    (pap.avatar_settings?.generation_mode as GenerationMode) || 'standard'
  )
  const setGenerationMode = (mode: GenerationMode) => {
    setGenerationModeRaw(mode)
    // Persist into avatar_settings so it survives save
    if (avatarSettingsLocal) {
      setAvatarSettingsLocal({ ...avatarSettingsLocal, generation_mode: mode })
    }
    markDirty()
  }

  // Avatar settings (stored for reproducibility)
  const avatarSettings = pap.avatar_settings || null

  // Documents
  const [documents, setDocuments] = useState<Array<{ name: string; size?: string; chunks?: number }>>(
    project.files || [],
  )

  // UI state
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [lightbox, setLightbox] = useState<string | null>(null)
  const [showGallery, setShowGallery] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [showAgents, setShowAgents] = useState(false)
  const [showWardrobe, setShowWardrobe] = useState(false)
  const [showAvatarSettings, setShowAvatarSettings] = useState(false)
  const [showChangePhoto, setShowChangePhoto] = useState(false)
  const [uploadingPhoto, setUploadingPhoto] = useState(false)
  const [generatingPhoto, setGeneratingPhoto] = useState(false)
  const [changePhotoError, setChangePhotoError] = useState<string | null>(null)
  const [avatarSettingsLocal, setAvatarSettingsLocal] = useState<AvatarGenerationSettings | null>(
    avatarSettings ?? null,
  )
  const [showEnableOutfits, setShowEnableOutfits] = useState(false)
  const [enableOutfitCharDesc, setEnableOutfitCharDesc] = useState('')

  // Class info
  const personaClass = pa.persona_class || pa.category || 'custom'
  const blueprint = PERSONA_BLUEPRINTS.find((bp) => bp.id === personaClass)

  // Total image count across base portraits + all outfits (for LV badge)
  const totalImageCount = allImages.length + outfits.reduce((n, o) => n + o.images.length, 0)

  // Find selected image URL — must search base portraits AND outfit images.
  // Resolve relative backend paths (e.g. /comfy/view/...) to full URLs.
  const selectedUrl = (() => {
    let raw: string | null = null
    if (selectedImage) {
      // Check base portraits
      for (const img of allImages) {
        if (img.id === selectedImage.image_id && img.set_id === selectedImage.set_id) { raw = img.url; break }
      }
      // Check outfit images
      if (!raw) {
        for (const outfit of outfits) {
          for (const img of outfit.images) {
            if (img.id === selectedImage.image_id && img.set_id === selectedImage.set_id) { raw = img.url; break }
          }
          if (raw) break
        }
      }
    }
    if (raw) return resolveImgUrl(raw, backendUrl)
    // Fallback: first image in gallery, or resolve from imported filename fields
    const fallback = allImages[0]?.url
    if (fallback) return resolveImgUrl(fallback, backendUrl)
    return fileUrl(backendUrl, pap.selected_thumb_filename as string | undefined)
      || fileUrl(backendUrl, pap.selected_filename as string | undefined)
  })()

  // --- RPG stat bars derived from persona config ---
  const toneValues: Record<string, number> = {
    warm: 70,
    professional: 85,
    playful: 50,
    assertive: 90,
    flirty: 40,
  }
  const styleValues: Record<string, number> = {
    Executive: 90,
    Elegant: 80,
    Romantic: 60,
    Casual: 40,
    Seductive: 55,
    Lingerie: 35,
    'Pin-Up': 50,
    Fantasy: 45,
  }

  // Track dirtiness
  const markDirty = () => {
    if (!dirty) setDirty(true)
  }

  // --- Fetch catalog ---
  useEffect(() => {
    const headers: Record<string, string> = {}
    if (apiKey) headers['x-api-key'] = apiKey

    fetch(`${backendUrl}/v1/agentic/catalog`, { headers })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) {
          setCatalogServers(
            Array.isArray(data.servers)
              ? data.servers.map((s: any) => ({
                  id: String(s.id || s.name),
                  name: String(s.name || s.id),
                  description: s.description,
                  enabled: s.enabled !== false,
                  tool_ids: Array.isArray(s.tool_ids)
                    ? s.tool_ids
                    : Array.isArray(s.associated_tools)
                      ? s.associated_tools
                      : [],
                }))
              : [],
          )
          setCatalogTools(
            Array.isArray(data.tools)
              ? data.tools.map((t: any) => ({
                  id: t.id || t.name,
                  name: t.name,
                  description: t.description,
                  enabled: t.enabled !== false,
                }))
              : [],
          )
          setCatalogAgents(
            Array.isArray(data.a2a_agents)
              ? data.a2a_agents.map((a: any) => ({
                  id: a.id || a.name,
                  name: a.name,
                  description: a.description,
                  enabled: a.enabled !== false,
                }))
              : [],
          )
        }
      })
      .catch(() => {})
      .finally(() => setCatalogLoading(false))
  }, [backendUrl, apiKey])

  // --- Derived: effective tool counts ---
  const enabledCatalogTools = catalogTools.filter((t) => t.enabled !== false)

  const serverToolCount = (() => {
    if (!toolSource.startsWith('server:')) return 0
    const sid = toolSource.replace('server:', '')
    const s = catalogServers.find((x) => x.id === sid)
    return s?.tool_ids?.length || 0
  })()

  const effectiveToolCount = (() => {
    if (toolSource === 'none') return 0
    if (toolSource === 'all') return enabledCatalogTools.length
    if (toolSource.startsWith('server:')) return serverToolCount
    return 0
  })()

  const visibleTools = (() => {
    if (toolSource === 'none') return []
    if (toolSource === 'all') return enabledCatalogTools
    if (toolSource.startsWith('server:')) {
      const sid = toolSource.replace('server:', '')
      const s = catalogServers.find((x) => x.id === sid)
      if (!s?.tool_ids?.length) return []
      const ids = new Set(s.tool_ids)
      return enabledCatalogTools.filter((t) => ids.has(t.id))
    }
    return []
  })()

  // --- Toggle helpers ---
  const toggleCap = (id: string) => {
    setCapabilities((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]))
    markDirty()
  }
  const toggleTool = (id: string) => {
    setToolIds((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]))
    markDirty()
  }
  const toggleAgent = (id: string) => {
    setAgentIds((prev) => (prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]))
    markDirty()
  }

  // --- Upload a new photo ---
  const handleUploadPhoto = useCallback(async (file: File) => {
    setUploadingPhoto(true)
    setChangePhotoError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey

      const uploadRes = await fetch(`${backendUrl}/upload`, {
        method: 'POST',
        headers,
        body: formData,
      })
      if (!uploadRes.ok) throw new Error(`Upload failed: ${uploadRes.status}`)
      const { url } = await uploadRes.json()

      // Extract the bare filename from the upload URL (e.g. "abc123.png")
      // The upload endpoint returns /files/<uuid>.<ext>
      const uploadedFilename = url.split('/files/').pop()?.split('?')[0]

      // Commit the uploaded file as the project's durable avatar
      const commitResult = await commitPersonaAvatar({
        backendUrl,
        apiKey,
        projectId: project.id,
        sourceFilename: uploadedFilename,
      })

      // Use the committed file URL for display
      const committedProject = commitResult.project || {}
      const committedPap = committedProject.persona_appearance || {}
      const committedRel = committedPap.selected_thumb_filename || committedPap.selected_filename
      const _tok = localStorage.getItem('homepilot_auth_token') || ''
      const displayUrl = committedRel
        ? `${backendUrl}/files/${String(committedRel).replace(/^\/+/, '')}?v=${Date.now()}${_tok ? `&token=${encodeURIComponent(_tok)}` : ''}`
        : url

      // Add to gallery sets and select
      const imgId = nextImageId()
      const setId = `set_upload_${Date.now()}`
      const newImage: PersonaImageRef = {
        id: imgId,
        url: displayUrl,
        created_at: new Date().toISOString(),
        set_id: setId,
      }
      setSets((prev) => [...prev, { set_id: setId, images: [newImage] }])
      setSelectedImage({ set_id: setId, image_id: imgId })
      setShowChangePhoto(false)
      markDirty()
    } catch (err: any) {
      setChangePhotoError(err?.message || 'Upload failed')
    } finally {
      setUploadingPhoto(false)
    }
  }, [backendUrl, apiKey, project.id])

  // --- Generate a new portrait photo ---
  const handleGenerateNewPhoto = useCallback(async () => {
    const charPrompt = avatarSettingsLocal?.character_prompt || `${name}, portrait`
    setGeneratingPhoto(true)
    setChangePhotoError(null)
    try {
      const out = await generatePersonaImages({
        backendUrl,
        apiKey,
        prompt: charPrompt,
        imgModel: avatarSettingsLocal?.img_model,
        imgBatchSize: 4,
        imgAspectRatio: avatarSettingsLocal?.aspect_ratio ?? '2:3',
        imgPreset: avatarSettingsLocal?.img_preset ?? 'med',
        promptRefinement: true,
        nsfwMode: avatarSettingsLocal?.nsfw_mode ?? false,
        generationMode,
        referenceImageUrl: generationMode === 'identity' ? selectedUrl ?? undefined : undefined,
      })

      if (out.urls.length === 0) {
        setChangePhotoError('No images returned. Check your image backend (ComfyUI).')
        return
      }

      // Commit the first generated image as the durable avatar
      // (ComfyUI URL — commit endpoint downloads and stores it)
      let displayUrl = out.urls[0]
      try {
        const commitResult = await commitPersonaAvatar({
          backendUrl,
          apiKey,
          projectId: project.id,
          sourceUrl: out.urls[0],
        })
        const committedPap = commitResult.project?.persona_appearance || {}
        const committedRel = committedPap.selected_thumb_filename || committedPap.selected_filename
        if (committedRel) {
          const _tok2 = localStorage.getItem('homepilot_auth_token') || ''
          displayUrl = `${backendUrl}/files/${String(committedRel).replace(/^\/+/, '')}?v=${Date.now()}${_tok2 ? `&token=${encodeURIComponent(_tok2)}` : ''}`
        }
      } catch {
        // Non-fatal — avatar still works from ComfyUI URL, just not committed
      }

      const setId = `set_gen_${Date.now()}`
      const newImages: PersonaImageRef[] = out.urls.map((url, i) => ({
        id: nextImageId(),
        url: i === 0 ? displayUrl : url,
        created_at: new Date().toISOString(),
        set_id: setId,
        seed: out.seeds?.[i],
      }))
      setSets((prev) => [...prev, { set_id: setId, images: newImages }])
      setSelectedImage({ set_id: setId, image_id: newImages[0].id })

      // Update avatar_settings with the generation params
      const newSettings: AvatarGenerationSettings = {
        character_prompt: charPrompt,
        outfit_prompt: avatarSettingsLocal?.outfit_prompt || 'default outfit',
        full_prompt: out.final_prompt ?? charPrompt,
        style_preset: stylePreset,
        gender: (pap.gender as 'female' | 'male' | 'neutral') ?? 'female',
        img_model: out.model ?? avatarSettingsLocal?.img_model ?? 'dreamshaper_8.safetensors',
        img_preset: avatarSettingsLocal?.img_preset ?? 'med',
        aspect_ratio: avatarSettingsLocal?.aspect_ratio ?? '2:3',
        nsfw_mode: avatarSettingsLocal?.nsfw_mode ?? false,
        generation_mode: generationMode,
      }
      setAvatarSettingsLocal(newSettings)
      setShowChangePhoto(false)
      markDirty()
    } catch (err: any) {
      setChangePhotoError(err?.message || 'Generation failed')
    } finally {
      setGeneratingPhoto(false)
    }
  }, [avatarSettingsLocal, backendUrl, apiKey, name, stylePreset, pap.gender, generationMode, selectedUrl])

  // --- Enable outfit variations for imported personas ---
  const handleEnableOutfitVariations = useCallback((charDescription: string) => {
    if (!charDescription.trim()) return
    const style = stylePreset || 'elegant'
    const newSettings: AvatarGenerationSettings = {
      character_prompt: charDescription.trim(),
      outfit_prompt: `${style} outfit variation`,
      full_prompt: `${charDescription.trim()}, ${style} outfit, elegant lighting, realistic, sharp focus`,
      style_preset: style,
      gender: (pap.gender as 'female' | 'male' | 'neutral') ?? 'female',
      img_model: pap.img_model ?? 'dreamshaper_8.safetensors',
      img_preset: pap.img_preset ?? 'med',
      aspect_ratio: pap.aspect_ratio ?? '2:3',
      nsfw_mode: !!pap.nsfwMode,
    }
    setAvatarSettingsLocal(newSettings)
    setShowEnableOutfits(false)
    markDirty()
  }, [stylePreset, pap])

  // --- Generate outfit variation ---
  // Uses avatarSettingsLocal which includes both original DB settings
  // and user-enabled settings (for imported personas that set it inline).
  const effectiveAvatarSettings = avatarSettingsLocal ?? avatarSettings ?? null
  const handleGenerateOutfit = useCallback(async () => {
    if (!effectiveAvatarSettings?.character_prompt) {
      setOutfitGenError('No character description set. Enable outfit variations first.')
      return
    }

    const outfitPrompt = customOutfitPrompt.trim()
      || OUTFIT_PRESETS.find((p) => p.id === selectedOutfitPreset)?.prompt
      || ''

    if (!outfitPrompt) {
      setOutfitGenError('Select an outfit preset or enter a custom outfit description.')
      return
    }

    const label = customOutfitLabel.trim()
      || OUTFIT_PRESETS.find((p) => p.id === selectedOutfitPreset)?.label
      || 'Custom Outfit'

    setGeneratingOutfit(true)
    setOutfitGenError(null)

    try {
      const out = await generateOutfitImages({
        backendUrl,
        apiKey,
        characterPrompt: effectiveAvatarSettings.character_prompt,
        outfitPrompt,
        imgModel: effectiveAvatarSettings.img_model,
        imgPreset: effectiveAvatarSettings.img_preset,
        imgAspectRatio: effectiveAvatarSettings.aspect_ratio,
        nsfwMode: effectiveAvatarSettings.nsfw_mode,
        generationMode,
        referenceImageUrl: generationMode === 'identity' ? selectedUrl ?? undefined : undefined,
      })

      if (out.urls.length === 0) {
        setOutfitGenError('No images returned. Check your image backend.')
        return
      }

      const created_at = new Date().toISOString()
      const images: PersonaImageRef[] = out.urls.map((url, i) => ({
        id: nextImageId(),
        url,
        created_at,
        set_id: `outfit_${Date.now()}`,
        seed: out.seeds?.[i],
      }))

      const newOutfit: PersonaOutfit = {
        id: `outfit_${Date.now()}`,
        label,
        outfit_prompt: outfitPrompt,
        images,
        selected_image_id: images[0]?.id,
        generation_settings: {
          ...effectiveAvatarSettings,
          outfit_prompt: outfitPrompt,
          full_prompt: out.final_prompt ?? `${effectiveAvatarSettings.character_prompt}, ${outfitPrompt}`,
        },
        created_at,
      }

      setOutfits((prev) => [...prev, newOutfit])
      setCustomOutfitPrompt('')
      setCustomOutfitLabel('')
      setSelectedOutfitPreset('')
      markDirty()
    } catch (err: any) {
      setOutfitGenError(err?.message || 'Outfit generation failed.')
    } finally {
      setGeneratingOutfit(false)
    }
  }, [effectiveAvatarSettings, customOutfitPrompt, customOutfitLabel, selectedOutfitPreset, backendUrl, apiKey, generationMode, selectedUrl])

  // --- Delete outfit ---
  const handleDeleteOutfit = (outfitId: string) => {
    setOutfits((prev) => prev.filter((o) => o.id !== outfitId))
    markDirty()
  }

  // --- Use outfit image as main avatar ---
  const handleUseOutfitAsAvatar = (outfitImage: { id: string; set_id: string }) => {
    setSelectedImage({ set_id: outfitImage.set_id, image_id: outfitImage.id })
    markDirty()
  }

  // --- Save ---
  const handleSave = useCallback(async () => {
    setSaving(true)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (apiKey) headers['x-api-key'] = apiKey

      const prevToolDetails: Record<string, { name: string; description?: string }> = {}
      for (const d of ag.tool_details || []) {
        if (d && typeof d === 'object' && d.id) prevToolDetails[d.id] = d
      }
      const prevAgentDetails: Record<string, { name: string; description?: string }> = {}
      for (const d of ag.agent_details || []) {
        if (d && typeof d === 'object' && d.id) prevAgentDetails[d.id] = d
      }

      const toolDetails = toolIds.map((tid) => {
        const t = catalogTools.find((x) => x.id === tid)
        const prev = prevToolDetails[tid]
        return {
          id: tid,
          name: t?.name || prev?.name || tid,
          description: t?.description || prev?.description || '',
        }
      })
      const agentDetailsList = agentIds.map((aid) => {
        const a = catalogAgents.find((x) => x.id === aid)
        const prev = prevAgentDetails[aid]
        return {
          id: aid,
          name: a?.name || prev?.name || aid,
          description: a?.description || prev?.description || '',
        }
      })

      const body = {
        name,
        description: role,
        instructions: systemPrompt,
        project_type: 'persona',
        persona_agent: {
          ...pa,
          label: name,
          role,
          system_prompt: systemPrompt,
          response_style: { ...(pa.response_style || {}), tone },
        },
        persona_appearance: {
          ...pap,
          sets,
          style_preset: stylePreset,
          selected: selectedImage,
          outfits,
          ...(avatarSettingsLocal ? { avatar_settings: avatarSettingsLocal } : {}),
        },
        agentic: {
          goal,
          capabilities,
          tool_ids: toolIds,
          a2a_agent_ids: agentIds,
          tool_details: toolDetails,
          agent_details: agentDetailsList,
          tool_source: toolSource,
          ask_before_acting: askFirst,
          execution_profile: profile,
        },
      }

      const res = await fetch(`${backendUrl}/projects/${project.id}`, {
        method: 'PUT',
        headers,
        body: JSON.stringify(body),
      })

      if (res.ok) {
        const data = await res.json()

        // Auto-commit the currently selected avatar so the durable
        // selected_filename / selected_thumb_filename stay in sync.
        // This ensures the mini thumbnail in the projects list updates.
        let finalProject = data.project
        try {
          const commitRes = await commitPersonaAvatar({
            backendUrl,
            apiKey,
            projectId: project.id,
            auto: true,
          })
          if (commitRes.project) {
            finalProject = commitRes.project
          }
        } catch {
          // Non-fatal — avatar may already be committed or ComfyUI offline
        }

        setDirty(false)
        onSaved(finalProject)
      } else {
        alert('Failed to save persona settings')
      }
    } catch {
      alert('Failed to save persona settings')
    } finally {
      setSaving(false)
    }
  }, [
    name, role, systemPrompt, tone, stylePreset, selectedImage, sets, outfits,
    goal, capabilities, profile, askFirst, toolIds, agentIds, toolSource,
    pa, pap, ag.tool_details, ag.agent_details, backendUrl, apiKey,
    project.id, onSaved, catalogTools, catalogAgents, avatarSettingsLocal,
  ])

  // --- Document delete ---
  const handleDeleteDoc = async (docName: string) => {
    if (!confirm(`Delete document "${docName}"?`)) return
    try {
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey
      const res = await fetch(
        `${backendUrl}/projects/${project.id}/documents/${encodeURIComponent(docName)}`,
        { method: 'DELETE', headers },
      )
      if (res.ok) setDocuments((prev) => prev.filter((d) => d.name !== docName))
    } catch {
      /* silent */
    }
  }

  // --- Available outfit presets based on NSFW mode ---
  const availableOutfitPresets = OUTFIT_PRESETS.filter(
    (p) => p.category === 'sfw' || isSpicy,
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-3xl bg-[#0f0f1e] rounded-2xl border border-white/10 shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* -- Header -- */}
        <div className="relative px-6 py-4 border-b border-white/10 bg-gradient-to-r from-pink-500/10 via-purple-500/10 to-transparent">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-pink-500/30 to-purple-500/30 border border-pink-500/30 flex items-center justify-center">
                <User size={18} className="text-pink-400" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                  Persona Profile
                  {blueprint && blueprint.id !== 'custom' && (
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-white/10 border border-white/10 text-white/60">
                      {blueprint.icon} {blueprint.label}
                    </span>
                  )}
                </h2>
                <p className="text-[11px] text-white/40 uppercase tracking-widest">Character Sheet</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* -- Content -- */}
        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {/* -- Top: Avatar + Stats -- */}
          <div className="p-6 border-b border-white/5">
            <div className="flex gap-6">
              {/* Avatar frame */}
              <div className="shrink-0">
                <div className="relative group">
                  {selectedUrl ? (
                    <img
                      src={selectedUrl}
                      alt={name}
                      onClick={() => setLightbox(selectedUrl)}
                      className="w-40 h-52 object-cover object-top rounded-xl border-2 border-pink-500/30 shadow-lg shadow-pink-500/10 cursor-zoom-in"
                    />
                  ) : (
                    <div
                      className="w-40 h-52 bg-white/5 border-2 border-dashed border-white/20 rounded-xl flex items-center justify-center cursor-pointer hover:border-pink-500/40 transition-colors"
                      onClick={() => setShowChangePhoto(true)}
                    >
                      <div className="text-center">
                        <Camera size={32} className="text-white/20 mx-auto mb-1" />
                        <span className="text-[10px] text-white/30">Add photo</span>
                      </div>
                    </div>
                  )}
                  {/* Change Photo button (hover) */}
                  <button
                    type="button"
                    onClick={() => setShowChangePhoto(!showChangePhoto)}
                    className="absolute top-2 right-2 p-1.5 bg-black/60 hover:bg-black/80 rounded-lg border border-white/20 transition-all opacity-0 group-hover:opacity-100"
                    title="Change photo"
                  >
                    <RefreshCw size={12} className="text-white" />
                  </button>
                  {allImages.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setShowGallery(!showGallery)}
                      className="absolute bottom-2 right-2 p-1.5 bg-black/60 hover:bg-black/80 rounded-lg border border-white/20 transition-all opacity-0 group-hover:opacity-100"
                    >
                      <Camera size={14} className="text-white" />
                    </button>
                  )}
                  <div className="absolute -top-2 -left-2 bg-gradient-to-br from-pink-500 to-purple-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full shadow-lg">
                    LV {totalImageCount}
                  </div>
                </div>

                {/* Change Photo panel */}
                {showChangePhoto && (
                  <div className="mt-2 w-40 space-y-2">
                    {/* Upload option */}
                    <label className="flex items-center gap-2 px-3 py-2 bg-white/[0.06] hover:bg-white/10 border border-white/10 rounded-lg cursor-pointer transition-colors">
                      <Upload size={14} className="text-pink-400 shrink-0" />
                      <span className="text-[11px] text-white/70">
                        {uploadingPhoto ? 'Uploading...' : 'Upload image'}
                      </span>
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        className="hidden"
                        disabled={uploadingPhoto}
                        onChange={(e) => {
                          const f = e.target.files?.[0]
                          if (f) handleUploadPhoto(f)
                          e.target.value = ''
                        }}
                      />
                    </label>

                    {/* Generate option */}
                    <button
                      type="button"
                      disabled={generatingPhoto}
                      onClick={handleGenerateNewPhoto}
                      className="w-full flex items-center gap-2 px-3 py-2 bg-white/[0.06] hover:bg-white/10 border border-white/10 rounded-lg transition-colors"
                    >
                      <Sparkles size={14} className="text-purple-400 shrink-0" />
                      <span className="text-[11px] text-white/70">
                        {generatingPhoto ? 'Generating...' : 'Generate new (4)'}
                      </span>
                      {generatingPhoto && <Loader2 size={12} className="animate-spin text-white/40 ml-auto" />}
                    </button>

                    {/* Generation mode toggle — Standard vs Same Person */}
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-1.5 px-2 py-1">
                        <span className="text-[10px] text-white/40 font-medium">Generation mode</span>
                      </div>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          onClick={() => setGenerationMode('standard')}
                          className={`flex-1 px-2 py-1.5 rounded-lg border text-[10px] font-medium transition-all ${
                            generationMode === 'standard'
                              ? 'bg-purple-500/15 border-purple-500/30 text-purple-300'
                              : 'bg-white/[0.03] border-white/10 text-white/40 hover:bg-white/[0.06]'
                          }`}
                        >
                          Standard
                        </button>
                        <button
                          type="button"
                          onClick={() => avatarCaps.canIdentityPortrait && setGenerationMode('identity')}
                          disabled={!avatarCaps.canIdentityPortrait}
                          title={avatarCaps.canIdentityPortrait
                            ? 'Keeps the same face consistent across generations'
                            : 'Install Avatar Models (Add-ons) to enable'}
                          className={`flex-1 px-2 py-1.5 rounded-lg border text-[10px] font-medium transition-all ${
                            generationMode === 'identity'
                              ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                              : avatarCaps.canIdentityPortrait
                                ? 'bg-white/[0.03] border-white/10 text-white/40 hover:bg-white/[0.06]'
                                : 'bg-white/[0.02] border-white/5 text-white/15 cursor-not-allowed'
                          }`}
                        >
                          Same Person
                        </button>
                      </div>
                      {generationMode === 'identity' && (
                        <div className="flex items-center gap-1 px-1.5">
                          <Check size={8} className="text-emerald-400 shrink-0" />
                          <span className="text-[9px] text-emerald-300/60">Face preservation active</span>
                        </div>
                      )}
                      {!avatarCaps.canIdentityPortrait && generationMode === 'standard' && (
                        <div className="flex items-center gap-1 px-1.5">
                          <Sparkles size={8} className="text-white/15 shrink-0" />
                          <span className="text-[9px] text-white/20">Install Avatar Models for same-person mode</span>
                        </div>
                      )}
                    </div>

                    {changePhotoError && (
                      <div className="text-[10px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-2 py-1.5">
                        {changePhotoError}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Stats panel */}
              <div className="flex-1 min-w-0 space-y-4">
                <div>
                  <input
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value)
                      markDirty()
                    }}
                    className="bg-transparent text-xl font-bold text-white focus:outline-none focus:border-b focus:border-pink-500 w-full border-b border-transparent hover:border-white/20 transition-all pb-1"
                    placeholder="Persona Name"
                  />
                  <input
                    value={role}
                    onChange={(e) => {
                      setRole(e.target.value)
                      markDirty()
                    }}
                    className="bg-transparent text-sm text-pink-300/80 focus:outline-none w-full mt-1 border-b border-transparent hover:border-white/10 transition-all pb-1"
                    placeholder="Role / Title"
                  />
                </div>

                <div className="space-y-2">
                  <StatBar label="Charisma" value={toneValues[tone] ?? 60} color="bg-pink-500" />
                  <StatBar label="Elegance" value={styleValues[stylePreset] ?? 60} color="bg-purple-500" />
                  <StatBar
                    label="Confidence"
                    value={tone === 'assertive' ? 95 : tone === 'professional' ? 80 : 65}
                    color="bg-amber-500"
                  />
                  <StatBar
                    label="Warmth"
                    value={tone === 'warm' ? 90 : tone === 'flirty' ? 75 : tone === 'playful' ? 85 : 50}
                    color="bg-rose-400"
                  />
                </div>

                <div className="flex flex-wrap gap-1.5">
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-pink-500/15 border border-pink-500/20 text-pink-300">
                    {stylePreset}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/20 text-purple-300 capitalize">
                    {tone}
                  </span>
                  {pap.nsfwMode && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-orange-500/15 border border-orange-500/20 text-orange-300">
                      Spicy
                    </span>
                  )}
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/10 border border-white/10 text-white/50">
                    {allImages.length} portrait{allImages.length !== 1 ? 's' : ''}
                  </span>
                  {outfits.length > 0 && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/20 text-amber-300">
                      {outfits.length} outfit{outfits.length !== 1 ? 's' : ''}
                    </span>
                  )}
                  {capabilities.length > 0 && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-cyan-500/15 border border-cyan-500/20 text-cyan-300">
                      {capabilities.length} skill{capabilities.length !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* -- Portrait Gallery (expandable) — base portraits only -- */}
          {showGallery && allImages.length > 0 && (
            <div className="p-6 border-b border-white/5 bg-white/[0.02]">
              <SectionHeader icon={Camera} title="Portrait Gallery" badge={allImages.length} color="text-pink-400" />
              <div className="grid grid-cols-4 gap-2">
                {allImages.map((img: any) => {
                  const isSel = selectedImage?.set_id === img.set_id && selectedImage?.image_id === img.id
                  return (
                    <div key={img.id} className="relative group/thumb">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedImage({ set_id: img.set_id, image_id: img.id })
                          markDirty()
                        }}
                        className={`relative w-full overflow-hidden rounded-lg border-2 transition-all ${
                          isSel
                            ? 'border-pink-500 ring-2 ring-pink-500/30 scale-[1.02]'
                            : 'border-white/10 hover:border-white/30 hover:scale-[1.01]'
                        }`}
                      >
                        <img src={resolveImgUrl(img.url, backendUrl)} className="w-full h-28 object-cover object-top" alt="" loading="lazy" />
                        {isSel && (
                          <div className="absolute bottom-1 left-1 text-[8px] bg-pink-500 px-1.5 py-0.5 rounded-full font-bold shadow">
                            Active
                          </div>
                        )}
                      </button>
                      {/* Delete — small bin icon, top-right, appears on hover */}
                      {!isSel && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSets((prev) =>
                              prev.map((s) => ({
                                ...s,
                                images: s.images.filter((i) => i.id !== img.id),
                              })).filter((s) => s.images.length > 0),
                            )
                            markDirty()
                          }}
                          className="absolute top-1 right-1 p-1 bg-black/70 hover:bg-red-600/90 rounded-md border border-white/10 transition-all opacity-0 group-hover/thumb:opacity-100"
                          title="Delete this portrait"
                        >
                          <Trash2 size={10} className="text-white/70 hover:text-white" />
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* -- Detail sections -- */}
          <div className="p-6 space-y-8">
            {/* --- Quest Objective --- */}
            <section>
              <SectionHeader icon={Star} title="Quest Objective" color="text-amber-400" />
              <textarea
                value={goal}
                onChange={(e) => {
                  setGoal(e.target.value)
                  markDirty()
                }}
                placeholder="e.g. Help me plan my week, be my creative writing partner, roleplay as a mentor..."
                rows={2}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/30 transition-all resize-none"
              />
              <p className="text-[10px] text-white/30 mt-1.5 px-1">
                Define what this persona should help you accomplish.
              </p>
            </section>

            {/* --- Style & Tone --- */}
            <section>
              <SectionHeader icon={Palette} title="Style & Tone" color="text-pink-400" />
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-white/60 mb-2">Style</label>
                  <div className="flex flex-wrap gap-2">
                    {[...['Executive', 'Elegant', 'Romantic', 'Casual'], ...(isSpicy ? ['Seductive', 'Lingerie', 'Pin-Up', 'Fantasy'] : [])].map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => {
                          setStylePreset(s)
                          markDirty()
                        }}
                        className={`px-3 py-1.5 rounded-full border text-xs transition-all ${
                          stylePreset === s
                            ? 'bg-pink-500/20 border-pink-500/40 text-pink-300'
                            : 'bg-white/5 border-white/10 text-white/50 hover:bg-white/10'
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-white/60 mb-2">Tone</label>
                  <div className="flex flex-wrap gap-2">
                    {(['warm', 'professional', 'playful', 'assertive', ...(isSpicy ? ['flirty'] : [])] as const).map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => {
                          setTone(t)
                          markDirty()
                        }}
                        className={`px-3 py-1.5 rounded-full border text-xs capitalize transition-all ${
                          tone === t
                            ? 'bg-purple-500/20 border-purple-500/40 text-purple-300'
                            : 'bg-white/5 border-white/10 text-white/50 hover:bg-white/10'
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            {/* --- Backstory & Personality --- */}
            <section>
              <SectionHeader icon={Heart} title="Backstory & Personality" color="text-rose-400" />
              <textarea
                value={systemPrompt}
                onChange={(e) => {
                  setSystemPrompt(e.target.value)
                  markDirty()
                }}
                placeholder="Define this persona's personality, background, and how they should respond..."
                rows={4}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-white placeholder-white/30 focus:outline-none focus:border-pink-500/50 focus:ring-1 focus:ring-pink-500/30 transition-all resize-none"
              />
            </section>

            {/* --- Wardrobe (Outfit Variations) --- */}
            <section>
              <SectionHeader
                icon={Shirt}
                title="Wardrobe (Outfits)"
                badge={outfits.length}
                color="text-amber-400"
              />

              {/* Existing outfits */}
              {outfits.length > 0 && (
                <div className="space-y-3 mb-4">
                  {outfits.map((outfit) => (
                    <div
                      key={outfit.id}
                      className="bg-white/[0.03] border border-white/10 rounded-xl p-3 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-white">{outfit.label}</span>
                        <button
                          type="button"
                          onClick={() => handleDeleteOutfit(outfit.id)}
                          className="p-1 text-white/30 hover:text-red-400 rounded hover:bg-red-500/10 transition-all"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                      <div className="grid grid-cols-4 gap-1.5">
                        {outfit.images.map((img) => {
                          const isActive =
                            selectedImage?.set_id === img.set_id && selectedImage?.image_id === img.id
                          return (
                            <div key={img.id} className="relative group/oimg">
                              <button
                                type="button"
                                onClick={() => handleUseOutfitAsAvatar(img)}
                                className={`relative w-full overflow-hidden rounded-lg border transition-all ${
                                  isActive
                                    ? 'border-amber-500 ring-1 ring-amber-500/30'
                                    : 'border-white/10 hover:border-white/25'
                                }`}
                              >
                                <img src={resolveImgUrl(img.url, backendUrl)} className="w-full h-20 object-cover object-top" alt="" loading="lazy" />
                                {isActive && (
                                  <div className="absolute bottom-0.5 left-0.5 text-[8px] bg-amber-500 px-1 py-0.5 rounded-full font-bold">
                                    Active
                                  </div>
                                )}
                              </button>
                              {/* Delete single image — bin icon, top-right */}
                              {!isActive && (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    setOutfits((prev) =>
                                      prev.map((o) =>
                                        o.id === outfit.id
                                          ? { ...o, images: o.images.filter((i) => i.id !== img.id) }
                                          : o,
                                      ).filter((o) => o.images.length > 0),
                                    )
                                    markDirty()
                                  }}
                                  className="absolute top-0.5 right-0.5 p-0.5 bg-black/70 hover:bg-red-600/90 rounded border border-white/10 transition-all opacity-0 group-hover/oimg:opacity-100"
                                  title="Delete this image"
                                >
                                  <Trash2 size={9} className="text-white/70 hover:text-white" />
                                </button>
                              )}
                            </div>
                          )
                        })}
                      </div>
                      <div className="text-[10px] text-white/30">{outfit.outfit_prompt}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Outfit generation mode selector */}
              <div className="mb-3 space-y-2">
                <div className="flex items-center gap-2 px-1">
                  <span className="text-[10px] text-white/50 font-medium">Outfit generation</span>
                </div>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => setGenerationMode('standard')}
                    className={`flex-1 px-3 py-2 rounded-lg border text-[11px] font-medium transition-all ${
                      generationMode === 'standard'
                        ? 'bg-amber-500/15 border-amber-500/30 text-amber-300'
                        : 'bg-white/[0.03] border-white/10 text-white/40 hover:bg-white/[0.06]'
                    }`}
                  >
                    <div>Standard</div>
                    <div className="text-[9px] font-normal mt-0.5 opacity-60">Fast, flexible</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => (avatarCaps.canOutfits || avatarCaps.canIdentityPortrait) && setGenerationMode('identity')}
                    disabled={!avatarCaps.canOutfits && !avatarCaps.canIdentityPortrait}
                    title={(avatarCaps.canOutfits || avatarCaps.canIdentityPortrait)
                      ? 'Keeps the same face consistent across outfit variations'
                      : 'Install Avatar Models (Add-ons) to enable'}
                    className={`flex-1 px-3 py-2 rounded-lg border text-[11px] font-medium transition-all ${
                      generationMode === 'identity'
                        ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
                        : (avatarCaps.canOutfits || avatarCaps.canIdentityPortrait)
                          ? 'bg-white/[0.03] border-white/10 text-white/40 hover:bg-white/[0.06]'
                          : 'bg-white/[0.02] border-white/5 text-white/15 cursor-not-allowed'
                    }`}
                  >
                    <div>Same Person</div>
                    <div className="text-[9px] font-normal mt-0.5 opacity-60">Face consistency</div>
                  </button>
                </div>
                {generationMode === 'identity' && avatarCaps.canOutfits && (
                  <div className="flex items-center gap-1.5 px-2 py-1 bg-emerald-500/5 border border-emerald-500/10 rounded-lg">
                    <Check size={9} className="text-emerald-400 shrink-0" />
                    <span className="text-[9px] text-emerald-300/60">Identity models ready — face preservation active for outfits</span>
                  </div>
                )}
                {generationMode === 'identity' && avatarCaps.canIdentityPortrait && !avatarCaps.canOutfits && (
                  <div className="flex items-center gap-1.5 px-2 py-1 bg-amber-500/5 border border-amber-500/10 rounded-lg">
                    <Sparkles size={9} className="text-amber-300/60 shrink-0" />
                    <span className="text-[9px] text-amber-300/50">Basic identity models installed. Add PhotoMaker V2 or PuLID for best outfit results.</span>
                  </div>
                )}
                {!avatarCaps.canOutfits && !avatarCaps.canIdentityPortrait && (
                  <div className="flex items-center gap-1.5 px-2 py-1 bg-white/[0.02] border border-white/5 rounded-lg">
                    <Shirt size={9} className="text-white/15 shrink-0" />
                    <span className="text-[9px] text-white/20">Install Avatar Models (Add-ons) to enable same-person mode</span>
                  </div>
                )}
              </div>

              {/* Generate new outfit */}
              <button
                type="button"
                onClick={() => setShowWardrobe(!showWardrobe)}
                className="flex items-center gap-2 text-xs text-white/50 hover:text-white/80 transition-colors mb-2"
              >
                {showWardrobe ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {showWardrobe ? 'Hide outfit creator' : 'Add new outfit variation'}
              </button>

              {showWardrobe && (
                <div className="space-y-3 bg-white/[0.02] border border-white/10 rounded-xl p-4">
                  {!effectiveAvatarSettings?.character_prompt ? (
                    /* Enable outfit variations — inline form */
                    <div className="space-y-3">
                      <div className="text-xs text-white/50">
                        Describe your character to enable outfit variations.
                        This description stays constant across all outfits.
                      </div>
                      {showEnableOutfits ? (
                        <div className="space-y-2">
                          <textarea
                            value={enableOutfitCharDesc}
                            onChange={(e) => setEnableOutfitCharDesc(e.target.value)}
                            rows={3}
                            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50 resize-none"
                            placeholder="e.g., young woman with long dark hair, green eyes, athletic build, elegant features..."
                          />
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => handleEnableOutfitVariations(enableOutfitCharDesc)}
                              disabled={!enableOutfitCharDesc.trim()}
                              className="flex-1 px-3 py-2 bg-amber-500/80 hover:bg-amber-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg transition-all flex items-center justify-center gap-1.5"
                            >
                              <Check size={12} />
                              Enable Outfits
                            </button>
                            <button
                              type="button"
                              onClick={() => { setShowEnableOutfits(false); setEnableOutfitCharDesc('') }}
                              className="px-3 py-2 bg-white/5 hover:bg-white/10 text-white/50 text-xs rounded-lg transition-colors"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            // Pre-fill with name + role if available
                            const hint = [name, role].filter(Boolean).join(', ')
                            setEnableOutfitCharDesc(hint ? `${hint}, portrait` : '')
                            setShowEnableOutfits(true)
                          }}
                          className="w-full px-4 py-2.5 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/30 text-amber-300 text-xs font-semibold rounded-xl transition-all flex items-center justify-center gap-2"
                        >
                          <Sparkles size={14} />
                          Set up outfit variations
                        </button>
                      )}
                    </div>
                  ) : (
                    <>
                      {/* Character prompt (read-only display) */}
                      <div>
                        <label className="block text-[10px] font-medium text-white/50 mb-1 flex items-center gap-1">
                          <Copy size={10} />
                          Stored character description (constant across outfits)
                        </label>
                        <div className="text-[11px] text-white/40 bg-white/5 border border-white/5 rounded-lg p-2 max-h-16 overflow-y-auto">
                          {effectiveAvatarSettings.character_prompt}
                        </div>
                      </div>

                      {/* Outfit presets */}
                      <div>
                        <label className="block text-xs font-medium text-white/60 mb-2">Outfit preset</label>
                        <div className="flex flex-wrap gap-1.5">
                          {availableOutfitPresets.map((preset) => (
                            <button
                              key={preset.id}
                              type="button"
                              onClick={() => {
                                setSelectedOutfitPreset(preset.id)
                                setCustomOutfitPrompt('')
                                setCustomOutfitLabel(preset.label)
                              }}
                              className={`px-2.5 py-1 rounded-full border text-[11px] transition-all ${
                                selectedOutfitPreset === preset.id
                                  ? 'bg-amber-500/20 border-amber-500/40 text-amber-300'
                                  : 'bg-white/5 border-white/10 text-white/50 hover:bg-white/10'
                              }`}
                            >
                              {preset.label}
                            </button>
                          ))}
                        </div>
                      </div>

                      {/* Custom outfit */}
                      <div>
                        <label className="block text-xs font-medium text-white/60 mb-1">
                          Or custom outfit description
                        </label>
                        <input
                          type="text"
                          value={customOutfitPrompt}
                          onChange={(e) => {
                            setCustomOutfitPrompt(e.target.value)
                            if (e.target.value.trim()) setSelectedOutfitPreset('')
                          }}
                          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50"
                          placeholder="e.g., medieval armor, enchanted forest setting..."
                        />
                      </div>

                      {/* Label */}
                      <div>
                        <label className="block text-xs font-medium text-white/60 mb-1">Outfit label</label>
                        <input
                          type="text"
                          value={customOutfitLabel}
                          onChange={(e) => setCustomOutfitLabel(e.target.value)}
                          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50"
                          placeholder="e.g., Medieval Knight"
                        />
                      </div>

                      <button
                        type="button"
                        onClick={handleGenerateOutfit}
                        disabled={generatingOutfit}
                        className="w-full px-4 py-2.5 bg-amber-500/80 hover:bg-amber-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-xl transition-all flex items-center justify-center gap-2"
                      >
                        {generatingOutfit ? (
                          <>
                            <Loader2 size={14} className="animate-spin" />
                            Generating outfit...
                          </>
                        ) : (
                          <>
                            <Plus size={14} />
                            Generate Outfit Variation (4 images)
                          </>
                        )}
                      </button>

                      {outfitGenError && (
                        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                          {outfitGenError}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </section>

            {/* --- Avatar Generation Settings (expandable) --- */}
            {effectiveAvatarSettings && (
              <section>
                <button
                  type="button"
                  onClick={() => setShowAvatarSettings(!showAvatarSettings)}
                  className="flex items-center gap-2 mb-3"
                >
                  <Settings size={14} className="text-white/40" />
                  <span className="text-xs font-semibold text-white/50 uppercase tracking-wider">
                    Generation Settings
                  </span>
                  {showAvatarSettings ? (
                    <ChevronUp size={12} className="text-white/30" />
                  ) : (
                    <ChevronDown size={12} className="text-white/30" />
                  )}
                </button>
                {showAvatarSettings && (
                  <div className="rounded-xl bg-white/[0.03] border border-white/10 p-4 space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-white/50">Model</span>
                      <span className="text-white/80 font-mono">{effectiveAvatarSettings.img_model}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/50">Quality</span>
                      <span className="text-white/80">{effectiveAvatarSettings.img_preset}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/50">Aspect ratio</span>
                      <span className="text-white/80">{effectiveAvatarSettings.aspect_ratio}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/50">Style</span>
                      <span className="text-white/80">{effectiveAvatarSettings.style_preset}</span>
                    </div>
                    {effectiveAvatarSettings.body_type && (
                      <div className="flex justify-between">
                        <span className="text-white/50">Body type</span>
                        <span className="text-white/80">{effectiveAvatarSettings.body_type}</span>
                      </div>
                    )}
                    <div className="mt-2 pt-2 border-t border-white/5">
                      <span className="text-white/40">Full prompt</span>
                      <div className="text-[10px] text-white/30 mt-1 bg-white/5 rounded-lg p-2 max-h-20 overflow-y-auto font-mono break-all">
                        {effectiveAvatarSettings.full_prompt}
                      </div>
                    </div>
                  </div>
                )}
              </section>
            )}

            {/* --- Execution Profile --- */}
            <section>
              <SectionHeader icon={Zap} title="Execution Stance" color="text-cyan-400" />
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-2">
                  {PROFILE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => {
                        setProfile(opt.value)
                        markDirty()
                      }}
                      className={[
                        'relative px-3 py-3 rounded-xl border text-left transition-all',
                        profile === opt.value
                          ? 'bg-cyan-500/15 border-cyan-500/40 ring-1 ring-cyan-500/20'
                          : 'bg-white/5 border-white/10 hover:bg-white/8 hover:border-white/15',
                      ].join(' ')}
                    >
                      <div className="text-sm font-medium text-white">
                        <span className="mr-1.5">{opt.icon}</span>
                        {opt.label}
                      </div>
                      <div className="text-[11px] text-white/40 mt-0.5 leading-tight">{opt.hint}</div>
                      {profile === opt.value && (
                        <div className="absolute top-2 right-2">
                          <Check size={12} className="text-cyan-400" />
                        </div>
                      )}
                    </button>
                  ))}
                </div>

                <div className="px-1">
                  <Toggle
                    checked={askFirst}
                    onChange={(v) => {
                      setAskFirst(v)
                      markDirty()
                    }}
                    label="Ask before executing actions"
                  />
                  <p className="text-[11px] text-white/35 mt-1 ml-0.5">
                    When enabled, the persona will confirm before running tools or taking actions.
                  </p>
                </div>
              </div>
            </section>

            {/* --- Skills --- */}
            <section>
              <SectionHeader icon={Shield} title="Skills" badge={capabilities.length} color="text-emerald-400" />
              <div className="grid grid-cols-2 gap-2">
                {BUILTIN_CAPABILITIES.map((cap) => {
                  const active = capabilities.includes(cap.id)
                  return (
                    <button
                      key={cap.id}
                      type="button"
                      onClick={() => toggleCap(cap.id)}
                      className={[
                        'flex items-center gap-2.5 px-3 py-2.5 rounded-xl border text-left transition-all',
                        active
                          ? 'bg-emerald-500/15 border-emerald-500/30'
                          : 'bg-white/5 border-white/10 hover:bg-white/8',
                      ].join(' ')}
                    >
                      <div
                        className={[
                          'w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors',
                          active ? 'bg-emerald-500 border-emerald-500' : 'border-white/20',
                        ].join(' ')}
                      >
                        {active && <Check size={10} className="text-white" />}
                      </div>
                      <span className={`text-sm ${active ? 'text-white' : 'text-white/60'}`}>{cap.label}</span>
                    </button>
                  )
                })}
              </div>
            </section>

            {/* --- Equipment (Tools) --- */}
            <section>
              <SectionHeader
                icon={Wrench}
                title="Equipment (Tools)"
                badge={effectiveToolCount}
                color="text-orange-400"
              />
              {catalogLoading ? (
                <div className="flex items-center gap-2 text-xs text-white/40 py-3">
                  <Loader2 size={12} className="animate-spin" /> Loading catalog...
                </div>
              ) : catalogTools.length === 0 ? (
                <div className="text-xs text-white/35 py-3 px-1">
                  No tools registered. Start MCP servers and run the seed script to populate.
                </div>
              ) : (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowTools(!showTools)}
                    className="flex items-center gap-2 text-xs text-white/50 hover:text-white/80 transition-colors mb-2"
                  >
                    {showTools ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    {showTools ? 'Collapse' : `Browse ${effectiveToolCount} in bundle (${toolIds.length} pinned)`}
                  </button>

                  {showTools && (
                    <div className="space-y-1 max-h-48 overflow-y-auto custom-scrollbar">
                      {visibleTools.map((tool) => {
                        const bound = toolIds.includes(tool.id)
                        return (
                          <button
                            key={tool.id}
                            type="button"
                            onClick={() => toggleTool(tool.id)}
                            className={[
                              'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all',
                              bound
                                ? 'bg-orange-500/10 border border-orange-500/20'
                                : 'hover:bg-white/5 border border-transparent',
                            ].join(' ')}
                          >
                            <StatusDot ok={tool.enabled !== false} />
                            <div className="flex-1 min-w-0">
                              <div className="text-xs font-medium text-white truncate">{tool.name}</div>
                              {tool.description && (
                                <div className="text-[10px] text-white/35 truncate">{tool.description}</div>
                              )}
                            </div>
                            <div
                              className={[
                                'w-4 h-4 rounded border flex items-center justify-center shrink-0',
                                bound ? 'bg-orange-500 border-orange-500' : 'border-white/20',
                              ].join(' ')}
                            >
                              {bound && <Check size={10} className="text-white" />}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  )}

                  <div className="flex items-center gap-3 mt-2 pt-2 border-t border-white/5">
                    <label className="text-xs text-white/50">Tool bundle:</label>
                    <select
                      value={toolSource}
                      onChange={(e) => {
                        setToolSource(e.target.value)
                        markDirty()
                      }}
                      className="bg-[#1a1a2e] border border-white/10 rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:border-pink-500/50 [&>option]:bg-[#1a1a2e] [&>option]:text-white"
                    >
                      <option value="all">All enabled tools</option>
                      {catalogServers.map((s) => (
                        <option key={s.id} value={`server:${s.id}`}>
                          Server: {s.name}
                        </option>
                      ))}
                      <option value="none">No tools</option>
                    </select>
                  </div>
                </div>
              )}
            </section>

            {/* --- Party Members (Agents) --- */}
            <section>
              <SectionHeader
                icon={Users}
                title="Party Members (Agents)"
                badge={agentIds.length}
                color="text-violet-400"
              />
              {catalogLoading ? (
                <div className="flex items-center gap-2 text-xs text-white/40 py-3">
                  <Loader2 size={12} className="animate-spin" /> Loading...
                </div>
              ) : catalogAgents.length === 0 ? (
                <div className="text-xs text-white/35 py-3 px-1">No A2A agents registered.</div>
              ) : (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowAgents(!showAgents)}
                    className="flex items-center gap-2 text-xs text-white/50 hover:text-white/80 transition-colors mb-2"
                  >
                    {showAgents ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                    {showAgents
                      ? 'Collapse'
                      : `Browse ${catalogAgents.length} available (${agentIds.length} in party)`}
                  </button>

                  {showAgents && (
                    <div className="space-y-1 max-h-36 overflow-y-auto custom-scrollbar">
                      {catalogAgents.map((agent) => {
                        const bound = agentIds.includes(agent.id)
                        return (
                          <button
                            key={agent.id}
                            type="button"
                            onClick={() => toggleAgent(agent.id)}
                            className={[
                              'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-all',
                              bound
                                ? 'bg-violet-500/10 border border-violet-500/20'
                                : 'hover:bg-white/5 border border-transparent',
                            ].join(' ')}
                          >
                            <StatusDot ok={agent.enabled !== false} />
                            <div className="flex-1 min-w-0">
                              <div className="text-xs font-medium text-white truncate">{agent.name}</div>
                              {agent.description && (
                                <div className="text-[10px] text-white/35 truncate">{agent.description}</div>
                              )}
                            </div>
                            <div
                              className={[
                                'w-4 h-4 rounded border flex items-center justify-center shrink-0',
                                bound ? 'bg-violet-500 border-violet-500' : 'border-white/20',
                              ].join(' ')}
                            >
                              {bound && <Check size={10} className="text-white" />}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* --- Character Summary --- */}
            <section>
              <SectionHeader icon={Server} title="Character Summary" color="text-white/50" />
              <div className="rounded-xl bg-white/[0.03] border border-white/10 p-4 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Class</span>
                  <span className="text-white/80 font-medium">
                    {blueprint ? `${blueprint.icon} ${blueprint.label}` : stylePreset} {role || 'Persona'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Alignment</span>
                  <span className="text-white/80 font-medium capitalize">{tone}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Portraits</span>
                  <span className="text-white/80 font-medium">{allImages.length}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Wardrobe</span>
                  <span className="text-white/80 font-medium">
                    {outfits.length} outfit{outfits.length !== 1 ? 's' : ''} ({outfits.reduce((n, o) => n + o.images.length, 0)} images)
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Generation</span>
                  <span className={`font-medium ${generationMode === 'identity' ? 'text-emerald-300' : 'text-white/80'}`}>
                    {generationMode === 'identity' ? 'Same Person' : 'Standard'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Equipment</span>
                  <span className="text-white/80 font-medium">
                    {toolSource === 'all'
                      ? `All tools (${effectiveToolCount})`
                      : toolSource === 'none'
                        ? 'No tools'
                        : (() => {
                            const sid = toolSource.replace('server:', '')
                            const s = catalogServers.find((x) => x.id === sid)
                            return s ? `${s.name} (${effectiveToolCount})` : toolSource
                          })()}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Party</span>
                  <span className="text-white/80 font-medium">
                    {agentIds.length === 0
                      ? 'Solo'
                      : agentIds
                          .map((id) => catalogAgents.find((a) => a.id === id)?.name || id)
                          .join(', ')}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Stance</span>
                  <span className="text-white/80 font-medium capitalize">
                    {profile} / {askFirst ? 'Cautious' : 'Auto'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-white/50">Skills</span>
                  <span className="text-white/80 font-medium">
                    {capabilities.length > 0 ? capabilities.length : 'None'}
                  </span>
                </div>
                {pap.nsfwMode && (
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-white/50">Mode</span>
                    <span className="text-orange-300 font-medium">Spicy</span>
                  </div>
                )}
                {/* Age in days — computed from project creation timestamp */}
                {(() => {
                  const ts = project.created_at
                  if (!ts || ts <= 0) return null
                  const createdDate = new Date(ts * 1000)
                  const ageDays = Math.max(0, Math.floor((Date.now() - createdDate.getTime()) / 86_400_000))
                  return (
                    <>
                      <div className="border-t border-white/5 my-1" />
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-white/50">Born</span>
                        <span className="text-white/80 font-medium">{createdDate.toLocaleDateString()}</span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-white/50">Age</span>
                        <span className="text-pink-300 font-semibold">
                          {ageDays === 0
                            ? 'Newborn (today)'
                            : ageDays === 1
                              ? '1 day'
                              : `${ageDays} days`}
                        </span>
                      </div>
                    </>
                  )
                })()}
              </div>
            </section>

            {/* --- Knowledge Base --- */}
            <section>
              <SectionHeader
                icon={FileText}
                title="Knowledge Base"
                badge={documents.length}
                color="text-blue-400"
              />
              {documents.length === 0 ? (
                <div className="text-xs text-white/35 py-3 px-1">
                  No documents uploaded. Upload files when using this persona project.
                </div>
              ) : (
                <div className="space-y-1">
                  {documents.map((doc, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/5 border border-white/10 group"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <FileText size={14} className="text-purple-400 shrink-0" />
                        <div className="min-w-0">
                          <div className="text-xs text-white truncate">{doc.name}</div>
                          <div className="text-[10px] text-white/30">
                            {doc.size || ''}
                            {doc.chunks ? ` \u00b7 ${doc.chunks} chunks` : ''}
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => handleDeleteDoc(doc.name)}
                        className="p-1 text-white/30 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all rounded hover:bg-red-500/10"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>

        {/* -- Footer -- */}
        <div className="px-6 py-4 border-t border-white/10 bg-[#0f0f1e] flex items-center justify-between">
          <div className="text-[11px] text-white/30">{dirty ? 'Unsaved changes' : 'All changes saved'}</div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-white/50 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !dirty}
              className={[
                'px-5 py-2 text-sm font-semibold rounded-full transition-all',
                dirty ? 'bg-pink-500 hover:bg-pink-600 text-white' : 'bg-white/10 text-white/30 cursor-not-allowed',
              ].join(' ')}
            >
              {saving ? (
                <span className="flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" /> Saving...
                </span>
              ) : (
                'Save Changes'
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Lightbox for full-screen avatar viewing (view-only, no edit/video) */}
      {lightbox ? (
        <ImageViewer
          imageUrl={lightbox}
          onClose={() => setLightbox(null)}
        />
      ) : null}
    </div>
  )
}
