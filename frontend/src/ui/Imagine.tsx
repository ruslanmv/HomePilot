import React, { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { Upload, Mic, Settings2, X, Play, MoreHorizontal, Wand2, Download, Copy, RefreshCw, Trash2, Gamepad2, Pause, History, Lock, Unlock, Zap, Grid2X2, Image, Sliders, ChevronRight, ChevronDown, Maximize2, Info, Film, Check, ArrowUp, Loader2 } from 'lucide-react'
import { upscaleImage } from './enhance/upscaleApi'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type AspectRatio = {
  label: string
  // Small preview box dimensions (UI only)
  previewW: number
  previewH: number
  // Suggested pixel dimensions for generation (used as defaults if provided)
  genW: number
  genH: number
}

type ImagineItem = {
  id: string
  url: string
  createdAt: number
  prompt: string
  // Generation parameters for reproducibility
  seed?: number
  width?: number
  height?: number
  steps?: number
  cfg?: number
  model?: string
}

export type ImagineParams = {
  backendUrl: string
  apiKey?: string
  // Image provider settings (from Enterprise Settings)
  providerImages: string
  baseUrlImages?: string
  modelImages?: string
  // Chat/LLM provider settings (for Game Mode and prompt refinement)
  providerChat?: string
  baseUrlChat?: string
  modelChat?: string
  // Generation controls
  imgWidth?: number
  imgHeight?: number
  imgSteps?: number
  imgCfg?: number
  imgSeed?: number
  imgPreset?: string  // "low", "med", "high", or "custom"
  nsfwMode?: boolean
  promptRefinement?: boolean
}

type ChatResponse = {
  ok?: boolean
  text?: string
  media?: {
    images?: string[]
    video_url?: string
    final_prompt?: string  // The actual refined prompt sent to ComfyUI
    // Generation parameters for reproducibility
    seed?: number
    seeds?: number[]
    width?: number
    height?: number
    steps?: number
    cfg?: number
    model?: string
    game?: {
      enabled?: boolean
      session_id?: string
      counter?: number
      base_prompt?: string
      variation_prompt?: string
      tags?: Record<string, string>
      error?: string
    }
  } | null
  message?: string
}

type GameLocks = {
  lock_world: boolean
  lock_style: boolean
  lock_subject_type: boolean
  lock_main_character: boolean
  lock_palette: boolean
  lock_time_of_day: boolean
}

type GameVariation = {
  prompt: string
  tags: Record<string, string>
  timestamp: number
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
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

async function deleteJson<T>(baseUrl: string, path: string, body: any, apiKey?: string): Promise<T> {
  const url = `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'DELETE',
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

const ASPECT_RATIOS: AspectRatio[] = [
  { label: '1:1', previewW: 24, previewH: 24, genW: 1024, genH: 1024 },
  { label: '4:3', previewW: 32, previewH: 24, genW: 1152, genH: 864 },
  { label: '3:4', previewW: 24, previewH: 32, genW: 864, genH: 1152 },
  { label: '16:9', previewW: 42, previewH: 24, genW: 1344, genH: 768 },
  { label: '9:16', previewW: 24, previewH: 42, genW: 768, genH: 1344 },
]

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

export default function ImagineView(props: ImagineParams) {
  const authKey = (props.apiKey || '').trim()
  const [prompt, setPrompt] = useState('')

  // Load items from localStorage on mount
  const [items, setItems] = useState<ImagineItem[]>(() => {
    try {
      const stored = localStorage.getItem('homepilot_imagine_items')
      if (stored) {
        const parsed = JSON.parse(stored)
        return Array.isArray(parsed) ? parsed : []
      }
    } catch (error) {
      console.error('Failed to load imagine items from localStorage:', error)
    }
    return []
  })

  const [isGenerating, setIsGenerating] = useState(false)
  const [upscalingId, setUpscalingId] = useState<string | null>(null)

  // Selection state for Lightbox (Grok-style detail view)
  const [selectedImage, setSelectedImage] = useState<ImagineItem | null>(null)
  const [showDetails, setShowDetails] = useState(false)  // Immersive mode: details hidden by default
  const [lightboxPrompt, setLightboxPrompt] = useState('')  // Editable prompt in lightbox
  const [isRegenerating, setIsRegenerating] = useState(false)  // Regenerating from lightbox

  const [aspect, setAspect] = useState<string>('1:1')
  const [showAspectPanel, setShowAspectPanel] = useState(false)

  // Number of images to generate per request (1, 2, or 4 like Grok)
  const [numImages, setNumImages] = useState<1 | 2 | 4>(1)

  // Game Mode state
  const [gameMode, setGameMode] = useState(false)
  const [gameSessionId, setGameSessionId] = useState<string | null>(null)
  const [gameStrength, setGameStrength] = useState(0.65)
  const [spicyStrength, setSpicyStrength] = useState(0.3)  // Spicy strength (only when nsfwMode + gameMode)
  const [gameLocks, setGameLocks] = useState<GameLocks>({
    lock_world: true,
    lock_style: true,
    lock_subject_type: true,
    lock_main_character: false,
    lock_palette: false,
    lock_time_of_day: false,
  })
  const [isAutoGenerating, setIsAutoGenerating] = useState(false)
  const [showGamePanel, setShowGamePanel] = useState(false)
  const [gameVariations, setGameVariations] = useState<GameVariation[]>([])
  const [showVariationHistory, setShowVariationHistory] = useState(false)
  const autoGenerateRef = useRef<boolean>(false)

  // Advanced Settings Panel state
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false)
  const [advancedMode, setAdvancedMode] = useState(false)
  const [customSteps, setCustomSteps] = useState(30)
  const [customCfg, setCustomCfg] = useState(5.5)
  const [customDenoise, setCustomDenoise] = useState(0.55)
  const [seedLock, setSeedLock] = useState(false)
  const [customSeed, setCustomSeed] = useState(0)
  const [useControlNet, setUseControlNet] = useState(false)
  const [cnStrength, setCnStrength] = useState(1.0)

  // Reference Image state (for img2img similar generation)
  const referenceInputRef = useRef<HTMLInputElement>(null)
  const [referenceUrl, setReferenceUrl] = useState<string | null>(null)
  const [referenceStrength, setReferenceStrength] = useState(0.35) // 0=very similar, 1=more creative
  const [isUploadingReference, setIsUploadingReference] = useState(false)

  // Ref for auto-scrolling to top when new images are added (Grok-style)
  const gridStartRef = useRef<HTMLDivElement>(null)

  // Save items to localStorage whenever they change
  useEffect(() => {
    try {
      localStorage.setItem('homepilot_imagine_items', JSON.stringify(items))
    } catch (error) {
      console.error('Failed to save imagine items to localStorage:', error)
    }
  }, [items])

  // Scroll to top when entering Imagine to avoid "empty space above" if previously scrolled
  useEffect(() => {
    gridStartRef.current?.scrollIntoView({ block: 'start' })
  }, [])

  // Initialize lightbox prompt when selecting an image
  useEffect(() => {
    if (selectedImage) {
      setLightboxPrompt(selectedImage.prompt)
    }
  }, [selectedImage])

  const aspectObj = useMemo(() => {
    return ASPECT_RATIOS.find((a) => a.label === aspect) || ASPECT_RATIOS[0]
  }, [aspect])

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
      // Backend typically returns { url: "http://.../files/..." }
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

  const handleGenerate = useCallback(async (overridePrompt?: string) => {
    const t = (overridePrompt || prompt).trim()
    // Allow empty prompt when reference image is uploaded
    if (!t && !referenceUrl) return
    if (isGenerating) return

    // Use default prompt for reference-only generation
    const effectivePrompt = t || 'similar image'

    setIsGenerating(true)
    setShowAspectPanel(false)
    setShowGamePanel(false)
    setShowAdvancedSettings(false)

    try {
      // IMPORTANT: Send aspect ratio to backend instead of hardcoded dimensions.
      // The backend's Dynamic Preset System will calculate correct dimensions
      // based on the model architecture (SD1.5 vs SDXL vs Flux).
      // Only send explicit width/height if user set them in settings.
      const hasExplicitDimensions = props.imgWidth && props.imgWidth > 0 && props.imgHeight && props.imgHeight > 0

      // Map 'comfyui' provider to 'ollama' for prompt refinement
      // ComfyUI is used automatically for actual image generation
      const llmProvider = props.providerImages === 'comfyui' ? 'ollama' : props.providerImages

      // Determine the LLM settings for prompt refinement and Game Mode
      // Use chat provider settings if available, otherwise fall back to ollama defaults
      const chatProvider = props.providerChat || 'ollama'
      const chatBaseUrl = props.baseUrlChat || 'http://localhost:11434'
      const chatModel = props.modelChat || 'llama3:8b'

      const requestBody: any = {
        message: /^\s*(imagine|generate|create|draw|make)\b/i.test(effectivePrompt) ? effectivePrompt : `imagine ${effectivePrompt}`,
        mode: 'imagine',

        // Provider override fields for image generation
        provider: llmProvider,
        provider_base_url: props.baseUrlImages || undefined,
        provider_model: props.modelImages || undefined,

        // LLM settings for prompt refinement and Game Mode variation generation
        // These are separate from the image provider settings
        ollama_base_url: chatProvider === 'ollama' ? chatBaseUrl : undefined,
        ollama_model: chatProvider === 'ollama' ? chatModel : undefined,
        llm_base_url: chatProvider !== 'ollama' ? chatBaseUrl : undefined,
        llm_model: chatProvider !== 'ollama' ? chatModel : undefined,

        // Image generation params
        // Send aspect ratio for backend to calculate model-appropriate dimensions
        // Only send explicit width/height if user set them in settings (not from aspect picker)
        imgAspectRatio: aspect,  // e.g., "16:9", "1:1", etc.
        imgWidth: hasExplicitDimensions ? props.imgWidth : undefined,
        imgHeight: hasExplicitDimensions ? props.imgHeight : undefined,
        // Use custom settings if advanced mode is enabled, otherwise use props
        imgSteps: advancedMode ? customSteps : props.imgSteps,
        imgCfg: advancedMode ? customCfg : props.imgCfg,
        imgSeed: advancedMode && seedLock ? customSeed : props.imgSeed,
        imgDenoise: advancedMode ? customDenoise : undefined,
        imgPreset: props.imgPreset || 'med',  // Send preset for architecture-aware settings
        imgModel: props.modelImages,
        nsfwMode: props.nsfwMode,
        promptRefinement: props.promptRefinement ?? true,
        imgBatchSize: numImages,
        // ControlNet settings
        useControlNet: advancedMode ? useControlNet : undefined,
        cnStrength: advancedMode && useControlNet ? cnStrength : undefined,
        // Reference image for img2img (similar image generation)
        imgReference: referenceUrl ?? undefined,
        imgRefStrength: referenceUrl ? referenceStrength : undefined,
      }

      // Add Game Mode parameters if enabled
      if (gameMode) {
        requestBody.gameMode = true
        requestBody.gameSessionId = gameSessionId
        requestBody.gameStrength = gameStrength
        requestBody.gameLocks = gameLocks
        // Only send spicyStrength if nsfwMode is also enabled
        if (props.nsfwMode) {
          requestBody.gameSpicyStrength = spicyStrength
        }
      }

      const data = await postJson<ChatResponse>(
        props.backendUrl,
        '/chat',
        requestBody,
        authKey
      )

      const urls = data?.media?.images || []
      if (urls.length === 0) {
        throw new Error(data?.message || data?.text || 'No images returned by backend.')
      }

      // Handle Game Mode response
      if (gameMode && data?.media?.game) {
        const gameData = data.media.game
        if (gameData.session_id) {
          setGameSessionId(gameData.session_id)
        }
        if (gameData.variation_prompt) {
          setGameVariations((prev) => [
            {
              prompt: gameData.variation_prompt!,
              tags: gameData.tags || {},
              timestamp: Date.now(),
            },
            ...prev,
          ].slice(0, 50))
        }
      }

      const now = Date.now()
      // Use the actual refined/final prompt that was sent to the image model
      // This is the real prompt that generated the image, so users can reproduce it
      // Priority: final_prompt (refined) > variation_prompt (game mode) > original user input
      const finalPrompt = data?.media?.final_prompt
        || (gameMode && data?.media?.game?.variation_prompt)
        || t

      // Extract generation parameters for reproducibility
      const seeds = data?.media?.seeds || (data?.media?.seed ? [data.media.seed] : [])
      const genWidth = data?.media?.width
      const genHeight = data?.media?.height
      const genSteps = data?.media?.steps
      const genCfg = data?.media?.cfg
      const genModel = data?.media?.model

      const newItems: ImagineItem[] = urls.map((u, idx) => ({
        id: uid(),
        url: u,
        createdAt: now,
        prompt: finalPrompt,
        seed: seeds[idx] ?? seeds[0],  // Use corresponding seed or fall back to first
        width: genWidth,
        height: genHeight,
        steps: genSteps,
        cfg: genCfg,
        model: genModel,
      }))

      // Prepend new images at the beginning (Grok-style: new images appear at top-left)
      // Fill order: top-left → right → next row (row-major order)
      // Keep only the first 100 items to prevent localStorage overflow
      setItems((prev) => [...newItems, ...prev].slice(0, 100))

      // Auto-scroll to top to show new images
      setTimeout(() => {
        gridStartRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 100)

      // Only clear prompt if not in auto-generate mode
      if (!autoGenerateRef.current) {
        setPrompt('')
      }
    } catch (err: any) {
      alert(`Generation failed: ${err.message || err}`)
      // Stop auto-generation on error
      autoGenerateRef.current = false
      setIsAutoGenerating(false)
    } finally {
      setIsGenerating(false)
    }
  }, [prompt, isGenerating, aspect, props, authKey, gameMode, gameSessionId, gameStrength, spicyStrength, gameLocks, numImages, advancedMode, customSteps, customCfg, customDenoise, seedLock, customSeed, useControlNet, cnStrength, referenceUrl, referenceStrength])

  // Auto-generation loop for Game Mode
  useEffect(() => {
    if (isAutoGenerating && gameMode && !isGenerating && prompt.trim()) {
      autoGenerateRef.current = true
      const timeoutId = setTimeout(() => {
        if (autoGenerateRef.current) {
          handleGenerate(prompt)
        }
      }, 500) // Small delay between generations
      return () => clearTimeout(timeoutId)
    }
  }, [isAutoGenerating, gameMode, isGenerating, prompt, handleGenerate])

  const toggleAutoGenerate = () => {
    if (isAutoGenerating) {
      autoGenerateRef.current = false
      setIsAutoGenerating(false)
    } else {
      if (!prompt.trim()) {
        alert('Please enter a base prompt first')
        return
      }
      autoGenerateRef.current = true
      setIsAutoGenerating(true)
      handleGenerate(prompt)
    }
  }

  const resetGameSession = () => {
    setGameSessionId(null)
    setGameVariations([])
  }

  const handleDelete = async (item: ImagineItem, e?: React.MouseEvent) => {
    if (e) {
      e.stopPropagation()
    }

    // Confirm deletion
    if (!confirm('Delete this image? This will remove it from your gallery and database.')) {
      return
    }

    try {
      // Delete from backend database
      await deleteJson(
        props.backendUrl,
        '/media/image',
        { image_url: item.url },
        authKey
      )

      // Remove from local state (and localStorage via useEffect)
      setItems((prev) => prev.filter((i) => i.id !== item.id))

      // Close lightbox if this image was selected
      if (selectedImage?.id === item.id) {
        setSelectedImage(null)
      }
    } catch (err: any) {
      alert(`Failed to delete image: ${err.message || err}`)
    }
  }

  const handleUpscale = async (item: ImagineItem, e?: React.MouseEvent) => {
    if (e) {
      e.stopPropagation()
    }

    if (upscalingId) {
      alert('Already upscaling an image. Please wait.')
      return
    }

    try {
      setUpscalingId(item.id)

      const result = await upscaleImage({
        backendUrl: props.backendUrl,
        apiKey: authKey,
        imageUrl: item.url,
        scale: 2,
        model: '4x-UltraSharp.pth',
      })

      const upscaledUrl = result?.media?.images?.[0]
      if (upscaledUrl) {
        // Add upscaled image to gallery (non-destructive - keeps original)
        const newItem: ImagineItem = {
          id: `upscale-${Date.now()}-${Math.random().toString(16).slice(2)}`,
          url: upscaledUrl,
          createdAt: Date.now(),
          prompt: `[Upscaled 2x] ${item.prompt}`,
          seed: item.seed,
          width: (item.width ?? 1024) * 2,
          height: (item.height ?? 1024) * 2,
          steps: item.steps,
          cfg: item.cfg,
          model: item.model,
        }
        setItems((prev) => [newItem, ...prev])
      } else {
        alert('Upscale completed but no image was returned.')
      }
    } catch (err: any) {
      alert(`Failed to upscale image: ${err.message || err}`)
    } finally {
      setUpscalingId(null)
    }
  }

  return (
    <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col relative">
      {/* Header overlay */}
      <div className="absolute top-0 left-0 right-0 z-20 flex justify-between items-center px-6 py-4 bg-gradient-to-b from-black/80 to-transparent pointer-events-none">
        <div className="pointer-events-auto flex items-center gap-3">
          {/* Keep HomePilot brand mark vibe (subtle, not a different product logo) */}
          <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
            <Wand2 size={16} className="text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold text-white leading-tight">HomePilot</div>
            <div className="text-xs text-white/50 leading-tight">Imagine</div>
          </div>
        </div>

        <div className="pointer-events-auto flex items-center gap-2">
          {/* Game Mode Toggle */}
          <button
            className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all border ${
              gameMode
                ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
                : 'bg-white/5 hover:bg-white/10 border-white/10 text-white/70'
            }`}
            type="button"
            onClick={() => {
              setGameMode(!gameMode)
              if (!gameMode) {
                setShowGamePanel(true)
              }
            }}
          >
            <Gamepad2 size={16} />
            <span>Game Mode {gameMode ? 'ON' : 'OFF'}</span>
          </button>

          {/* Variation History */}
          {gameMode && gameVariations.length > 0 && (
            <button
              className="flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-2 rounded-full text-sm font-semibold transition-all"
              type="button"
              onClick={() => setShowVariationHistory(true)}
            >
              <History size={16} className="text-white/70" />
              <span>{gameVariations.length}</span>
            </button>
          )}

          {/* Reference Upload Button */}
          <input
            ref={referenceInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleUploadReference(f)
              e.currentTarget.value = ''
            }}
          />
          <button
            className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition-all border ${
              referenceUrl
                ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
                : 'bg-white/5 hover:bg-white/10 border-white/10 text-white/70'
            }`}
            type="button"
            onClick={() => referenceInputRef.current?.click()}
            disabled={isUploadingReference}
          >
            {isUploadingReference ? (
              <>
                <span className="animate-spin">⏳</span>
                <span>Uploading...</span>
              </>
            ) : (
              <>
                <Upload size={16} />
                <span>{referenceUrl ? 'Change reference' : 'Upload reference'}</span>
              </>
            )}
          </button>

          {/* Advanced Settings Toggle */}
          <button
            className={`p-2 rounded-full border transition-all ${
              showAdvancedSettings
                ? 'bg-white text-black border-white'
                : 'bg-white/5 hover:bg-white/10 border-white/10 text-white/70'
            }`}
            type="button"
            onClick={() => setShowAdvancedSettings(!showAdvancedSettings)}
            title="Advanced Settings"
          >
            <Settings2 size={18} />
          </button>
        </div>
      </div>

      {/* Game Mode Settings Panel */}
      {showGamePanel && gameMode && (
        <div className="absolute top-20 right-6 z-30 bg-black/95 border border-white/10 rounded-2xl p-5 shadow-2xl w-80 backdrop-blur-xl">
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Gamepad2 size={16} className="text-purple-400" />
              Game Mode Settings
            </h3>
            <button type="button" onClick={() => setShowGamePanel(false)} className="text-white/50 hover:text-white">
              <X size={16} />
            </button>
          </div>

          {/* Variation Strength */}
          <div className="mb-4">
            <label className="text-[11px] font-bold text-white/50 uppercase tracking-wider mb-2 block">
              Variation Strength: {gameStrength.toFixed(2)}
            </label>
            <div className="flex items-center gap-2">
              <span className="text-xs text-white/40">Subtle</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={gameStrength}
                onChange={(e) => setGameStrength(parseFloat(e.target.value))}
                className="flex-1 h-2 bg-white/10 rounded-full appearance-none cursor-pointer accent-purple-500"
              />
              <span className="text-xs text-white/40">Wild</span>
            </div>
          </div>

          {/* Spicy Strength - Only visible when nsfwMode is enabled */}
          {props.nsfwMode && (
            <div className="mb-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20">
              <div className="flex justify-between items-center mb-2">
                <span className="text-xs text-red-300 font-semibold">🔥 Spicy Strength</span>
                <span className="text-xs text-white/60">{spicyStrength.toFixed(2)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={spicyStrength}
                onChange={(e) => setSpicyStrength(parseFloat(e.target.value))}
                className="w-full h-2 bg-red-500/20 rounded-full appearance-none cursor-pointer accent-red-500"
              />
              <div className="flex justify-between text-[10px] text-white/30 mt-1">
                <span>Tasteful</span>
                <span>Bold</span>
              </div>
            </div>
          )}

          {/* Lock Settings */}
          <div className="mb-4">
            <label className="text-[11px] font-bold text-white/50 uppercase tracking-wider mb-2 block">
              Consistency Locks
            </label>
            <div className="space-y-2">
              {[
                { key: 'lock_world', label: 'World/Setting' },
                { key: 'lock_style', label: 'Art Style' },
                { key: 'lock_subject_type', label: 'Subject Type' },
                { key: 'lock_main_character', label: 'Main Character' },
                { key: 'lock_palette', label: 'Color Palette' },
                { key: 'lock_time_of_day', label: 'Time of Day' },
              ].map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg transition-colors ${
                    gameLocks[key as keyof GameLocks]
                      ? 'bg-purple-500/20 border border-purple-500/30'
                      : 'bg-white/5 border border-white/10 hover:bg-white/10'
                  }`}
                  onClick={() => setGameLocks((prev) => ({ ...prev, [key]: !prev[key as keyof GameLocks] }))}
                >
                  <span className="text-xs text-white/80">{label}</span>
                  {gameLocks[key as keyof GameLocks] ? (
                    <Lock size={14} className="text-purple-400" />
                  ) : (
                    <Unlock size={14} className="text-white/40" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Session Info */}
          {gameSessionId && (
            <div className="mb-4 p-3 bg-white/5 rounded-lg">
              <div className="text-[10px] text-white/40 mb-1">Session ID</div>
              <div className="text-xs text-white/60 font-mono truncate">{gameSessionId}</div>
              <button
                type="button"
                className="mt-2 text-xs text-red-400 hover:text-red-300"
                onClick={resetGameSession}
              >
                Reset Session
              </button>
            </div>
          )}

          <div className="text-[10px] text-white/40 leading-relaxed">
            Game Mode generates infinite variations of your prompt. Each generation creates a new variation while
            maintaining consistency based on your lock settings.
          </div>
        </div>
      )}

      {/* Advanced Settings Panel */}
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

                {/* Use ControlNet */}
                <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                  <span className="text-sm text-white/80">Use ControlNet</span>
                  <button
                    onClick={() => setUseControlNet(!useControlNet)}
                    className={`w-10 h-5 rounded-full transition-colors relative ${useControlNet ? 'bg-purple-500' : 'bg-white/20'}`}
                  >
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${useControlNet ? 'translate-x-5' : 'translate-x-0.5'}`} />
                  </button>
                </div>
                {useControlNet && (
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="uppercase tracking-wider text-white/40 font-semibold">CN Strength</span>
                      <span className="text-white/60">{cnStrength.toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={2}
                      step={0.05}
                      value={cnStrength}
                      onChange={(e) => setCnStrength(Number(e.target.value))}
                      className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                    />
                  </div>
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

      {/* Grid - Row-wise layout like Grok (fills left to right, then next row) */}
      <div className="flex-1 overflow-y-auto px-4 pb-48 pt-8 scrollbar-hide">
        <div className="max-w-[1600px] mx-auto grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 content-start">
          {/* Scroll anchor for auto-scroll to top (Grok-style: new images at top) */}
          <div ref={gridStartRef} className="col-span-full h-1" />

          {/* Empty hint */}
          {items.length === 0 && !isGenerating ? (
            <div className="col-span-full rounded-2xl border border-white/10 bg-white/5 p-6 text-white/70">
              <div className="text-sm font-semibold">Your gallery is empty</div>
              <div className="text-xs text-white/45 mt-1">Type a prompt below and hit Generate.</div>
            </div>
          ) : null}

          {/* Loading skeletons - shown at TOP (where new images will appear) */}
          {isGenerating && Array.from({ length: numImages }).map((_, idx) => (
            <div key={`skeleton-${idx}`} className="relative rounded-2xl overflow-hidden bg-white/5 border border-white/10 aspect-square animate-pulse">
              <div className="absolute inset-0 bg-gradient-to-tr from-white/10 to-transparent"></div>
              <div className="absolute bottom-4 left-4 text-sm font-mono text-white/70">
                {idx === 0 ? 'Generating…' : `Image ${idx + 1}…`}
              </div>
            </div>
          ))}

          {/* Images - rendered in order (newest first at top-left, oldest at bottom-right) */}
          {items.map((img) => (
            <div
              key={img.id}
              onClick={() => setSelectedImage(img)}
              className="relative group rounded-2xl overflow-hidden bg-white/5 border border-white/10 hover:border-white/20 transition-colors cursor-pointer aspect-square"
            >
              <img
                src={img.url}
                alt={img.prompt}
                className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
                loading="lazy"
              />

              {/* Card overlay */}
              <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex flex-col justify-end p-4">
                <div className="flex gap-2 justify-end transform translate-y-4 group-hover:translate-y-0 transition-transform duration-300">
                  <button
                    className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-full text-white transition-colors"
                    type="button"
                    title="Play"
                    onClick={(e) => {
                      e.stopPropagation()
                    }}
                  >
                    <Play size={18} fill="currentColor" />
                  </button>
                  <button
                    className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-full text-white transition-colors"
                    type="button"
                    title="Copy URL"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigator.clipboard?.writeText(img.url).catch(() => {})
                    }}
                  >
                    <MoreHorizontal size={18} />
                  </button>
                  <button
                    className={`backdrop-blur-md p-2 rounded-full transition-colors ${
                      upscalingId === img.id
                        ? 'bg-purple-500/40 text-purple-300 animate-pulse'
                        : 'bg-purple-500/20 hover:bg-purple-500/40 text-purple-300 hover:text-purple-200'
                    }`}
                    type="button"
                    title="Upscale 2x"
                    disabled={upscalingId !== null}
                    onClick={(e) => handleUpscale(img, e)}
                  >
                    <Maximize2 size={18} />
                  </button>
                  <button
                    className="bg-red-500/20 backdrop-blur-md hover:bg-red-500/40 p-2 rounded-full text-red-400 hover:text-red-300 transition-colors"
                    type="button"
                    title="Delete"
                    onClick={(e) => handleDelete(img, e)}
                  >
                    <Trash2 size={18} />
                  </button>
                </div>

                <div className="mt-3 text-xs text-white/80 line-clamp-2">{img.prompt}</div>
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
                  alt="Reference"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-2">
                    <div className="text-sm font-semibold text-white flex items-center gap-2">
                      <Image size={14} className="text-purple-400" />
                      Reference Active
                    </div>
                    <button
                      type="button"
                      className="p-1.5 rounded-lg bg-white/5 hover:bg-red-500/20 border border-white/10 hover:border-red-500/30 text-white/50 hover:text-red-400 transition-colors"
                      onClick={() => setReferenceUrl(null)}
                      title="Remove reference"
                    >
                      <X size={14} />
                    </button>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="text-white/50">Similarity</span>
                      <span className="text-white/70 font-mono">
                        {referenceStrength < 0.3 ? 'Very Similar' : referenceStrength < 0.6 ? 'Balanced' : 'More Creative'}
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={referenceStrength}
                      onChange={(e) => setReferenceStrength(Number(e.target.value))}
                      className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                    />
                    <div className="flex justify-between text-[10px] text-white/40">
                      <span>Similar</span>
                      <span>Creative</span>
                    </div>
                  </div>
                </div>
              </div>
              <div className="mt-3 text-[10px] text-white/40 leading-relaxed">
                Generated images will be similar to your reference. Adjust the slider to control how closely to follow the reference.
              </div>
            </div>
          )}

          {/* Aspect panel */}
          {showAspectPanel ? (
            <div className="absolute bottom-[110%] left-0 bg-black border border-white/10 rounded-xl p-3 shadow-2xl mb-2 flex flex-col gap-3">
              {/* Aspect Ratio Section */}
              <div>
                <div className="flex justify-between items-center text-xs text-white/50 uppercase font-semibold px-1 mb-2">
                  <span>Aspect Ratio</span>
                  <button type="button" onClick={() => setShowAspectPanel(false)}>
                    <X size={14} />
                  </button>
                </div>
                <div className="flex gap-2">
                  {ASPECT_RATIOS.map((r) => (
                    <button
                      key={r.label}
                      onClick={() => {
                        setAspect(r.label)
                      }}
                      className={`p-2 rounded-lg hover:bg-white/5 transition-colors group flex flex-col items-center gap-1 ${
                        aspect === r.label ? 'bg-white/5 ring-1 ring-white/20' : ''
                      }`}
                      title={r.label}
                      type="button"
                    >
                      <div
                        className={`border-2 ${
                          aspect === r.label ? 'border-white/70' : 'border-white/30 group-hover:border-white/50'
                        } rounded-[2px]`}
                        style={{ width: r.previewW, height: r.previewH }}
                      />
                      <span className="text-[10px] text-white/50">{r.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Number of Images Section */}
              <div className="border-t border-white/10 pt-3">
                <div className="text-xs text-white/50 uppercase font-semibold px-1 mb-2">
                  Images per generation
                </div>
                <div className="flex gap-2">
                  {([1, 2, 4] as const).map((n) => (
                    <button
                      key={n}
                      onClick={() => setNumImages(n)}
                      className={`flex-1 py-2 px-3 rounded-lg transition-colors flex items-center justify-center gap-2 ${
                        numImages === n
                          ? 'bg-white/10 ring-1 ring-white/30 text-white'
                          : 'bg-white/5 hover:bg-white/10 text-white/60'
                      }`}
                      type="button"
                    >
                      {n === 1 ? (
                        <Image size={14} />
                      ) : (
                        <Grid2X2 size={14} />
                      )}
                      <span className="text-sm font-medium">{n}</span>
                    </button>
                  ))}
                </div>
                <div className="text-[10px] text-white/40 px-1 mt-1.5">
                  {numImages === 1 ? 'Single full-size image' : `${numImages} thumbnails per generation`}
                </div>
              </div>
            </div>
          ) : null}

          <div className="relative group">
            <div
              className={`absolute -inset-0.5 bg-gradient-to-r from-white/10 to-white/0 rounded-full opacity-0 transition duration-500 group-hover:opacity-100 blur ${
                isGenerating ? 'opacity-100 animate-pulse' : ''
              }`}
            ></div>

            <div className="relative bg-black border border-white/10 rounded-[32px] p-2 pr-2 flex items-center shadow-2xl transition-all focus-within:border-white/20">
              <button
                className="p-3 text-white/50 hover:text-white transition-colors rounded-full hover:bg-white/5"
                type="button"
                title="Voice input (not implemented)"
              >
                <Mic size={20} />
              </button>

              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => (e.key === 'Enter' ? void handleGenerate() : undefined)}
                placeholder="Describe what you want to see…"
                className="flex-1 bg-transparent text-white placeholder-white/35 outline-none px-2 h-12 text-lg"
              />

              <div className="flex items-center gap-2 pl-2">
                <button
                  onClick={() => setShowAspectPanel((v) => !v)}
                  className={`p-2 rounded-full transition-colors ${
                    showAspectPanel ? 'text-white bg-white/5' : 'text-white/50 hover:text-white hover:bg-white/5'
                  }`}
                  type="button"
                  title="Aspect & settings"
                >
                  <Settings2 size={20} />
                </button>

                {/* Game Mode: Auto Generate Button */}
                {gameMode && (
                  <button
                    onClick={toggleAutoGenerate}
                    disabled={!prompt.trim()}
                    className={`ml-1 h-10 px-4 rounded-full font-semibold text-sm transition-all flex items-center gap-2 ${
                      isAutoGenerating
                        ? 'bg-red-500 text-white hover:bg-red-600'
                        : prompt.trim()
                        ? 'bg-purple-500 text-white hover:bg-purple-600'
                        : 'bg-white/10 text-white/40 cursor-not-allowed'
                    }`}
                    type="button"
                  >
                    {isAutoGenerating ? (
                      <>
                        <Pause size={16} />
                        Stop
                      </>
                    ) : (
                      <>
                        <Zap size={16} />
                        Auto
                      </>
                    )}
                  </button>
                )}

                <button
                  onClick={() => void handleGenerate()}
                  disabled={(!prompt.trim() && !referenceUrl) || isGenerating || isAutoGenerating}
                  className={`ml-1 h-10 px-6 rounded-full font-semibold text-sm transition-all flex items-center gap-2 ${
                    (prompt.trim() || referenceUrl) && !isGenerating && !isAutoGenerating
                      ? gameMode
                        ? 'bg-purple-500 text-white hover:bg-purple-600 hover:scale-[1.02]'
                        : 'bg-white text-black hover:bg-gray-200 hover:scale-[1.02]'
                      : 'bg-white/10 text-white/40 cursor-not-allowed'
                  }`}
                  type="button"
                >
                  {isGenerating ? (
                    <span className="animate-pulse">Creating…</span>
                  ) : gameMode ? (
                    'Variation'
                  ) : (
                    'Generate'
                  )}
                </button>
              </div>
            </div>

            <div className="mt-2 text-[11px] text-white/35 px-2">
              Using provider <span className="text-white/55 font-semibold">{props.providerImages}</span>
              {props.modelImages ? (
                <>
                  {' '}
                  · model <span className="text-white/55 font-semibold">{props.modelImages}</span>
                </>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      {/* Immersive Lightbox - Clean, Image-first Design */}
      {selectedImage && (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-black animate-in fade-in duration-200"
          onClick={() => { setSelectedImage(null); setShowDetails(false); }}
        >
          {/* Floating Controls - Top Right */}
          <div className="absolute top-4 right-4 z-50 flex items-center gap-2">
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
                // Use native fullscreen API - find the image element and fullscreen it
                const imgEl = document.querySelector('[data-lightbox-media]') as HTMLElement
                if (imgEl?.requestFullscreen) {
                  imgEl.requestFullscreen().catch(() => {})
                }
              }}
              type="button"
              title="View full size"
            >
              <Maximize2 size={18} />
            </button>
            <button
              className="p-2.5 bg-white/10 text-white/70 hover:bg-white/20 hover:text-white rounded-full transition-all"
              onClick={() => { setSelectedImage(null); setShowDetails(false); }}
              type="button"
              title="Close"
            >
              <X size={18} />
            </button>
          </div>

          {/* Main Content Area */}
          <div className="flex-1 flex" onClick={(e) => e.stopPropagation()}>
            {/* Hero Image Container - LARGER, fills more space */}
            <div className="flex-1 flex items-center justify-center p-2 relative group">
              <img
                src={selectedImage.url}
                data-lightbox-media
                className="max-h-[calc(100vh-140px)] max-w-full object-contain rounded-lg shadow-2xl"
                alt="Selected"
              />

              {/* Chips Overlay - Fade in on hover */}
              <div className="absolute bottom-6 left-6 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                {selectedImage.model && (
                  <span className="px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10">
                    {selectedImage.model.split('.')[0].split('-')[0].toUpperCase()}
                  </span>
                )}
                {selectedImage.width && selectedImage.height && (
                  <span className="px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10">
                    {selectedImage.width}×{selectedImage.height}
                  </span>
                )}
                {selectedImage.steps && (
                  <span className="px-3 py-1.5 bg-black/60 backdrop-blur-md text-white text-xs font-semibold rounded-full border border-white/10">
                    {selectedImage.steps} steps
                  </span>
                )}
              </div>

              {/* Floating Action Bar - Bottom Right, appears on hover */}
              <div className="absolute bottom-6 right-6 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                {/* Primary Action: Download */}
                <button
                  className="px-4 py-2 bg-white text-black font-semibold rounded-full hover:opacity-90 transition-opacity text-sm flex items-center gap-2 shadow-lg"
                  onClick={() => window.open(selectedImage.url, '_blank')}
                  type="button"
                >
                  <Download size={16} />
                  Download
                </button>
                {/* Next-step Affordance: Animate This */}
                <button
                  className="px-4 py-2 bg-gradient-to-r from-purple-500 to-blue-500 text-white font-semibold rounded-full hover:opacity-90 transition-opacity text-sm flex items-center gap-2 shadow-lg"
                  onClick={() => {
                    // Store image URL for Animate mode to use
                    localStorage.setItem('homepilot_animate_source', selectedImage.url)
                    // Switch to Animate mode (parent component handles this via URL or state)
                    window.dispatchEvent(new CustomEvent('switch-to-animate', { detail: { imageUrl: selectedImage.url } }))
                    setSelectedImage(null)
                    setShowDetails(false)
                  }}
                  type="button"
                  title="Animate this image"
                >
                  <Film size={16} />
                  Animate
                </button>
                {/* More Options Dropdown */}
                <div className="relative group/more">
                  <button
                    className="p-2.5 bg-white/10 text-white/70 hover:bg-white/20 hover:text-white rounded-full transition-all"
                    type="button"
                    title="More options"
                  >
                    <MoreHorizontal size={18} />
                  </button>
                  {/* Dropdown Menu */}
                  <div className="absolute bottom-full right-0 mb-2 bg-[#1a1a1a] border border-white/10 rounded-xl shadow-2xl overflow-hidden opacity-0 group-hover/more:opacity-100 pointer-events-none group-hover/more:pointer-events-auto transition-opacity duration-200 min-w-[160px]">
                    <button
                      className="w-full px-4 py-2.5 text-left text-sm text-white/80 hover:bg-white/10 flex items-center gap-3 transition-colors"
                      onClick={() => { setPrompt(selectedImage.prompt); setSelectedImage(null); setShowDetails(false); }}
                      type="button"
                    >
                      <RefreshCw size={14} />
                      Reuse Prompt
                    </button>
                    <button
                      className="w-full px-4 py-2.5 text-left text-sm text-white/80 hover:bg-white/10 flex items-center gap-3 transition-colors"
                      onClick={() => navigator.clipboard.writeText(selectedImage.prompt)}
                      type="button"
                    >
                      <Copy size={14} />
                      Copy Prompt
                    </button>
                    <button
                      className="w-full px-4 py-2.5 text-left text-sm text-red-400 hover:bg-red-500/10 flex items-center gap-3 transition-colors"
                      onClick={() => handleDelete(selectedImage)}
                      type="button"
                    >
                      <Trash2 size={14} />
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Details Panel - Slide in from right */}
            {showDetails && (
              <div className="w-80 bg-[#0a0a0a] border-l border-white/10 flex flex-col animate-in slide-in-from-right duration-200">
                <div className="p-4 border-b border-white/10">
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <Wand2 size={14} className="text-white/60" />
                    Generation Details
                  </h3>
                </div>
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {/* Prompt - Only visible in details panel */}
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-2 block">Prompt</label>
                    <p className="text-sm text-white/70 leading-relaxed">{selectedImage.prompt}</p>
                  </div>
                  {/* Seed */}
                  {selectedImage.seed && (
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Seed</label>
                      <div className="text-base text-white font-mono font-bold">{selectedImage.seed}</div>
                    </div>
                  )}
                  {/* Resolution */}
                  {selectedImage.width && selectedImage.height && (
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Resolution</label>
                      <div className="text-sm text-white/80 font-mono">{selectedImage.width} × {selectedImage.height}</div>
                    </div>
                  )}
                  {/* Steps & CFG */}
                  <div className="grid grid-cols-2 gap-3">
                    {selectedImage.steps && (
                      <div>
                        <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Steps</label>
                        <div className="text-sm text-white/70 font-mono">{selectedImage.steps}</div>
                      </div>
                    )}
                    {selectedImage.cfg && (
                      <div>
                        <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">CFG</label>
                        <div className="text-sm text-white/70 font-mono">{selectedImage.cfg}</div>
                      </div>
                    )}
                  </div>
                  {/* Date & Time */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Date</label>
                      <div className="text-xs text-white/60 font-mono">{new Date(selectedImage.createdAt).toLocaleDateString()}</div>
                    </div>
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Time</label>
                      <div className="text-xs text-white/60 font-mono">{new Date(selectedImage.createdAt).toLocaleTimeString()}</div>
                    </div>
                  </div>
                  {/* Model */}
                  {selectedImage.model && (
                    <div>
                      <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">Model</label>
                      <div className="text-xs text-white/50 font-mono break-all">{selectedImage.model}</div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Inline Prompt Composer Bar - Grok-style editable prompt */}
          <div className="bg-[#0a0a0a] border-t border-white/10 px-4 py-3" onClick={(e) => e.stopPropagation()}>
            <div className="max-w-3xl mx-auto">
              <div className="relative flex items-center gap-3">
                {/* Provenance Indicator */}
                <div className="flex items-center gap-1.5 text-green-400/80" title="Generated with this prompt">
                  <Check size={14} strokeWidth={3} />
                </div>

                {/* Editable Prompt Input */}
                <input
                  type="text"
                  value={lightboxPrompt}
                  onChange={(e) => setLightboxPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && lightboxPrompt.trim() && !isRegenerating) {
                      setIsRegenerating(true)
                      handleGenerate(lightboxPrompt).finally(() => {
                        setIsRegenerating(false)
                        setSelectedImage(null)
                        setShowDetails(false)
                      })
                    }
                  }}
                  placeholder="Edit prompt and regenerate..."
                  className="flex-1 bg-transparent text-white/80 text-sm placeholder-white/30 outline-none border-none"
                  disabled={isRegenerating}
                />

                {/* Regenerate Button */}
                <button
                  onClick={() => {
                    if (lightboxPrompt.trim() && !isRegenerating) {
                      setIsRegenerating(true)
                      handleGenerate(lightboxPrompt).finally(() => {
                        setIsRegenerating(false)
                        setSelectedImage(null)
                        setShowDetails(false)
                      })
                    }
                  }}
                  disabled={!lightboxPrompt.trim() || isRegenerating}
                  className={`p-2 rounded-full transition-all ${
                    lightboxPrompt.trim() && !isRegenerating
                      ? 'bg-white text-black hover:opacity-90'
                      : 'bg-white/10 text-white/30 cursor-not-allowed'
                  }`}
                  type="button"
                  title="Regenerate with this prompt"
                >
                  {isRegenerating ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <ArrowUp size={16} />
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Variation History Modal */}
      {showVariationHistory && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4 backdrop-blur-md"
          onClick={() => setShowVariationHistory(false)}
        >
          <div
            className="max-w-2xl w-full max-h-[80vh] bg-[#121212] border border-white/10 rounded-2xl overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-5 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <History size={16} className="text-purple-400" />
                Variation History ({gameVariations.length})
              </h3>
              <button
                type="button"
                onClick={() => setShowVariationHistory(false)}
                className="text-white/50 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>

            <div className="overflow-y-auto max-h-[60vh] p-4 space-y-3">
              {gameVariations.map((v, i) => (
                <div
                  key={i}
                  className="p-4 bg-white/5 rounded-xl border border-white/10 hover:border-white/20 transition-colors"
                >
                  <div className="text-sm text-white/90 mb-2">{v.prompt}</div>
                  <div className="flex flex-wrap gap-2 mb-2">
                    {Object.entries(v.tags).map(([key, value]) => (
                      <span
                        key={key}
                        className="px-2 py-1 bg-purple-500/20 text-purple-300 text-[10px] rounded-full"
                      >
                        {key}: {value}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-white/40">
                      {new Date(v.timestamp).toLocaleTimeString()}
                    </span>
                    <button
                      type="button"
                      className="text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1"
                      onClick={() => {
                        setPrompt(v.prompt)
                        setShowVariationHistory(false)
                      }}
                    >
                      <RefreshCw size={12} />
                      Use as base
                    </button>
                  </div>
                </div>
              ))}

              {gameVariations.length === 0 && (
                <div className="text-center text-white/40 py-8">
                  No variations generated yet. Start generating to see history.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
        .line-clamp-2 {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
      `}</style>
    </div>
  )
}
