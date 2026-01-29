import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { Upload, Mic, Settings2, X, Play, Pause, Download, Copy, RefreshCw, Trash2, Film, Image, ChevronDown, ChevronRight, Maximize2, Clock, Zap, Sliders, Loader2 } from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type AnimateItem = {
  id: string
  videoUrl: string
  posterUrl?: string
  createdAt: number
  prompt: string
  finalPrompt?: string
  sourceImageUrl?: string
  // Generation parameters for reproducibility
  seed?: number
  seconds?: number
  fps?: number
  motion?: string
  model?: string
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
    seed?: number
    model?: string
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
function isAnimatedImage(url: string): boolean {
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
        return Array.isArray(parsed) ? parsed : []
      }
    } catch (error) {
      console.error('Failed to load animate items from localStorage:', error)
    }
    return []
  })

  const [isGenerating, setIsGenerating] = useState(false)

  // Selection state for Lightbox (Grok-style detail view)
  const [selectedVideo, setSelectedVideo] = useState<AnimateItem | null>(null)

  // Video settings
  const [seconds, setSeconds] = useState(props.vidSeconds || 4)
  const [fps, setFps] = useState(props.vidFps || 8)
  const [motion, setMotion] = useState(props.vidMotion || 'medium')
  const [showSettingsPanel, setShowSettingsPanel] = useState(false)
  const [qualityPreset, setQualityPreset] = useState('medium')

  // Advanced Controls state
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false)
  const [advancedMode, setAdvancedMode] = useState(false)
  const [customSteps, setCustomSteps] = useState(30)
  const [customCfg, setCustomCfg] = useState(3.5)
  const [customDenoise, setCustomDenoise] = useState(0.85)
  const [seedLock, setSeedLock] = useState(false)
  const [customSeed, setCustomSeed] = useState(0)

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

  // Scroll to top when entering Animate
  useEffect(() => {
    gridStartRef.current?.scrollIntoView({ block: 'start' })
  }, [])

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

  const handleGenerate = useCallback(async () => {
    // For animate, we need either a prompt or a reference image
    const t = prompt.trim()
    if (!t && !referenceUrl) return
    if (isGenerating) return

    // Use default prompt for reference-only generation
    const effectivePrompt = t || 'animate this image with natural motion'

    setIsGenerating(true)
    setShowSettingsPanel(false)

    try {
      // Build message for animate mode
      const animateMessage = referenceUrl
        ? `animate ${referenceUrl} ${effectivePrompt}`
        : `animate ${effectivePrompt}`

      const requestBody: any = {
        message: animateMessage,
        mode: 'animate',

        // Video generation params
        vidSeconds: seconds,
        vidFps: fps,
        vidMotion: motion,
        vidModel: props.modelVideo || undefined,
        vidPreset: qualityPreset,

        // Advanced parameters (when enabled)
        ...(advancedMode && {
          vidSteps: customSteps,
          vidCfg: customCfg,
          vidDenoise: customDenoise,
          ...(seedLock && { vidSeed: customSeed }),
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

      if (!data.media?.video_url) {
        throw new Error(data.message || data.text || 'No video URL returned')
      }

      const newItem: AnimateItem = {
        id: uid(),
        videoUrl: data.media.video_url,
        posterUrl: data.media.poster_url,
        createdAt: Date.now(),
        prompt: effectivePrompt,
        finalPrompt: data.media.final_prompt,
        sourceImageUrl: referenceUrl || undefined,
        seed: data.media.seed || (seedLock ? customSeed : undefined),
        seconds,
        fps,
        motion,
        model: data.media.model || props.modelVideo,
        // Advanced parameters (if used)
        ...(advancedMode && {
          steps: customSteps,
          cfg: customCfg,
          denoise: customDenoise,
        }),
      }

      // Prepend new item (newest first)
      setItems((prev) => [newItem, ...prev])
      setPrompt('')

      // Auto-scroll to show new video
      setTimeout(() => {
        gridStartRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 100)
    } catch (err: any) {
      console.error('Video generation failed:', err)
      alert(`Generation failed: ${err.message || err}`)
    } finally {
      setIsGenerating(false)
    }
  }, [prompt, referenceUrl, isGenerating, seconds, fps, motion, qualityPreset, props, authKey, advancedMode, customSteps, customCfg, customDenoise, seedLock, customSeed])

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
            <button type="button" onClick={() => setShowAdvancedSettings(false)} className="text-white/50 hover:text-white">
              <X size={16} />
            </button>
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

                {/* Denoise Strength */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="uppercase tracking-wider text-white/40 font-semibold">Denoise Strength</span>
                    <span className="text-white/60">{customDenoise.toFixed(2)}</span>
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
              </div>
            )}

            <div className="p-4 rounded-xl bg-purple-900/10 border border-purple-500/20 text-xs text-purple-200/70 leading-relaxed">
              <span className="font-bold text-purple-400 block mb-1">PRO TIP</span>
              Enable Advanced Controls to fine-tune generation parameters. Use Lock Seed to regenerate with the same composition.
            </div>
          </div>
        </div>
      )}

      {/* Settings Panel (slides in from bottom) */}
      {showSettingsPanel && (
        <div className="absolute bottom-[110%] left-1/2 -translate-x-1/2 z-40 bg-black/95 border border-white/10 rounded-2xl p-5 shadow-2xl backdrop-blur-xl w-full max-w-lg mb-2">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Sliders size={16} className="text-purple-400" />
              Video Settings
            </h3>
            <button
              type="button"
              className="p-1.5 rounded-lg hover:bg-white/10 text-white/50 hover:text-white transition-colors"
              onClick={() => setShowSettingsPanel(false)}
            >
              <X size={16} />
            </button>
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

          {/* Duration */}
          <div className="mb-4">
            <label className="text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2 block">
              Duration
            </label>
            <div className="flex gap-2">
              {DURATION_PRESETS.map((d) => (
                <button
                  key={d.value}
                  onClick={() => setSeconds(d.value)}
                  className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
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

          {/* FPS */}
          <div className="mb-4">
            <label className="text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2 block">
              Frame Rate
            </label>
            <div className="flex gap-2">
              {FPS_PRESETS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => setFps(f.value)}
                  className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
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

          {/* Motion Strength */}
          <div className="mb-4">
            <label className="text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2 block">
              Motion Strength
            </label>
            <div className="flex gap-2">
              {MOTION_PRESETS.map((m) => (
                <button
                  key={m.value}
                  onClick={() => setMotion(m.value)}
                  className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                    motion === m.value
                      ? 'bg-purple-500/30 text-purple-200 border border-purple-500/50'
                      : 'bg-white/5 text-white/70 border border-white/10 hover:bg-white/10'
                  }`}
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

          {/* Loading skeleton */}
          {isGenerating && (
            <div className="relative rounded-2xl overflow-hidden bg-white/5 border border-white/10 aspect-video animate-pulse">
              <div className="absolute inset-0 bg-gradient-to-tr from-purple-500/10 to-transparent"></div>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="flex flex-col items-center gap-3">
                  <Loader2 size={32} className="animate-spin text-purple-400" />
                  <span className="text-sm font-mono text-white/70">Generating video...</span>
                </div>
              </div>
            </div>
          )}

          {/* Video items */}
          {items.map((item) => (
            <div
              key={item.id}
              onClick={() => setSelectedVideo(item)}
              className="relative group rounded-2xl overflow-hidden bg-white/5 border border-white/10 hover:border-purple-500/30 transition-colors cursor-pointer aspect-video"
            >
              {isAnimatedImage(item.videoUrl) ? (
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
              )}

              {/* Play indicator */}
              <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                <div className="p-3 bg-black/50 rounded-full backdrop-blur-sm">
                  <Play size={24} className="text-white" fill="white" />
                </div>
              </div>

              {/* Card overlay */}
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
                      handleDownload(item.videoUrl)
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
            </div>
          ))}
        </div>
      </div>

      {/* Floating prompt bar */}
      <div className="absolute bottom-0 left-0 right-0 z-30 p-6 flex justify-center items-end bg-gradient-to-t from-black via-black/90 to-transparent h-48 pointer-events-none">
        <div className="w-full max-w-2xl relative pointer-events-auto">
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
              <span>{qualityPreset} · {seconds}s @ {fps}fps · {motion} motion</span>
            </div>
          </div>
        </div>
      </div>

      {/* Grok-style Lightbox / Detail View */}
      {selectedVideo && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/95 p-4 backdrop-blur-md animate-in fade-in duration-200"
          onClick={() => setSelectedVideo(null)}
        >
          {/* Close button */}
          <button
            className="absolute top-4 right-4 p-2 text-white/50 hover:text-white bg-white/5 rounded-full z-50"
            onClick={() => setSelectedVideo(null)}
            type="button"
            aria-label="Close"
          >
            <X size={24} />
          </button>

          <div
            className="max-w-6xl w-full max-h-[90vh] flex flex-col md:flex-row gap-0 bg-[#121212] border border-white/10 rounded-2xl overflow-hidden shadow-2xl ring-1 ring-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Left: Video Container */}
            <div className="flex-1 bg-black/50 flex items-center justify-center p-4 min-h-[400px] relative">
              {isAnimatedImage(selectedVideo.videoUrl) ? (
                <img
                  src={selectedVideo.videoUrl}
                  alt="Generated animation"
                  className="max-h-full max-w-full object-contain shadow-lg rounded-lg"
                />
              ) : (
                <video
                  src={selectedVideo.videoUrl}
                  poster={selectedVideo.posterUrl}
                  controls
                  autoPlay
                  loop
                  className="max-h-full max-w-full object-contain shadow-lg rounded-lg"
                />
              )}
            </div>

            {/* Right: Sidebar Details */}
            <div className="w-full md:w-96 flex flex-col border-l border-white/10 bg-[#161616]">
              {/* Sidebar Header */}
              <div className="p-5 border-b border-white/10 flex items-center justify-between">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Film size={14} className="text-purple-400" />
                  Video Details
                </h3>
                <span className="text-[10px] text-white/40 font-mono tracking-wide">{selectedVideo.id.slice(0, 8)}</span>
              </div>

              {/* Sidebar Content */}
              <div className="flex-1 overflow-y-auto p-5 space-y-6">
                {/* Prompt */}
                <div>
                  <label className="text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2 block">
                    Prompt
                  </label>
                  <div className="text-sm text-white/90 leading-relaxed font-light whitespace-pre-wrap selection:bg-white/20">
                    {selectedVideo.finalPrompt || selectedVideo.prompt}
                  </div>
                </div>

                {/* Source Image */}
                {selectedVideo.sourceImageUrl && (
                  <div>
                    <label className="text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2 block">
                      Source Image
                    </label>
                    <img
                      src={selectedVideo.sourceImageUrl}
                      alt="Source"
                      className="w-full h-32 object-cover rounded-lg border border-white/10"
                    />
                  </div>
                )}

                {/* Seed */}
                {selectedVideo.seed && (
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Seed
                    </label>
                    <div className="text-lg text-white font-mono font-bold tracking-wide">
                      {selectedVideo.seed}
                    </div>
                  </div>
                )}

                {/* Video Parameters */}
                <div className="grid grid-cols-3 gap-4 pt-2">
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Duration
                    </label>
                    <div className="text-sm text-white/80 font-mono">
                      {selectedVideo.seconds || '-'}s
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      FPS
                    </label>
                    <div className="text-sm text-white/80 font-mono">
                      {selectedVideo.fps || '-'}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Motion
                    </label>
                    <div className="text-sm text-white/80 font-mono capitalize">
                      {selectedVideo.motion || '-'}
                    </div>
                  </div>
                </div>

                {/* Advanced Parameters (if used) */}
                {(selectedVideo.steps || selectedVideo.cfg || selectedVideo.denoise) && (
                  <div className="grid grid-cols-3 gap-4 pt-2 border-t border-white/5">
                    {selectedVideo.steps && (
                      <div>
                        <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                          Steps
                        </label>
                        <div className="text-sm text-white/80 font-mono">
                          {selectedVideo.steps}
                        </div>
                      </div>
                    )}
                    {selectedVideo.cfg && (
                      <div>
                        <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                          CFG
                        </label>
                        <div className="text-sm text-white/80 font-mono">
                          {selectedVideo.cfg}
                        </div>
                      </div>
                    )}
                    {selectedVideo.denoise && (
                      <div>
                        <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                          Denoise
                        </label>
                        <div className="text-sm text-white/80 font-mono">
                          {selectedVideo.denoise}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Date
                    </label>
                    <div className="text-xs text-white/70 font-mono">
                      {new Date(selectedVideo.createdAt).toLocaleDateString()}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Time
                    </label>
                    <div className="text-xs text-white/70 font-mono">
                      {new Date(selectedVideo.createdAt).toLocaleTimeString()}
                    </div>
                  </div>
                </div>

                {/* Model */}
                {selectedVideo.model && (
                  <div className="pt-2">
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Model
                    </label>
                    <div className="text-xs text-white/60 font-mono truncate">
                      {selectedVideo.model}
                    </div>
                  </div>
                )}
              </div>

              {/* Sidebar Footer / Actions */}
              <div className="p-5 border-t border-white/10 bg-[#141414] flex flex-col gap-3">
                <button
                  className="w-full py-3 bg-gradient-to-r from-purple-500 to-blue-500 text-white font-bold rounded-lg hover:opacity-90 transition-opacity text-sm flex items-center justify-center gap-2"
                  onClick={() => handleDownload(selectedVideo.videoUrl)}
                  type="button"
                >
                  <Download size={16} />
                  Download Video
                </button>

                <div className="flex gap-2">
                  <button
                    className="flex-1 py-3 bg-white/5 text-white/80 font-semibold rounded-lg hover:bg-white/10 transition-colors text-sm flex items-center justify-center gap-2"
                    onClick={() => {
                      setPrompt(selectedVideo.finalPrompt || selectedVideo.prompt)
                      if (selectedVideo.sourceImageUrl) {
                        setReferenceUrl(selectedVideo.sourceImageUrl)
                      }
                      setSelectedVideo(null)
                    }}
                    type="button"
                  >
                    <RefreshCw size={16} />
                    Reuse
                  </button>

                  <button
                    className="flex-1 py-3 bg-white/5 text-white/80 font-semibold rounded-lg hover:bg-white/10 transition-colors text-sm flex items-center justify-center gap-2"
                    onClick={() => handleCopyPrompt(selectedVideo.finalPrompt || selectedVideo.prompt)}
                    type="button"
                  >
                    <Copy size={16} />
                    Copy
                  </button>

                  <button
                    className="py-3 px-4 bg-red-500/10 text-red-400 font-semibold rounded-lg hover:bg-red-500/20 transition-colors text-sm flex items-center justify-center gap-2"
                    onClick={() => {
                      if (confirm('Delete this video?')) {
                        setItems((prev) => prev.filter((x) => x.id !== selectedVideo.id))
                        setSelectedVideo(null)
                      }
                    }}
                    type="button"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
