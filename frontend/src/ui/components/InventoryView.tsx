/**
 * InventoryView — MMORPG-style inventory management panel.
 *
 * Replaces the PersonaSettingsPanel content when viewMode="inventory".
 * Two-pane layout:
 *   Left:  category sidebar with counts
 *   Right: search bar + item grid with lazy loading
 *
 * Mental model: A persona has exactly ONE "Active Look" — the image that
 * represents them everywhere.  Inventory is a gallery of stored images;
 * any image can be promoted to Active Look via a single click.  Thumbnails
 * are derived automatically and never shown as selectable items.
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  ArrowLeft,
  Search,
  Shirt,
  Image as ImageIcon,
  FileText,
  Loader2,
  Eye,
  Lock,
  Package,
  AlertCircle,
  Trash2,
  RotateCcw,
} from 'lucide-react'
import type { InventoryCategory, InventoryItem } from '../inventoryApi'
import {
  fetchInventoryCategories,
  searchInventory,
  deleteInventoryItem,
} from '../inventoryApi'
import { PersonaDocumentsPanel } from './PersonaDocumentsPanel'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Props = {
  projectId: string
  backendUrl: string
  apiKey?: string
  onBack: () => void
  /** Called when user clicks "Show in chat" with a resolved image URL */
  onShowInChat?: (item: InventoryItem, resolvedUrl: string) => void
  /** Currently selected image (from PersonaSettingsPanel selectedImage state).
   *  Used to draw the amber "Equipped" border on the matching inventory card. */
  activeSelection?: { set_id: string; image_id: string } | null
  /** Called when user selects an image as the persona's Active Look.
   *  Passes the persona_appearance set_id + image_id for wardrobe-style selection. */
  onSetActiveLook?: (selection: { set_id: string; image_id: string }) => void
  /** Draft persona appearance from local state so newly generated
   *  images appear in inventory before they are saved to backend. */
  draftAppearance?: DraftAppearance
}

type SelectedCategory = 'outfit' | 'image' | 'file' | 'all'

// ---------------------------------------------------------------------------
// Draft appearance type — local state passed from PersonaSettingsPanel
// so generated images appear in inventory before they are saved to backend.
// ---------------------------------------------------------------------------

type DraftAppearance = {
  sets: Array<{ set_id: string; images: Array<{ id: string; url: string; set_id: string }> }>
  outfits: Array<{
    id: string
    label: string
    outfit_prompt?: string
    images: Array<{ id: string; url: string; set_id: string }>
  }>
  selected: { set_id: string; image_id: string } | null
}

// ---------------------------------------------------------------------------
// Sensitivity helpers (mirrors backend inventory.py)
// ---------------------------------------------------------------------------

const SENS_ORDER: Record<string, number> = { safe: 0, sensitive: 1, explicit: 2 }

function classifySensitivity(label: string): 'safe' | 'sensitive' {
  const low = (label || '').trim().toLowerCase()
  const keywords = ['lingerie', 'intimate', 'underwear', 'bra', 'panties', 'sexy', 'bikini']
  return keywords.some(k => low.includes(k)) ? 'sensitive' : 'safe'
}

function allowedBySensitivity(itemSens: string, maxSens: string): boolean {
  return (SENS_ORDER[itemSens] ?? 0) <= (SENS_ORDER[maxSens] ?? 0)
}

// ---------------------------------------------------------------------------
// Build InventoryItem[] from local draft state
// ---------------------------------------------------------------------------

