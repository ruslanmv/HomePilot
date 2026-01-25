/**
 * EditTab - Main component for the Edit mode workspace.
 *
 * Provides a dedicated UI for natural language image editing with:
 * - Persistent active image session
 * - Image history for undo/branch
 * - Result grid with use/download actions
 * - Integration with the edit-session sidecar service
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Sparkles, Trash2, Upload, Loader2, Wand2, AlertCircle } from 'lucide-react'

import { EditDropzone } from './EditDropzone'
import { EditHistoryStrip } from './EditHistoryStrip'
import { EditResultGrid } from './EditResultGrid'
import {
  uploadToEditSession,
  sendEditMessage,
  selectActiveImage,
  clearEditSession,
  getEditSession,
  extractImages,
} from './editApi'
import type { EditTabProps } from './types'

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

  // State
  const [active, setActive] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const [results, setResults] = useState<string[]>([])
  const [prompt, setPrompt] = useState('')
  const [lastPrompt, setLastPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [initialized, setInitialized] = useState(false)

  const hasImage = Boolean(active)

  // Load existing session on mount
  useEffect(() => {
    let cancelled = false

    const loadSession = async () => {
      try {
        const session = await getEditSession({
          backendUrl,
          apiKey,
          conversationId,
        })

        if (!cancelled) {
          setActive(session.active_image_url ?? null)
          setHistory(session.history ?? [])
          setInitialized(true)
        }
      } catch {
        // Session doesn't exist yet, that's fine
        if (!cancelled) {
          setInitialized(true)
        }
      }
    }

    loadSession()

    return () => {
      cancelled = true
    }
  }, [backendUrl, apiKey, conversationId])

  // Handle file upload
  const handlePickFile = useCallback(
    async (file: File) => {
      setError(null)
      setBusy(true)
      setResults([])

      try {
        const data = await uploadToEditSession({
          backendUrl,
          apiKey,
          conversationId,
          file,
        })

        setActive(data.active_image_url ?? null)
        setHistory(Array.isArray(data.history) ? data.history : [])
      } catch (e) {
        const message = e instanceof Error ? e.message : 'Upload failed'
        setError(message)
      } finally {
        setBusy(false)
      }
    },
    [backendUrl, apiKey, conversationId]
  )

  // Run edit operation
  const runEdit = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return

      setError(null)
      setBusy(true)
      setLastPrompt(trimmed)

      try {
        const out = await sendEditMessage({
          backendUrl,
          apiKey,
          conversationId,
          message: trimmed,
          provider,
          provider_base_url: providerBaseUrl,
          model: providerModel,
        })

        const imgs = extractImages(out.raw)
        setResults(imgs)

        // Update history with new results
        if (imgs.length) {
          setHistory((prev) => {
            const combined = [...imgs, ...prev]
            return Array.from(new Set(combined)).slice(0, 10)
          })
        }
      } catch (e) {
        const message = e instanceof Error ? e.message : 'Edit failed'
        setError(message)
      } finally {
        setBusy(false)
      }
    },
    [backendUrl, apiKey, conversationId, provider, providerBaseUrl, providerModel]
  )

  // Select a result as the new active image
  const handleUse = useCallback(
    async (url: string) => {
      setError(null)
      setBusy(true)

      try {
        const state = await selectActiveImage({
          backendUrl,
          apiKey,
          conversationId,
          image_url: url,
        })

        setActive(state.active_image_url ?? url)
        setHistory(state.history ?? [])
        setResults([])
      } catch (e) {
        const message = e instanceof Error ? e.message : 'Failed to set active image'
        setError(message)
      } finally {
        setBusy(false)
      }
    },
    [backendUrl, apiKey, conversationId]
  )

  // Reset the session
  const handleReset = useCallback(async () => {
    setError(null)
    setBusy(true)

    try {
      await clearEditSession({
        backendUrl,
        apiKey,
        conversationId,
      })

      setActive(null)
      setHistory([])
      setResults([])
      setPrompt('')
      setLastPrompt('')
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Failed to reset'
      setError(message)
    } finally {
      setBusy(false)
    }
  }, [backendUrl, apiKey, conversationId])

  // Handle form submission
  const handleSubmit = useCallback(
    (e?: React.FormEvent) => {
      e?.preventDefault()
      if (prompt.trim()) {
        runEdit(prompt)
        setPrompt('')
      }
    },
    [prompt, runEdit]
  )

  // Handle keyboard shortcuts
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit]
  )

  // Loading state
  if (!initialized) {
    return (
      <div className="w-full max-w-6xl mx-auto px-4 py-6 flex items-center justify-center min-h-[400px]">
        <div className="flex items-center gap-3 text-white/50">
          <Loader2 size={20} className="animate-spin" />
          <span>Loading edit session...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full max-w-6xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-white/80" />
            <h1 className="text-lg font-bold">Edit</h1>
          </div>
          <p className="text-sm text-white/50 mt-1">
            Upload once, then describe changes naturally. Click "Use this" to continue editing a result.
          </p>
        </div>

        {/* Header actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={busy}
            className={[
              'inline-flex items-center gap-2 px-4 py-2 rounded-xl',
              'bg-white/10 hover:bg-white/15 border border-white/10',
              'transition-colors text-sm font-semibold',
              busy ? 'opacity-50 cursor-not-allowed' : '',
            ].join(' ')}
          >
            <Upload size={16} />
            Upload new
          </button>

          <button
            type="button"
            onClick={handleReset}
            disabled={busy}
            className={[
              'inline-flex items-center gap-2 px-4 py-2 rounded-xl',
              'bg-white/5 hover:bg-white/10 border border-white/10',
              'transition-colors text-sm font-semibold text-white/80',
              busy ? 'opacity-50 cursor-not-allowed' : '',
            ].join(' ')}
          >
            <Trash2 size={16} />
            Reset
          </button>

          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) handlePickFile(file)
              e.currentTarget.value = ''
            }}
          />
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="mb-4 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 flex items-start gap-3">
          <AlertCircle size={18} className="text-red-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm text-red-200">{error}</p>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-xs text-red-300/70 hover:text-red-300 mt-1"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {/* Main content */}
      {!hasImage ? (
        <EditDropzone onPickFile={handlePickFile} disabled={busy} />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Left panel: Active image preview */}
          <div className="lg:col-span-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 shadow-2xl ring-1 ring-white/10 overflow-hidden">
              {/* Panel header */}
              <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
                <div className="text-sm font-bold text-white">Active image</div>
                {busy && (
                  <div className="text-xs text-white/50 inline-flex items-center gap-2">
                    <Loader2 size={14} className="animate-spin" />
                    Working...
                  </div>
                )}
              </div>

              {/* Active image */}
              <button
                type="button"
                className="block w-full focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500/50"
                onClick={() => active && onOpenLightbox(active)}
                aria-label="View active image fullscreen"
              >
                <img
                  src={active ?? ''}
                  className="w-full aspect-square object-cover"
                  alt="Active edit image"
                />
              </button>

              {/* History strip */}
              <div className="p-4">
                <EditHistoryStrip
                  history={history}
                  active={active}
                  onSelect={handleUse}
                  disabled={busy}
                />
              </div>
            </div>
          </div>

          {/* Right panel: Edit prompt + results */}
          <div className="lg:col-span-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 shadow-2xl ring-1 ring-white/10 p-4">
              {/* Section header */}
              <div className="flex items-center gap-2 mb-3">
                <Wand2 size={18} className="text-white/70" />
                <div className="text-sm font-bold">Describe your edit</div>
              </div>

              {/* Prompt input */}
              <form onSubmit={handleSubmit} className="flex gap-2">
                <input
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder='e.g., "Remove the background", "Make it sunset lighting", "Add a red hat"'
                  className={[
                    'flex-1 px-4 py-3 bg-white/5 border border-white/10 rounded-xl',
                    'focus:outline-none focus:ring-2 focus:ring-blue-500/60',
                    'placeholder-white/30 text-white',
                    'transition-colors',
                  ].join(' ')}
                  disabled={busy}
                  aria-label="Edit instruction"
                />

                <button
                  type="submit"
                  disabled={busy || !prompt.trim()}
                  className={[
                    'px-5 py-3 rounded-xl bg-blue-600 hover:bg-blue-700',
                    'disabled:opacity-50 disabled:cursor-not-allowed',
                    'transition-colors text-sm font-semibold',
                    'flex items-center justify-center min-w-[80px]',
                  ].join(' ')}
                >
                  {busy ? <Loader2 size={18} className="animate-spin" /> : 'Edit'}
                </button>
              </form>

              {/* Tip */}
              <div className="mt-3 text-xs text-white/40">
                Tip: click{' '}
                <span className="text-white/70 font-semibold">Use this</span> on a
                result to keep editing it.
              </div>

              {/* Results grid */}
              <EditResultGrid
                images={results}
                onUse={handleUse}
                onTryAgain={() => lastPrompt && runEdit(lastPrompt)}
                onOpen={onOpenLightbox}
                disabled={busy}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default EditTab
