/**
 * EditTab - Main component for the Edit mode workspace.
 *
 * TWO-VIEW ARCHITECTURE:
 * 1. Gallery View (Landing): Shows thumbnails of all edited images (like Imagine)
 * 2. Editor View: Full Grok-style editing workspace when an image is selected
 *
 * Features:
 * - localStorage persistence for edit history
 * - Cyber-Noir aesthetic (True Black backgrounds)
 * - Centralized Canvas for immersive editing
 * - Floating "Conversational" Input Bar at the bottom
 * - Right-side "Studio" controls panel with advanced edit options
 * - Horizontal Filmstrip for version history with metadata
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  Sparkles,
  Trash2,
  Upload,
  Loader2,
  Wand2,
  AlertCircle,
  Settings2,
  Download,
  History,
  ChevronRight,
  ChevronDown,
  ChevronLeft,
  Maximize2,
  X,
  RotateCcw,
  Clock,
  Sliders,
  Edit3,
  Plus,
  PaintBucket,
} from 'lucide-react'

import { EditDropzone } from './EditDropzone'
import { MaskCanvas } from './MaskCanvas'
import { upscaleImage } from '../enhance/upscaleApi'
import { QuickActions } from './QuickActions'
import { BackgroundTools } from './BackgroundTools'
import { OutpaintTools } from './OutpaintTools'
import type { ExtendDirection } from '../enhance/outpaintApi'
import {
  uploadToEditSession,
  sendEditMessage,
  selectActiveImage,
  clearEditSession,
  getEditSession,
  extractImages,
} from './editApi'
import type { EditTabProps, VersionEntry } from './types'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type EditItem = {
  id: string
  url: string
  createdAt: number
  originalUrl: string
  instruction: string
  conversationId: string
  settings?: Record<string, unknown>
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function formatTimeAgo(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

export function EditTab({
  backendUrl,
  apiKey,
  conversationId,
  onOpenLightbox,
  provider,
  providerBaseUrl,
  providerModel,
}: EditTabProps) {
  // Refs
  const fileInputRef = useRef<HTMLInputElement>(null)
  const resultsEndRef = useRef<HTMLDivElement>(null)
  const gridStartRef = useRef<HTMLDivElement>(null)

  // ==========================================================================
  // STATE - Gallery (persisted to localStorage)
  // ==========================================================================
  const [galleryItems, setGalleryItems] = useState<EditItem[]>(() => {
    try {
      const stored = localStorage.getItem('homepilot_edit_items')
      if (stored) {
        const parsed = JSON.parse(stored)
        return Array.isArray(parsed) ? parsed : []
      }
    } catch (error) {
      console.error('Failed to load edit items from localStorage:', error)
    }
    return []
  })

  // View mode: 'gallery' or 'editor'
  const [viewMode, setViewMode] = useState<'gallery' | 'editor'>('gallery')
  const [currentEditItem, setCurrentEditItem] = useState<EditItem | null>(null)

  // ==========================================================================
  // STATE - Editor Session
  // ==========================================================================
  const [active, setActive] = useState<string | null>(null)
  const [versions, setVersions] = useState<VersionEntry[]>([])
  const [results, setResults] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [lastPrompt, setLastPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [initialized, setInitialized] = useState(false)
  const [showSettings, setShowSettings] = useState(true)

  // State - Advanced Controls
  const [advancedMode, setAdvancedMode] = useState(false)
  const [editMode, setEditMode] = useState<'auto' | 'global' | 'inpaint'>('auto')
  const [steps, setSteps] = useState(30)
  const [cfg, setCfg] = useState(5.5)
  const [denoise, setDenoise] = useState(0.55)
  const [seedLock, setSeedLock] = useState(false)
  const [seed, setSeed] = useState(0)
  const [useCN, setUseCN] = useState(false)
  const [cnStrength, setCnStrength] = useState(1.0)

  // State - Inpainting Mask
  const [showMaskCanvas, setShowMaskCanvas] = useState(false)
  const [maskDataUrl, setMaskDataUrl] = useState<string | null>(null)
  const [uploadingMask, setUploadingMask] = useState(false)

  // State - Upscaling
  const [isUpscaling, setIsUpscaling] = useState(false)

  const hasImage = Boolean(active)

  // ==========================================================================
  // EFFECTS
  // ==========================================================================

  // Save gallery items to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('homepilot_edit_items', JSON.stringify(galleryItems))
    } catch (error) {
      console.error('Failed to save edit items to localStorage:', error)
    }
  }, [galleryItems])

  // Load session when entering editor mode
  useEffect(() => {
    if (viewMode !== 'editor' || !currentEditItem) return

    let cancelled = false
    const loadSession = async () => {
      try {
        const session = await getEditSession({
          backendUrl,
          apiKey,
          conversationId: currentEditItem.conversationId
        })
        if (!cancelled) {
          setActive(session.active_image_url ?? currentEditItem.url)
          if (session.versions && session.versions.length > 0) {
            setVersions(session.versions)
          } else if (session.history) {
            setVersions(session.history.map((url, i) => ({
              url,
              instruction: '',
              created_at: Date.now() / 1000 - i * 60,
              parent_url: null,
              settings: {},
            })))
          }
          setInitialized(true)
        }
      } catch {
        if (!cancelled) {
          // Session doesn't exist yet, use the item's URL
          setActive(currentEditItem.url)
          setVersions([{
            url: currentEditItem.url,
            instruction: currentEditItem.instruction,
            created_at: currentEditItem.createdAt / 1000,
            parent_url: null,
            settings: {},
          }])
          setInitialized(true)
        }
      }
    }
    loadSession()
    return () => { cancelled = true }
  }, [viewMode, currentEditItem, backendUrl, apiKey])

  // Scroll to new results
  useEffect(() => {
    if (results.length > 0) {
      resultsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [results])

  // ==========================================================================
  // HELPERS
  // ==========================================================================

  const buildEditMessage = useCallback((userText: string, maskUrl?: string | null): string => {
    const parts: string[] = [userText.trim()]

    // Always include mask if provided (for inpainting)
    if (maskUrl) {
      parts.push(`--mask ${maskUrl}`)
      parts.push(`--mode inpaint`)
    }

    if (!advancedMode) {
      return parts.join(' ')
    }

    // Add advanced parameters
    if (!maskUrl) {
      parts.push(`--mode ${editMode}`)
    }
    parts.push(`--steps ${steps}`)
    parts.push(`--cfg ${cfg}`)
    parts.push(`--denoise ${denoise}`)
    if (seedLock && seed > 0) {
      parts.push(`--seed ${seed}`)
    }
    if (useCN) {
      parts.push(`--cn on`)
      parts.push(`--cn-strength ${cnStrength}`)
    }
    return parts.join(' ')
  }, [advancedMode, editMode, steps, cfg, denoise, seedLock, seed, useCN, cnStrength])

  // Upload mask data URL to server and get a URL
  const uploadMask = useCallback(async (dataUrl: string): Promise<string | null> => {
    try {
      // Convert data URL to blob
      const response = await fetch(dataUrl)
      const blob = await response.blob()

      // Create form data
      const formData = new FormData()
      formData.append('file', blob, 'mask.png')

      // Upload to backend
      const uploadUrl = `${backendUrl}/upload`
      const uploadRes = await fetch(uploadUrl, {
        method: 'POST',
        headers: apiKey ? { 'x-api-key': apiKey } : {},
        body: formData,
      })

      if (!uploadRes.ok) {
        throw new Error(`Upload failed: ${uploadRes.status}`)
      }

      const uploadData = await uploadRes.json()
      return uploadData.url || null
    } catch (e) {
      console.error('Failed to upload mask:', e)
      return null
    }
  }, [backendUrl, apiKey])

  // ==========================================================================
  // HANDLERS - Gallery
  // ==========================================================================

  const handleUploadNew = useCallback(async (file: File) => {
    setError(null)
    setBusy(true)

    const newConversationId = uid()

    try {
      const data = await uploadToEditSession({
        backendUrl,
        apiKey,
        conversationId: newConversationId,
        file,
      })

      const uploadedUrl = data.active_image_url
      if (!uploadedUrl) {
        throw new Error('No image URL returned from upload')
      }

      const newItem: EditItem = {
        id: uid(),
        url: uploadedUrl,
        createdAt: Date.now(),
        originalUrl: uploadedUrl,
        instruction: '[Original Upload]',
        conversationId: newConversationId,
      }

      setGalleryItems((prev) => [newItem, ...prev].slice(0, 100))

      // Open editor for this new item
      setCurrentEditItem(newItem)
      setActive(uploadedUrl)
      setVersions([{
        url: uploadedUrl,
        instruction: '[Original Upload]',
        created_at: Date.now() / 1000,
        parent_url: null,
        settings: {},
      }])
      setInitialized(true)
      setViewMode('editor')

    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }, [backendUrl, apiKey])

  const handleOpenEditor = useCallback((item: EditItem) => {
    setCurrentEditItem(item)
    setInitialized(false)
    setActive(null)
    setVersions([])
    setResults([])
    setPrompt('')
    setError(null)
    setViewMode('editor')
  }, [])

  const handleBackToGallery = useCallback(() => {
    setViewMode('gallery')
    setCurrentEditItem(null)
    setActive(null)
    setVersions([])
    setResults([])
    setPrompt('')
    setError(null)
    setInitialized(false)
  }, [])

  const handleDeleteItem = useCallback((item: EditItem, e?: React.MouseEvent) => {
    if (e) e.stopPropagation()
    if (!confirm('Delete this edited image from gallery?')) return
    setGalleryItems((prev) => prev.filter((i) => i.id !== item.id))
  }, [])

  // ==========================================================================
  // HANDLERS - Editor
  // ==========================================================================

  const handlePickFile = useCallback(async (file: File) => {
    if (viewMode === 'gallery') {
      return handleUploadNew(file)
    }

    if (!currentEditItem) return

    setError(null)
    setBusy(true)
    setResults([])

    try {
      const data = await uploadToEditSession({
        backendUrl,
        apiKey,
        conversationId: currentEditItem.conversationId,
        file
      })
      setActive(data.active_image_url ?? null)
      if (data.versions && data.versions.length > 0) {
        setVersions(data.versions)
      } else if (data.history) {
        setVersions(data.history.map((url, i) => ({
          url,
          instruction: i === 0 ? '[Original Upload]' : '',
          created_at: Date.now() / 1000 - i * 60,
          parent_url: null,
          settings: {},
        })))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }, [viewMode, currentEditItem, backendUrl, apiKey, handleUploadNew])

  const runEdit = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || !currentEditItem) return

    setError(null)
    setBusy(true)
    setLastPrompt(trimmed)
    setResults([])

    // Upload mask if one is set
    let uploadedMaskUrl: string | null = null
    if (maskDataUrl) {
      setUploadingMask(true)
      uploadedMaskUrl = await uploadMask(maskDataUrl)
      setUploadingMask(false)
      if (!uploadedMaskUrl) {
        setError('Failed to upload mask. Please try again.')
        setBusy(false)
        return
      }
    }

    const messageToSend = buildEditMessage(trimmed, uploadedMaskUrl)

    try {
      const out = await sendEditMessage({
        backendUrl,
        apiKey,
        conversationId: currentEditItem.conversationId,
        message: messageToSend,
        provider,
        provider_base_url: providerBaseUrl,
        model: providerModel,
      })

      const imgs = extractImages(out.raw)
      setResults(imgs)

      if (imgs.length) {
        const now = Date.now()
        const newVersions: VersionEntry[] = imgs.map(url => ({
          url,
          instruction: trimmed,
          created_at: now / 1000,
          parent_url: active,
          settings: advancedMode ? { steps, cfg, denoise, editMode } : {},
        }))

        setVersions((prev) => {
          const existing = prev.filter(v => !imgs.includes(v.url))
          return [...newVersions, ...existing].slice(0, 20)
        })

        // Auto-select first result
        const firstResult = imgs[0]
        setActive(firstResult)

        // Update gallery - keep only one thumbnail per project (conversationId)
        // Always show the latest edited version, not duplicates
        setGalleryItems((prev) => {
          // Remove any existing items with the same conversationId
          const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId)

          // Create updated item with the latest version
          const updatedItem: EditItem = {
            id: currentEditItem.id, // Keep same ID
            url: firstResult, // Use the latest edited version
            createdAt: now,
            originalUrl: currentEditItem.originalUrl,
            instruction: trimmed,
            conversationId: currentEditItem.conversationId,
            settings: advancedMode ? { steps, cfg, denoise, editMode } : undefined,
          }

          // Add updated item at the beginning (most recent first)
          return [updatedItem, ...filtered].slice(0, 100)
        })

        // Update current edit item reference
        setCurrentEditItem(prev => prev ? {
          ...prev,
          url: firstResult,
          createdAt: now,
          instruction: trimmed,
        } : prev)

        // Persist to backend
        selectActiveImage({
          backendUrl,
          apiKey,
          conversationId: currentEditItem.conversationId,
          image_url: firstResult,
        }).catch(err => console.warn('Failed to persist active image:', err))

        // Clear mask after successful edit
        if (maskDataUrl) {
          setMaskDataUrl(null)
        }

        setResults([])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Edit failed')
    } finally {
      setBusy(false)
    }
  }, [currentEditItem, buildEditMessage, backendUrl, apiKey, provider, providerBaseUrl, providerModel, active, advancedMode, steps, cfg, denoise, editMode, maskDataUrl, uploadMask])

  const handleUse = useCallback(async (url: string) => {
    if (!currentEditItem) return

    setError(null)
    setBusy(true)

    try {
      const state = await selectActiveImage({
        backendUrl,
        apiKey,
        conversationId: currentEditItem.conversationId,
        image_url: url,
      })
      setActive(state.active_image_url ?? url)
      if (state.versions && state.versions.length > 0) {
        setVersions(state.versions)
      } else if (state.history) {
        setVersions(state.history.map((u, i) => ({
          url: u,
          instruction: '',
          created_at: Date.now() / 1000 - i * 60,
          parent_url: null,
          settings: {},
        })))
      }
      setResults([])
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to set active image')
    } finally {
      setBusy(false)
    }
  }, [currentEditItem, backendUrl, apiKey])

  const handleReset = useCallback(async () => {
    if (!currentEditItem) return

    setError(null)
    setBusy(true)

    try {
      await clearEditSession({
        backendUrl,
        apiKey,
        conversationId: currentEditItem.conversationId,
      })
      setActive(null)
      setVersions([])
      setResults([])
      setPrompt('')
      setLastPrompt('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reset')
    } finally {
      setBusy(false)
    }
  }, [currentEditItem, backendUrl, apiKey])

  const handleSubmit = useCallback((e?: React.FormEvent) => {
    e?.preventDefault()
    if (prompt.trim()) {
      runEdit(prompt)
      setPrompt('')
    }
  }, [prompt, runEdit])

  const handleUpscale = useCallback(async () => {
    if (!active || !currentEditItem || isUpscaling) return

    setIsUpscaling(true)
    setError(null)

    try {
      const result = await upscaleImage({
        backendUrl,
        apiKey,
        imageUrl: active,
        scale: 2,
        model: '4x-UltraSharp.pth',
      })

      const upscaledUrl = result?.media?.images?.[0]
      if (upscaledUrl) {
        // Add to versions (non-destructive)
        const now = Date.now()
        const newVersion = {
          url: upscaledUrl,
          instruction: '[Upscaled 2x]',
          created_at: now / 1000,
          parent_url: active,
          settings: {},
        }
        setVersions((prev) => [newVersion, ...prev])
        setActive(upscaledUrl)

        // Persist to backend
        selectActiveImage({
          backendUrl,
          apiKey,
          conversationId: currentEditItem.conversationId,
          image_url: upscaledUrl,
        }).catch(err => console.warn('Failed to persist upscaled image:', err))
      } else {
        setError('Upscale completed but no image was returned.')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upscale failed')
    } finally {
      setIsUpscaling(false)
    }
  }, [active, currentEditItem, isUpscaling, backendUrl, apiKey])

  // Handler for QuickActions (Enhance, Restore, Fix Faces)
  const handleQuickActionResult = useCallback((resultUrl: string, mode: string) => {
    if (!currentEditItem) return

    const now = Date.now()
    const modeLabels: Record<string, string> = {
      photo: 'Enhanced',
      restore: 'Restored',
      faces: 'Faces Fixed',
    }
    const instruction = `[${modeLabels[mode] || mode}]`

    const newVersion = {
      url: resultUrl,
      instruction,
      created_at: now / 1000,
      parent_url: active,
      settings: { mode },
    }

    setVersions((prev) => [newVersion, ...prev])
    setActive(resultUrl)

    // Update gallery
    setGalleryItems((prev) => {
      const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId)
      const updatedItem: EditItem = {
        id: currentEditItem.id,
        url: resultUrl,
        createdAt: now,
        originalUrl: currentEditItem.originalUrl,
        instruction,
        conversationId: currentEditItem.conversationId,
      }
      return [updatedItem, ...filtered].slice(0, 100)
    })

    // Update current edit item reference
    setCurrentEditItem(prev => prev ? { ...prev, url: resultUrl, createdAt: now, instruction } : prev)

    // Persist to backend
    selectActiveImage({
      backendUrl,
      apiKey,
      conversationId: currentEditItem.conversationId,
      image_url: resultUrl,
    }).catch(err => console.warn('Failed to persist active image:', err))
  }, [currentEditItem, active, backendUrl, apiKey])

  // Handler for BackgroundTools (Remove BG, Change BG, Blur BG)
  const handleBackgroundResult = useCallback((resultUrl: string, action: string) => {
    if (!currentEditItem) return

    const now = Date.now()
    const actionLabels: Record<string, string> = {
      remove: 'BG Removed',
      replace: 'BG Changed',
      blur: 'BG Blurred',
    }
    const instruction = `[${actionLabels[action] || action}]`

    const newVersion = {
      url: resultUrl,
      instruction,
      created_at: now / 1000,
      parent_url: active,
      settings: { action },
    }

    setVersions((prev) => [newVersion, ...prev])
    setActive(resultUrl)

    // Update gallery
    setGalleryItems((prev) => {
      const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId)
      const updatedItem: EditItem = {
        id: currentEditItem.id,
        url: resultUrl,
        createdAt: now,
        originalUrl: currentEditItem.originalUrl,
        instruction,
        conversationId: currentEditItem.conversationId,
      }
      return [updatedItem, ...filtered].slice(0, 100)
    })

    setCurrentEditItem(prev => prev ? { ...prev, url: resultUrl, createdAt: now, instruction } : prev)

    selectActiveImage({
      backendUrl,
      apiKey,
      conversationId: currentEditItem.conversationId,
      image_url: resultUrl,
    }).catch(err => console.warn('Failed to persist active image:', err))
  }, [currentEditItem, active, backendUrl, apiKey])

  // Handler for OutpaintTools (Extend canvas)
  const handleOutpaintResult = useCallback((resultUrl: string, direction: ExtendDirection, newSize: [number, number]) => {
    if (!currentEditItem) return

    const now = Date.now()
    const directionLabels: Record<string, string> = {
      left: 'Extended Left',
      right: 'Extended Right',
      up: 'Extended Up',
      down: 'Extended Down',
      horizontal: 'Extended Horizontal',
      vertical: 'Extended Vertical',
      all: 'Extended All Sides',
    }
    const instruction = `[${directionLabels[direction] || 'Extended'}] → ${newSize[0]}×${newSize[1]}`

    const newVersion = {
      url: resultUrl,
      instruction,
      created_at: now / 1000,
      parent_url: active,
      settings: { direction, newSize },
    }

    setVersions((prev) => [newVersion, ...prev])
    setActive(resultUrl)

    // Update gallery
    setGalleryItems((prev) => {
      const filtered = prev.filter(item => item.conversationId !== currentEditItem.conversationId)
      const updatedItem: EditItem = {
        id: currentEditItem.id,
        url: resultUrl,
        createdAt: now,
        originalUrl: currentEditItem.originalUrl,
        instruction,
        conversationId: currentEditItem.conversationId,
      }
      return [updatedItem, ...filtered].slice(0, 100)
    })

    setCurrentEditItem(prev => prev ? { ...prev, url: resultUrl, createdAt: now, instruction } : prev)

    selectActiveImage({
      backendUrl,
      apiKey,
      conversationId: currentEditItem.conversationId,
      image_url: resultUrl,
    }).catch(err => console.warn('Failed to persist active image:', err))
  }, [currentEditItem, active, backendUrl, apiKey])

  const handleDeleteVersion = useCallback((versionUrl: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation()

    setVersions((prev) => {
      const filtered = prev.filter(v => v.url !== versionUrl)

      // If we deleted the active version, select the next available
      if (active === versionUrl && filtered.length > 0) {
        const newActive = filtered[0].url
        setActive(newActive)

        // Persist the new active to backend
        if (currentEditItem) {
          selectActiveImage({
            backendUrl,
            apiKey,
            conversationId: currentEditItem.conversationId,
            image_url: newActive,
          }).catch(err => console.warn('Failed to persist active image:', err))
        }
      }

      return filtered
    })
  }, [active, currentEditItem, backendUrl, apiKey])

  // ==========================================================================
  // RENDER - Gallery View
  // ==========================================================================

  if (viewMode === 'gallery') {
    return (
      <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col relative">
        {/* Header */}
        <div className="absolute top-0 left-0 right-0 z-20 flex justify-between items-center px-6 py-4 bg-gradient-to-b from-black/80 to-transparent pointer-events-none">
          <div className="pointer-events-auto flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
              <Edit3 size={16} className="text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-white leading-tight">HomePilot</div>
              <div className="text-xs text-white/50 leading-tight">Edit Studio</div>
            </div>
          </div>

          <div className="pointer-events-auto flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleUploadNew(file)
                e.currentTarget.value = ''
              }}
            />
            <button
              className="flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-2 rounded-full text-sm font-semibold transition-all"
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
            >
              <Upload size={16} className="text-white/70" />
              <span>Upload Image</span>
            </button>
          </div>
        </div>

        {/* Grid Gallery */}
        <div className="flex-1 overflow-y-auto px-4 pb-8 pt-20 scrollbar-hide">
          <div className="max-w-[1600px] mx-auto grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 content-start">
            <div ref={gridStartRef} className="col-span-full h-1" />

            {/* Empty state */}
            {galleryItems.length === 0 && !busy ? (
              <div className="col-span-full">
                <EditDropzone onPickFile={handleUploadNew} disabled={busy} />
              </div>
            ) : null}

            {/* Loading skeleton */}
            {busy && (
              <div className="relative rounded-2xl overflow-hidden bg-white/5 border border-white/10 aspect-square animate-pulse">
                <div className="absolute inset-0 bg-gradient-to-tr from-white/10 to-transparent"></div>
                <div className="absolute bottom-4 left-4 text-sm font-mono text-white/70">Uploading…</div>
              </div>
            )}

            {/* Gallery items */}
            {galleryItems.map((item) => (
              <div
                key={item.id}
                onClick={() => handleOpenEditor(item)}
                className="relative group rounded-2xl overflow-hidden bg-white/5 border border-white/10 hover:border-white/20 transition-colors cursor-pointer aspect-square"
              >
                <img
                  src={item.url}
                  alt={item.instruction}
                  className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
                  loading="lazy"
                />

                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex flex-col justify-between p-4">
                  <div className="flex justify-end gap-2">
                    <button
                      className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-full text-white transition-colors"
                      type="button"
                      title="Edit"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleOpenEditor(item)
                      }}
                    >
                      <Edit3 size={16} />
                    </button>
                    <button
                      className="bg-red-500/20 backdrop-blur-md hover:bg-red-500/40 p-2 rounded-full text-red-400 hover:text-red-300 transition-colors"
                      type="button"
                      title="Delete"
                      onClick={(e) => handleDeleteItem(item, e)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>

                  <div>
                    <div className="text-xs text-white/80 line-clamp-2 mb-1">{item.instruction}</div>
                    <div className="text-[10px] text-white/50 flex items-center gap-1">
                      <Clock size={10} />
                      {formatTimeAgo(item.createdAt)}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Floating Add Button */}
        {galleryItems.length > 0 && (
          <div className="absolute bottom-6 right-6 z-30">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
              className="w-14 h-14 rounded-full bg-white text-black hover:bg-gray-200 transition-all shadow-2xl flex items-center justify-center"
              type="button"
              title="Upload new image"
            >
              <Plus size={24} />
            </button>
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

  // ==========================================================================
  // RENDER - Editor View (Original Grok-style design)
  // ==========================================================================

  if (!initialized) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-black">
        <div className="flex flex-col items-center gap-4 text-white/50">
          <Loader2 size={32} className="animate-spin text-white" />
          <span className="text-sm font-mono tracking-wider">INITIALIZING STUDIO...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="relative flex h-full w-full bg-black text-white overflow-hidden font-sans">
      {/* --- Main Workspace (Canvas) --- */}
      <div className="flex-1 flex flex-col relative z-0">
        {/* Top Bar (Transparent) */}
        <div className="absolute top-0 left-0 right-0 p-6 flex items-start justify-between z-20 pointer-events-none">
          <div className="pointer-events-auto flex items-center gap-3">
            {/* Back to Gallery Button */}
            <button
              onClick={handleBackToGallery}
              className="h-8 w-8 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center backdrop-blur-md transition-colors"
              title="Back to Gallery"
            >
              <ChevronLeft size={18} className="text-white" />
            </button>
            <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center backdrop-blur-md">
              <Sparkles size={16} className="text-white" />
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-wide">EDIT STUDIO</h1>
              <p className="text-[10px] text-white/40 font-mono uppercase tracking-wider">
                {hasImage ? 'Session Active' : 'No Image Loaded'}
              </p>
            </div>
          </div>

          <div className="pointer-events-auto flex gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handlePickFile(file)
                e.currentTarget.value = ''
              }}
            />
            {hasImage && (
              <>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="p-2 rounded-lg bg-black/40 hover:bg-white/10 border border-white/10 text-white/70 hover:text-white transition-colors backdrop-blur-md"
                  title="Upload New"
                >
                  <Upload size={18} />
                </button>
                <button
                  onClick={handleReset}
                  className="p-2 rounded-lg bg-black/40 hover:bg-red-500/20 border border-white/10 text-white/70 hover:text-red-400 transition-colors backdrop-blur-md"
                  title="Reset Session"
                >
                  <Trash2 size={18} />
                </button>
                <button
                  onClick={() => setShowSettings(!showSettings)}
                  className={`p-2 rounded-lg border border-white/10 transition-colors backdrop-blur-md ${showSettings ? 'bg-white text-black' : 'bg-black/40 text-white/70 hover:text-white'}`}
                  title="Toggle Settings"
                >
                  <Settings2 size={18} />
                </button>
              </>
            )}
          </div>
        </div>

        {/* Canvas Area */}
        <div className="flex-1 relative flex items-center justify-center bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-white/5 to-black">
          {!hasImage ? (
            <div className="w-full max-w-xl px-6 relative z-10">
              <EditDropzone onPickFile={handlePickFile} disabled={busy} />
            </div>
          ) : (
            <div className="relative w-full h-full p-8 flex items-center justify-center">
              <div className="relative group max-w-full max-h-full shadow-2xl">
                <img
                  src={active!}
                  alt="Active Canvas"
                  className="max-w-full max-h-[75vh] object-contain rounded-sm shadow-[0_0_50px_rgba(0,0,0,0.5)] border border-white/5"
                />
                <div className="absolute bottom-4 right-4 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                  <button
                    onClick={() => active && onOpenLightbox(active)}
                    className="p-2 bg-black/80 text-white rounded-md hover:bg-white hover:text-black transition-colors"
                    title="Full screen"
                  >
                    <Maximize2 size={16} />
                  </button>
                  <button
                    onClick={handleUpscale}
                    disabled={isUpscaling || busy}
                    className={`p-2 rounded-md transition-colors ${
                      isUpscaling
                        ? 'bg-purple-500/60 text-white animate-pulse'
                        : 'bg-purple-500/80 text-white hover:bg-purple-400'
                    }`}
                    title="Upscale 2x"
                  >
                    {isUpscaling ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                  </button>
                  <a
                    href={active!}
                    download="edited-image.png"
                    className="p-2 bg-black/80 text-white rounded-md hover:bg-white hover:text-black transition-colors"
                    title="Download"
                  >
                    <Download size={16} />
                  </a>
                </div>

                {busy && (
                  <div className="absolute inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center rounded-sm">
                    <div className="flex flex-col items-center gap-3">
                      <Loader2 size={32} className="animate-spin text-white" />
                      <span className="text-xs font-mono uppercase tracking-widest text-white/70">Processing Edit...</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Bottom Floating Bar (Input + History) */}
        {hasImage && (
          <div className="absolute bottom-0 left-0 right-0 z-20 flex flex-col items-center pb-6 px-4 bg-gradient-to-t from-black via-black/80 to-transparent pt-20">
            {error && (
              <div className="mb-4 flex items-center gap-3 px-4 py-3 bg-red-950/80 border border-red-500/30 rounded-lg backdrop-blur-xl animate-in fade-in slide-in-from-bottom-5">
                <AlertCircle size={16} className="text-red-400" />
                <span className="text-sm text-red-100">{error}</span>
                <button onClick={() => setError(null)} className="ml-2 text-red-400 hover:text-white"><X size={14}/></button>
              </div>
            )}

            {/* Input Bar (Grok Style) */}
            <div className="w-full max-w-3xl relative mb-8">
              <form onSubmit={handleSubmit} className="relative group">
                <div className="absolute inset-0 bg-white/5 rounded-2xl blur-xl group-hover:bg-white/10 transition-colors" />
                <div className="relative flex items-center bg-[#0A0A0A] border border-white/10 rounded-2xl shadow-2xl focus-within:border-white/30 transition-colors overflow-hidden">
                  <div className="pl-4 text-white/40">
                    <Wand2 size={20} />
                  </div>
                  <input
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder={busy ? "Processing..." : "Describe changes naturally (e.g. 'Make the lighting cyberpunk', 'Add rain')..."}
                    className="flex-1 bg-transparent border-none text-white px-4 py-4 focus:ring-0 placeholder:text-white/30 text-base outline-none"
                    disabled={busy}
                  />
                  <div className="pr-3">
                    <button
                      type="submit"
                      disabled={!prompt.trim() || busy}
                      className="py-2 px-5 rounded-xl bg-white text-black hover:bg-gray-200 disabled:bg-white/10 disabled:text-white/30 disabled:cursor-not-allowed transition-all font-medium text-sm"
                    >
                      Generate
                    </button>
                  </div>
                </div>
              </form>
            </div>

            {/* Filmstrip (Version History with Metadata) */}
            <div className="w-full max-w-5xl flex gap-3 overflow-x-auto pb-4 px-2 pt-2 snap-x scrollbar-hide">
              {results.map((url, idx) => (
                <div key={`res-${idx}`} className="snap-center shrink-0 relative group w-24 h-24 rounded-lg overflow-hidden border-2 border-purple-500/50 cursor-pointer shadow-[0_0_20px_rgba(147,51,234,0.3)]">
                  <img src={url} className="w-full h-full object-cover" alt="Result" />
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-1">
                    <button onClick={() => handleUse(url)} className="text-[10px] font-bold bg-purple-500 text-white px-2 py-1 rounded hover:bg-purple-400 hover:scale-105 transition-all">
                      USE THIS
                    </button>
                    <div className="flex gap-1">
                      <button onClick={() => onOpenLightbox(url)} className="text-white/70 hover:text-white p-1"><Maximize2 size={12}/></button>
                      <a href={url} download className="text-white/70 hover:text-white p-1"><Download size={12}/></a>
                    </div>
                  </div>
                  <div className="absolute top-1 left-1 px-1.5 py-0.5 bg-purple-500 text-[8px] font-bold text-white rounded">NEW</div>
                </div>
              ))}

              {results.length > 0 && versions.length > 0 && (
                <div className="w-px h-16 bg-white/10 shrink-0 self-center mx-2" />
              )}

              {versions.map((version, idx) => (
                <div
                  key={`ver-${version.url}-${idx}`}
                  onClick={() => handleUse(version.url)}
                  className={`snap-center shrink-0 relative group w-20 h-20 rounded-lg overflow-hidden border cursor-pointer transition-all ${
                    active === version.url
                      ? 'border-white ring-1 ring-white'
                      : 'border-white/10 hover:border-white/40'
                  }`}
                >
                  <img src={version.url} className="w-full h-full object-cover opacity-60 group-hover:opacity-100 transition-opacity" alt="Version" />

                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                    <button onClick={(e) => { e.stopPropagation(); onOpenLightbox(version.url) }} className="text-white/70 hover:text-white p-1"><Maximize2 size={14}/></button>
                    <a href={version.url} download onClick={(e) => e.stopPropagation()} className="text-white/70 hover:text-white p-1"><Download size={14}/></a>
                  </div>

                  <div className="absolute -bottom-16 left-1/2 -translate-x-1/2 w-40 p-2 bg-black/90 border border-white/10 rounded-lg text-[10px] opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10 shadow-xl">
                    <div className="text-white/80 truncate font-medium">{version.instruction || 'Original'}</div>
                    <div className="text-white/40 flex items-center gap-1 mt-1">
                      <Clock size={8} />
                      {formatTimeAgo(version.created_at)}
                    </div>
                  </div>

                  {active === version.url && (
                    <div className="absolute top-1 right-1 w-2 h-2 bg-white rounded-full" />
                  )}
                </div>
              ))}
              <div ref={resultsEndRef} />
            </div>
          </div>
        )}
      </div>

      {/* --- Right Settings Panel (Collapsible) --- */}
      {hasImage && (
        <div className={`border-l border-white/10 bg-[#050505] transition-all duration-300 ease-in-out flex flex-col ${showSettings ? 'w-80 translate-x-0' : 'w-0 translate-x-full opacity-0 overflow-hidden'}`}>
          <div className="p-5 border-b border-white/10 flex items-center justify-between">
            <h3 className="font-bold text-sm tracking-wide flex items-center gap-2">
              <Settings2 size={16} />
              PARAMETERS
            </h3>
            <button onClick={() => setShowSettings(false)} className="text-white/40 hover:text-white">
              <ChevronRight size={18} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-5 space-y-6">
            {/* Advanced Mode Toggle */}
            <div className="space-y-3">
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
                  <div className="space-y-2">
                    <label className="text-xs uppercase tracking-wider text-white/40 font-semibold">Edit Mode</label>
                    <select
                      value={editMode}
                      onChange={(e) => setEditMode(e.target.value as 'auto' | 'global' | 'inpaint')}
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2.5 text-sm text-white focus:border-purple-500/50 focus:outline-none"
                    >
                      <option value="auto">Auto (Smart Detection)</option>
                      <option value="global">Global (Full Image)</option>
                      <option value="inpaint">Inpaint (Masked Area)</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="uppercase tracking-wider text-white/40 font-semibold">Steps</span>
                      <span className="text-white/60">{steps}</span>
                    </div>
                    <input
                      type="range"
                      min={10}
                      max={50}
                      value={steps}
                      onChange={(e) => setSteps(Number(e.target.value))}
                      className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="uppercase tracking-wider text-white/40 font-semibold">CFG Scale</span>
                      <span className="text-white/60">{cfg.toFixed(1)}</span>
                    </div>
                    <input
                      type="range"
                      min={1}
                      max={15}
                      step={0.5}
                      value={cfg}
                      onChange={(e) => setCfg(Number(e.target.value))}
                      className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="uppercase tracking-wider text-white/40 font-semibold">Denoise Strength</span>
                      <span className="text-white/60">{denoise.toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      min={0.1}
                      max={1.0}
                      step={0.05}
                      value={denoise}
                      onChange={(e) => setDenoise(Number(e.target.value))}
                      className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-purple-400 [&::-webkit-slider-thumb]:rounded-full"
                    />
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                    <span className="text-sm text-white/80">Lock Seed</span>
                    <button
                      onClick={() => {
                        if (!seedLock) setSeed(Math.floor(Math.random() * 2147483647))
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
                      value={seed}
                      onChange={(e) => setSeed(Number(e.target.value))}
                      className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm text-white font-mono focus:border-purple-500/50 focus:outline-none"
                      placeholder="Seed value"
                    />
                  )}

                  <div className="flex items-center justify-between p-3 rounded-xl bg-white/5 border border-white/10">
                    <span className="text-sm text-white/80">Use ControlNet</span>
                    <button
                      onClick={() => setUseCN(!useCN)}
                      className={`w-10 h-5 rounded-full transition-colors relative ${useCN ? 'bg-purple-500' : 'bg-white/20'}`}
                    >
                      <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${useCN ? 'translate-x-5' : 'translate-x-0.5'}`} />
                    </button>
                  </div>
                  {useCN && (
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
            </div>

            {/* Quick Enhancement Actions */}
            <QuickActions
              backendUrl={backendUrl}
              apiKey={apiKey}
              imageUrl={active}
              onResult={handleQuickActionResult}
              onError={(err) => setError(err)}
              disabled={busy}
              compact={false}
            />

            {/* Background Tools */}
            <BackgroundTools
              backendUrl={backendUrl}
              apiKey={apiKey}
              imageUrl={active}
              onResult={handleBackgroundResult}
              onError={(err) => setError(err)}
              disabled={busy}
              compact={false}
            />

            {/* Outpaint / Extend Canvas */}
            <OutpaintTools
              backendUrl={backendUrl}
              apiKey={apiKey}
              imageUrl={active}
              onResult={handleOutpaintResult}
              onError={(err) => setError(err)}
              disabled={busy}
            />

            {/* Inpainting Mask Section */}
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs uppercase tracking-wider text-white/40 font-semibold">
                <span className="flex items-center gap-2">
                  <PaintBucket size={14} />
                  Inpainting Mask
                </span>
                {maskDataUrl && (
                  <button
                    onClick={() => setMaskDataUrl(null)}
                    className="text-red-400 hover:text-red-300 text-[10px]"
                  >
                    Clear
                  </button>
                )}
              </div>

              {maskDataUrl ? (
                <div className="space-y-2">
                  <div className="relative rounded-lg overflow-hidden border border-purple-500/30 bg-purple-500/10">
                    <img
                      src={maskDataUrl}
                      alt="Mask preview"
                      className="w-full h-20 object-contain opacity-70"
                    />
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-[10px] text-purple-300 bg-black/60 px-2 py-1 rounded">
                        Mask Active
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => setShowMaskCanvas(true)}
                    className="w-full flex items-center justify-center gap-2 p-2.5 rounded-xl bg-purple-500/20 border border-purple-500/30 text-purple-300 hover:bg-purple-500/30 transition-colors text-sm font-medium"
                  >
                    <PaintBucket size={14} />
                    Edit Mask
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowMaskCanvas(true)}
                  disabled={!active}
                  className="w-full flex items-center justify-center gap-2 p-3 rounded-xl bg-white/5 border border-white/10 text-white/60 hover:bg-purple-500/20 hover:border-purple-500/30 hover:text-purple-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-sm font-medium"
                >
                  <PaintBucket size={16} />
                  Draw Mask for Inpainting
                </button>
              )}

              <p className="text-[10px] text-white/30 leading-relaxed">
                Draw a mask to edit only specific areas. White = areas to change, black = areas to preserve.
              </p>
            </div>

            {/* Version History Summary */}
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs uppercase tracking-wider text-white/40 font-semibold">
                <span className="flex items-center gap-2">
                  <History size={14} />
                  Version History
                </span>
                <span className="text-white/30">{versions.length} versions</span>
              </div>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {versions.slice(0, 5).map((v, idx) => (
                  <div
                    key={`${v.url}-${idx}`}
                    onClick={() => handleUse(v.url)}
                    className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors group/item ${
                      active === v.url
                        ? 'bg-purple-500/20 border border-purple-500/30'
                        : 'bg-white/5 border border-transparent hover:border-white/10'
                    }`}
                  >
                    <img src={v.url} alt="" className="w-10 h-10 rounded object-cover" />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-white/80 truncate">
                        {v.instruction || 'Original'}
                      </div>
                      <div className="text-[10px] text-white/40 flex items-center gap-1">
                        <Clock size={10} />
                        {formatTimeAgo(v.created_at)}
                      </div>
                    </div>
                    <div className="flex gap-1 opacity-0 group-hover/item:opacity-100 transition-opacity">
                      {active !== v.url && (
                        <button className="p-1 text-white/30 hover:text-white" title="Use this version">
                          <RotateCcw size={12} />
                        </button>
                      )}
                      <button
                        onClick={(e) => handleDeleteVersion(v.url, e)}
                        className="p-1 text-white/30 hover:text-red-400 transition-colors"
                        title="Delete this version"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="p-4 rounded-xl bg-purple-900/10 border border-purple-500/20 text-xs text-purple-200/70 leading-relaxed">
              <span className="font-bold text-purple-400 block mb-1">PRO TIP</span>
              Enable Advanced Controls to fine-tune edit parameters like steps, CFG, and denoise strength for better results.
            </div>
          </div>
        </div>
      )}

      {/* Mask Canvas Modal */}
      {showMaskCanvas && active && (
        <MaskCanvas
          imageUrl={active}
          initialMask={maskDataUrl}
          onSaveMask={(dataUrl) => {
            setMaskDataUrl(dataUrl)
            setShowMaskCanvas(false)
          }}
          onCancel={() => setShowMaskCanvas(false)}
        />
      )}

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>
  )
}

export default EditTab