function buildDraftItems(
  draft: DraftAppearance,
  sensitivityMax: string,
): InventoryItem[] {
  const out: InventoryItem[] = []
  const active = draft.selected

  // Base portraits from sets → type='image'
  for (const s of draft.sets) {
    for (const img of s.images) {
      if (!img.url) continue
      if (!allowedBySensitivity('safe', sensitivityMax)) continue
      out.push({
        id: img.id,
        type: 'image',
        label: 'Portrait',
        tags: ['portrait', 'set'],
        sensitivity: 'safe',
        url: img.url,
        set_id: s.set_id,
        image_id: img.id,
        is_active_look: !!(active && s.set_id === active.set_id && img.id === active.image_id),
      })
    }
  }

  // Outfits → type='outfit' with preview image (mirrors backend search output)
  for (const outfit of draft.outfits) {
    const sens = classifySensitivity(outfit.label)
    if (!allowedBySensitivity(sens, sensitivityMax)) continue
    const firstImg = outfit.images[0]
    out.push({
      id: outfit.id,
      type: 'outfit',
      label: outfit.label,
      tags: [outfit.label.toLowerCase()],
      sensitivity: sens,
      description: outfit.outfit_prompt,
      asset_ids: outfit.images.map(img => img.id),
      preview_asset_id: firstImg?.id,
      url: firstImg?.url,
      // set_id/image_id from first image so the outfit card is selectable
      set_id: firstImg ? outfit.id : undefined,
      image_id: firstImg?.id,
      is_active_look: !!(active && firstImg && outfit.id === active.set_id && firstImg.id === active.image_id),
    })
  }

  return out
}

// ---------------------------------------------------------------------------
// Category icon map
// ---------------------------------------------------------------------------

const CATEGORY_ICONS: Record<string, React.ElementType> = {
  outfit: Shirt,
  image: ImageIcon,
  file: FileText,
  all: Package,
}

