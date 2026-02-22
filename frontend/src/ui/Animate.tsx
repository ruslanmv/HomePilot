import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { Upload, Mic, Settings2, X, Play, Pause, Download, Copy, RefreshCw, Trash2, Film, Image, ChevronDown, ChevronRight, Maximize2, Clock, Zap, Sliders, Loader2, Info, MoreHorizontal, Check, ArrowUp } from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type AnimateItem = {
  id: string
  videoUrl?: string  // Only present when status is "done"
  posterUrl?: string
  createdAt: number
  prompt: string
  finalPrompt?: string
  sourceImageUrl?: string
  // Job status for persistent generation tracking
  status: 'done' | 'processing' | 'failed'
  jobId?: string  // For tracking/resuming jobs
  progress?: number  // 0-100 during processing
  error?: string  // Error message when failed
  // Generation parameters for reproducibility
  seed?: number
  seconds?: number
  frames?: number
  fps?: number
  motion?: string
  model?: string
  preset?: string
  aspectRatio?: string
  // Resolution for reproducibility
  width?: number
  height?: number
  // Advanced parameters
  steps?: number
  cfg?: number
  denoise?: number
}

export type AnimateParams = {
  backendUrl: string
  apiKey?: string
  // Video provider settings
  providerVideo: string
  baseUrlVideo?: string
  modelVideo?: string
  // Chat/LLM provider settings (for prompt refinement)
  providerChat?: string
  baseUrlChat?: string
  modelChat?: string
  // Video generation controls
  vidSeconds?: number
  vidFps?: number
  vidMotion?: string
  vidPreset?: string  // Hardware/quality preset from global settings
  nsfwMode?: boolean
  promptRefinement?: boolean
}

type ChatResponse = {
  ok?: boolean
  text?: string
  media?: {
    images?: string[]
    video_url?: string
    poster_url?: string
    final_prompt?: string
    prompt?: string
    seed?: number
    model?: string
    // Video generation metadata
    duration?: number
    fps?: number
    frames?: number
    steps?: number
    cfg?: number
    denoise?: number
    motion?: string
    preset?: string
    source_image?: string
    auto_generated_image?: string
    // Resolution for reproducibility
    width?: number
    height?: number
  } | null
  message?: string
}

// Motion strength presets
const MOTION_PRESETS = [
  { label: 'Subtle', value: 'low', description: 'Gentle, minimal movement' },
  { label: 'Medium', value: 'medium', description: 'Balanced motion' },
  { label: 'Dynamic', value: 'high', description: 'Strong, dramatic motion' },
]

// Duration presets
const DURATION_PRESETS = [
  { label: '2s', value: 2 },
  { label: '4s', value: 4 },
  { label: '6s', value: 6 },
  { label: '8s', value: 8 },
]

// FPS presets
const FPS_PRESETS = [
  { label: '8 fps', value: 8 },
  { label: '12 fps', value: 12 },
  { label: '16 fps', value: 16 },
  { label: '24 fps', value: 24 },
]

// Quality presets
const QUALITY_PRESETS = [
  { id: 'low', label: 'Low', short: 'Fast', description: 'For 6-8GB VRAM. Fastest generation.' },
  { id: 'medium', label: 'Medium', short: 'Balanced', description: 'For 10-12GB VRAM. Good quality/speed balance.' },
  { id: 'high', label: 'High', short: 'Quality', description: 'For 16GB+ VRAM. Higher quality output.' },
  { id: 'ultra', label: 'Ultra', short: 'Maximum', description: 'For 24GB+ VRAM. Best quality, longest clips.' },
]

// Video aspect ratio presets with preview dimensions
type VideoAspectRatio = {
  id: string
  label: string
  previewW: number
  previewH: number
}

// Default aspect ratios (used as fallback)
const DEFAULT_ASPECT_RATIOS: VideoAspectRatio[] = [
  { id: '16:9', label: 'Widescreen', previewW: 42, previewH: 24 },
  { id: '9:16', label: 'Vertical', previewW: 24, previewH: 42 },
  { id: '1:1', label: 'Square', previewW: 24, previewH: 24 },
  { id: '4:3', label: 'Classic', previewW: 32, previewH: 24 },
  { id: '3:4', label: 'Portrait', previewW: 24, previewH: 32 },
]

// Fallback default values (used when API is unavailable)
// Matches LTX "high" preset - proven working configuration
const FALLBACK_ADVANCED_PARAMS = {
  steps: 32,
  cfg: 4.0,
  denoise: 0.8,
}

// Type for preset values from API
type PresetValues = {
  steps?: number
  cfg?: number
  denoise?: number
  fps?: number
  frames?: number
  negativePrompt?: string
  defaultAspectRatio?: string
}

// Type for resolution options (from aspect ratio dimensions)
type ResolutionOption = {
  id: string  // 'auto' | 'low' | 'medium' | 'high' | 'ultra'
  label: string
  width: number
  height: number
}

// -----------------------------------------------------------------------------
// Video resolution helpers (additive)
// -----------------------------------------------------------------------------

type Dim = { width: number; height: number }

function isDim(x: any): x is Dim {
  return x && typeof x.width === 'number' && typeof x.height === 'number'
}

/** Returns the preset-derived (Auto) resolution for the current aspectRatio + qualityPreset */
function getAutoVideoDims(opts: {
  rawAspectRatioData: any[]
  aspectRatio: string
  qualityPreset: string
}): Dim | null {
  const { rawAspectRatioData, aspectRatio, qualityPreset } = opts
  const ratioEntry = rawAspectRatioData?.find((ar: any) => ar.id === aspectRatio)

  // Prefer all_dimensions (keyed by tier), fall back to legacy dimensions
  const allDims = ratioEntry?.all_dimensions
  if (allDims) {
    const d = allDims[qualityPreset]
    if (isDim(d)) return d
    const fallback = allDims['medium']
    return isDim(fallback) ? fallback : null
  }

  // Legacy path: dimensions was a flat {width, height} for the selected preset
  const flat = ratioEntry?.dimensions
  if (isDim(flat)) return flat
  return null
}

