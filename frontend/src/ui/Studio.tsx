import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import {
  Play,
  Pause,
  Plus,
  Settings2,
  X,
  Tv2,
  Film,
  Trash2,
  ChevronLeft,
  BookOpen,
  Users,
  MapPin,
  Maximize2,
} from 'lucide-react'
import { useTVModeStore } from './studio/stores/tvModeStore'
import type { TVScene } from './studio/stores/tvModeStore'
import { TVModeContainer } from './studio/components/TVMode'
import { SceneChips, StudioPreviewPanel, StudioActions, StudioEmptyState } from './studio/components'
import type { SceneChipData } from './studio/components'

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

type CreatorProject = {
  id: string
  title: string
  logline: string
  status: 'draft' | 'in_review' | 'approved' | 'archived'
  updatedAt: number
  platformPreset: 'youtube_16_9' | 'shorts_9_16' | 'slides_16_9'
  contentRating: 'sfw' | 'mature'
}

// Unified project type for display
type UnifiedProject = {
  id: string
  title: string
  description: string
  type: 'play' | 'creator'
  status: 'draft' | 'finished'
  updatedAt: number
  raw: StorySession | CreatorProject
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
  // Callback to switch to Creator Studio mode (optional projectId to open existing project)
  onOpenCreatorStudio?: (projectId?: string) => void
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

/**
 * Format a timestamp for display, handling epoch dates (1970) gracefully.
 * Returns "Just now" for missing/invalid dates, otherwise a formatted date.
 */
function formatDate(timestamp: number): string {
  // Check for invalid/epoch dates (anything before year 2000 is likely a bug)
  if (!timestamp || timestamp < 946684800000) { // Jan 1, 2000 in ms
    return "Just now"
  }

  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffDays === 0) return "Today"
  if (diffDays === 1) return "Yesterday"
  if (diffDays < 7) return `${diffDays} days ago`

  return date.toLocaleDateString()
}

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

  // TV Mode state
  const { isActive: tvModeActive, enterTVMode, addScene: addTVScene, updateSceneImageByIdx, setSceneImageStatusByIdx, setStoryComplete, isStoryComplete } = useTVModeStore()

  // View state
  const [view, setView] = useState<'list' | 'create' | 'player'>('list')
  const [showModeChooser, setShowModeChooser] = useState(false)

  // Get default story mode from localStorage
  const getDefaultStoryMode = () => {
    try {
      return localStorage.getItem('hp_default_story_mode') as 'play' | 'creator' | null
    } catch {
      return null
    }
  }

  const setDefaultStoryMode = (mode: 'play' | 'creator') => {
    try {
      localStorage.setItem('hp_default_story_mode', mode)
    } catch {
      // ignore
    }
  }

  const handleNewStoryClick = () => {
    // Always show the mode chooser when Creator Studio is available
    // This gives users the choice each time instead of auto-remembering
    if (props.onOpenCreatorStudio) {
      setShowModeChooser(true)
    } else {
      // No Creator Studio available, go directly to Play create view
      setView('create')
    }
  }

  const handleChoosePlay = () => {
    setDefaultStoryMode('play')
    setShowModeChooser(false)
    setView('create')
  }

  const handleChooseCreator = () => {
    if (props.onOpenCreatorStudio) {
      setDefaultStoryMode('creator')
      setShowModeChooser(false)
      props.onOpenCreatorStudio()
    }
  }

  // Story list
  const [sessions, setSessions] = useState<StorySession[]>([])
  const [creatorProjects, setCreatorProjects] = useState<CreatorProject[]>([])
  const [loadingSessions, setLoadingSessions] = useState(true)

  // Unified projects list (memoized)
  const unifiedProjects = useMemo((): UnifiedProject[] => {
    const playProjects: UnifiedProject[] = sessions.map((s) => ({
      id: s.id,
      title: s.title,
      description: s.premise,
      type: 'play' as const,
      status: 'draft' as const, // Play stories are always "in progress"
      updatedAt: s.updated_at * 1000,
      raw: s,
    }))

    const creatorProjectsMapped: UnifiedProject[] = creatorProjects.map((p) => ({
      id: p.id,
      title: p.title,
      description: p.logline,
      type: 'creator' as const,
      status: p.status === 'approved' ? 'finished' as const : 'draft' as const,
      updatedAt: p.updatedAt,
      raw: p,
    }))

    // Sort by updated time, most recent first
    return [...playProjects, ...creatorProjectsMapped].sort((a, b) => b.updatedAt - a.updatedAt)
  }, [sessions, creatorProjects])

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
  const [isCreatingChapter, setIsCreatingChapter] = useState(false)
  const [showChapterSettings, setShowChapterSettings] = useState(false)
  const [chapterHint, setChapterHint] = useState('')

  // Image generation queue to prevent dropped requests
  // Store scene data directly to avoid stale closure issues with currentStory
  // Include retry count for automatic retries on failure
  const imageQueueRef = useRef<Map<number, { image_prompt: string; negative_prompt?: string; session_id: string; retryCount?: number }>>(new Map())
  const MAX_IMAGE_RETRIES = 3
  const imageInFlightRef = useRef<number | null>(null)
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
      // Fetch both Play Story sessions and Creator Studio projects in parallel
      const [storyData, creatorData] = await Promise.allSettled([
        fetchJson<{ ok: boolean; sessions: StorySession[] }>(
          props.backendUrl,
          '/story/sessions/list',
          authKey
        ),
        fetchJson<{ videos: CreatorProject[] }>(
          props.backendUrl,
          '/studio/videos',
          authKey
        ),
      ])

      // Handle Play Story sessions
      if (storyData.status === 'fulfilled') {
        setSessions(storyData.value.sessions || [])
      } else {
        console.error('Failed to load story sessions:', storyData.reason)
        setSessions([])
      }

      // Handle Creator Studio projects (may not exist on all backends)
      if (creatorData.status === 'fulfilled') {
        setCreatorProjects(creatorData.value.videos || [])
      } else {
        // Silently fail - Creator Studio endpoint may not exist
        setCreatorProjects([])
      }
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
      // Step 1: Create story bible
      const storyData = await postJson<{
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

      console.log('[Studio] Story bible created:', storyData.title)

      // Step 2: Auto-generate first scene
      setIsGeneratingScene(true)
      const sceneData = await postJson<{
        ok: boolean
        scene?: Scene
        story_complete?: boolean
        message?: string
      }>(
        props.backendUrl,
        '/story/next',
        {
          session_id: storyData.session_id,
          refine_image_prompt: props.promptRefinement ?? true,
        },
        authKey
      )

      if (!sceneData.scene) {
        throw new Error('Failed to generate first scene')
      }

      console.log('[Studio] First scene generated')

      // Step 3: Load the full story with the first scene
      const fullStory = await fetchJson<StoryData>(props.backendUrl, `/story/${storyData.session_id}`, authKey)
      setCurrentStory(fullStory)
      setCurrentSceneIndex(0)
      setIsPlaying(false)
      setStoryComplete(false)

      // Switch to player view
      setView('player')
      setPremise('')
      setTitleHint('')

      // Step 4: Auto-generate image for the first scene
      if (fullStory.scenes.length > 0) {
        const firstScene = fullStory.scenes[0]
        generateImageForScene(firstScene, storyData.session_id)
      }
    } catch (err: any) {
      alert(`Failed to create story: ${err.message || err}`)
    } finally {
      setIsCreating(false)
      setIsGeneratingScene(false)
    }
  }

  const loadStory = async (sessionId: string) => {
    try {
      const data = await fetchJson<StoryData>(props.backendUrl, `/story/${sessionId}`, authKey)
      setCurrentStory(data)
      setCurrentSceneIndex(0)
      setIsPlaying(false)
      setStoryComplete(false) // Reset story complete state when loading a different story
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

  const deleteScene = async (sceneIdx: number) => {
    if (!currentStory) {
      console.error('[Studio] deleteScene: No current story')
      return
    }

    console.log('[Studio] Deleting scene:', sceneIdx, 'from story:', currentStory.session_id)

    // Find the array index before deleting
    const deletedArrayIndex = currentStory.scenes.findIndex((s) => s.idx === sceneIdx)
    if (deletedArrayIndex < 0) {
      console.error('[Studio] deleteScene: Scene not found in array, sceneIdx:', sceneIdx)
      return
    }

    try {
      const result = await deleteJson<{ ok: boolean; deleted?: boolean; error?: string }>(
        props.backendUrl,
        `/story/${currentStory.session_id}/scene/${sceneIdx}`,
        authKey
      )
      console.log('[Studio] Delete response:', result)

      if (!result.ok) {
        throw new Error(result.error || 'Delete failed')
      }

      // Update local state - re-index scenes
      setCurrentStory((prev) => {
        if (!prev) return prev
        const newScenes = prev.scenes
          .filter((s) => s.idx !== sceneIdx)
          .map((s, i) => ({ ...s, idx: i })) // Re-index

        console.log('[Studio] Updated scenes count:', newScenes.length)
        return { ...prev, scenes: newScenes }
      })

      // Adjust current scene index if needed (after state update to avoid race)
      if (deletedArrayIndex <= currentSceneIndex) {
        const newIndex = Math.max(0, currentSceneIndex - 1)
        console.log('[Studio] Adjusting currentSceneIndex from', currentSceneIndex, 'to', newIndex)
        setCurrentSceneIndex(newIndex)
      }
    } catch (err: any) {
      console.error('[Studio] Delete scene error:', err)
      alert(`Failed to delete scene: ${err.message || err}`)
    }
  }

  const generateNextScene = async () => {
    if (!currentStory || isGeneratingScene) return
    setIsGeneratingScene(true)

    try {
      const data = await postJson<{
        ok: boolean
        session_id?: string
        title?: string
        scene?: Scene
        bible?: StoryBible
        story_complete?: boolean
        message?: string
      }>(
        props.backendUrl,
        '/story/next',
        {
          session_id: currentStory.session_id,
          refine_image_prompt: props.promptRefinement ?? true,
        },
        authKey
      )

      // Check if story is complete (no more scenes can be generated for this chapter)
      if (data.story_complete) {
        console.log('[Studio] Chapter complete -', data.message)
        console.log('[Studio] Automatically starting next chapter...')

        // Auto-continue to next chapter
        try {
          const chapterData = await postJson<{
            ok: boolean
            session_id: string
            title: string
            chapter_number: number
            bible: StoryBible
            saga_id: string
            previous_session_id: string
          }>(
            props.backendUrl,
            '/story/continue',
            {
              previous_session_id: currentStory.session_id,
            },
            authKey
          )

          console.log(`[Studio] Started chapter ${chapterData.chapter_number}: ${chapterData.title}`)

          // Generate first scene of new chapter
          const firstSceneData = await postJson<{
            ok: boolean
            scene?: Scene
            story_complete?: boolean
            message?: string
          }>(
            props.backendUrl,
            '/story/next',
            {
              session_id: chapterData.session_id,
              refine_image_prompt: props.promptRefinement ?? true,
            },
            authKey
          )

          if (!firstSceneData.scene) {
            throw new Error('Failed to generate first scene of new chapter')
          }

          console.log('[Studio] First scene of new chapter generated')

          // Load the full story with the first scene
          const fullStory = await fetchJson<StoryData>(props.backendUrl, `/story/${chapterData.session_id}`, authKey)
          setCurrentStory(fullStory)
          setCurrentSceneIndex(0)
          setStoryComplete(false)

          // Add the new chapter to the sessions list
          const now = Date.now()
          setSessions((prev) => [
            {
              id: chapterData.session_id,
              title: chapterData.title,
              premise: `Chapter ${chapterData.chapter_number} continuation`,
              created_at: now,
              updated_at: now,
            },
            ...prev,
          ])

          // Generate image for the first scene
          if (fullStory.scenes.length > 0) {
            generateImageForScene(fullStory.scenes[0], chapterData.session_id)
          }

          return // Successfully continued to new chapter
        } catch (continueErr: any) {
          console.error('[Studio] Failed to auto-continue chapter:', continueErr)
          // Fall back to showing completion message
          setStoryComplete(true)
          alert('Chapter complete! Click "New Chapter" to continue the story.')
          return
        }
      }

      // Make sure we have a valid scene before adding
      if (!data.scene) {
        throw new Error('No scene returned from backend')
      }

      // Add new scene to current story
      setCurrentStory((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          scenes: [...prev.scenes, data.scene!],
        }
      })

      // Move to the new scene
      setCurrentSceneIndex(currentStory.scenes.length)

      // Generate image for the new scene (pass session_id to avoid stale closure)
      await generateImageForScene(data.scene, currentStory.session_id)
    } catch (err: any) {
      alert(`Failed to generate scene: ${err.message || err}`)
    } finally {
      setIsGeneratingScene(false)
    }
  }

  // Process the image generation queue
  const processImageQueue = useCallback(async () => {
    // Already processing?
    if (imageInFlightRef.current !== null) return

    // Get next scene from queue (stored with its data to avoid stale closure)
    const nextEntry = imageQueueRef.current.entries().next().value
    if (!nextEntry) {
      setIsGeneratingImage(false)
      return
    }

    const [nextIdx, sceneData] = nextEntry as [number, { image_prompt: string; negative_prompt?: string; session_id: string; retryCount?: number }]
    imageInFlightRef.current = nextIdx
    imageQueueRef.current.delete(nextIdx)

    const currentRetry = sceneData.retryCount || 0

    // Helper to re-queue for retry with delay
    const requeue = async (reason: string) => {
      if (currentRetry < MAX_IMAGE_RETRIES) {
        const nextRetry = currentRetry + 1
        const delayMs = Math.min(1000 * Math.pow(2, currentRetry), 8000) // 1s, 2s, 4s, 8s max
        console.warn(`[IMAGE] ${reason} for scene ${nextIdx}, retry ${nextRetry}/${MAX_IMAGE_RETRIES} in ${delayMs}ms`)

        // Wait before retrying (exponential backoff)
        await new Promise(resolve => setTimeout(resolve, delayMs))

        // Re-add to queue with incremented retry count
        imageQueueRef.current.set(nextIdx, { ...sceneData, retryCount: nextRetry })
      } else {
        console.error(`[IMAGE] Max retries (${MAX_IMAGE_RETRIES}) exceeded for scene ${nextIdx}, giving up`)
        // Mark as failed in TV Mode if active
        // IMPORTANT: Check current state at runtime, not closure value
        if (useTVModeStore.getState().isActive) {
          setSceneImageStatusByIdx(nextIdx, 'error')
        }
      }
    }

    try {
      const llmProvider = props.providerImages === 'comfyui' ? 'ollama' : props.providerImages

      // Use stored scene data (avoids stale currentStory closure)
      if (!sceneData?.image_prompt) {
        console.warn(`Scene ${nextIdx} has no image_prompt for generation`)
        return
      }

      const data = await postJson<{
        media?: { images?: string[] }
      }>(
        props.backendUrl,
        '/chat',
        {
          message: `imagine ${sceneData.image_prompt}`,
          mode: 'imagine',
          provider: llmProvider,
          provider_base_url: props.baseUrlImages,
          imgModel: props.modelImages || undefined,
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
        // Success! Update scene with image URL in state
        setCurrentStory((prev) => {
          if (!prev) return prev
          return {
            ...prev,
            scenes: prev.scenes.map((s) => (s.idx === nextIdx ? { ...s, image_url: imageUrl } : s)),
          }
        })

        // Also update TV Mode store if active (for sync) - use ByIdx variant
        // IMPORTANT: Check current state at runtime, not closure value, to avoid race condition
        // where user enters TV mode while images are generating
        if (useTVModeStore.getState().isActive) {
          updateSceneImageByIdx(nextIdx, imageUrl)
        }

        // Persist image URL to database so it survives page reload
        try {
          await postJson(
            props.backendUrl,
            '/story/scene/image',
            {
              session_id: sceneData.session_id,
              scene_idx: nextIdx,
              image_url: imageUrl,
            },
            authKey
          )
        } catch (persistErr) {
          console.error('Failed to persist image URL:', persistErr)
          // Image is still shown in UI, just won't survive reload
        }
      } else {
        // No image returned (0 images from ComfyUI) - retry
        await requeue('No image returned from backend')
      }
    } catch (err: any) {
      console.error('Failed to generate image:', err)
      // Network or server error - retry
      await requeue(`Error: ${err.message || err}`)
    } finally {
      imageInFlightRef.current = null
      // Process next item in queue if any
      if (imageQueueRef.current.size > 0) {
        processImageQueue()
      } else {
        setIsGeneratingImage(false)
      }
    }
  }, [props.backendUrl, props.providerImages, props.baseUrlImages, props.modelImages, props.imgWidth, props.imgHeight, props.imgSteps, props.imgCfg, props.nsfwMode, authKey, updateSceneImageByIdx, setSceneImageStatusByIdx])

  // Enqueue image generation for a scene
  // Set force=true to regenerate even if image already exists
  const generateImageForScene = useCallback((scene: Scene | TVScene, sessionId?: string, force: boolean = false) => {
    // Already has image? Skip unless force regenerate
    const hasImage = Boolean((scene as Scene).image_url || (scene as TVScene).image_url || (scene as TVScene).image)
    if (hasImage && !force) return

    // Already in queue or in flight?
    if (imageQueueRef.current.has(scene.idx) || imageInFlightRef.current === scene.idx) {
      console.log('[Studio] Image generation already queued/in-flight for scene:', scene.idx)
      return
    }

    // Get session_id from parameter or current story
    const storySessionId = sessionId || currentStory?.session_id
    if (!storySessionId) {
      console.warn('No session_id available for image generation')
      return
    }

    console.log('[Studio] Queueing image generation for scene:', scene.idx, force ? '(forced regenerate)' : '')

    // Mark as generating in TV Mode store
    // IMPORTANT: Check current state at runtime, not closure value
    if (useTVModeStore.getState().isActive) {
      setSceneImageStatusByIdx(scene.idx, 'generating')
    }

    // Add to queue with scene data (avoids stale closure when processing)
    imageQueueRef.current.set(scene.idx, {
      image_prompt: scene.image_prompt,
      negative_prompt: scene.negative_prompt,
      session_id: storySessionId,
    })
    setIsGeneratingImage(true)
    processImageQueue()
  }, [setSceneImageStatusByIdx, processImageQueue, currentStory?.session_id])

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

  // Handle entering TV Mode
  const handleEnterTVMode = useCallback(() => {
    if (!currentStory || currentStory.scenes.length === 0) return

    // Convert scenes to TV Mode format
    const tvScenes = currentStory.scenes.map((scene) => ({
      ...scene,
      status: 'ready' as const,
    }))

    enterTVMode(currentStory.session_id, currentStory.title, tvScenes, currentSceneIndex)
  }, [currentStory, currentSceneIndex, enterTVMode])

  // Generate next scene for TV Mode (prefetching)
  const generateNextForTVMode = useCallback(async () => {
    if (!currentStory) return null

    try {
      const data = await postJson<{
        ok: boolean
        session_id?: string
        title?: string
        scene?: Scene
        bible?: StoryBible
        story_complete?: boolean
        message?: string
      }>(
        props.backendUrl,
        '/story/next',
        {
          session_id: currentStory.session_id,
          refine_image_prompt: props.promptRefinement ?? true,
        },
        authKey
      )

      // Check if chapter is complete - auto-continue to next chapter
      if (data.story_complete) {
        console.log('[TV Mode] Chapter complete -', data.message)
        console.log('[TV Mode] Automatically starting next chapter...')

        try {
          // Create next chapter
          const chapterData = await postJson<{
            ok: boolean
            session_id: string
            title: string
            chapter_number: number
            bible: StoryBible
            saga_id: string
          }>(
            props.backendUrl,
            '/story/continue',
            {
              previous_session_id: currentStory.session_id,
            },
            authKey
          )

          console.log(`[TV Mode] Started chapter ${chapterData.chapter_number}: ${chapterData.title}`)

          // Generate first scene of new chapter
          const firstSceneData = await postJson<{
            ok: boolean
            scene?: Scene
          }>(
            props.backendUrl,
            '/story/next',
            {
              session_id: chapterData.session_id,
              refine_image_prompt: props.promptRefinement ?? true,
            },
            authKey
          )

          if (!firstSceneData.scene) {
            throw new Error('Failed to generate first scene of new chapter')
          }

          console.log('[TV Mode] First scene of new chapter generated')

          // Load the full story with the first scene
          const fullStory = await fetchJson<StoryData>(props.backendUrl, `/story/${chapterData.session_id}`, authKey)

          // Update current story to the new chapter
          setCurrentStory(fullStory)
          setStoryComplete(false)

          // Generate image for the first scene
          if (fullStory.scenes.length > 0) {
            generateImageForScene(fullStory.scenes[0], chapterData.session_id)
          }

          // Return the first scene so TV mode continues seamlessly
          return {
            ...firstSceneData.scene,
            status: 'ready' as const,
          }
        } catch (continueErr: any) {
          console.error('[TV Mode] Failed to auto-continue chapter:', continueErr)
          setStoryComplete(true)
          return null // Fall back to showing end screen
        }
      }

      // Make sure we have a scene
      if (!data.scene) {
        throw new Error('No scene returned from backend')
      }

      // Add new scene to current story state
      setCurrentStory((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          scenes: [...prev.scenes, data.scene!],
        }
      })

      // Generate image for the new scene in background (pass session_id to avoid stale closure)
      generateImageForScene(data.scene, currentStory.session_id)

      return {
        ...data.scene,
        status: 'ready' as const,
      }
    } catch (error: any) {
      // Check if story is complete (legacy error format for backwards compatibility)
      const errorMsg = error?.message || String(error)
      if (errorMsg.includes('Story complete') || (errorMsg.includes('All') && errorMsg.includes('scenes have been generated'))) {
        console.log('[TV Mode] Chapter complete (legacy) - auto-continuing...')

        // Try to auto-continue to next chapter
        try {
          const chapterData = await postJson<{
            ok: boolean
            session_id: string
            title: string
            chapter_number: number
            bible: StoryBible
          }>(
            props.backendUrl,
            '/story/continue',
            {
              previous_session_id: currentStory.session_id,
            },
            authKey
          )

          const firstSceneData = await postJson<{
            ok: boolean
            scene?: Scene
          }>(
            props.backendUrl,
            '/story/next',
            {
              session_id: chapterData.session_id,
              refine_image_prompt: props.promptRefinement ?? true,
            },
            authKey
          )

          if (firstSceneData.scene) {
            const fullStory = await fetchJson<StoryData>(props.backendUrl, `/story/${chapterData.session_id}`, authKey)
            setCurrentStory(fullStory)
            setStoryComplete(false)

            if (fullStory.scenes.length > 0) {
              generateImageForScene(fullStory.scenes[0], chapterData.session_id)
            }

            return {
              ...firstSceneData.scene,
              status: 'ready' as const,
            }
          }
        } catch (continueErr) {
          console.error('[TV Mode] Failed to auto-continue:', continueErr)
        }

        setStoryComplete(true)
        return null
      }
      console.error('TV Mode generate error:', error)
      throw error
    }
  }, [currentStory, props.backendUrl, props.promptRefinement, authKey, setStoryComplete, generateImageForScene])

  // Continue story as next chapter (saga mode)
  const continueAsNextChapter = useCallback(async () => {
    if (!currentStory) return null

    try {
      const data = await postJson<{
        ok: boolean
        session_id: string
        title: string
        chapter_number: number
        bible: StoryBible
        saga_id: string
        previous_session_id: string
      }>(
        props.backendUrl,
        '/story/continue',
        {
          previous_session_id: currentStory.session_id,
        },
        authKey
      )

      console.log(`[TV Mode] Started chapter ${data.chapter_number}: ${data.title}`)

      // Load the new chapter's story data
      const newStoryData = await fetchJson<StoryData>(props.backendUrl, `/story/${data.session_id}`, authKey)

      // Update current story state
      setCurrentStory(newStoryData)
      setCurrentSceneIndex(0)
      setStoryComplete(false) // Reset story complete state for new chapter

      return {
        sessionId: data.session_id,
        title: data.title,
        chapterNumber: data.chapter_number,
        scenes: newStoryData.scenes.map((scene) => ({
          ...scene,
          status: 'ready' as const,
        })),
      }
    } catch (error: any) {
      console.error('Failed to continue story:', error)
      throw error
    }
  }, [currentStory, props.backendUrl, authKey])

  // Continue to next chapter in Studio mode (with optional hint for customization)
  const continueChapterInStudio = useCallback(async () => {
    if (!currentStory || isCreatingChapter) return

    setIsCreatingChapter(true)
    setShowChapterSettings(false)

    try {
      const data = await postJson<{
        ok: boolean
        session_id: string
        title: string
        chapter_number: number
        bible: StoryBible
        saga_id: string
        previous_session_id: string
      }>(
        props.backendUrl,
        '/story/continue',
        {
          previous_session_id: currentStory.session_id,
          ...(chapterHint.trim() ? { direction_hint: chapterHint.trim() } : {}),
        },
        authKey
      )

      console.log(`[Studio] Started chapter ${data.chapter_number}: ${data.title}`)

      // Load the new chapter's story data
      const newStoryData = await fetchJson<StoryData>(props.backendUrl, `/story/${data.session_id}`, authKey)

      // Update current story state - new chapter continues seamlessly
      setCurrentStory(newStoryData)
      setCurrentSceneIndex(0)
      setStoryComplete(false)
      setChapterHint('') // Clear hint after use

      // Add the new chapter to the sessions list so it appears in the list view
      const now = Date.now()
      setSessions((prev) => [
        {
          id: data.session_id,
          title: data.title,
          premise: `Chapter ${data.chapter_number} continuation`,
          created_at: now,
          updated_at: now,
        },
        ...prev,
      ])
    } catch (error: any) {
      console.error('Failed to create new chapter:', error)
      alert(`Failed to create new chapter: ${error.message || error}`)
    } finally {
      setIsCreatingChapter(false)
    }
  }, [currentStory, isCreatingChapter, chapterHint, props.backendUrl, authKey, setStoryComplete])

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
            onClick={handleNewStoryClick}
            className="flex items-center gap-2 bg-purple-500 hover:bg-purple-600 px-4 py-2 rounded-full text-sm font-semibold transition-all"
            type="button"
          >
            <Plus size={16} />
            Create Story
          </button>
        </div>

        {/* Project List */}
        <div className="flex-1 overflow-y-auto p-6">
          {loadingSessions ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full" />
            </div>
          ) : unifiedProjects.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-white/50">
              <Film size={48} className="mb-4 opacity-50" />
              <p className="text-lg font-semibold mb-2">No stories yet</p>
              <p className="text-sm">Create your first AI-generated story</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {unifiedProjects.map((project) => (
                <div
                  key={`${project.type}-${project.id}`}
                  className={`bg-white/5 border rounded-2xl p-5 hover:border-white/20 transition-colors group cursor-pointer ${
                    project.type === 'creator' ? 'border-blue-500/30' : 'border-white/10'
                  }`}
                  onClick={() => {
                    if (project.type === 'play') {
                      loadStory(project.id)
                      setView('player')
                    } else if (project.type === 'creator' && props.onOpenCreatorStudio) {
                      // Open Creator Studio with project ID to open the editor
                      props.onOpenCreatorStudio(project.id)
                    }
                  }}
                >
                  {/* Type & Status Badges */}
                  <div className="flex items-center gap-2 mb-3">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        project.type === 'creator'
                          ? 'bg-blue-500/20 text-blue-300'
                          : 'bg-purple-500/20 text-purple-300'
                      }`}
                    >
                      {project.type === 'creator' ? 'Creator Studio' : 'Play Story'}
                    </span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        project.status === 'finished'
                          ? 'bg-green-500/20 text-green-300'
                          : 'bg-yellow-500/20 text-yellow-300'
                      }`}
                    >
                      {project.status === 'finished' ? 'Finished' : 'Draft'}
                    </span>
                  </div>

                  <div className="flex items-start justify-between mb-3">
                    <h3 className="text-lg font-semibold text-white">{project.title}</h3>
                    {project.type === 'play' && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          deleteStory(project.id)
                        }}
                        className="opacity-0 group-hover:opacity-100 p-1 text-red-400 hover:text-red-300 transition-all"
                        type="button"
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                  <p className="text-sm text-white/60 line-clamp-2 mb-3">{project.description}</p>
                  <div className="text-xs text-white/40">
                    {formatDate(project.updatedAt)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Mode Chooser Modal */}
        {showModeChooser && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
            <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl p-8 max-w-lg w-full mx-4 shadow-2xl">
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-xl font-bold text-white">Choose Your Studio</h2>
                <button
                  onClick={() => setShowModeChooser(false)}
                  className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-full transition-colors"
                >
                  <X size={20} />
                </button>
              </div>

              <div className="space-y-4">
                {/* Play Studio Option */}
                <button
                  onClick={handleChoosePlay}
                  className="w-full p-6 bg-gradient-to-r from-purple-500/10 to-pink-500/10 border border-purple-500/30 rounded-xl text-left hover:border-purple-500/60 hover:bg-purple-500/20 transition-all group"
                >
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center flex-shrink-0">
                      <Play size={24} className="text-white" />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-white mb-1">Play Story</h3>
                      <p className="text-sm text-white/60">
                        Simple, relaxing story creation. Just enter a premise and watch your story come to life with AI-generated scenes and images.
                      </p>
                      <span className="inline-block mt-2 text-xs text-purple-400 font-medium">Recommended for beginners</span>
                    </div>
                  </div>
                </button>

                {/* Creator Studio Option */}
                {props.onOpenCreatorStudio && (
                  <button
                    onClick={handleChooseCreator}
                    className="w-full p-6 bg-gradient-to-r from-blue-500/10 to-cyan-500/10 border border-blue-500/30 rounded-xl text-left hover:border-blue-500/60 hover:bg-blue-500/20 transition-all group"
                  >
                    <div className="flex items-start gap-4">
                      <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center flex-shrink-0">
                        <Settings2 size={24} className="text-white" />
                      </div>
                      <div>
                        <h3 className="text-lg font-semibold text-white mb-1">Creator Studio</h3>
                        <p className="text-sm text-white/60">
                          Full project-based workflow with presets, policy controls, export options, and advanced generation settings.
                        </p>
                        <span className="inline-block mt-2 text-xs text-blue-400 font-medium">Advanced features</span>
                      </div>
                    </div>
                  </button>
                )}
              </div>

              <p className="text-xs text-white/40 text-center mt-6">
                Your choice will be remembered for next time
              </p>
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
                  {isGeneratingScene ? 'Generating First Scene...' : 'Creating Story Bible...'}
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

      {/* Scene Chips Rail */}
      {currentStory && currentStory.scenes.length > 0 && (
        <SceneChips
          scenes={currentStory.scenes.map((scene) => ({
            idx: scene.idx,
            status: scene.image_url ? 'ready' : (isGeneratingImage && scene.idx === currentScene?.idx ? 'generating' : 'pending'),
            thumbnailUrl: scene.image_url,
          } as SceneChipData))}
          activeIndex={currentScene?.idx ?? 0}
          onSelect={(sceneIdx) => {
            // Convert scene.idx to array index
            const arrayIndex = currentStory.scenes.findIndex(s => s.idx === sceneIdx)
            if (arrayIndex >= 0) setCurrentSceneIndex(arrayIndex)
          }}
          onDelete={deleteScene}
          className="border-b border-white/10"
        />
      )}

      {/* Main Preview Area */}
      {currentStory && currentStory.scenes.length > 0 ? (
        <StudioPreviewPanel
          imageUrl={currentScene?.image_url}
          isGenerating={isGeneratingImage}
          narration={currentScene?.narration}
          prompt={currentScene?.image_prompt}
          onRegenerateImage={currentScene ? () => generateImageForScene(currentScene, undefined, true) : undefined}
        />
      ) : (
        <StudioEmptyState
          isGenerating={isGeneratingScene}
          generatingLabel="Creating your first scene..."
          onGenerateFirstScene={generateNextScene}
        />
      )}

      {/* Action Bar */}
      <StudioActions
        isPlaying={isPlaying}
        onTogglePlay={() => setIsPlaying(!isPlaying)}
        canGoBack={currentSceneIndex > 0}
        canGoForward={currentStory ? currentSceneIndex < currentStory.scenes.length - 1 : false}
        onPrevScene={() => setCurrentSceneIndex((prev) => Math.max(0, prev - 1))}
        onNextScene={() => setCurrentSceneIndex((prev) => Math.min((currentStory?.scenes.length || 1) - 1, prev + 1))}
        isGeneratingScene={isGeneratingScene}
        onGenerateNextScene={generateNextScene}
        isStoryComplete={isStoryComplete}
        onContinueChapter={continueChapterInStudio}
        isCreatingChapter={isCreatingChapter}
        onShowChapterSettings={() => setShowChapterSettings(true)}
        currentIndex={currentSceneIndex}
        totalScenes={currentStory?.scenes.length || 0}
        onSelectScene={setCurrentSceneIndex}
        isMuted={isMuted}
        onToggleMute={() => setIsMuted(!isMuted)}
        onFullscreen={toggleFullscreen}
        onEnterTVMode={handleEnterTVMode}
        tvModeDisabled={!currentStory || currentStory.scenes.length === 0}
      />

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

      {/* Chapter Settings Modal */}
      {showChapterSettings && isStoryComplete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4 backdrop-blur-md"
          onClick={() => setShowChapterSettings(false)}
        >
          <div
            className="max-w-lg w-full bg-[#121212] border border-white/10 rounded-2xl overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-5 border-b border-white/10 flex items-center justify-between">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <BookOpen size={20} className="text-purple-400" />
                New Chapter Settings
              </h3>
              <button
                type="button"
                onClick={() => setShowChapterSettings(false)}
                className="text-white/50 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <p className="text-white/70 text-sm">
                Customize the direction for the next chapter. Leave empty to let the AI continue naturally.
              </p>

              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">
                  Chapter Direction (Optional)
                </label>
                <textarea
                  value={chapterHint}
                  onChange={(e) => setChapterHint(e.target.value)}
                  placeholder="e.g., 'Focus on the mysterious stranger from scene 3' or 'Add a plot twist involving...'"
                  className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-purple-500/50 resize-none"
                  rows={3}
                />
              </div>

              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setShowChapterSettings(false)}
                  className="flex-1 px-4 py-3 bg-white/5 hover:bg-white/10 text-white rounded-xl transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={continueChapterInStudio}
                  disabled={isCreatingChapter}
                  className="flex-1 px-4 py-3 bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 text-white font-medium rounded-xl transition-colors disabled:opacity-50"
                >
                  {isCreatingChapter ? 'Creating...' : 'Start New Chapter'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Mode Chooser Modal */}
      {showModeChooser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl p-8 max-w-lg w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white">Choose Your Studio</h2>
              <button
                onClick={() => setShowModeChooser(false)}
                className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-full transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              {/* Play Studio Option */}
              <button
                onClick={handleChoosePlay}
                className="w-full p-6 bg-gradient-to-r from-purple-500/10 to-pink-500/10 border border-purple-500/30 rounded-xl text-left hover:border-purple-500/60 hover:bg-purple-500/20 transition-all group"
              >
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center flex-shrink-0">
                    <Play size={24} className="text-white" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-white mb-1">Play Story</h3>
                    <p className="text-sm text-white/60">
                      Simple, relaxing story creation. Just enter a premise and watch your story come to life with AI-generated scenes and images.
                    </p>
                    <span className="inline-block mt-2 text-xs text-purple-400 font-medium">Recommended for beginners</span>
                  </div>
                </div>
              </button>

              {/* Creator Studio Option */}
              {props.onOpenCreatorStudio && (
                <button
                  onClick={handleChooseCreator}
                  className="w-full p-6 bg-gradient-to-r from-blue-500/10 to-cyan-500/10 border border-blue-500/30 rounded-xl text-left hover:border-blue-500/60 hover:bg-blue-500/20 transition-all group"
                >
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center flex-shrink-0">
                      <Settings2 size={24} className="text-white" />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-white mb-1">Creator Studio</h3>
                      <p className="text-sm text-white/60">
                        Full project-based workflow with presets, policy controls, export options, and advanced generation settings.
                      </p>
                      <span className="inline-block mt-2 text-xs text-blue-400 font-medium">Advanced features</span>
                    </div>
                  </div>
                </button>
              )}
            </div>

            <p className="text-xs text-white/40 text-center mt-6">
              Your choice will be remembered for next time
            </p>
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

      {/* TV Mode Overlay */}
      {tvModeActive && (
        <TVModeContainer
          onGenerateNext={generateNextForTVMode}
          onEnsureImage={generateImageForScene}
          onContinueChapter={continueAsNextChapter}
        />
      )}
    </div>
  )
}