const CATEGORY_COLORS: Record<string, string> = {
  outfit: 'text-amber-400',
  image: 'text-pink-400',
  file: 'text-blue-400',
  all: 'text-purple-400',
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function InventoryView({ projectId, backendUrl, apiKey, onBack, onShowInChat, activeSelection, onSetActiveLook, draftAppearance }: Props) {
  // State
  const [categories, setCategories] = useState<InventoryCategory[]>([])
  const [items, setItems] = useState<InventoryItem[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [searchLoading, setSearchLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedCategory, setSelectedCategory] = useState<SelectedCategory>('all')
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [limit] = useState(30)
  const [refreshKey, setRefreshKey] = useState(0)
  const [deleting, setDeleting] = useState<string | null>(null)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout>>()

  // Sensitivity from localStorage (matches PersonaSettingsPanel)
  const isSpicy = (() => {
    try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false }
  })()
  const sensitivityMax = isSpicy ? 'explicit' : 'safe'

  // -----------------------------------------------------------------------
  // Draft items from local state (appear before backend save)
  // -----------------------------------------------------------------------
  const draftItems = useMemo(() => {
    if (!draftAppearance) return []
    return buildDraftItems(draftAppearance, sensitivityMax)
  }, [draftAppearance, sensitivityMax])

  // Merge backend items + draft extras (backend wins on ID conflicts)
  const mergedItems = useMemo(() => {
    const backendIds = new Set(items.map(i => i.id))
    const q = debouncedQuery.toLowerCase()
    const extras = draftItems.filter(d => {
      if (backendIds.has(d.id)) return false
      if (selectedCategory !== 'all' && d.type !== selectedCategory) return false
      if (q) {
        const label = (d.label || '').toLowerCase()
        const desc = (d.description || '').toLowerCase()
        const tags = (d.tags || []).join(' ').toLowerCase()
        if (!label.includes(q) && !desc.includes(q) && !tags.includes(q)) return false
      }
      return true
    })
    return [...items, ...extras]
  }, [items, draftItems, selectedCategory, debouncedQuery])

  // Merged category counts: backend counts + genuinely new draft items
  // (items with uncommitted URLs that aren't in the backend yet).
  const mergedCategories = useMemo((): InventoryCategory[] => {
    const extrasByType: Record<string, number> = {}
    const backendIds = new Set(items.map(i => i.id))
    for (const d of draftItems) {
      if (backendIds.has(d.id)) continue
      // Items with /files/ URLs are already committed — avoid double-count
      const url = d.url || ''
      if (url.includes('/files/')) continue
      if (!url) continue
      extrasByType[d.type] = (extrasByType[d.type] || 0) + 1
    }

    if (categories.length > 0) {
      return categories.map(cat => ({
        ...cat,
        count: (cat.count ?? 0) + (extrasByType[cat.type] ?? 0),
      }))
    }
    return [
      { type: 'outfit', label: 'Outfits', count: extrasByType.outfit ?? 0 },
      { type: 'image', label: 'Photos', count: extrasByType.image ?? 0 },
      { type: 'file', label: 'Documents', count: extrasByType.file ?? 0 },
    ]
  }, [categories, items, draftItems])

  // -----------------------------------------------------------------------
  // Debounced search
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    searchTimerRef.current = setTimeout(() => setDebouncedQuery(query), 300)
    return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current) }
  }, [query])

  // -----------------------------------------------------------------------
  // Load categories on mount
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await fetchInventoryCategories(backendUrl, projectId, {
          apiKey,
          includeTags: true,
          sensitivityMax,
        })
        if (!cancelled) setCategories(data.categories || [])
      } catch (e: any) {
        if (!cancelled) setError(e.message)
      }
    })()
    return () => { cancelled = true }
  }, [backendUrl, projectId, apiKey, sensitivityMax, refreshKey])

  // -----------------------------------------------------------------------
  // Search when category or query changes
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setSearchLoading(true)
      try {
        const types = selectedCategory === 'all' ? undefined : [selectedCategory]
        const data = await searchInventory(backendUrl, projectId, {
          apiKey,
          query: debouncedQuery || undefined,
          types,
          limit,
          sensitivityMax,
        })
        if (!cancelled) {
          setItems(data.items || [])
          setTotalCount(data.total_count || 0)
          setError(null)
        }
      } catch (e: any) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) {
          setSearchLoading(false)
          setLoading(false)
        }
      }
    })()
    return () => { cancelled = true }
  }, [backendUrl, projectId, apiKey, selectedCategory, debouncedQuery, limit, sensitivityMax, refreshKey])

  // -----------------------------------------------------------------------
  // Resolve image URL for display
  // -----------------------------------------------------------------------
  const resolveImageUrl = useCallback((item: InventoryItem): string | undefined => {
    const url = item.url
    if (!url) return undefined
    const tok = (() => { try { return localStorage.getItem('homepilot_auth_token') || '' } catch { return '' } })()
    let full = url.startsWith('http') ? url : `${backendUrl}${url}`
    if (tok && full.includes('/files/')) {
      const sep = full.includes('?') ? '&' : '?'
      full = `${full}${sep}token=${encodeURIComponent(tok)}`
    }
    return full
  }, [backendUrl])

  // -----------------------------------------------------------------------
  // Delete handler
  // -----------------------------------------------------------------------
  const handleDelete = useCallback(async (item: InventoryItem) => {
    if (deleting) return
    // Prevent deleting the active look from the UI side
    if (item.is_active_look) {
      setError('Cannot delete the active look. Change the active look first.')
      return
    }
    if (!confirm(`Delete "${item.label}"? This cannot be undone.`)) return
    setDeleting(item.id)
    try {
      await deleteInventoryItem(backendUrl, projectId, item.id, { apiKey })
      setRefreshKey((k) => k + 1)
    } catch (e: any) {
      const msg = e.message || ''
      if (msg.includes('409') || msg.includes('active look')) {
        setError('Cannot delete the active look. Change the active look first.')
      } else {
        setError(`Delete failed: ${msg}`)
      }
    } finally {
      setDeleting(null)
    }
  }, [backendUrl, projectId, apiKey, deleting])

  // -----------------------------------------------------------------------
  // Set as Active Look handler (wardrobe-style selection)
  // -----------------------------------------------------------------------
  const handleSetActiveLook = useCallback((item: InventoryItem) => {
    if (!item.set_id || !item.image_id) return
    onSetActiveLook?.({ set_id: item.set_id, image_id: item.image_id })
  }, [onSetActiveLook])

  // -----------------------------------------------------------------------
  // Render: category sidebar
  // -----------------------------------------------------------------------
  const totalItems = mergedCategories.reduce((sum, c) => sum + (c.count || 0), 0)

  const renderSidebar = () => (
    <div className="w-44 shrink-0 border-r border-white/10 py-3 space-y-0.5">
      {/* All items */}
      <SidebarItem
        icon={Package}
        label="All Items"
        count={totalItems}
        color="text-purple-400"
        active={selectedCategory === 'all'}
        onClick={() => setSelectedCategory('all')}
      />
      {/* Per-category */}
      {mergedCategories.map((cat) => (
        <SidebarItem
          key={cat.type}
          icon={CATEGORY_ICONS[cat.type] || Package}
          label={cat.label}
          count={cat.count}
          color={CATEGORY_COLORS[cat.type] || 'text-white/50'}
          active={selectedCategory === cat.type}
          onClick={() => setSelectedCategory(cat.type as SelectedCategory)}
        />
      ))}
    </div>
  )

  // -----------------------------------------------------------------------
  // Render: item card
  // -----------------------------------------------------------------------
  const renderItemCard = (item: InventoryItem) => {
    const isImage = item.type === 'image'
    const isOutfit = item.type === 'outfit'
    const isFile = item.type === 'file'
    const isSensitive = item.sensitivity === 'sensitive' || item.sensitivity === 'explicit'
    const imgUrl = (isImage || isOutfit) ? resolveImageUrl(item) : undefined
    const canSetActive = !!(item.set_id && item.image_id && onSetActiveLook)

    // Wardrobe-style: check if this card matches the current selection
    const isSelected = !!(
      activeSelection
      && item.set_id === activeSelection.set_id
      && item.image_id === activeSelection.image_id
    )

    const isDeleting = deleting === item.id

    return (
      <div
        key={item.id}
        className={[
          'group relative rounded-xl overflow-hidden transition-all',
          isSelected
            ? 'border-2 border-amber-500/50 ring-2 ring-amber-500/20 shadow-[0_0_12px_rgba(245,158,11,0.15)]'
            : 'border border-white/[0.06] bg-white/[0.02] hover:border-white/15',
          isDeleting ? 'opacity-40 pointer-events-none' : '',
        ].join(' ')}
      >
        {/* Equipped badge — Wardrobe style (top-right, always visible when selected or outfit is equipped) */}
        {(isSelected || (isOutfit && item.equipped)) && (
          <div className="absolute top-1.5 right-1.5 px-1.5 py-0.5 rounded-md bg-amber-500/80 text-[7px] text-white font-bold uppercase tracking-wider z-10">
            Equipped
          </div>
        )}

        {/* Delete button — top-right on hover (shifts left when Equipped badge is showing) */}
        <div className={[
          'absolute top-1.5 z-10 opacity-0 group-hover:opacity-100 transition-opacity',
          isSelected ? 'left-1.5' : 'right-1.5',
        ].join(' ')}>
          <ActionButton
            icon={Trash2}
            label="Delete"
            onClick={() => handleDelete(item)}
            variant="danger"
          />
        </div>

        {/* Image preview — primary click selects (like Wardrobe) */}
        {(isImage || isOutfit) && (
          <div
            className="aspect-[3/4] bg-black/30 relative overflow-hidden cursor-pointer"
            onClick={() => {
              if (canSetActive) {
                handleSetActiveLook(item)
              }
            }}
          >
            {isSensitive && !isSpicy ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60">
                <Lock size={20} className="text-white/30" />
                <span className="text-[10px] text-white/30">Locked</span>
              </div>
            ) : imgUrl ? (
              <img
                src={imgUrl}
                alt={item.label}
                className="w-full h-full object-cover"
                loading="lazy"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <ImageIcon size={24} className="text-white/20" />
              </div>
            )}

            {/* Hover actions — bottom center (only Show in chat) */}
            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all flex items-end justify-center pb-2 gap-1.5 opacity-0 group-hover:opacity-100">
              {onShowInChat && imgUrl && (
                <ActionButton
                  icon={Eye}
                  label="Show in chat"
                  onClick={() => onShowInChat(item, imgUrl)}
                />
              )}
            </div>
          </div>
        )}

        {/* File icon for documents */}
        {isFile && (
          <div className="aspect-[4/3] bg-black/20 flex items-center justify-center relative">
            <div className="flex flex-col items-center gap-1.5">
              <FileText size={28} className="text-blue-400/60" />
              <span className="text-[9px] text-white/30 uppercase tracking-wider">
                {(item.mime || '').split('/').pop() || 'file'}
              </span>
            </div>
          </div>
        )}

        {/* Label + metadata */}
        <div className="px-2.5 py-2">
          <div className="text-xs text-white truncate font-medium">{item.label}</div>
          <div className="flex items-center gap-1 mt-1 flex-wrap">
            <span className={`text-[9px] uppercase tracking-wider ${CATEGORY_COLORS[item.type] || 'text-white/40'}`}>
              {item.type}
            </span>
            {isSensitive && (
              <span className={`text-[9px] flex items-center gap-0.5 ${item.sensitivity === 'explicit' ? 'text-red-400/60' : 'text-orange-400/60'}`}>
                <Lock size={8} /> {item.sensitivity}
              </span>
            )}
            {/* 360 preview badge for outfits with view packs */}
            {isOutfit && item.interactive_preview && (
              <span className="text-[9px] flex items-center gap-0.5 text-violet-300/60">
                <RotateCcw size={8} /> 360
              </span>
            )}
          </div>
          {/* Tags */}
          {item.tags && item.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {item.tags.slice(0, 3).map((tag) => (
                <span
                  key={tag}
                  className="text-[9px] px-1.5 py-0.5 rounded-full bg-white/5 text-white/30 border border-white/5"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
          {/* View angle chips for outfits with view packs */}
          {isOutfit && item.available_views && item.available_views.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {item.available_views.map((angle) => (
                <span
                  key={angle}
                  className="text-[8px] px-1.5 py-0.5 rounded-full bg-violet-500/8 text-violet-300/50 border border-violet-500/15 capitalize"
                >
                  {angle}
                </span>
              ))}
            </div>
          )}
          {isFile && item.size_bytes != null && item.size_bytes > 0 && (
            <div className="text-[9px] text-white/25 mt-1">
              {item.size_bytes > 1048576
                ? `${(item.size_bytes / 1048576).toFixed(1)} MB`
                : `${Math.round(item.size_bytes / 1024)} KB`}
            </div>
          )}
        </div>
      </div>
    )
  }

  // -----------------------------------------------------------------------
  // Render: loadout summary (compact, top of content)
  // -----------------------------------------------------------------------
  const activeLookItem = mergedItems.find((i) => i.is_active_look)
  const outfitCount = mergedCategories.find((c) => c.type === 'outfit')?.count || 0
  const photoCount = mergedCategories.find((c) => c.type === 'image')?.count || 0
  const docCount = mergedCategories.find((c) => c.type === 'file')?.count || 0

  const renderLoadoutSummary = () => (
    <div className="flex items-center gap-4 px-4 py-2.5 bg-white/[0.03] border-b border-white/5">
      {/* Mini Active Look */}
      {activeLookItem?.url && (
        <div className="w-8 h-8 rounded-lg overflow-hidden border border-amber-500/30 shrink-0">
          <img
            src={resolveImageUrl(activeLookItem) || ''}
            alt="Active Look"
            className="w-full h-full object-cover"
          />
        </div>
      )}
      <div className="flex items-center gap-3 text-[10px] text-white/40">
        <span className="flex items-center gap-1"><Shirt size={10} className="text-amber-400/60" /> {outfitCount} outfits</span>
        <span className="flex items-center gap-1"><ImageIcon size={10} className="text-pink-400/60" /> {photoCount} photos</span>
        <span className="flex items-center gap-1"><FileText size={10} className="text-blue-400/60" /> {docCount} docs</span>
      </div>
    </div>
  )

  // -----------------------------------------------------------------------
  // Main render
  // -----------------------------------------------------------------------
  if (loading && items.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin text-white/30" />
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Top bar: back + search */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-white/10 bg-white/[0.02]">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-xs text-white/50 hover:text-white transition-colors shrink-0"
        >
          <ArrowLeft size={14} />
          <span>Back</span>
        </button>
        <div className="flex-1 relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search inventory..."
            className="w-full pl-9 pr-3 py-1.5 text-xs bg-white/5 border border-white/10 rounded-lg text-white placeholder:text-white/25 focus:outline-none focus:border-white/20 transition-colors"
          />
        </div>
        <div className="text-[10px] text-white/30 shrink-0">
          {searchLoading ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            `${mergedItems.length} items`
          )}
        </div>
      </div>

      {/* Loadout summary */}
      {renderLoadoutSummary()}

      {/* Two-pane body */}
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        {renderSidebar()}

        {/* Item grid */}
        <div className="flex-1 overflow-y-auto custom-scrollbar p-3">
          {error && (
            <div className="flex items-center gap-2 px-3 py-2 mb-3 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400">
              <AlertCircle size={14} />
              {error}
            </div>
          )}

          {/* Knowledge Base panel (shown when Documents category is selected) */}
          {selectedCategory === 'file' && (
            <div className="mb-4 p-3 rounded-xl bg-white/[0.02] border border-white/5">
              <PersonaDocumentsPanel
                projectId={projectId}
                backendUrl={backendUrl}
                apiKey={apiKey}
                onChanged={() => setRefreshKey((k) => k + 1)}
              />
            </div>
          )}

          {mergedItems.length === 0 && !searchLoading && selectedCategory !== 'file' && (
            <div className="flex flex-col items-center justify-center py-16 gap-2 text-white/30">
              <Package size={32} className="text-white/15" />
              <p className="text-xs">
                {debouncedQuery
                  ? 'No items match your search.'
                  : totalItems > 0 && mergedItems.length === 0
                    ? 'No items returned. Check sensitivity filters or try refreshing.'
                    : 'Inventory is empty.'}
              </p>
            </div>
          )}

          {/* Hide inventory grid when Documents tab is active — the Knowledge Base panel above is the single source of truth */}
          {selectedCategory !== 'file' && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
              {mergedItems.map(renderItemCard)}
            </div>
          )}

          {selectedCategory !== 'file' && items.length < totalCount && !searchLoading && (
            <div className="text-center py-4">
              <span className="text-[10px] text-white/25">
                Showing {mergedItems.length} of {totalCount + (mergedItems.length - items.length)} items
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sidebar item
// ---------------------------------------------------------------------------

function SidebarItem({
  icon: Icon,
  label,
  count,
  color,
  active,
  onClick,
}: {
  icon: React.ElementType
  label: string
  count?: number
  color: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'w-full flex items-center gap-2.5 px-3 py-2 text-xs transition-colors',
        active
          ? 'bg-white/10 text-white border-r-2 border-pink-500'
          : 'text-white/50 hover:text-white/70 hover:bg-white/5',
      ].join(' ')}
    >
      <Icon size={14} className={active ? color : 'text-white/30'} />
      <span className="flex-1 text-left truncate">{label}</span>
      {count != null && (
        <span className="text-[10px] text-white/30 tabular-nums">{count}</span>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Action button (hover overlay)
// ---------------------------------------------------------------------------

function ActionButton({
  icon: Icon,
  label,
  onClick,
  variant,
}: {
  icon: React.ElementType
  label: string
  onClick: () => void
  variant?: 'default' | 'danger'
}) {
  const isDanger = variant === 'danger'
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick() }}
      title={label}
      className={[
        'p-1.5 rounded-lg transition-all border',
        isDanger
          ? 'bg-red-900/60 text-red-300/70 hover:text-red-200 hover:bg-red-800/80 border-red-500/20'
          : 'bg-black/60 text-white/70 hover:text-white hover:bg-black/80 border-white/10',
      ].join(' ')}
    >
      <Icon size={12} />
    </button>
  )
}
