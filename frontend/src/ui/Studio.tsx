import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Plus,
  Settings2,
  X,
  Tv2,
  Film,
  RefreshCw,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Volume2,
  VolumeX,
  Maximize2,
  BookOpen,
  Users,
  MapPin,
} from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type Scene = {
  idx: number
  narration: string
  image_prompt: string
  negative_prompt: string
  duration_s: number
  tags: Record<string, string>
  audio_url?: string | null
  image_url?: string | null
}

type StoryBible = {
  title: string
  logline: string
  setting: string
  visual_style_rules: string[]
  recurring_characters: { name: string; description: string }[]
  recurring_locations: string[]
  do_not_change: string[]
}

type StorySession = {
  id: string
  title: string
  premise: string
  created_at: number
  updated_at: number
}

type StoryData = {
  ok: boolean
  session_id: string
  title: string
  premise: string
  bible: StoryBible
  scenes: Scene[]
}

export type StudioParams = {
  backendUrl: string
  apiKey?: string
  providerImages: string
  baseUrlImages?: string
  modelImages?: string
  imgWidth?: number
  imgHeight?: number
  imgSteps?: number
  imgCfg?: number
  nsfwMode?: boolean
  promptRefinement?: boolean
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

async function fetchJson<T>(baseUrl: string, path: string, apiKey?: string): Promise<T> {
  const url = `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

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
    throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

async function deleteJson<T>(baseUrl: string, path: string, apiKey?: string): Promise<T> {
  const url = `${baseUrl.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

export default function StudioView(props: StudioParams) {
  const authKey = (props.apiKey || '').trim()

  // View state
  const [view, setView] = useState<'list' | 'create' | 'player'>('list')

  // Story list
  const [sessions, setSessions] = useState<StorySession[]>([])
  const [loadingSessions, setLoadingSessions] = useState(true)

  // Create story form
  const [premise, setPremise] = useState('')
  const [titleHint, setTitleHint] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  // Player state
  const [currentStory, setCurrentStory] = useState<StoryData | null>(null)
  const [currentSceneIndex, setCurrentSceneIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isGeneratingScene, setIsGeneratingScene] = useState(false)
  const [isGeneratingImage, setIsGeneratingImage] = useState(false)
  const [showBible, setShowBible] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)

  const playerRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Load sessions on mount
  useEffect(() => {
    loadSessions()
  }, [])

  const loadSessions = async () => {
    setLoadingSessions(true)
    try {
      const data = await fetchJson<{ ok: boolean; sessions: StorySession[] }>(
        props.backendUrl,
        '/story/sessions/list',
        authKey
      )
      setSessions(data.sessions || [])
    } catch (err) {
      console.error('Failed to load story sessions:', err)
    } finally {
      setLoadingSessions(false)
    }
  }

  const createStory = async () => {
    if (!premise.trim() || isCreating) return
    setIsCreating(true)

    try {
      const data = await postJson<{
        ok: boolean
        session_id: string
        title: string
        bible: StoryBible
      }>(
        props.backendUrl,
        '/story/start',
        {
          premise: premise.trim(),
          title_hint: titleHint.trim(),
          options: {
            visual_style: 'cinematic, high detail, coherent lighting',
            aspect_ratio: '16:9',
            refine_image_prompt: props.promptRefinement ?? true,
          },
        },
        authKey
      )

      // Load the full story and switch to player
      await loadStory(data.session_id)
      setView('player')
      setPremise('')
      setTitleHint('')
    } catch (err: any) {
      alert(`Failed to create story: ${err.message || err}`)
    } finally {
      setIsCreating(false)
    }
  }

  const loadStory = async (sessionId: string) => {
    try {
      const data = await fetchJson<StoryData>(props.backendUrl, `/story/${sessionId}`, authKey)
      setCurrentStory(data)
      setCurrentSceneIndex(0)
      setIsPlaying(false)
    } catch (err: any) {
      alert(`Failed to load story: ${err.message || err}`)
    }
  }

  const deleteStory = async (sessionId: string) => {
    if (!confirm('Delete this story and all its scenes?')) return
    try {
      await deleteJson(props.backendUrl, `/story/${sessionId}`, authKey)
      setSessions((prev) => prev.filter((s) => s.id !== sessionId))
      if (currentStory?.session_id === sessionId) {
        setCurrentStory(null)
        setView('list')
      }
    } catch (err: any) {
      alert(`Failed to delete story: ${err.message || err}`)
    }
  }

  const generateNextScene = async () => {
    if (!currentStory || isGeneratingScene) return
    setIsGeneratingScene(true)

    try {
      const data = await postJson<{
        ok: boolean
        session_id: string
        title: string
        scene: Scene
        bible: StoryBible
      }>(
        props.backendUrl,
        '/story/next',
        {
          session_id: currentStory.session_id,
          refine_image_prompt: props.promptRefinement ?? true,
        },
        authKey
      )

      // Add new scene to current story
      setCurrentStory((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          scenes: [...prev.scenes, data.scene],
        }
      })

      // Move to the new scene
      setCurrentSceneIndex(currentStory.scenes.length)

      // Generate image for the new scene
      await generateImageForScene(data.scene)
    } catch (err: any) {
      alert(`Failed to generate scene: ${err.message || err}`)
    } finally {
      setIsGeneratingScene(false)
    }
  }

  const generateImageForScene = async (scene: Scene) => {
    if (isGeneratingImage) return
    setIsGeneratingImage(true)

    try {
      const llmProvider = props.providerImages === 'comfyui' ? 'ollama' : props.providerImages

      const data = await postJson<{
        media?: { images?: string[] }
      }>(
        props.backendUrl,
        '/chat',
        {
          message: `imagine ${scene.image_prompt}`,
          mode: 'imagine',
          provider: llmProvider,
          provider_base_url: props.baseUrlImages,
          provider_model: props.modelImages,
          imgWidth: props.imgWidth || 1344,
          imgHeight: props.imgHeight || 768,
          imgSteps: props.imgSteps,
          imgCfg: props.imgCfg,
          nsfwMode: props.nsfwMode,
          promptRefinement: false, // Already refined by story mode
        },
        authKey
      )

      const imageUrl = data?.media?.images?.[0]
      if (imageUrl) {
        // Update scene with image URL
        setCurrentStory((prev) => {
          if (!prev) return prev
          return {
            ...prev,
            scenes: prev.scenes.map((s) => (s.idx === scene.idx ? { ...s, image_url: imageUrl } : s)),
          }
        })
      }
    } catch (err: any) {
      console.error('Failed to generate image:', err)
    } finally {
      setIsGeneratingImage(false)
    }
  }

  // Auto-play logic
  useEffect(() => {
    if (isPlaying && currentStory && currentStory.scenes.length > 0) {
      const currentScene = currentStory.scenes[currentSceneIndex]
      const duration = (currentScene?.duration_s || 7) * 1000

      timerRef.current = setTimeout(() => {
        if (currentSceneIndex < currentStory.scenes.length - 1) {
          setCurrentSceneIndex((prev) => prev + 1)
        } else {
          // End of story
          setIsPlaying(false)
        }
      }, duration)

      return () => {
        if (timerRef.current) clearTimeout(timerRef.current)
      }
    }
  }, [isPlaying, currentSceneIndex, currentStory])

  const toggleFullscreen = () => {
    if (!playerRef.current) return
    if (!document.fullscreenElement) {
      playerRef.current.requestFullscreen()
      setIsFullscreen(true)
    } else {
      document.exitFullscreen()
      setIsFullscreen(false)
    }
  }

  const currentScene = currentStory?.scenes[currentSceneIndex]

  // -----------------------------------------------------------------------------
  // Render: Story List
  // -----------------------------------------------------------------------------
  if (view === 'list') {
    return (
      <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex justify-between items-center px-6 py-4 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-white/10 flex items-center justify-center">
              <Tv2 size={18} className="text-purple-400" />
            </div>
            <div>
              <div className="text-sm font-semibold text-white leading-tight">HomePilot</div>
              <div className="text-xs text-white/50 leading-tight">Studio</div>
            </div>
          </div>

          <button
            onClick={() => setView('create')}
            className="flex items-center gap-2 bg-purple-500 hover:bg-purple-600 px-4 py-2 rounded-full text-sm font-semibold transition-all"
            type="button"
          >
            <Plus size={16} />
            New Story
          </button>
        </div>

        {/* Story List */}
        <div className="flex-1 overflow-y-auto p-6">
          {loadingSessions ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-white/50">
              <Film size={48} className="mb-4 opacity-50" />
              <p className="text-lg font-semibold mb-2">No stories yet</p>
              <p className="text-sm">Create your first AI-generated story</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className="bg-white/5 border border-white/10 rounded-2xl p-5 hover:border-white/20 transition-colors group cursor-pointer"
                  onClick={() => {
                    loadStory(session.id)
                    setView('player')
                  }}
                >
                  <div className="flex items-start justify-between mb-3">
                    <h3 className="text-lg font-semibold text-white">{session.title}</h3>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        deleteStory(session.id)
                      }}
                      className="opacity-0 group-hover:opacity-100 p-1 text-red-400 hover:text-red-300 transition-all"
                      type="button"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                  <p className="text-sm text-white/60 line-clamp-2 mb-3">{session.premise}</p>
                  <div className="text-xs text-white/40">
                    {new Date(session.updated_at * 1000).toLocaleDateString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  // -----------------------------------------------------------------------------
  // Render: Create Story
  // -----------------------------------------------------------------------------
  if (view === 'create') {
    return (
      <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center px-6 py-4 border-b border-white/10">
          <button
            onClick={() => setView('list')}
            className="mr-4 p-2 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors"
            type="button"
          >
            <ChevronLeft size={20} />
          </button>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-white/10 flex items-center justify-center">
              <Plus size={18} className="text-purple-400" />
            </div>
            <div>
              <div className="text-sm font-semibold text-white leading-tight">Create New Story</div>
              <div className="text-xs text-white/50 leading-tight">AI-powered visual storytelling</div>
            </div>
          </div>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-2xl mx-auto space-y-6">
            <div>
              <label className="text-sm font-semibold text-white/70 mb-2 block">Story Premise *</label>
              <textarea
                value={premise}
                onChange={(e) => setPremise(e.target.value)}
                placeholder="A cyberpunk detective in Naples solves surreal crimes in the neon rain..."
                className="w-full h-40 bg-white/5 border border-white/10 rounded-xl p-4 text-white placeholder-white/30 focus:border-purple-500/50 focus:outline-none resize-none"
              />
              <p className="text-xs text-white/40 mt-1">
                Describe your story concept. Be creative - the AI will build a complete world from this.
              </p>
            </div>

            <div>
              <label className="text-sm font-semibold text-white/70 mb-2 block">Title Hint (optional)</label>
              <input
                type="text"
                value={titleHint}
                onChange={(e) => setTitleHint(e.target.value)}
                placeholder="Neon Tide"
                className="w-full bg-white/5 border border-white/10 rounded-xl p-4 text-white placeholder-white/30 focus:border-purple-500/50 focus:outline-none"
              />
            </div>

            <button
              onClick={createStory}
              disabled={!premise.trim() || isCreating}
              className={`w-full py-4 rounded-xl font-semibold text-lg transition-all flex items-center justify-center gap-2 ${
                premise.trim() && !isCreating
                  ? 'bg-gradient-to-r from-purple-500 to-pink-500 text-white hover:opacity-90'
                  : 'bg-white/10 text-white/40 cursor-not-allowed'
              }`}
              type="button"
            >
              {isCreating ? (
                <>
                  <div className="animate-spin w-5 h-5 border-2 border-white border-t-transparent rounded-full" />
                  Creating Story Bible...
                </>
              ) : (
                <>
                  <Film size={20} />
                  Create Story
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // -----------------------------------------------------------------------------
  // Render: Player
  // -----------------------------------------------------------------------------
  return (
    <div ref={playerRef} className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col">
      {/* Header */}
      {!isFullscreen && (
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div className="flex items-center gap-4">
            <button
              onClick={() => {
                setView('list')
                setIsPlaying(false)
                loadSessions()
              }}
              className="p-2 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors"
              type="button"
            >
              <ChevronLeft size={20} />
            </button>
            <div>
              <div className="text-lg font-semibold text-white">{currentStory?.title || 'Loading...'}</div>
              <div className="text-xs text-white/50">
                Scene {currentSceneIndex + 1} of {currentStory?.scenes.length || 0}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowBible(true)}
              className="p-2 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors"
              type="button"
              title="Story Bible"
            >
              <BookOpen size={20} />
            </button>
            <button
              onClick={toggleFullscreen}
              className="p-2 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors"
              type="button"
              title="Fullscreen"
            >
              <Maximize2 size={20} />
            </button>
          </div>
        </div>
      )}

      {/* Main Stage */}
      <div className="flex-1 relative overflow-hidden bg-gradient-to-b from-black to-gray-900">
        {/* Image Display */}
        {currentScene?.image_url ? (
          <img
            src={currentScene.image_url}
            alt={`Scene ${currentScene.idx}`}
            className="absolute inset-0 w-full h-full object-contain transition-opacity duration-1000"
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            {isGeneratingImage ? (
              <div className="text-center">
                <div className="animate-spin w-12 h-12 border-3 border-purple-500 border-t-transparent rounded-full mx-auto mb-4" />
                <p className="text-white/50">Generating image...</p>
              </div>
            ) : currentScene ? (
              <div className="text-center p-8 max-w-2xl">
                <p className="text-white/50 mb-4">No image for this scene yet</p>
                <button
                  onClick={() => generateImageForScene(currentScene)}
                  className="px-6 py-3 bg-purple-500 hover:bg-purple-600 rounded-full font-semibold transition-colors"
                  type="button"
                >
                  Generate Image
                </button>
              </div>
            ) : (
              <div className="text-center">
                <p className="text-white/50 mb-4">No scenes yet</p>
                <button
                  onClick={generateNextScene}
                  disabled={isGeneratingScene}
                  className="px-6 py-3 bg-purple-500 hover:bg-purple-600 rounded-full font-semibold transition-colors disabled:opacity-50"
                  type="button"
                >
                  {isGeneratingScene ? 'Generating...' : 'Generate First Scene'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* Narration Subtitle */}
        {currentScene && (
          <div className="absolute bottom-24 left-0 right-0 flex justify-center px-8">
            <div className="bg-black/80 backdrop-blur-sm px-6 py-4 rounded-xl max-w-3xl">
              <p className="text-lg text-white leading-relaxed text-center">{currentScene.narration}</p>
            </div>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="border-t border-white/10 bg-black/50 backdrop-blur-sm p-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          {/* Left: Scene navigation */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCurrentSceneIndex((prev) => Math.max(0, prev - 1))}
              disabled={currentSceneIndex === 0}
              className="p-3 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors disabled:opacity-30"
              type="button"
            >
              <SkipBack size={20} />
            </button>

            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className="p-4 bg-purple-500 hover:bg-purple-600 rounded-full transition-colors"
              type="button"
            >
              {isPlaying ? <Pause size={24} /> : <Play size={24} fill="currentColor" />}
            </button>

            <button
              onClick={() =>
                setCurrentSceneIndex((prev) => Math.min((currentStory?.scenes.length || 1) - 1, prev + 1))
              }
              disabled={!currentStory || currentSceneIndex >= currentStory.scenes.length - 1}
              className="p-3 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors disabled:opacity-30"
              type="button"
            >
              <SkipForward size={20} />
            </button>
          </div>

          {/* Center: Progress */}
          <div className="flex-1 mx-8">
            <div className="flex gap-1">
              {currentStory?.scenes.map((_, i) => (
                <button
                  key={i}
                  onClick={() => setCurrentSceneIndex(i)}
                  className={`flex-1 h-1 rounded-full transition-colors ${
                    i === currentSceneIndex
                      ? 'bg-purple-500'
                      : i < currentSceneIndex
                      ? 'bg-white/30'
                      : 'bg-white/10'
                  }`}
                  type="button"
                />
              ))}
            </div>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsMuted(!isMuted)}
              className="p-3 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors"
              type="button"
            >
              {isMuted ? <VolumeX size={20} /> : <Volume2 size={20} />}
            </button>

            <button
              onClick={generateNextScene}
              disabled={isGeneratingScene}
              className="flex items-center gap-2 px-4 py-2 bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 rounded-full transition-colors disabled:opacity-50"
              type="button"
            >
              {isGeneratingScene ? (
                <>
                  <div className="animate-spin w-4 h-4 border-2 border-purple-300 border-t-transparent rounded-full" />
                  Generating...
                </>
              ) : (
                <>
                  <Plus size={16} />
                  Next Scene
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Story Bible Modal */}
      {showBible && currentStory && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4 backdrop-blur-md"
          onClick={() => setShowBible(false)}
        >
          <div
            className="max-w-3xl w-full max-h-[80vh] bg-[#121212] border border-white/10 rounded-2xl overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-5 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <BookOpen size={20} className="text-purple-400" />
                Story Bible
              </h3>
              <button
                type="button"
                onClick={() => setShowBible(false)}
                className="text-white/50 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>

            <div className="overflow-y-auto max-h-[60vh] p-6 space-y-6">
              <div>
                <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-2">Logline</h4>
                <p className="text-white/90">{currentStory.bible.logline}</p>
              </div>

              <div>
                <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-2">Setting</h4>
                <p className="text-white/90">{currentStory.bible.setting}</p>
              </div>

              {currentStory.bible.recurring_characters.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <Users size={14} />
                    Characters
                  </h4>
                  <div className="space-y-2">
                    {currentStory.bible.recurring_characters.map((char, i) => (
                      <div key={i} className="bg-white/5 rounded-lg p-3">
                        <div className="font-semibold text-white">{char.name}</div>
                        <div className="text-sm text-white/60">{char.description}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {currentStory.bible.recurring_locations.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <MapPin size={14} />
                    Locations
                  </h4>
                  <div className="flex flex-wrap gap-2">
                    {currentStory.bible.recurring_locations.map((loc, i) => (
                      <span key={i} className="px-3 py-1 bg-white/5 rounded-full text-sm text-white/70">
                        {loc}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {currentStory.bible.visual_style_rules.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-2">
                    Visual Style Rules
                  </h4>
                  <ul className="space-y-1">
                    {currentStory.bible.visual_style_rules.map((rule, i) => (
                      <li key={i} className="text-sm text-white/70">
                        • {rule}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {currentStory.bible.do_not_change.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-white/50 uppercase tracking-wider mb-2">
                    Consistency Rules
                  </h4>
                  <ul className="space-y-1">
                    {currentStory.bible.do_not_change.map((rule, i) => (
                      <li key={i} className="text-sm text-white/70">
                        • {rule}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`
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
