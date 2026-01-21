import React, { useEffect, useMemo, useState } from 'react'
import { Upload, Mic, Settings2, X, Play, MoreHorizontal, Wand2, Download, Copy, RefreshCw, Trash2 } from 'lucide-react'

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
}

export type ImagineParams = {
  backendUrl: string
  apiKey?: string
  // Image provider settings (from Enterprise Settings)
  providerImages: string
  baseUrlImages?: string
  modelImages?: string
  // Generation controls
  imgWidth?: number
  imgHeight?: number
  imgSteps?: number
  imgCfg?: number
  imgSeed?: number
  nsfwMode?: boolean
  promptRefinement?: boolean
}

type ChatResponse = {
  ok?: boolean
  text?: string
  media?: {
    images?: string[]
    video_url?: string
  } | null
  message?: string
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

  // Selection state for Lightbox (Grok-style detail view)
  const [selectedImage, setSelectedImage] = useState<ImagineItem | null>(null)

  const [aspect, setAspect] = useState<string>('1:1')
  const [showAspectPanel, setShowAspectPanel] = useState(false)

  // Save items to localStorage whenever they change
  useEffect(() => {
    try {
      localStorage.setItem('homepilot_imagine_items', JSON.stringify(items))
    } catch (error) {
      console.error('Failed to save imagine items to localStorage:', error)
    }
  }, [items])

  const aspectObj = useMemo(() => {
    return ASPECT_RATIOS.find((a) => a.label === aspect) || ASPECT_RATIOS[0]
  }, [aspect])

  const handleGenerate = async () => {
    const t = prompt.trim()
    if (!t || isGenerating) return

    setIsGenerating(true)
    setShowAspectPanel(false)

    try {
      // Prefer explicit width/height from props; otherwise use aspect defaults.
      const width = props.imgWidth && props.imgWidth > 0 ? props.imgWidth : aspectObj.genW
      const height = props.imgHeight && props.imgHeight > 0 ? props.imgHeight : aspectObj.genH

      // Map 'comfyui' provider to 'ollama' for prompt refinement
      // ComfyUI is used automatically for actual image generation
      const llmProvider = props.providerImages === 'comfyui' ? 'ollama' : props.providerImages

      const data = await postJson<ChatResponse>(
        props.backendUrl,
        '/chat',
        {
          message: /^\s*(imagine|generate|create|draw|make)\b/i.test(t) ? t : `imagine ${t}`,
          mode: 'imagine',

          // Provider override fields (preferred by backend)
          provider: llmProvider,
          provider_base_url: props.baseUrlImages || undefined,
          provider_model: props.modelImages || undefined,

          // Image generation params
          imgWidth: width,
          imgHeight: height,
          imgSteps: props.imgSteps,
          imgCfg: props.imgCfg,
          imgSeed: props.imgSeed,
          imgModel: props.modelImages,
          nsfwMode: props.nsfwMode,
          promptRefinement: props.promptRefinement ?? true,
        },
        authKey
      )

      const urls = data?.media?.images || []
      if (urls.length === 0) {
        throw new Error(data?.message || data?.text || 'No images returned by backend.')
      }

      const now = Date.now()
      const newItems: ImagineItem[] = urls.map((u) => ({
        id: uid(),
        url: u,
        createdAt: now,
        prompt: t,
      }))

      // Keep only the last 100 items to prevent localStorage overflow
      setItems((prev) => [...newItems, ...prev].slice(0, 100))
      setPrompt('')
    } catch (err: any) {
      alert(`Generation failed: ${err.message || err}`)
    } finally {
      setIsGenerating(false)
    }
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

        <button
          className="pointer-events-auto flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-2 rounded-full text-sm font-semibold transition-all"
          type="button"
          onClick={() => {
            alert('Reference upload is not implemented yet.')
          }}
        >
          <Upload size={16} className="text-white/70" />
          <span>Upload reference</span>
        </button>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto px-4 pb-48 pt-20 scrollbar-hide">
        <div className="max-w-[1600px] mx-auto columns-2 md:columns-3 lg:columns-4 gap-4 space-y-4">
          {/* Empty hint */}
          {items.length === 0 && !isGenerating ? (
            <div className="break-inside-avoid rounded-2xl border border-white/10 bg-white/5 p-6 text-white/70">
              <div className="text-sm font-semibold">Your gallery is empty</div>
              <div className="text-xs text-white/45 mt-1">Type a prompt below and hit Generate.</div>
            </div>
          ) : null}

          {/* Skeleton */}
          {isGenerating ? (
            <div className="break-inside-avoid relative rounded-2xl overflow-hidden bg-white/5 border border-white/10 aspect-square animate-pulse mb-4">
              <div className="absolute inset-0 bg-gradient-to-tr from-white/10 to-transparent"></div>
              <div className="absolute bottom-4 left-4 text-sm font-mono text-white/70">Generating…</div>
            </div>
          ) : null}

          {items.map((img) => (
            <div
              key={img.id}
              onClick={() => setSelectedImage(img)}
              className="break-inside-avoid relative group rounded-2xl overflow-hidden bg-white/5 border border-white/10 hover:border-white/20 transition-colors cursor-pointer"
            >
              <img
                src={img.url}
                alt={img.prompt}
                className="w-full h-auto object-cover transition-transform duration-700 group-hover:scale-105"
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
          {/* Aspect panel */}
          {showAspectPanel ? (
            <div className="absolute bottom-[110%] left-0 bg-black border border-white/10 rounded-xl p-3 shadow-2xl mb-2 flex flex-col gap-2">
              <div className="flex justify-between items-center text-xs text-white/50 uppercase font-semibold px-1">
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
                      setShowAspectPanel(false)
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

                <button
                  onClick={() => void handleGenerate()}
                  disabled={!prompt.trim() || isGenerating}
                  className={`ml-1 h-10 px-6 rounded-full font-semibold text-sm transition-all flex items-center gap-2 ${
                    prompt.trim() && !isGenerating
                      ? 'bg-white text-black hover:bg-gray-200 hover:scale-[1.02]'
                      : 'bg-white/10 text-white/40 cursor-not-allowed'
                  }`}
                  type="button"
                >
                  {isGenerating ? <span className="animate-pulse">Creating…</span> : 'Generate'}
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

      {/* Grok-style Lightbox / Detail View */}
      {selectedImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/95 p-4 backdrop-blur-md animate-in fade-in duration-200"
          onClick={() => setSelectedImage(null)}
        >
          {/* Close button outside content */}
          <button
            className="absolute top-4 right-4 p-2 text-white/50 hover:text-white bg-white/5 rounded-full z-50"
            onClick={() => setSelectedImage(null)}
            type="button"
            aria-label="Close"
          >
            <X size={24} />
          </button>

          <div
            className="max-w-6xl w-full max-h-[90vh] flex flex-col md:flex-row gap-0 bg-[#121212] border border-white/10 rounded-2xl overflow-hidden shadow-2xl ring-1 ring-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Left: Image Container */}
            <div className="flex-1 bg-black/50 flex items-center justify-center p-4 min-h-[400px] relative">
              <img
                src={selectedImage.url}
                className="max-h-full max-w-full object-contain shadow-lg rounded-sm"
                alt="Selected"
              />
            </div>

            {/* Right: Sidebar Details */}
            <div className="w-full md:w-96 flex flex-col border-l border-white/10 bg-[#161616]">
              {/* Sidebar Header */}
              <div className="p-5 border-b border-white/10 flex items-center justify-between">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <Wand2 size={14} className="text-white/60" />
                  Generation Details
                </h3>
                <span className="text-[10px] text-white/40 font-mono tracking-wide">{selectedImage.id.slice(0, 8)}</span>
              </div>

              {/* Sidebar Content */}
              <div className="flex-1 overflow-y-auto p-5 space-y-6">
                <div>
                  <label className="text-[11px] font-bold text-white/40 uppercase tracking-wider mb-2 block">
                    Prompt
                  </label>
                  <div className="text-sm text-white/90 leading-relaxed font-light whitespace-pre-wrap selection:bg-white/20">
                    {selectedImage.prompt}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-2">
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Date
                    </label>
                    <div className="text-xs text-white/70 font-mono">
                      {new Date(selectedImage.createdAt).toLocaleDateString()}
                    </div>
                  </div>
                  <div>
                    <label className="text-[10px] font-bold text-white/40 uppercase tracking-wider mb-1 block">
                      Time
                    </label>
                    <div className="text-xs text-white/70 font-mono">
                      {new Date(selectedImage.createdAt).toLocaleTimeString()}
                    </div>
                  </div>
                </div>
              </div>

              {/* Sidebar Footer / Actions */}
              <div className="p-5 border-t border-white/10 bg-[#141414] flex flex-col gap-3">
                <button
                  className="w-full py-3 bg-white text-black font-bold rounded-lg hover:opacity-90 transition-opacity text-sm flex items-center justify-center gap-2"
                  onClick={() => window.open(selectedImage.url, '_blank')}
                  type="button"
                >
                  <Download size={16} />
                  Download Original
                </button>

                <div className="flex gap-2">
                  <button
                    className="flex-1 py-3 bg-white/5 text-white/80 font-semibold rounded-lg hover:bg-white/10 transition-colors text-sm flex items-center justify-center gap-2"
                    onClick={() => {
                      setPrompt(selectedImage.prompt)
                      setSelectedImage(null)
                    }}
                    type="button"
                  >
                    <RefreshCw size={16} />
                    Reuse
                  </button>
                  <button
                    className="flex-1 py-3 bg-white/5 text-white/80 font-semibold rounded-lg hover:bg-white/10 transition-colors text-sm flex items-center justify-center gap-2"
                    onClick={() => {
                      navigator.clipboard.writeText(selectedImage.prompt)
                    }}
                    type="button"
                  >
                    <Copy size={16} />
                    Copy
                  </button>
                </div>

                <button
                  className="w-full py-3 bg-red-500/10 text-red-400 font-semibold rounded-lg hover:bg-red-500/20 transition-colors text-sm flex items-center justify-center gap-2 border border-red-500/20"
                  onClick={() => handleDelete(selectedImage)}
                  type="button"
                >
                  <Trash2 size={16} />
                  Delete Image
                </button>
              </div>
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
