/**
 * CommunityGallery — Phase 3 Community Gallery
 *
 * Embeddable gallery component that renders inside ProjectsView's
 * "Shared with me" tab. Fetches from the backend proxy (/community/registry),
 * shows persona cards with previews, search, tag filtering, and one-click
 * install via the existing PersonaImportModal flow.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Search,
  Download,
  RefreshCw,
  Globe,
  AlertTriangle,
  Package,
  Tag,
  User,
  Loader2,
  Info,
  X,
  Sparkles,
  BookOpen,
  Wrench,
} from 'lucide-react'

import type { CommunityPersonaItem } from './communityApi'
import {
  communityStatus,
  communityRegistry,
  communityDownloadPackage,
  communityCard,
} from './communityApi'
import { previewPersonaPackage, importPersonaPackage } from './personaPortability'
import type { PersonaPreview } from './personaPortability'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type GalleryState =
  | { kind: 'loading' }
  | { kind: 'not_configured' }
  | { kind: 'unreachable' }
  | { kind: 'loaded'; items: CommunityPersonaItem[]; total: number }
  | { kind: 'error'; message: string }

type InstallState =
  | { kind: 'idle' }
  | { kind: 'downloading'; personaId: string }
  | { kind: 'previewing'; personaId: string }
  | { kind: 'preview'; personaId: string; file: File; preview: PersonaPreview }
  | { kind: 'installing'; personaId: string }
  | { kind: 'done'; personaId: string; projectName: string }
  | { kind: 'error'; personaId: string; message: string }

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type CommunityGalleryProps = {
  backendUrl: string
  apiKey?: string
  onInstalled?: () => void  // refresh project list after install
}

// ---------------------------------------------------------------------------
// Gallery Card
// ---------------------------------------------------------------------------

function GalleryCard({
  item,
  installing,
  onInstall,
  onDetail,
}: {
  item: CommunityPersonaItem
  installing: boolean
  onInstall: () => void
  onDetail: () => void
}) {
  const size = item.latest?.size_bytes
  const sizeLabel = size
    ? size < 1048576
      ? `${(size / 1024).toFixed(0)} KB`
      : `${(size / 1048576).toFixed(1)} MB`
    : null

  return (
    <div className="relative w-full max-w-[340px] bg-white/[0.04] border border-white/[0.08] rounded-xl overflow-hidden hover:border-white/[0.16] transition-all group">
      {/* Preview */}
      <div className="relative aspect-[4/5] bg-black/20 overflow-hidden">
        {item.latest?.preview_url ? (
          <img
            src={item.latest.preview_url}
            alt={item.name}
            loading="lazy"
            className="block w-full h-full object-cover"
            onError={(e) => {
              ;(e.target as HTMLImageElement).style.display = 'none'
            }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-white/20">
            <User size={48} />
          </div>
        )}
        {item.nsfw && (
          <span className="absolute top-2 right-2 px-2 py-0.5 rounded-full bg-red-500/80 text-white text-[10px] font-bold uppercase backdrop-blur-sm">
            NSFW
          </span>
        )}
      </div>

      {/* Body */}
      <div className="p-3.5">
        <div className="text-sm font-semibold text-white truncate mb-1">
          {item.name}
        </div>
        <div className="text-xs text-white/40 line-clamp-2 mb-2.5 min-h-[32px]">
          {item.short}
        </div>

        {/* Tags */}
        <div className="flex items-center gap-1.5 mb-2.5 flex-wrap">
          {item.tags.slice(0, 3).map((t) => (
            <span
              key={t}
              className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300"
            >
              {t}
            </span>
          ))}
        </div>

        {/* Meta */}
        <div className="flex items-center justify-between text-[11px] text-white/30 mb-3">
          <span>{(item.downloads || 0).toLocaleString()} downloads</span>
          {sizeLabel && <span>{sizeLabel}</span>}
        </div>

        {/* Action buttons */}
        <div className="flex gap-2">
          <button
            onClick={onDetail}
            className="flex-1 py-2 rounded-lg text-xs font-semibold transition-all
              bg-white/[0.06] hover:bg-white/[0.12] text-white/70 hover:text-white
              border border-white/[0.08]
              flex items-center justify-center gap-1.5"
          >
            <Info size={13} />
            Details
          </button>
          <button
            onClick={onInstall}
            disabled={installing}
            className="flex-1 py-2 rounded-lg text-xs font-semibold transition-all
              bg-purple-500/90 hover:bg-purple-500 text-white
              disabled:opacity-50 disabled:cursor-not-allowed
              flex items-center justify-center gap-1.5"
          >
            {installing ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                Installing...
              </>
            ) : (
              <>
                <Download size={13} />
                Install
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Install Preview Modal
// ---------------------------------------------------------------------------

function InstallPreviewModal({
  state,
  onConfirm,
  onCancel,
}: {
  state: InstallState
  onConfirm: () => void
  onCancel: () => void
}) {
  if (state.kind !== 'preview') return null
  const { preview } = state

  const agent = preview.persona_agent || {}
  const depCheck = preview.dependency_check
  const allGood = depCheck?.all_satisfied !== false

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#1a1a1c] border border-white/10 rounded-2xl max-w-md w-full mx-4 overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="p-5 border-b border-white/[0.06]">
          <div className="text-base font-semibold text-white">
            Install: {agent.label || 'Persona'}
          </div>
          <div className="text-xs text-white/40 mt-1">
            {agent.role || 'Community persona'}
          </div>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 max-h-[50vh] overflow-y-auto">
          {/* System prompt preview */}
          {agent.system_prompt && (
            <div>
              <div className="text-xs font-medium text-white/50 mb-1.5">System Prompt</div>
              <div className="text-xs text-white/60 bg-white/[0.03] border border-white/[0.06] rounded-lg p-3 max-h-24 overflow-y-auto leading-relaxed">
                {agent.system_prompt.slice(0, 300)}
                {agent.system_prompt.length > 300 && '...'}
              </div>
            </div>
          )}

          {/* Dependency status */}
          {depCheck && (
            <div>
              <div className="text-xs font-medium text-white/50 mb-1.5">Dependencies</div>
              <div className={`text-xs px-3 py-2 rounded-lg border ${
                allGood
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
                  : 'bg-amber-500/10 border-amber-500/20 text-amber-300'
              }`}>
                {allGood
                  ? 'All dependencies satisfied'
                  : depCheck.summary || 'Some dependencies may need setup'}
              </div>
            </div>
          )}

          {/* Tools */}
          {agent.allowed_tools && agent.allowed_tools.length > 0 && (
            <div>
              <div className="text-xs font-medium text-white/50 mb-1.5">Tools</div>
              <div className="flex flex-wrap gap-1">
                {agent.allowed_tools.map((t: string) => (
                  <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-white/[0.06] text-white/50">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.06] flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-white/60 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-5 py-2 rounded-lg text-sm font-semibold bg-purple-500 hover:bg-purple-600 text-white transition-colors"
          >
            Install Persona
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Detail Modal
// ---------------------------------------------------------------------------

function DetailModal({
  card,
  item,
  previewUrl,
  onClose,
  onInstall,
}: {
  card: Record<string, any>
  item: CommunityPersonaItem
  previewUrl?: string
  onClose: () => void
  onInstall: () => void
}) {
  const stats = card.stats || {} as Record<string, number>
  const statEntries = Object.entries(stats).filter(([k]) => k !== 'level') as [string, number][]
  const level = stats.level ?? 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-[#1a1a1c] border border-white/10 rounded-2xl max-w-lg w-full mx-4 overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header with preview */}
        <div className="relative">
          {previewUrl ? (
            <img
              src={previewUrl}
              alt={card.name || item.name}
              className="w-full h-48 object-cover"
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
            />
          ) : (
            <div className="w-full h-32 bg-gradient-to-br from-purple-900/40 to-black/40 flex items-center justify-center">
              <User size={48} className="text-white/20" />
            </div>
          )}
          <button
            onClick={onClose}
            className="absolute top-3 right-3 p-1.5 rounded-full bg-black/50 text-white/70 hover:text-white backdrop-blur-sm transition-colors"
          >
            <X size={16} />
          </button>
          {level > 0 && (
            <div className="absolute bottom-3 left-3 px-2.5 py-1 rounded-full bg-purple-500/80 text-white text-[10px] font-bold backdrop-blur-sm">
              Lv. {level}
            </div>
          )}
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 max-h-[50vh] overflow-y-auto">
          {/* Name & Role */}
          <div>
            <h2 className="text-lg font-bold text-white">{card.name || item.name}</h2>
            <p className="text-sm text-white/50">{card.role || ''}</p>
          </div>

          {/* Short description */}
          {card.short && (
            <p className="text-sm text-white/60 leading-relaxed">{card.short}</p>
          )}

          {/* Backstory */}
          {card.backstory && (
            <div>
              <div className="flex items-center gap-1.5 text-xs font-medium text-white/50 mb-1.5">
                <BookOpen size={12} />
                Backstory
              </div>
              <p className="text-xs text-white/50 bg-white/[0.03] border border-white/[0.06] rounded-lg p-3 leading-relaxed">
                {card.backstory}
              </p>
            </div>
          )}

          {/* Stats bars */}
          {statEntries.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 text-xs font-medium text-white/50 mb-2">
                <Sparkles size={12} />
                Stats
              </div>
              <div className="space-y-1.5">
                {statEntries.map(([key, val]) => (
                  <div key={key} className="flex items-center gap-2">
                    <span className="text-[10px] text-white/40 w-20 capitalize">{key}</span>
                    <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-purple-500/70 rounded-full transition-all"
                        style={{ width: `${Math.min(100, val)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-white/30 w-6 text-right">{val}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Style & Tone tags */}
          {(card.style_tags?.length > 0 || card.tone_tags?.length > 0) && (
            <div className="flex flex-wrap gap-1.5">
              {(card.style_tags || []).map((t: string) => (
                <span key={`s-${t}`} className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300">
                  {t}
                </span>
              ))}
              {(card.tone_tags || []).map((t: string) => (
                <span key={`t-${t}`} className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300">
                  {t}
                </span>
              ))}
            </div>
          )}

          {/* Tools */}
          {card.tools?.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 text-xs font-medium text-white/50 mb-1.5">
                <Wrench size={12} />
                Tools
              </div>
              <div className="flex flex-wrap gap-1.5">
                {card.tools.map((t: string) => (
                  <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-white/[0.06] text-white/50">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-white/[0.06] flex items-center justify-between">
          <div className="text-xs text-white/30">
            {(item.downloads || 0).toLocaleString()} downloads
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-white/60 hover:text-white transition-colors"
            >
              Close
            </button>
            <button
              onClick={() => { onClose(); onInstall() }}
              className="px-5 py-2 rounded-lg text-sm font-semibold bg-purple-500 hover:bg-purple-600 text-white transition-colors flex items-center gap-2"
            >
              <Download size={14} />
              Install
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Success / Error Toast
// ---------------------------------------------------------------------------

function InstallToast({
  state,
  onDismiss,
}: {
  state: InstallState
  onDismiss: () => void
}) {
  if (state.kind === 'done') {
    return (
      <div className="fixed bottom-6 right-6 z-50 bg-emerald-600/90 text-white px-5 py-3 rounded-xl shadow-lg backdrop-blur-sm flex items-center gap-3 animate-in slide-in-from-bottom-4">
        <Package size={18} />
        <div>
          <div className="text-sm font-semibold">Installed!</div>
          <div className="text-xs opacity-80">{state.projectName} is ready in My Projects.</div>
        </div>
        <button onClick={onDismiss} className="ml-3 text-white/60 hover:text-white">&times;</button>
      </div>
    )
  }
  if (state.kind === 'error') {
    return (
      <div className="fixed bottom-6 right-6 z-50 bg-red-600/90 text-white px-5 py-3 rounded-xl shadow-lg backdrop-blur-sm flex items-center gap-3">
        <AlertTriangle size={18} />
        <div>
          <div className="text-sm font-semibold">Install failed</div>
          <div className="text-xs opacity-80">{state.message}</div>
        </div>
        <button onClick={onDismiss} className="ml-3 text-white/60 hover:text-white">&times;</button>
      </div>
    )
  }
  return null
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 48

export function CommunityGallery({ backendUrl, apiKey, onInstalled }: CommunityGalleryProps) {
  const [gallery, setGallery] = useState<GalleryState>({ kind: 'loading' })
  const [search, setSearch] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [install, setInstall] = useState<InstallState>({ kind: 'idle' })
  const [detail, setDetail] = useState<{ item: CommunityPersonaItem; card: Record<string, any> } | null>(null)
  const [detailLoading, setDetailLoading] = useState<string | null>(null)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  const cleanUrl = backendUrl.replace(/\/+$/, '')

  // Fetch registry
  const loadRegistry = useCallback(async () => {
    setGallery({ kind: 'loading' })
    try {
      const status = await communityStatus({ backendUrl: cleanUrl, apiKey })
      if (!status.configured) {
        setGallery({ kind: 'not_configured' })
        return
      }
      if (status.reachable === false) {
        setGallery({ kind: 'unreachable' })
        return
      }
      const data = await communityRegistry({
        backendUrl: cleanUrl,
        apiKey,
        search: search || undefined,
        tag: tagFilter || undefined,
      })
      setGallery({
        kind: 'loaded',
        items: data.items,
        total: data.total,
      })
    } catch (e: any) {
      setGallery({ kind: 'error', message: e.message || 'Unknown error' })
    }
  }, [cleanUrl, apiKey, search, tagFilter])

  useEffect(() => {
    loadRegistry()
  }, [loadRegistry])

  // Collect all unique tags
  const allTags = useMemo(() => {
    if (gallery.kind !== 'loaded') return []
    const tags = new Set<string>()
    for (const item of gallery.items) {
      for (const t of item.tags) tags.add(t)
    }
    return [...tags].sort()
  }, [gallery])

  // Install flow
  const handleInstall = useCallback(async (item: CommunityPersonaItem) => {
    const personaId = item.id
    const version = item.latest?.version
    if (!version) return

    try {
      // Step 1: Download
      setInstall({ kind: 'downloading', personaId })
      const file = await communityDownloadPackage({
        backendUrl: cleanUrl,
        apiKey,
        personaId,
        version,
      })

      // Step 2: Preview
      setInstall({ kind: 'previewing', personaId })
      const preview = await previewPersonaPackage({
        backendUrl: cleanUrl,
        apiKey,
        file,
      })

      // Step 3: Show preview modal
      setInstall({ kind: 'preview', personaId, file, preview })
    } catch (e: any) {
      setInstall({ kind: 'error', personaId, message: e.message || 'Download failed' })
    }
  }, [cleanUrl, apiKey])

  const handleConfirmInstall = useCallback(async () => {
    if (install.kind !== 'preview') return
    const { personaId, file } = install

    try {
      setInstall({ kind: 'installing', personaId })
      const result = await importPersonaPackage({
        backendUrl: cleanUrl,
        apiKey,
        file,
      })
      const projectName = result.project?.name || 'Persona'
      setInstall({ kind: 'done', personaId, projectName })
      onInstalled?.()
    } catch (e: any) {
      setInstall({ kind: 'error', personaId, message: e.message || 'Import failed' })
    }
  }, [install, cleanUrl, apiKey, onInstalled])

  const dismissInstall = useCallback(() => {
    setInstall({ kind: 'idle' })
  }, [])

  // Detail flow
  const handleDetail = useCallback(async (item: CommunityPersonaItem) => {
    const version = item.latest?.version
    if (!version) return

    setDetailLoading(item.id)
    try {
      const card = await communityCard({
        backendUrl: cleanUrl,
        apiKey,
        personaId: item.id,
        version,
      })
      setDetail({ item, card })
    } catch {
      // Fallback: show what we have from the registry item
      setDetail({
        item,
        card: { name: item.name, short: item.short, tags: item.tags },
      })
    } finally {
      setDetailLoading(null)
    }
  }, [cleanUrl, apiKey])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // Loading
  if (gallery.kind === 'loading') {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-white/50">
        <Loader2 size={32} className="animate-spin mb-4 opacity-50" />
        <p className="text-sm">Loading community gallery...</p>
      </div>
    )
  }

  // Not configured
  if (gallery.kind === 'not_configured') {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-white/50">
        <Globe size={40} className="mb-4 opacity-40" />
        <p className="text-base font-semibold text-white/60 mb-2">Community Gallery</p>
        <p className="text-sm text-white/40 text-center max-w-md mb-4">
          Browse and install community-created personas. The gallery was explicitly disabled.
          Remove{' '}
          <code className="text-xs bg-white/10 px-1.5 py-0.5 rounded">COMMUNITY_GALLERY_URL</code>{' '}
          from your <code className="text-xs bg-white/10 px-1.5 py-0.5 rounded">.env</code>{' '}
          to restore the default gallery, or set a custom URL.
        </p>
        <a
          href="https://github.com/ruslanmv/HomePilot/blob/main/docs/COMMUNITY_GALLERY.md"
          target="_blank"
          rel="noopener"
          className="text-xs text-purple-400 hover:text-purple-300 transition-colors"
        >
          Learn how to set up the gallery
        </a>
      </div>
    )
  }

  // Unreachable
  if (gallery.kind === 'unreachable') {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-white/50">
        <AlertTriangle size={40} className="mb-4 text-amber-400/60" />
        <p className="text-base font-semibold text-white/60 mb-2">Gallery Unavailable</p>
        <p className="text-sm text-white/40 mb-4">The community gallery is configured but not reachable.</p>
        <button
          onClick={loadRegistry}
          className="flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 hover:bg-white/20 text-sm transition-colors"
        >
          <RefreshCw size={14} /> Retry
        </button>
      </div>
    )
  }

  // Error
  if (gallery.kind === 'error') {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-white/50">
        <AlertTriangle size={40} className="mb-4 text-red-400/60" />
        <p className="text-sm mb-4">{gallery.message}</p>
        <button
          onClick={loadRegistry}
          className="flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 hover:bg-white/20 text-sm transition-colors"
        >
          <RefreshCw size={14} /> Retry
        </button>
      </div>
    )
  }

  // Loaded
  const { items, total } = gallery

  return (
    <>
      {/* Search & filter bar */}
      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setVisibleCount(PAGE_SIZE) }}
            placeholder="Search personas..."
            className="w-full pl-9 pr-4 py-2 rounded-lg bg-white/[0.06] border border-white/[0.08] text-sm text-white placeholder:text-white/30 outline-none focus:border-purple-500/50 transition-colors"
          />
        </div>

        {allTags.length > 0 && (
          <select
            value={tagFilter}
            onChange={(e) => { setTagFilter(e.target.value); setVisibleCount(PAGE_SIZE) }}
            className="px-3 py-2 rounded-lg bg-white/[0.06] border border-white/[0.08] text-sm text-white/70 outline-none focus:border-purple-500/50 transition-colors"
          >
            <option value="" className="bg-white text-gray-900">All Tags</option>
            {allTags.map((t) => (
              <option key={t} value={t} className="bg-white text-gray-900">{t}</option>
            ))}
          </select>
        )}

        <button
          onClick={loadRegistry}
          className="p-2 rounded-lg bg-white/[0.06] border border-white/[0.08] text-white/40 hover:text-white hover:bg-white/10 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={16} />
        </button>

        <span className="text-xs text-white/30 ml-auto">
          {items.length === total
            ? `${total} personas`
            : `${items.length} of ${total} personas`}
        </span>
      </div>

      {/* Grid */}
      {items.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48 text-white/50">
          <Package size={36} className="mb-3 opacity-40" />
          <p className="text-sm">No personas found.</p>
          {(search || tagFilter) && (
            <button
              onClick={() => { setSearch(''); setTagFilter('') }}
              className="mt-2 text-xs text-purple-400 hover:text-purple-300"
            >
              Clear filters
            </button>
          )}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 justify-items-center">
            {items.slice(0, visibleCount).map((item) => (
              <GalleryCard
                key={item.id}
                item={item}
                installing={
                  (install.kind === 'downloading' || install.kind === 'previewing' || install.kind === 'installing')
                  && install.personaId === item.id
                }
                onInstall={() => handleInstall(item)}
                onDetail={() => handleDetail(item)}
              />
            ))}
          </div>
          {visibleCount < items.length && (
            <div className="flex justify-center pt-6 pb-2">
              <button
                onClick={() => setVisibleCount((v) => v + PAGE_SIZE)}
                className="px-7 py-2.5 rounded-full border border-white/[0.08] bg-white/[0.04] text-white/50 text-sm font-semibold hover:border-purple-500/40 hover:text-purple-300 transition-all"
              >
                Load more ({items.length - visibleCount} remaining)
              </button>
            </div>
          )}
        </>
      )}

      {/* Detail modal */}
      {detail && (
        <DetailModal
          card={detail.card}
          item={detail.item}
          previewUrl={detail.item.latest?.preview_url}
          onClose={() => setDetail(null)}
          onInstall={() => handleInstall(detail.item)}
        />
      )}

      {/* Install preview modal */}
      <InstallPreviewModal
        state={install}
        onConfirm={handleConfirmInstall}
        onCancel={dismissInstall}
      />

      {/* Toast */}
      <InstallToast state={install} onDismiss={dismissInstall} />
    </>
  )
}

export default CommunityGallery