/** Returns the override tier dims from availableResolutions */
function getOverrideVideoDims(opts: {
  availableResolutions: ResolutionOption[]
  customResolution: string
}): Dim | null {
  const { availableResolutions, customResolution } = opts
  if (customResolution === 'auto') return null
  const hit = availableResolutions?.find((r) => r.id === customResolution)
  return hit ? { width: hit.width, height: hit.height } : null
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

async function postJson<T>(baseUrl: string, path: string, body: any, apiKey?: string): Promise<T> {
  const url = `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
    },
    credentials: 'include',
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (mins > 0) return `${mins}m ${secs}s`
  return `${secs}s`
}

// Check if URL points to an animated image (WEBP/GIF) vs video (MP4/WebM)
// Animated WEBP/GIF must use <img> tag, videos use <video> tag
function isAnimatedImage(url: string | undefined): boolean {
  if (!url) return false
  const lower = url.toLowerCase()
  // ComfyUI URLs look like: /view?filename=xxx.webp&subfolder=...
  return lower.includes('.webp') || lower.includes('.gif')
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

export default function AnimateView(props: AnimateParams) {
  const authKey = (props.apiKey || '').trim()
  const [prompt, setPrompt] = useState('')

  // Load items from localStorage on mount
  const [items, setItems] = useState<AnimateItem[]>(() => {
    try {
      const stored = localStorage.getItem('homepilot_animate_items')
      if (stored) {
        const parsed = JSON.parse(stored)
        if (Array.isArray(parsed)) {
          // Thresholds for handling stale processing items:
          // - IN_FLIGHT_THRESHOLD: Video generation can take 30s-3min depending on settings.
          //   If processing item is older than 3 min, generation likely completed but state
          //   update was lost due to tab switch (component unmount).
          // - STALE_THRESHOLD: If processing item is older than this, app was closed during
          //   generation - mark as definitively failed.
          const IN_FLIGHT_THRESHOLD = 3 * 60 * 1000  // 3 minutes - likely completed but lost track
          const STALE_THRESHOLD = 10 * 60 * 1000  // 10 minutes - definitively failed
          const now = Date.now()
          return parsed.map((item: any) => {
            // Migrate: old items without status get 'done' if they have videoUrl
            if (!item.status) {
              return { ...item, status: item.videoUrl ? 'done' : 'failed' }
            }
            // Handle processing items based on age
            if (item.status === 'processing') {
              const age = now - item.createdAt
              // Very old items (app was closed) - mark as failed
              if (age > STALE_THRESHOLD) {
                return { ...item, status: 'failed', error: 'Generation interrupted - please retry' }
              }
              // Medium-age items (tab was switched) - likely completed but we lost track
              // Mark as failed since we can't verify the result without backend check
              if (age > IN_FLIGHT_THRESHOLD) {
                return {
                  ...item,
                  status: 'failed',
                  error: 'Generation may have completed - check your gallery or retry'
                }
              }
            }
            // Keep recent processing items as-is (still in-flight)
            return item
          })
        }
      }
    } catch (error) {
      console.error('Failed to load animate items from localStorage:', error)
    }
    return []
  })

  const [isGenerating, setIsGenerating] = useState(false)

  // Selection state for Lightbox (Grok-style detail view)
  const [selectedVideo, setSelectedVideo] = useState<AnimateItem | null>(null)
  const [showDetails, setShowDetails] = useState(false)  // Immersive mode: details hidden by default
  const [showSourceImage, setShowSourceImage] = useState(false)  // Source image overlay
  const [lightboxPrompt, setLightboxPrompt] = useState('')  // Editable prompt in lightbox
  const [isRegenerating, setIsRegenerating] = useState(false)  // Regenerating from lightbox
  const [regenProgress, setRegenProgress] = useState<number | null>(null)  // Progress 0-100 during regen
  const [regenAbortController, setRegenAbortController] = useState<AbortController | null>(null)  // For cancellation

  // Video settings
  const [seconds, setSeconds] = useState(props.vidSeconds || 4)
  const [fps, setFps] = useState(props.vidFps || 8)
  const [motion, setMotion] = useState(props.vidMotion || 'medium')
  const [showSettingsPanel, setShowSettingsPanel] = useState(false)
  const [qualityPreset, setQualityPreset] = useState(props.vidPreset || 'medium')
  // Sync with global preset when it changes
  useEffect(() => {
    if (props.vidPreset) {
      setQualityPreset(props.vidPreset)
    }
  }, [props.vidPreset])
  const [aspectRatio, setAspectRatio] = useState('16:9')
  const [compatibleAspectRatios, setCompatibleAspectRatios] = useState<VideoAspectRatio[]>(DEFAULT_ASPECT_RATIOS)
  const [rawAspectRatioData, setRawAspectRatioData] = useState<any[]>([])  // Store raw API response for resolution lookup

  // Advanced Controls state
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false)
  const [advancedMode, setAdvancedMode] = useState(false)
  const [customSteps, setCustomSteps] = useState(FALLBACK_ADVANCED_PARAMS.steps)
  const [customCfg, setCustomCfg] = useState(FALLBACK_ADVANCED_PARAMS.cfg)
  const [customDenoise, setCustomDenoise] = useState(FALLBACK_ADVANCED_PARAMS.denoise)
  const [seedLock, setSeedLock] = useState(false)
  const [customSeed, setCustomSeed] = useState(0)
  const [customNegativePrompt, setCustomNegativePrompt] = useState('')
  const [showNegativePrompt, setShowNegativePrompt] = useState(false)
  // Resolution override (allows testing different resolutions in Advanced Mode)
  const [customResolution, setCustomResolution] = useState<string>('auto')  // 'auto' | 'low' | 'medium' | 'high' | 'ultra'
  const [availableResolutions, setAvailableResolutions] = useState<ResolutionOption[]>([])
  // Resolution mode (additive): "auto" uses preset-derived dims, "override" uses customResolution tier
  const [vidResolutionMode, setVidResolutionMode] = useState<'auto' | 'override'>('auto')

  // Preset defaults from API (model-specific)
  const [presetDefaults, setPresetDefaults] = useState<PresetValues>(FALLBACK_ADVANCED_PARAMS)

  // Detect model type from model filename
  const detectedModelType = useMemo(() => {
    const model = (props.modelVideo || '').toLowerCase()
    if (model.includes('ltx')) return 'ltx'
    if (model.includes('svd')) return 'svd'
    if (model.includes('wan')) return 'wan'
    if (model.includes('hunyuan')) return 'hunyuan'
    if (model.includes('mochi')) return 'mochi'
    if (model.includes('cogvideo')) return 'cogvideo'
    return null // Unknown model, use base preset
  }, [props.modelVideo])

  // Fetch preset defaults when model or quality changes
  useEffect(() => {
    const fetchPresets = async () => {
      try {
        const base = props.backendUrl.replace(/\/+$/, '')
        const params = new URLSearchParams()
        if (detectedModelType) params.set('model', detectedModelType)
        // Map hardware presets to video quality presets
        // Hardware: 4060 → low, 4080 → medium, a100 → high, custom → medium
        // Also normalise "med" → "medium" (UI shorthand)
        const videoPreset = qualityPreset === 'custom' ? 'medium'
          : qualityPreset === 'med' ? 'medium'
          : qualityPreset === '4060' ? 'low'
          : qualityPreset === '4080' ? 'medium'
          : qualityPreset === 'a100' ? 'high'
          : qualityPreset  // Already a valid video preset (low/medium/high/ultra)
        params.set('preset', videoPreset)

        const res = await fetch(`${base}/video-presets?${params}`, {
          headers: authKey ? { 'x-api-key': authKey } : undefined,
        })

        if (res.ok) {
          const data = await res.json()
          if (data.ok && data.values) {
            setPresetDefaults({
              steps: data.values.steps ?? FALLBACK_ADVANCED_PARAMS.steps,
              cfg: data.values.cfg ?? FALLBACK_ADVANCED_PARAMS.cfg,
              denoise: data.values.denoise ?? FALLBACK_ADVANCED_PARAMS.denoise,
              fps: data.values.fps,
              frames: data.values.frames,
              negativePrompt: data.model_rules?.default_negative_prompt ?? '',
              defaultAspectRatio: data.default_aspect_ratio,
            })
          }

          // Also update compatible aspect ratios from API response
          if (data.compatible_aspect_ratios && Array.isArray(data.compatible_aspect_ratios)) {
            // Store raw data for resolution lookup
            setRawAspectRatioData(data.compatible_aspect_ratios)

            const mappedRatios: VideoAspectRatio[] = data.compatible_aspect_ratios.map((ar: any) => ({
              id: ar.id,
              label: ar.label?.replace(/\s*\([^)]*\)/g, '') || ar.id, // Strip parenthetical like "(16:9)"
              previewW: getPreviewDimension(ar.id, 'width'),
              previewH: getPreviewDimension(ar.id, 'height'),
            }))
            if (mappedRatios.length > 0) {
              setCompatibleAspectRatios(mappedRatios)
              // If current aspect ratio is not in the compatible list, switch to the first one
              if (!mappedRatios.find((r) => r.id === aspectRatio)) {
                setAspectRatio(mappedRatios[0].id)
              }
            }
          }
        }
      } catch (err) {
        console.warn('Failed to fetch video presets:', err)
        // Keep using fallback defaults
        setCompatibleAspectRatios(DEFAULT_ASPECT_RATIOS)
      }
    }

    fetchPresets()
    // Note: aspectRatio intentionally omitted to avoid infinite loop
    // (this effect may update aspectRatio if it's incompatible with new model)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.backendUrl, authKey, detectedModelType, qualityPreset])

  // Update available resolutions when aspect ratio or model changes
  // Uses all_dimensions (every tier) so the Override grid shows all options
  useEffect(() => {
    if (rawAspectRatioData.length === 0) return

    const currentRatioData = rawAspectRatioData.find((ar: any) => ar.id === aspectRatio)
    // Prefer all_dimensions (every tier), fall back to single-preset dimensions
    const allDims = currentRatioData?.all_dimensions || currentRatioData?.dimensions
    if (allDims && typeof allDims === 'object') {
      const presetLabels: Record<string, string> = {
        test: 'Lowest (6GB)',
        low: 'Low (8GB)',
        medium: 'Medium (12GB)',
        high: 'High (16GB)',
        ultra: 'Ultra (24GB+)',
      }
      // Ensure consistent ordering
      const tierOrder = ['test', 'low', 'medium', 'high', 'ultra']
      const resolutions: ResolutionOption[] = tierOrder
        .filter((tier) => allDims[tier]?.width && allDims[tier]?.height)
        .map((tier) => ({
          id: tier,
          label: `${allDims[tier].width}×${allDims[tier].height} ${presetLabels[tier] || tier}`,
          width: allDims[tier].width,
          height: allDims[tier].height,
        }))
      setAvailableResolutions(resolutions)
      // Smart reset: keep override tier if still available, otherwise fall back to auto
      if (vidResolutionMode === 'override' && customResolution !== 'auto') {
        const stillValid = resolutions.some((r) => r.id === customResolution)
        if (!stillValid) {
          setCustomResolution('auto')
          setVidResolutionMode('auto')
        }
      } else {
        setCustomResolution('auto')
        setVidResolutionMode('auto')
      }
    }
  }, [aspectRatio, rawAspectRatioData])  // eslint-disable-line react-hooks/exhaustive-deps

  // Helper to get preview dimensions for aspect ratio thumbnails
  function getPreviewDimension(ratioId: string, dimension: 'width' | 'height'): number {
    const previewSizes: Record<string, { w: number; h: number }> = {
      '16:9': { w: 42, h: 24 },
      '9:16': { w: 24, h: 42 },
      '1:1': { w: 24, h: 24 },
      '4:3': { w: 32, h: 24 },
      '3:4': { w: 24, h: 32 },
    }
    const size = previewSizes[ratioId] || { w: 32, h: 24 }
    return dimension === 'width' ? size.w : size.h
  }

  // Reset advanced parameters to preset defaults (model-specific)
  const resetAdvancedParams = useCallback(() => {
    setCustomSteps(presetDefaults.steps ?? FALLBACK_ADVANCED_PARAMS.steps)
    setCustomCfg(presetDefaults.cfg ?? FALLBACK_ADVANCED_PARAMS.cfg)
    setCustomDenoise(presetDefaults.denoise ?? FALLBACK_ADVANCED_PARAMS.denoise)
    setSeedLock(false)
    setCustomSeed(0)
    setCustomNegativePrompt('')
    setShowNegativePrompt(false)
    setCustomResolution('auto')  // Reset resolution to use preset default
    setVidResolutionMode('auto')
  }, [presetDefaults])

  // Reset Video Settings to model-specific defaults
  // Resets: Aspect Ratio (model default), Quality Preset (global), Motion (medium)
  const resetVideoSettings = useCallback(() => {
    // Reset aspect ratio to model's recommended default
    const defaultRatio = presetDefaults.defaultAspectRatio
    if (defaultRatio && compatibleAspectRatios.find(r => r.id === defaultRatio)) {
      setAspectRatio(defaultRatio)
    } else if (compatibleAspectRatios.length > 0) {
      // Fallback to first compatible ratio
      setAspectRatio(compatibleAspectRatios[0].id)
    }

    // Reset quality preset to global setting
    setQualityPreset(props.vidPreset || 'medium')

    // Reset motion strength to balanced default
    setMotion('medium')
  }, [presetDefaults.defaultAspectRatio, compatibleAspectRatios, props.vidPreset])

  // Sync slider values when preset defaults change (from API or quality/model change)
  // Only sync if user hasn't entered Advanced Mode yet (preserves custom values)
  useEffect(() => {
    if (!advancedMode) {
      // Sync advanced params (steps, cfg, denoise)
      setCustomSteps(presetDefaults.steps ?? FALLBACK_ADVANCED_PARAMS.steps)
      setCustomCfg(presetDefaults.cfg ?? FALLBACK_ADVANCED_PARAMS.cfg)
      setCustomDenoise(presetDefaults.denoise ?? FALLBACK_ADVANCED_PARAMS.denoise)

      // Sync FPS from preset (model-specific optimal value)
      if (presetDefaults.fps) {
        setFps(presetDefaults.fps)
      }

      // Calculate and sync Duration from preset frames
      if (presetDefaults.frames && presetDefaults.fps) {
        const calculatedSeconds = Math.round(presetDefaults.frames / presetDefaults.fps)
        // Clamp to valid duration options (2, 4, 6, 8)
        const validDurations = [2, 4, 6, 8]
        const closestDuration = validDurations.reduce((prev, curr) =>
          Math.abs(curr - calculatedSeconds) < Math.abs(prev - calculatedSeconds) ? curr : prev
        )
        setSeconds(closestDuration)
      }
    }
  }, [presetDefaults, advancedMode])

  // Reference Image state (source image for animation)
  const referenceInputRef = useRef<HTMLInputElement>(null)
  const [referenceUrl, setReferenceUrl] = useState<string | null>(null)
  const [isUploadingReference, setIsUploadingReference] = useState(false)

  // Ref for auto-scrolling to top when new videos are added
  const gridStartRef = useRef<HTMLDivElement>(null)

  // Save items to localStorage whenever they change
  useEffect(() => {
    try {
      localStorage.setItem('homepilot_animate_items', JSON.stringify(items))
    } catch (error) {
      console.error('Failed to save animate items to localStorage:', error)
    }
  }, [items])

  // On mount, periodically check localStorage for items that completed while unmounted
  // This handles the race condition where API completes after component remounts
  useEffect(() => {
    const processingItems = items.filter(item => item.status === 'processing')
    if (processingItems.length === 0) return

    // Video generation can take up to 3 minutes, so use longer threshold
    const IN_FLIGHT_THRESHOLD = 3 * 60 * 1000  // 3 minutes

    // Check localStorage for updates and sync state
    const syncFromLocalStorage = () => {
      try {
        const stored = localStorage.getItem('homepilot_animate_items')
        if (!stored) return false

        const storedItems: AnimateItem[] = JSON.parse(stored)
        const storedMap = new Map(storedItems.map(item => [item.id, item]))

        let hasUpdates = false
        setItems(prev => {
          const updated = prev.map(item => {
            if (item.status !== 'processing') return item

            // Check if this item was completed in localStorage (by another instance)
            const storedItem = storedMap.get(item.id)
            if (storedItem && storedItem.status === 'done' && storedItem.videoUrl) {
              console.log('[Animate] Synced completed item from localStorage:', item.id)
              hasUpdates = true
              return storedItem
            }

            // Check if this processing item is now too old
            const age = Date.now() - item.createdAt
            if (age > IN_FLIGHT_THRESHOLD) {
              hasUpdates = true
              return {
                ...item,
                status: 'failed' as const,
                error: 'Generation may have completed - check your gallery or retry'
              }
            }

            // Continue progress simulation
            return {
              ...item,
              progress: Math.min(90, (item.progress || 0) + Math.random() * 3 + 1)
            }
          })
          return updated
        })
        return hasUpdates
      } catch (e) {
        console.error('[Animate] Failed to sync from localStorage:', e)
        return false
      }
    }

    // Run sync check periodically
    const progressInterval = setInterval(() => {
      syncFromLocalStorage()
    }, 800)  // Slower interval for video (takes longer)

    // Also run immediately on mount
    syncFromLocalStorage()

    return () => clearInterval(progressInterval)
    // Only run on mount (empty deps) - items will be stale but that's intentional
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Scroll to top when entering Animate
  useEffect(() => {
    gridStartRef.current?.scrollIntoView({ block: 'start' })
  }, [])

  // Load handoff from Imagine (Grok-style "Animate this image")
  useEffect(() => {
    try {
      const raw = localStorage.getItem('homepilot_animate_handoff')
      if (!raw) return

      const data = JSON.parse(raw)
      const tooOld = Date.now() - (data.createdAt ?? 0) > 2 * 60 * 1000 // 2 min TTL

      if (tooOld) {
        localStorage.removeItem('homepilot_animate_handoff')
        return
      }

      if (data.imageUrl) {
        setReferenceUrl(data.imageUrl)
        console.log('[Animate] Loaded source image from Imagine handoff:', data.imageUrl)
      }
      if (typeof data.prompt === 'string' && data.prompt.trim()) {
        setPrompt(data.prompt)
      }

      // Clean up handoff after use
      localStorage.removeItem('homepilot_animate_handoff')
    } catch {
      localStorage.removeItem('homepilot_animate_handoff')
    }
  }, [])

  // Initialize lightbox prompt when selecting a video
  useEffect(() => {
    if (selectedVideo) {
      setLightboxPrompt(selectedVideo.finalPrompt || selectedVideo.prompt)
    }
  }, [selectedVideo])

  // Upload reference image handler
  const handleUploadReference = useCallback(async (file: File) => {
    setIsUploadingReference(true)
    try {
      const base = props.backendUrl.replace(/\/+$/, '')
      const url = `${base}/upload`

      const fd = new FormData()
      fd.append('file', file)

      const res = await fetch(url, {
        method: 'POST',
        headers: authKey ? { 'x-api-key': authKey } : undefined,
        body: fd,
      })

      if (!res.ok) {
        const text = await res.text().catch(() => `HTTP ${res.status}`)
        throw new Error(text)
      }

      const data = await res.json()
      const imageUrl = data?.url || data?.file_url || data?.media_url
      if (!imageUrl) {
        throw new Error('Upload succeeded but no URL returned')
      }

      setReferenceUrl(imageUrl)
    } catch (err: any) {
      console.error('Reference upload failed:', err)
      alert(`Failed to upload reference: ${err.message || err}`)
    } finally {
      setIsUploadingReference(false)
    }
  }, [props.backendUrl, authKey])

  // --- Compute effective video dimensions (used by callbacks + render) ---
  const mappedPreset = useMemo(() => {
    return qualityPreset === 'custom' ? 'medium'
      : qualityPreset === 'med' ? 'medium'
      : qualityPreset === '4060' ? 'low'
      : qualityPreset === '4080' ? 'medium'
      : qualityPreset === 'a100' ? 'high'
      : qualityPreset
  }, [qualityPreset])
  const autoDims = useMemo(() => getAutoVideoDims({ rawAspectRatioData, aspectRatio, qualityPreset: mappedPreset }), [rawAspectRatioData, aspectRatio, mappedPreset])
  const overrideDims = useMemo(() => getOverrideVideoDims({ availableResolutions, customResolution }), [availableResolutions, customResolution])
  const effectiveDims = vidResolutionMode === 'override' && overrideDims ? overrideDims : autoDims
  // Actual duration from frames/fps (honest reporting)
  const actualDuration = presetDefaults?.frames && presetDefaults?.fps
    ? (presetDefaults.frames / presetDefaults.fps).toFixed(1)
    : null
  // Model capability flags (for conditional UI)
  const isMotionSupported = detectedModelType !== 'svd'
  const handleGenerate = useCallback(async () => {
    // For animate, we need either a prompt or a reference image
    const t = prompt.trim()
    if (!t && !referenceUrl) return
    if (isGenerating) return

    // Use default prompt for reference-only generation
    const effectivePrompt = t || 'animate this image with natural motion'

    setIsGenerating(true)
    setShowSettingsPanel(false)

    // Create placeholder item IMMEDIATELY (persists across tab switches)
    const placeholderId = uid()
    const placeholder: AnimateItem = {
      id: placeholderId,
      status: 'processing',
      progress: 0,
      createdAt: Date.now(),
      prompt: effectivePrompt,
      sourceImageUrl: referenceUrl || undefined,
      posterUrl: referenceUrl || undefined,  // Use reference as thumbnail while processing
      seconds: seconds,
      fps: fps,
      motion: motion,
      model: props.modelVideo,
      preset: qualityPreset,
      aspectRatio: aspectRatio,
    }

    // Add placeholder to items (will be persisted to localStorage)
    setItems((prev) => [placeholder, ...prev])
    setPrompt('')

    // Auto-scroll to show new placeholder
    setTimeout(() => {
      gridStartRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 100)

    // Simulate progress while waiting for API
    const progressInterval = setInterval(() => {
      setItems(prev => prev.map(item =>
        item.id === placeholderId && item.status === 'processing'
          ? { ...item, progress: Math.min(90, (item.progress || 0) + Math.random() * 8 + 2) }
          : item
      ))
    }, 500)

    try {
      // Build message for animate mode
      const animateMessage = referenceUrl
        ? `animate ${referenceUrl} ${effectivePrompt}`
        : `animate ${effectivePrompt}`

      // Determine video resolution override values (additive + backward compatible)
      const useOverride = vidResolutionMode === 'override' && overrideDims != null
      const resolvedVidWidth = useOverride ? overrideDims!.width : autoDims?.width
      const resolvedVidHeight = useOverride ? overrideDims!.height : autoDims?.height

      // Map hardware presets to video quality presets (normalise "med" → "medium")
      const videoPreset = qualityPreset === 'custom' ? 'medium'
        : qualityPreset === 'med' ? 'medium'
        : qualityPreset === '4060' ? 'low'
        : qualityPreset === '4080' ? 'medium'
        : qualityPreset === 'a100' ? 'high'
        : qualityPreset

      const requestBody: any = {
        message: animateMessage,
        mode: 'animate',

        // Video generation params
        vidSeconds: seconds,
        vidFps: fps,
        vidMotion: motion,
        vidModel: props.modelVideo || undefined,
        vidPreset: videoPreset,
        vidAspectRatio: aspectRatio,

        // Video resolution override (new, preferred fields)
        vidResolutionMode: useOverride ? 'override' : 'auto',
        ...(useOverride && {
          vidWidth: resolvedVidWidth,
          vidHeight: resolvedVidHeight,
        }),

        // Legacy compatibility (keep until backend fully switches to vidWidth/vidHeight)
        ...(useOverride && {
          imgWidth: resolvedVidWidth,
          imgHeight: resolvedVidHeight,
        }),

        // Advanced parameters (when enabled)
        ...(advancedMode && {
          vidSteps: customSteps,
          vidCfg: customCfg,
          vidDenoise: customDenoise,
          ...(seedLock && { vidSeed: customSeed }),
          ...(customNegativePrompt.trim() && { vidNegativePrompt: customNegativePrompt.trim() }),
        }),

        // Provider settings
        provider: props.providerVideo === 'comfyui' ? 'ollama' : props.providerVideo,
        provider_base_url: props.baseUrlVideo || undefined,
        provider_model: props.modelVideo || undefined,

        // LLM settings for prompt refinement
        ollama_base_url: props.providerChat === 'ollama' ? props.baseUrlChat : undefined,
        ollama_model: props.providerChat === 'ollama' ? props.modelChat : undefined,

        nsfwMode: props.nsfwMode,
        promptRefinement: props.promptRefinement ?? true,
      }

      const data = await postJson<ChatResponse>(
        props.backendUrl,
        '/chat',
        requestBody,
        authKey
      )

      clearInterval(progressInterval)

      if (!data.media?.video_url) {
        throw new Error(data.message || data.text || 'No video URL returned')
      }

      // Build the completed item
      const completedItem: AnimateItem = {
        ...placeholder,
        status: 'done' as const,
        progress: 100,
        videoUrl: data.media!.video_url,
        posterUrl: data.media!.poster_url || placeholder.posterUrl,
        finalPrompt: data.media!.final_prompt || data.media!.prompt,
        sourceImageUrl: data.media!.auto_generated_image || referenceUrl || data.media!.source_image || placeholder.sourceImageUrl,
        seed: data.media!.seed ?? (seedLock ? customSeed : undefined),
        seconds: data.media!.duration ?? seconds,
        frames: data.media!.frames,
        fps: data.media!.fps ?? fps,
        motion: data.media!.motion ?? motion,
        model: data.media!.model ?? props.modelVideo,
        preset: data.media!.preset ?? qualityPreset,
        aspectRatio: aspectRatio,
        // Resolution for reproducibility
        width: data.media!.width,
        height: data.media!.height,
        steps: data.media!.steps ?? (advancedMode ? customSteps : undefined),
        cfg: data.media!.cfg ?? (advancedMode ? customCfg : undefined),
        denoise: data.media!.denoise ?? (advancedMode ? customDenoise : undefined),
      }

      // CRITICAL: Directly persist to localStorage BEFORE setItems
      // This ensures the result is saved even if component unmounts between
      // API response and React's state update
      try {
        const stored = localStorage.getItem('homepilot_animate_items')
        const currentItems: AnimateItem[] = stored ? JSON.parse(stored) : []
        const updatedItems = currentItems.map(item =>
          item.id === placeholderId ? completedItem : item
        )
        localStorage.setItem('homepilot_animate_items', JSON.stringify(updatedItems))
        console.log('[Animate] Persisted completed video to localStorage:', placeholderId)
      } catch (e) {
        console.error('[Animate] Failed to persist to localStorage:', e)
      }

      // Update React state (may not process if component unmounted, but localStorage is already updated)
      setItems(prev => prev.map(item =>
        item.id === placeholderId ? completedItem : item
      ))
    } catch (err: any) {
      clearInterval(progressInterval)
      console.error('Video generation failed:', err)

      // Build failed item
      const failedItem: AnimateItem = {
        ...placeholder,
        status: 'failed' as const,
        error: err.message || 'Generation failed'
      }

      // CRITICAL: Directly persist failure to localStorage
      try {
        const stored = localStorage.getItem('homepilot_animate_items')
        const currentItems: AnimateItem[] = stored ? JSON.parse(stored) : []
        const updatedItems = currentItems.map(item =>
          item.id === placeholderId ? failedItem : item
        )
        localStorage.setItem('homepilot_animate_items', JSON.stringify(updatedItems))
      } catch (e) {
        console.error('Failed to persist to localStorage:', e)
      }

      // Update React state
      setItems(prev => prev.map(item =>
        item.id === placeholderId ? failedItem : item
      ))
    } finally {
      setIsGenerating(false)
    }
  }, [prompt, referenceUrl, isGenerating, seconds, fps, motion, qualityPreset, aspectRatio, props, authKey, advancedMode, customSteps, customCfg, customDenoise, seedLock, customSeed, customNegativePrompt, vidResolutionMode, autoDims, overrideDims])

  const handleDelete = useCallback((item: AnimateItem, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Delete this video from gallery?')) return
    setItems((prev) => prev.filter((x) => x.id !== item.id))
    if (selectedVideo?.id === item.id) setSelectedVideo(null)
  }, [selectedVideo])

  const handleDownload = useCallback((url: string, filename?: string) => {
    const a = document.createElement('a')
    a.href = url
    a.download = filename || 'animated-video.mp4'
    document.body.appendChild(a)
    a.click()
    a.remove()
  }, [])

  const handleCopyPrompt = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
    } catch {}
  }, [])

  // Grok-style in-place regeneration: keeps lightbox open, shows progress overlay
  const handleRegenerateInPlace = useCallback(async () => {
    if (!selectedVideo || !lightboxPrompt.trim() || isRegenerating) return

    const abortController = new AbortController()
    setRegenAbortController(abortController)
    setIsRegenerating(true)
    setRegenProgress(0)

    // Simulate progress while waiting for sync API (progress increases gradually)
    const progressInterval = setInterval(() => {
      setRegenProgress(prev => {
        if (prev === null) return 0
        // Slow down as we approach 90% (leave room for completion)
        if (prev >= 90) return prev
        return Math.min(90, prev + Math.random() * 8 + 2)
      })
    }, 500)

    try {
      // Check if we have an existing source image to reuse
      const existingSourceImage = selectedVideo.sourceImageUrl

      // Build message for animate mode
      // If we have a source image, REUSE it (don't generate new) - Grok behavior
      // If no source image, let backend generate one from the prompt
      const animateMessage = existingSourceImage
        ? `animate ${existingSourceImage} ${lightboxPrompt}`
        : `animate ${lightboxPrompt}`

      // Determine video resolution override values (additive + backward compatible)
      const regenUseOverride = vidResolutionMode === 'override' && overrideDims != null
      const regenVidWidth = regenUseOverride ? overrideDims!.width : autoDims?.width
      const regenVidHeight = regenUseOverride ? overrideDims!.height : autoDims?.height

      // Map hardware presets to video quality presets (normalise "med" → "medium")
      const videoPreset = qualityPreset === 'custom' ? 'medium'
        : qualityPreset === 'med' ? 'medium'
        : qualityPreset === '4060' ? 'low'
        : qualityPreset === '4080' ? 'medium'
        : qualityPreset === 'a100' ? 'high'
        : qualityPreset

      const requestBody: any = {
        message: animateMessage,
        mode: 'animate',
        vidSeconds: seconds,
        vidFps: fps,
        vidMotion: motion,
        vidModel: props.modelVideo || undefined,
        vidPreset: videoPreset,
        vidAspectRatio: aspectRatio,
        // When we have an existing source image, tell backend to skip image generation
        // The prompt should only affect the animation, not regenerate the source
        ...(existingSourceImage && { skipImageGeneration: true }),
        // Video resolution override (new, preferred fields)
        vidResolutionMode: regenUseOverride ? 'override' : 'auto',
        ...(regenUseOverride && {
          vidWidth: regenVidWidth,
          vidHeight: regenVidHeight,
        }),
        // Legacy compatibility
        ...(regenUseOverride && {
          imgWidth: regenVidWidth,
          imgHeight: regenVidHeight,
        }),
        ...(advancedMode && {
          vidSteps: customSteps,
          vidCfg: customCfg,
          vidDenoise: customDenoise,
          ...(seedLock && { vidSeed: customSeed }),
          ...(customNegativePrompt.trim() && { vidNegativePrompt: customNegativePrompt.trim() }),
        }),
        provider: props.providerVideo === 'comfyui' ? 'ollama' : props.providerVideo,
        provider_base_url: props.baseUrlVideo || undefined,
        provider_model: props.modelVideo || undefined,
        ollama_base_url: props.providerChat === 'ollama' ? props.baseUrlChat : undefined,
        ollama_model: props.providerChat === 'ollama' ? props.modelChat : undefined,
        nsfwMode: props.nsfwMode,
        promptRefinement: props.promptRefinement ?? true,
      }

      const data = await postJson<ChatResponse>(
        props.backendUrl,
        '/chat',
        requestBody,
        authKey
      )

      // Check if aborted
      if (abortController.signal.aborted) {
        return
      }

      if (!data.media?.video_url) {
        throw new Error(data.message || data.text || 'No video URL returned')
      }

      // Progress complete
      setRegenProgress(100)

      // Create new item with updated video
      // IMPORTANT: If we had an existing source image, KEEP IT (don't replace with auto_generated)
      // Only use auto_generated when we didn't have a source image (text-to-video flow)
      const newItem: AnimateItem = {
        id: uid(),
        status: 'done',
        videoUrl: data.media.video_url,
        posterUrl: data.media.poster_url,
        createdAt: Date.now(),
        prompt: lightboxPrompt,
        finalPrompt: data.media.final_prompt || data.media.prompt,
        // Grok behavior: keep the original source image when regenerating
        // Only use auto_generated_image when there was no source (text-to-video)
        sourceImageUrl: existingSourceImage || data.media.auto_generated_image || data.media.source_image || undefined,
        seed: data.media.seed ?? (seedLock ? customSeed : undefined),
        seconds: data.media.duration ?? seconds,
        frames: data.media.frames,
        fps: data.media.fps ?? fps,
        motion: data.media.motion ?? motion,
        model: data.media.model ?? props.modelVideo,
        preset: data.media.preset ?? qualityPreset,
        aspectRatio: aspectRatio,
        // Resolution for reproducibility
        width: data.media.width,
        height: data.media.height,
        steps: data.media.steps ?? (advancedMode ? customSteps : undefined),
        cfg: data.media.cfg ?? (advancedMode ? customCfg : undefined),
        denoise: data.media.denoise ?? (advancedMode ? customDenoise : undefined),
      }

      // Update selected video in-place (Grok behavior)
      setSelectedVideo(newItem)
      setLightboxPrompt(newItem.finalPrompt || newItem.prompt)

      // Also prepend to items list
      setItems(prev => [newItem, ...prev])

      // Brief delay to show 100% before clearing
      await new Promise(r => setTimeout(r, 300))
    } catch (err: any) {
      if (abortController.signal.aborted) {
        return // User cancelled
      }
      console.error('Regeneration failed:', err)
      alert(`Regeneration failed: ${err.message || err}`)
    } finally {
      clearInterval(progressInterval)
      setIsRegenerating(false)
      setRegenProgress(null)
      setRegenAbortController(null)
    }
  }, [selectedVideo, lightboxPrompt, isRegenerating, seconds, fps, motion, qualityPreset, aspectRatio, props, authKey, advancedMode, customSteps, customCfg, customDenoise, seedLock, customSeed, customNegativePrompt, vidResolutionMode, autoDims, overrideDims])

  // Cancel in-place regeneration
  const handleCancelRegeneration = useCallback(() => {
    if (regenAbortController) {
      regenAbortController.abort()
      setIsRegenerating(false)
      setRegenProgress(null)
      setRegenAbortController(null)
    }
  }, [regenAbortController])

  return (
    <div className="flex flex-col h-full w-full bg-black text-white overflow-hidden relative">
      {/* Advanced Settings Panel (top-right) */}
      {showAdvancedSettings && (
        <div className="absolute top-20 right-6 z-30 bg-black/95 border border-white/10 rounded-2xl shadow-2xl w-80 backdrop-blur-xl overflow-hidden">
          <div className="p-5 border-b border-white/10 flex items-center justify-between">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Settings2 size={16} />
              PARAMETERS
            </h3>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={resetAdvancedParams}
                className="text-white/50 hover:text-purple-400 transition-colors flex items-center gap-1 text-xs"
                title="Reset to recommended defaults"
              >
                <RefreshCw size={14} />
                Reset
              </button>
              <button type="button" onClick={() => setShowAdvancedSettings(false)} className="text-white/50 hover:text-white">
                <X size={16} />
              </button>
            </div>
          </div>

          <div className="p-5 space-y-6 max-h-[70vh] overflow-y-auto">
            {/* Advanced Mode Toggle */}
            <button
              onClick={() => setAdvancedMode(!advancedMode)}
              className={`w-full flex items-center justify-between p-3 rounded-xl border transition-colors ${
                advancedMode
                  ? 'bg-purple-500/20 border-purple-500/40 text-purple-300'
                  : 'bg-white/5 border-white/10 text-white/60 hover:border-white/20'
              }`}
            >
              <span className="flex items-center gap-2 font-medium text-sm">
                <Sliders size={16} />
                Advanced Controls
              </span>
              {advancedMode ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </button>

            {advancedMode && (
              <div className="space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
                {/* Duration */}
                <div className="space-y-2">
                  <span className="uppercase tracking-wider text-white/40 font-semibold text-xs">Duration</span>
                  <div className="flex gap-2">
                    {DURATION_PRESETS.map((d) => (
                      <button
                        key={d.value}
                        onClick={() => setSeconds(d.value)}
                        className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium transition-colors ${
                          seconds === d.value
                            ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                            : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                        }`}
                      >
                        {d.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Frame Rate */}
                <div className="space-y-2">
                  <span className="uppercase tracking-wider text-white/40 font-semibold text-xs">Frame Rate</span>
                  <div className="flex gap-2">
                    {FPS_PRESETS.map((f) => (
                      <button
                        key={f.value}
                        onClick={() => setFps(f.value)}
                        className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium transition-colors ${
                          fps === f.value
                            ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                            : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                        }`}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Resolution: Auto(Preset) vs Override tier */}
                <div className="space-y-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="uppercase tracking-wider text-white/40 font-semibold">Resolution</span>
                    {effectiveDims && (
                      <span className="text-purple-400/60 font-mono text-[10px]">
                        {effectiveDims.width}x{effectiveDims.height}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-1.5 mb-1.5">
                    <button
                      onClick={() => { setVidResolutionMode('auto'); setCustomResolution('auto') }}
                      className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium transition-colors ${
                        vidResolutionMode === 'auto'
                          ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                          : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                      }`}
                    >
                      Auto (Preset)
                    </button>
                    <button
                      onClick={() => setVidResolutionMode('override')}
                      className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-medium transition-colors ${
                        vidResolutionMode === 'override'
                          ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                          : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                      }`}
                    >
                      Override
                    </button>
                  </div>
                  {vidResolutionMode === 'override' && (
                    <div className="grid grid-cols-3 gap-1.5">
                      {availableResolutions.map((r) => {
                        const isSelected = customResolution === r.id
                        const isCurrentPreset = r.id === mappedPreset
                        return (
                          <button
                            key={r.id}
                            onClick={() => setCustomResolution(r.id)}
                            title={`${r.width}x${r.height}${isCurrentPreset ? ' (current preset default)' : ''}`}
                            className={`relative py-1.5 px-2 rounded-lg text-xs font-medium transition-colors ${
                              isSelected
                                ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                                : isCurrentPreset
                                  ? 'bg-white/8 text-white/80 border border-white/20 ring-1 ring-purple-500/25'
                                  : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                            }`}
                          >
                            <div className="font-mono text-[10px]">{r.width}x{r.height}</div>
                            <div className="text-[9px] text-white/40 capitalize">{r.id}</div>
                            {isCurrentPreset && !isSelected && (
                              <div className="absolute -top-1 -right-1 w-1.5 h-1.5 bg-purple-400/60 rounded-full" />
                            )}
                          </button>
                        )
                      })}
                    </div>
                  )}
                  <p className="text-[10px] text-white/30 leading-relaxed">
                    Override resolution to test what works best on your GPU. Lower = faster, less VRAM.
                  </p>
                </div>

                {/* Steps */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="uppercase tracking-wider text-white/40 font-semibold">Steps</span>
                    <span className="text-white/60">{customSteps}</span>
                  </div>
                  <input
                    type="range"
                    min={10}
                    max={50}
                    value={customSteps}
                    onChange={(e) => setCustomSteps(Number(e.target.value))}
                    className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                  />
                </div>

                {/* CFG Scale */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="uppercase tracking-wider text-white/40 font-semibold">CFG Scale</span>
                    <span className="text-white/60">{customCfg.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={15}
                    step={0.5}
                    value={customCfg}
                    onChange={(e) => setCustomCfg(Number(e.target.value))}
                    className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                  />
                </div>

                {/* Creativity / Denoise Strength */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="uppercase tracking-wider text-white/40 font-semibold">Creativity</span>
                    <span className="text-white/60">{customDenoise.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between text-[10px] text-white/30 mb-1">
                    <span>More Faithful</span>
                    <span>More Creative</span>
                  </div>
                  <input
                    type="range"
                    min={0.1}
                    max={1.0}
                    step={0.05}
                    value={customDenoise}
                    onChange={(e) => setCustomDenoise(Number(e.target.value))}
                    className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                  />
                </div>

                {/* Custom Negative Prompt */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                    <span className="text-sm text-white/80">Custom Negative Prompt</span>
                    <button
                      onClick={() => setShowNegativePrompt(!showNegativePrompt)}
                      className={`w-10 h-5 rounded-full transition-colors relative ${showNegativePrompt ? 'bg-purple-500' : 'bg-white/20'}`}
                    >
                      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${showNegativePrompt ? 'translate-x-5' : 'translate-x-0.5'}`} />
                    </button>
                  </div>
                  {showNegativePrompt && (
                    <div className="space-y-2">
                      <textarea
                        value={customNegativePrompt}
                        onChange={(e) => setCustomNegativePrompt(e.target.value)}
                        placeholder={presetDefaults.negativePrompt || 'text, watermark, logo, low quality, blurry, flicker, jitter, deformed'}
                        className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm text-white focus:border-purple-500/50 focus:outline-none resize-none h-20"
                      />
                      <p className="text-[10px] text-white/40">
                        Leave empty to use model default. Separate terms with commas.
                      </p>
                    </div>
                  )}
                </div>

                {/* Lock Seed */}
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                  <span className="text-sm text-white/80">Lock Seed</span>
                  <button
                    onClick={() => {
                      if (!seedLock) setCustomSeed(Math.floor(Math.random() * 2147483647))
                      setSeedLock(!seedLock)
                    }}
                    className={`w-10 h-5 rounded-full transition-colors relative ${seedLock ? 'bg-purple-500' : 'bg-white/20'}`}
                  >
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${seedLock ? 'translate-x-5' : 'translate-x-0.5'}`} />
                  </button>
                </div>
                {seedLock && (
                  <input
                    type="number"
                    value={customSeed}
                    onChange={(e) => setCustomSeed(Number(e.target.value))}
                    className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:border-purple-500/50 focus:outline-none"
                    placeholder="Seed value"
                  />
                )}

                {/* Final Output Summary */}
                <div className="p-3 rounded-xl bg-white/[0.03] border border-white/10">
                  <div className="uppercase tracking-wider text-white/40 font-semibold text-xs mb-2">Final Output</div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <div className="flex justify-between">
                      <span className="text-white/40">Resolution</span>
                      <span className="text-white/70 font-mono">
                        {effectiveDims ? `${effectiveDims.width}x${effectiveDims.height}` : '\u2014'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/40">Aspect</span>
                      <span className="text-white/70 font-mono">{aspectRatio}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/40">Frames</span>
                      <span className="text-white/70 font-mono">{presetDefaults?.frames ?? '\u2014'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-white/40">FPS</span>
                      <span className="text-white/70 font-mono">{presetDefaults?.fps ?? '\u2014'}</span>
                    </div>
                    <div className="flex justify-between col-span-2">
                      <span className="text-white/40">Duration</span>
                      <span className="text-white/70 font-mono">
                        {actualDuration ? `~${actualDuration}s` : '\u2014'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div className="p-4 rounded-xl bg-purple-900/10 border border-purple-500/20 text-xs text-purple-200/70 leading-relaxed">
              <span className="font-bold text-purple-400 block mb-1">PRO TIP</span>
              Enable Advanced Controls to fine-tune generation parameters. Use Lock Seed to regenerate with the same composition.
            </div>
          </div>
        </div>
      )}

      {/* Floating Advanced Settings Toggle Button */}
      <button
        className={`absolute top-6 right-6 z-20 p-3 rounded-full border shadow-lg transition-all ${
          showAdvancedSettings
            ? 'bg-purple-500 text-white border-purple-400'
            : 'bg-black/80 hover:bg-black border-white/20 text-white/70 hover:text-white backdrop-blur-sm'
        }`}
        type="button"
        onClick={() => setShowAdvancedSettings(!showAdvancedSettings)}
        title="Advanced Parameters"
      >
        <Sliders size={20} />
      </button>

      {/* Grid Gallery */}
      <div className="flex-1 overflow-y-auto px-4 pb-48 pt-8 scrollbar-hide">
        <div className="max-w-[1600px] mx-auto grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 content-start">
          {/* Scroll anchor */}
          <div ref={gridStartRef} className="col-span-full h-1" />

          {/* Empty hint */}
          {items.length === 0 && !isGenerating ? (
            <div className="col-span-full rounded-2xl border border-white/10 bg-white/5 p-8 text-center">
              <Film size={48} className="mx-auto mb-4 text-purple-400/50" />
              <div className="text-lg font-semibold text-white/90 mb-2">Your video gallery is empty</div>
              <div className="text-sm text-white/45 mb-4">
                Upload an image and describe the motion you want to see, or just describe a scene.
              </div>
              <button
                onClick={() => referenceInputRef.current?.click()}
                className="px-4 py-2 bg-purple-500/20 text-purple-200 rounded-xl border border-purple-500/30 hover:bg-purple-500/30 transition-colors"
              >
                <span className="inline-flex items-center gap-2">
                  <Upload size={16} />
                  Upload Source Image
                </span>
              </button>
            </div>
          ) : null}

          {/* Video items (including processing placeholders) */}
          {items.map((item) => (
            <div
              key={item.id}
              onClick={() => item.status === 'done' && setSelectedVideo(item)}
              className={`relative group rounded-2xl overflow-hidden bg-white/5 border border-white/10 transition-colors aspect-video ${
                item.status === 'done' ? 'hover:border-purple-500/30 cursor-pointer' : ''
              }`}
            >
              {/* Thumbnail/Video content - show based on status */}
              {item.status === 'done' && item.videoUrl ? (
                // Completed video
                isAnimatedImage(item.videoUrl) ? (
                  <img
                    src={item.videoUrl}
                    alt="Generated animation"
                    className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
                  />
                ) : (
                  <video
                    src={item.videoUrl}
                    poster={item.posterUrl}
                    muted
                    loop
                    playsInline
                    preload="metadata"
                    className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
                    onMouseEnter={(e) => e.currentTarget.play()}
                    onMouseLeave={(e) => {
                      e.currentTarget.pause()
                      e.currentTarget.currentTime = 0
                    }}
                  />
                )
              ) : (
                // Processing or Failed - show thumbnail placeholder
                <div className="absolute inset-0 w-full h-full">
                  {(item.posterUrl || item.sourceImageUrl) ? (
                    <img
                      src={item.posterUrl || item.sourceImageUrl}
                      alt="Generating..."
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full bg-gradient-to-br from-purple-900/30 to-black" />
                  )}
                </div>
              )}

              {/* Processing overlay - "Generating video..." */}
              {item.status === 'processing' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/50 backdrop-blur-sm">
                  <Loader2 size={32} className="text-purple-400 animate-spin mb-3" />
                  <div className="text-white/90 text-sm font-medium">Generating video...</div>
                  {typeof item.progress === 'number' && (
                    <div className="mt-2 px-3 py-1 rounded-full bg-black/60 border border-white/10 text-white/90 text-xs">
                      {Math.round(item.progress)}%
                    </div>
                  )}
                </div>
              )}

              {/* Failed overlay */}
              {item.status === 'failed' && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/60 backdrop-blur-sm">
                  <X size={32} className="text-red-400 mb-2" />
                  <div className="text-red-400 text-sm font-medium">Generation failed</div>
                  <div className="text-white/50 text-xs mt-1 px-4 text-center line-clamp-2">
                    {item.error || 'Unknown error'}
                  </div>
                  <button
                    className="mt-3 px-4 py-1.5 rounded-full bg-white/10 hover:bg-white/20 text-white text-xs font-medium transition-colors"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(item, e)
                    }}
                  >
                    Remove
                  </button>
                </div>
              )}

              {/* Play indicator (only for completed videos) */}
              {item.status === 'done' && (
                <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                  <div className="p-3 bg-black/50 rounded-full backdrop-blur-sm">
                    <Play size={24} className="text-white" fill="white" />
                  </div>
                </div>
              )}

              {/* Card overlay (only for completed videos) */}
              {item.status === 'done' && (
                <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex flex-col justify-end p-4">
                  <div className="flex gap-2 justify-end transform translate-y-4 group-hover:translate-y-0 transition-transform duration-300">
                    <button
                      className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-full text-white transition-colors"
                      type="button"
                      title="Copy prompt"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleCopyPrompt(item.finalPrompt || item.prompt)
                      }}
                    >
                      <Copy size={16} />
                    </button>
                    <button
                      className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-full text-white transition-colors"
                      type="button"
                      title="Download"
                      onClick={(e) => {
                        e.stopPropagation()
                        if (item.videoUrl) handleDownload(item.videoUrl)
                      }}
                    >
                      <Download size={16} />
                    </button>
                    <button
                      className="bg-red-500/20 backdrop-blur-md hover:bg-red-500/40 p-2 rounded-full text-red-400 hover:text-red-300 transition-colors"
                      type="button"
                      title="Delete"
                      onClick={(e) => handleDelete(item, e)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>

                  <div className="mt-3 text-xs text-white/80 line-clamp-2">{item.finalPrompt || item.prompt}</div>
                  <div className="flex items-center gap-2 mt-1 text-[10px] text-white/50">
                    <Clock size={10} />
                    {item.seconds}s @ {item.fps}fps
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Floating prompt bar */}
      <div className="absolute bottom-0 left-0 right-0 z-30 p-6 flex justify-center items-end bg-gradient-to-t from-black via-black/90 to-transparent h-48 pointer-events-none">
        <div className="w-full max-w-2xl relative pointer-events-auto">
          {/* Settings Panel (slides in from bottom) */}
          {showSettingsPanel && (
            <div className="absolute bottom-[110%] left-0 right-0 z-40 bg-black/95 border border-white/10 rounded-2xl p-5 shadow-2xl backdrop-blur-xl mb-2">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Sliders size={16} className="text-purple-400" />
                  Video Settings
                </h3>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="p-1.5 rounded-lg hover:bg-white/10 text-white/50 hover:text-purple-400 transition-colors"
                    onClick={resetVideoSettings}
                    title="Reset to model defaults"
                  >
                    <RefreshCw size={14} />
                  </button>
                  <button
                    type="button"
                    className="p-1.5 rounded-lg hover:bg-white/10 text-white/50 hover:text-white transition-colors"
                    onClick={() => setShowSettingsPanel(false)}
                  >
                    <X size={16} />
                  </button>
                </div>
              </div>

              {/* Aspect Ratio */}
              <div className="mb-4">
                <div className="flex justify-between items-center text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2">
                  <span>Aspect Ratio</span>
                  {detectedModelType && (
                    <span className="text-purple-400/60 normal-case font-normal">
                      {compatibleAspectRatios.length} available for {detectedModelType.toUpperCase()}
                    </span>
                  )}
                </div>
                <div className="flex gap-2 flex-wrap">
                  {compatibleAspectRatios.map((r) => (
                    <button
                      key={r.id}
                      onClick={() => setAspectRatio(r.id)}
                      className={`p-2 rounded-lg hover:bg-white/5 transition-colors group flex flex-col items-center gap-1 ${
                        aspectRatio === r.id ? 'bg-white/5 ring-1 ring-purple-500/50' : ''
                      }`}
                      title={r.label}
                    >
                      <div
                        className={`border-2 ${
                          aspectRatio === r.id ? 'border-purple-400' : 'border-white/30 group-hover:border-white/50'
                        } rounded-[2px]`}
                        style={{ width: r.previewW, height: r.previewH }}
                      />
                      <span className={`text-[10px] ${aspectRatio === r.id ? 'text-purple-300' : 'text-white/50'}`}>
                        {r.id}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Quality Preset */}
              <div className="mb-4">
                <label className="text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2 block">
                  Quality Preset
                </label>
                <div className="grid grid-cols-4 gap-2">
                  {QUALITY_PRESETS.map((q) => (
                    <button
                      key={q.id}
                      onClick={() => setQualityPreset(q.id)}
                      title={q.description}
                      className={`py-2 px-2 rounded-lg text-sm font-medium transition-colors ${
                        qualityPreset === q.id
                          ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                          : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                      }`}
                    >
                      <div className="text-xs font-bold">{q.label}</div>
                      <div className="text-[9px] text-white/40 mt-0.5">{q.short}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Motion Strength (model-aware: disabled for SVD) */}
              <div className={`mb-4 ${!isMotionSupported ? 'opacity-50' : ''}`}>
                <div className="flex justify-between items-center text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2">
                  <span>Motion Strength</span>
                  {!isMotionSupported && detectedModelType && (
                    <span className="text-yellow-500/60 normal-case font-normal text-[10px]">
                      Not supported by {detectedModelType.toUpperCase()}
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  {MOTION_PRESETS.map((m) => (
                    <button
                      key={m.value}
                      onClick={() => isMotionSupported && setMotion(m.value)}
                      disabled={!isMotionSupported}
                      className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                        motion === m.value
                          ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                          : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                      } ${!isMotionSupported ? 'cursor-not-allowed' : ''}`}
                    >
                      <div>{m.label}</div>
                      <div className="text-[10px] text-white/40 mt-0.5">{m.description}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="p-3 rounded-xl bg-purple-900/10 border border-purple-500/20 text-xs text-purple-200/70 leading-relaxed">
                <span className="font-bold text-purple-400 block mb-1">PRO TIP</span>
                Start with shorter durations and lower FPS for faster generation. Increase for smoother, longer videos.
              </div>
            </div>
          )}

          {/* Reference Image Preview Panel */}
          {referenceUrl && (
            <div className="absolute bottom-[110%] left-0 right-0 bg-black/95 border border-white/10 rounded-2xl p-4 shadow-2xl mb-2 backdrop-blur-xl">
              <div className="flex items-center gap-4">
                <img
                  src={referenceUrl}
                  className="h-20 w-20 rounded-xl object-cover border border-white/20 shadow-lg"
                  alt="Source"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-sm font-semibold text-white flex items-center gap-2">
                      <Image size={14} className="text-purple-400" />
                      Source Image Ready
                    </div>
                    <button
                      type="button"
                      className="p-1.5 rounded-lg bg-white/5 hover:bg-red-500/20 border border-white/10 hover:border-red-500/30 text-white/50 hover:text-red-400 transition-colors"
                      onClick={() => setReferenceUrl(null)}
                      title="Remove source image"
                    >
                      <X size={14} />
                    </button>
                  </div>
                  <div className="text-xs text-white/50 leading-relaxed">
                    Describe the motion you want to apply to this image. Examples: "slow zoom out", "gentle parallax", "camera pan left"
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Settings panel toggle area */}
          {showSettingsPanel && (
            <div
              className="fixed inset-0 z-30"
              onClick={() => setShowSettingsPanel(false)}
            />
          )}

          {/* Main input bar */}
          <div className="group relative">
            <div
              className={`absolute -inset-0.5 bg-gradient-to-r from-purple-500/20 to-blue-500/20 rounded-full opacity-0 transition duration-500 group-hover:opacity-100 blur ${
                isGenerating ? 'opacity-100 animate-pulse' : ''
              }`}
            ></div>

            <div className="relative bg-black border border-white/10 rounded-[32px] p-2 pr-2 flex items-center shadow-2xl transition-all focus-within:border-purple-500/30">
              {/* Upload button */}
              <button
                className={`p-3 rounded-full transition-colors ${
                  isUploadingReference
                    ? 'text-purple-400 animate-pulse'
                    : referenceUrl
                    ? 'text-purple-400 bg-purple-500/10'
                    : 'text-white/50 hover:text-white hover:bg-white/5'
                }`}
                type="button"
                title="Upload source image"
                onClick={() => referenceInputRef.current?.click()}
                disabled={isUploadingReference}
              >
                {isUploadingReference ? <Loader2 size={20} className="animate-spin" /> : <Upload size={20} />}
              </button>

              <input
                ref={referenceInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) handleUploadReference(file)
                  e.target.value = ''
                }}
              />

              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => (e.key === 'Enter' ? void handleGenerate() : undefined)}
                placeholder={referenceUrl ? "Describe the motion... (slow drift, parallax, zoom)" : "Describe a scene to animate..."}
                className="flex-1 bg-transparent text-white placeholder-white/35 outline-none px-2 h-12 text-lg"
              />

              <div className="flex items-center gap-2 pl-2">
                {/* Settings button */}
                <button
                  onClick={() => setShowSettingsPanel((v) => !v)}
                  className={`p-2 rounded-full transition-colors ${
                    showSettingsPanel ? 'text-purple-400 bg-purple-500/10' : 'text-white/50 hover:text-white hover:bg-white/5'
                  }`}
                  type="button"
                  title="Video settings"
                >
                  <Settings2 size={20} />
                </button>

                {/* Quick duration indicator */}
                <div className="px-2 py-1 rounded-lg bg-white/5 text-[11px] text-white/50 font-mono">
                  {seconds}s
                </div>

                {/* Generate button */}
                <button
                  onClick={() => void handleGenerate()}
                  disabled={(!prompt.trim() && !referenceUrl) || isGenerating}
                  className={`ml-1 h-10 px-6 rounded-full font-semibold text-sm transition-all flex items-center gap-2 ${
                    (prompt.trim() || referenceUrl) && !isGenerating
                      ? 'bg-gradient-to-r from-purple-500 to-blue-500 text-white hover:opacity-90 hover:scale-[1.02]'
                      : 'bg-white/10 text-white/40 cursor-not-allowed'
                  }`}
                  type="button"
                >
                  {isGenerating ? (
                    <span className="animate-pulse flex items-center gap-2">
                      <Loader2 size={16} className="animate-spin" />
                      Creating...
                    </span>
                  ) : (
                    <>
                      <Film size={16} />
                      Animate
                    </>
                  )}
                </button>
              </div>
            </div>

            <div className="mt-2 text-[11px] text-white/35 px-2 flex items-center gap-2">
              <span>Using</span>
              <span className="text-white/55 font-semibold">{props.providerVideo}</span>
              {props.modelVideo ? (
                <>
                  <span>·</span>
                  <span className="text-white/55 font-semibold truncate max-w-[200px]">{props.modelVideo}</span>
                </>
              ) : null}
              <span>·</span>
              <span className="text-white/55">{aspectRatio}</span>
              <span>·</span>
              {effectiveDims && <><span className="text-white/55 font-mono">{effectiveDims.width}x{effectiveDims.height}</span><span>·</span></>}
              <span>{qualityPreset} · {actualDuration ? `~${actualDuration}s` : `${seconds}s`} @ {fps}fps · {motion} motion</span>
            </div>
          </div>
        </div>
      </div>

      {/* Immersive Lightbox - Clean, Video-first Design */}
      {selectedVideo && (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-black animate-in fade-in duration-200"
          onClick={() => { setSelectedVideo(null); setShowDetails(false); setShowSourceImage(false); }}
        >
          {/* Floating Controls - Top Right */}
          <div className="absolute top-4 right-4 z-50 flex items-center gap-2">
            {selectedVideo.sourceImageUrl && (
              <button
                className={`p-2.5 rounded-full transition-all ${showSourceImage ? 'bg-white text-black' : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'}`}
                onClick={(e) => { e.stopPropagation(); setShowSourceImage(!showSourceImage); }}
                type="button"
                title="View source image"
              >
                <Image size={18} />
              </button>
            )}
            <button
              className={`p-2.5 rounded-full transition-all ${showDetails ? 'bg-white text-black' : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'}`}
              onClick={(e) => { e.stopPropagation(); setShowDetails(!showDetails); }}
              type="button"
              title="Toggle details"
            >
              <Info size={18} />
            </button>
            <button
              className="p-2.5 bg-white/10 text-white/70 hover:bg-white/20 hover:text-white rounded-full transition-all"
              onClick={(e) => {
                e.stopPropagation()
                // Use native fullscreen API - find the media element and fullscreen it
                const mediaEl = document.querySelector('[data-lightbox-media]') as HTMLElement
                if (mediaEl?.requestFullscreen) {
                  mediaEl.requestFullscreen().catch(() => {})
                }
              }}
              type="button"
              title="View full size"
            >
              <Maximize2 size={18} />
            </button>
            <button
              className="p-2.5 bg-white/10 text-white/70 hover:bg-white/20 hover:text-white rounded-full transition-all"
              onClick={() => { setSelectedVideo(null); setShowDetails(false); setShowSourceImage(false); }}
              type="button"
              title="Close"
            >
              <X size={18} />
            </button>
          </div>

          {/* Main Content Area */}
          <div className="flex-1 flex" onClick={(e) => e.stopPropagation()}>
            {/* Hero Video Container - LARGER, fills more space */}
            <div className="flex-1 flex items-center justify-center p-2 relative group">
              {selectedVideo.videoUrl ? (
                isAnimatedImage(selectedVideo.videoUrl) ? (
                  <img
                    src={selectedVideo.videoUrl}
                    data-lightbox-media
                    alt="Generated animation"
                    className="max-h-[calc(100vh-120px)] max-w-full object-contain rounded-lg shadow-2xl"
                  />
                ) : (
                  <video
                    src={selectedVideo.videoUrl}
                    data-lightbox-media
                    poster={selectedVideo.posterUrl}
                    controls
                    autoPlay
                    loop
                    className="max-h-[calc(100vh-120px)] max-w-full object-contain rounded-lg shadow-2xl"
                  />
                )
              ) : (
                // Fallback for items without videoUrl (shouldn't happen but safety)
                <div className="flex items-center justify-center h-64 w-full max-w-lg bg-white/5 rounded-lg">
                  <Loader2 size={32} className="text-white/50 animate-spin" />
                </div>
              )}

              {/* Chips Overlay - Fade in on hover */}
              <div className="absolute bottom-6 left-6 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                {selectedVideo.model && (
                  <span className="px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10">
                    {selectedVideo.model.split('.')[0].split('-')[0].toUpperCase()}
                  </span>
                )}
                {selectedVideo.seconds && (
                  <span className="px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10">
                    {selectedVideo.seconds}s
                  </span>
                )}
                {selectedVideo.fps && (
                  <span className="px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10">
                    {selectedVideo.fps}fps
                  </span>
                )}
                {selectedVideo.motion && (
                  <span className="px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10 capitalize">
                    {selectedVideo.motion}
                  </span>
                )}
              </div>

              {/* Grok-style Regeneration Overlay - Blur + Dots + Progress */}
              {isRegenerating && (
                <div className="absolute inset-0 z-30 flex items-center justify-center rounded-lg overflow-hidden">
                  {/* Blur + Dim background */}
                  <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />

                  {/* Dotted pattern overlay */}
                  <div
                    className="absolute inset-0 opacity-40 pointer-events-none"
                    style={{
                      backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.4) 1px, transparent 1px)',
                      backgroundSize: '24px 24px'
                    }}
                  />

                  {/* Center controls */}
                  <div className="relative z-10 flex flex-col items-center gap-4">
                    {/* Progress indicator */}
                    {typeof regenProgress === 'number' && (
                      <div className="px-5 py-2.5 rounded-full bg-black/70 border border-white/20 text-white font-medium text-lg shadow-xl">
                        {Math.round(regenProgress)}%
                      </div>
                    )}

                    {/* Cancel button */}
                    <button
                      className="px-5 py-2.5 rounded-full bg-black/70 border border-white/20 text-white/90 hover:bg-black/80 hover:text-white transition-colors font-medium shadow-xl"
                      onClick={(e) => { e.stopPropagation(); handleCancelRegeneration(); }}
                      type="button"
                    >
                      Cancel Video
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Source Image Overlay - Shows when toggled */}
            {showSourceImage && selectedVideo.sourceImageUrl && (
              <div
                className="absolute inset-0 z-40 flex items-center justify-center bg-black/90 animate-in fade-in duration-200"
                onClick={(e) => { e.stopPropagation(); setShowSourceImage(false); }}
              >
                <div className="relative" onClick={(e) => e.stopPropagation()}>
                  <img
                    src={selectedVideo.sourceImageUrl}
                    alt="Source image"
                    data-lightbox-media
                    className="max-h-[calc(100vh-80px)] max-w-[90vw] object-contain rounded-lg shadow-2xl"
                  />
                  <button
                    className="absolute top-4 right-4 p-2.5 bg-black/60 text-white/80 hover:bg-black/80 hover:text-white rounded-full transition-all"
                    onClick={() => setShowSourceImage(false)}
                    type="button"
                    title="Close"
                  >
                    <X size={18} />
                  </button>
                  <div className="absolute bottom-4 left-4 px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10">
                    Source Image
                  </div>
                </div>
              </div>
            )}

            {/* Details Panel - Slide in from right */}
            {showDetails && (
              <div className="w-80 bg-[#0a0a0a] border-l border-white/10 flex flex-col animate-in slide-in-from-right duration-200">
                <div className="p-4 border-b border-white/10">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <Film size={14} className="text-purple-400" />
                    Video Details
                  </h3>
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {/* Prompt - Only visible in details panel */}
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-2 block">Prompt</label>
                    <p className="text-sm text-white/70 leading-relaxed">{selectedVideo.finalPrompt || selectedVideo.prompt}</p>
                  </div>
                  {/* Source Image Thumbnail */}
                  {selectedVideo.sourceImageUrl && (
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-2 block">Source Image</label>
                      <img src={selectedVideo.sourceImageUrl} alt="Source" className="w-full h-24 object-cover rounded-lg border border-white/10" />
                    </div>
                  )}
                  {/* Seed */}
                  {selectedVideo.seed && (
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Seed</label>
                      <div className="text-base text-white font-mono font-bold">{selectedVideo.seed}</div>
                    </div>
                  )}
                  {/* Resolution, Aspect Ratio, Preset */}
                  {(selectedVideo.width || selectedVideo.aspectRatio || selectedVideo.preset) && (
                    <div className="grid grid-cols-3 gap-3">
                      {(selectedVideo.width && selectedVideo.height) && (
                        <div>
                          <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Resolution</label>
                          <div className="text-sm text-white/70 font-mono">{selectedVideo.width}×{selectedVideo.height}</div>
                        </div>
                      )}
                      {selectedVideo.aspectRatio && (
                        <div>
                          <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Aspect Ratio</label>
                          <div className="text-sm text-white/70 font-mono">{selectedVideo.aspectRatio}</div>
                        </div>
                      )}
                      {selectedVideo.preset && (
                        <div>
                          <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Preset</label>
                          <div className="text-sm text-white/70 font-mono capitalize">{selectedVideo.preset}</div>
                        </div>
                      )}
                    </div>
                  )}
                  {/* Duration, FPS, Motion */}
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Duration</label>
                      <div className="text-sm text-white/70 font-mono">{selectedVideo.seconds || '-'}s</div>
                    </div>
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">FPS</label>
                      <div className="text-sm text-white/70 font-mono">{selectedVideo.fps || '-'}</div>
                    </div>
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Motion</label>
                      <div className="text-sm text-white/70 font-mono capitalize">{selectedVideo.motion || '-'}</div>
                    </div>
                  </div>
                  {/* Steps, CFG, Denoise */}
                  {(selectedVideo.steps || selectedVideo.cfg || selectedVideo.denoise) && (
                    <div className="grid grid-cols-3 gap-3 pt-2 border-t border-white/5">
                      {selectedVideo.steps && (
                        <div>
                          <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Steps</label>
                          <div className="text-sm text-white/70 font-mono">{selectedVideo.steps}</div>
                        </div>
                      )}
                      {selectedVideo.cfg && (
                        <div>
                          <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">CFG</label>
                          <div className="text-sm text-white/70 font-mono">{selectedVideo.cfg}</div>
                        </div>
                      )}
                      {selectedVideo.denoise && (
                        <div>
                          <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Denoise</label>
                          <div className="text-sm text-white/70 font-mono">{selectedVideo.denoise}</div>
                        </div>
                      )}
                    </div>
                  )}
                  {/* Date & Time */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Date</label>
                      <div className="text-xs text-white/60 font-mono">{new Date(selectedVideo.createdAt).toLocaleDateString()}</div>
                    </div>
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Time</label>
                      <div className="text-xs text-white/60 font-mono">{new Date(selectedVideo.createdAt).toLocaleTimeString()}</div>
                    </div>
                  </div>
                  {/* Model */}
                  {selectedVideo.model && (
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Model</label>
                      <div className="text-xs text-white/50 font-mono break-all">{selectedVideo.model}</div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Grok-style Prompt Composer Bar */}
          <div className="bg-[#0a0a0a] border-t border-white/10 px-4 py-3" onClick={(e) => e.stopPropagation()}>
            <div className="max-w-4xl mx-auto flex items-center gap-3">

              {/* Prompt Card Container */}
              <div className="flex-1 flex items-center gap-3 bg-[#1a1a1a] rounded-2xl px-4 py-2.5 border border-white/10">
                {/* Progress indicator in prompt bar during regeneration */}
                {isRegenerating && typeof regenProgress === 'number' && (
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <div className="px-2.5 py-1 rounded-full bg-white/10 text-white/80 text-xs font-medium">
                      {Math.round(regenProgress)}%
                    </div>
                    <ChevronDown size={14} className="text-white/40" />
                  </div>
                )}

                {/* Editable Prompt Input */}
                <input
                  type="text"
                  value={lightboxPrompt}
                  onChange={(e) => setLightboxPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && lightboxPrompt.trim() && !isRegenerating) {
                      handleRegenerateInPlace()
                    }
                  }}
                  placeholder={isRegenerating ? "Generating video..." : "Edit prompt and regenerate..."}
                  className="flex-1 bg-transparent text-white/90 text-sm placeholder-white/30 outline-none min-w-0"
                  disabled={isRegenerating}
                />

                {/* Make Video Button (inside card) - Grok style */}
                <button
                  onClick={isRegenerating ? handleCancelRegeneration : handleRegenerateInPlace}
                  disabled={!lightboxPrompt.trim() && !isRegenerating}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium transition-all flex-shrink-0 ${
                    isRegenerating
                      ? 'bg-white/10 hover:bg-white/20 text-white'
                      : lightboxPrompt.trim()
                        ? 'bg-white/10 hover:bg-white/20 text-white'
                        : 'bg-white/5 text-white/30 cursor-not-allowed'
                  }`}
                  type="button"
                  title={isRegenerating ? "Cancel" : "Make video"}
                >
                  {isRegenerating ? (
                    <>Make video <ArrowUp size={14} /></>
                  ) : (
                    <>Make video <ArrowUp size={14} /></>
                  )}
                </button>
              </div>

              {/* Action Icons (outside card) */}
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  className="p-2.5 text-white/60 hover:text-white hover:bg-white/10 rounded-full transition-colors"
                  onClick={() => selectedVideo.videoUrl && handleDownload(selectedVideo.videoUrl)}
                  type="button"
                  title="Download"
                  disabled={!selectedVideo.videoUrl}
                >
                  <Download size={18} />
                </button>
                <button
                  className="p-2.5 text-white/60 hover:text-white hover:bg-white/10 rounded-full transition-colors"
                  onClick={() => handleCopyPrompt(selectedVideo.finalPrompt || selectedVideo.prompt)}
                  type="button"
                  title="Copy prompt"
                >
                  <Copy size={18} />
                </button>
                <button
                  className="p-2.5 text-white/60 hover:text-red-400 hover:bg-red-500/10 rounded-full transition-colors"
                  onClick={() => {
                    if (confirm('Delete this video?')) {
                      setItems((prev) => prev.filter((x) => x.id !== selectedVideo.id))
                      setSelectedVideo(null)
                      setShowDetails(false)
                      setShowSourceImage(false)
                    }
                  }}
                  type="button"
                  title="Delete"
                >
                  <Trash2 size={18} />
                </button>
              </div>

            </div>
          </div>
        </div>
      )}
    </div>
  )
}
