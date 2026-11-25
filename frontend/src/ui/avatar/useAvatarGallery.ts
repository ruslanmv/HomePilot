/**
 * useAvatarGallery — hook for persistent avatar gallery.
 *
 * The gallery is kept in localStorage for instant loads AND saved to the
 * signed-in account on the server (/v1/avatar-gallery), so a different
 * browser, address or cleared site data no longer loses it. When the gallery
 * is gone everywhere, restoreFromComputer() rebuilds it from the avatar images
 * ComfyUI left on disk.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { authFetch } from '../lib/authFetch'
import { resolveBackendUrl } from '../lib/backendUrl'
import { getCurrentUserId } from '../lib/userScopedStorage'
import type { AvatarResult, AvatarMode } from './types'
import type { GalleryItem, GalleryItemRole, OutfitScenarioTag, WizardMeta, FramingType } from './galleryTypes'
import { GALLERY_STORAGE_KEY, GALLERY_MAX_ITEMS } from './galleryTypes'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Set when localStorage held a gallery we could not read. While set, the hook
 *  does not write an empty list over it, so the bytes stay recoverable. */
let storageUnreadable = false

function loadFromStorage(): GalleryItem[] {
  storageUnreadable = false
  try {
    const stored = localStorage.getItem(GALLERY_STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (!Array.isArray(parsed)) {
        storageUnreadable = true
        return []
      }
      return migrateOrphanOutfits(parsed)
    }
  } catch {
    storageUnreadable = true
  }
  return []
}

/** Union of two galleries by id, newest first, capped at GALLERY_MAX_ITEMS. */
export function mergeGalleries(a: GalleryItem[], b: GalleryItem[]): GalleryItem[] {
  const byId = new Map<string, GalleryItem>()
  for (const item of [...a, ...b]) {
    if (item && typeof item.id === 'string' && typeof item.url === 'string' && !byId.has(item.id)) {
      byId.set(item.id, item)
    }
  }
  return Array.from(byId.values())
    .sort((x, y) => (y.createdAt || 0) - (x.createdAt || 0))
    .slice(0, GALLERY_MAX_ITEMS)
}

function galleryEndpoint(path = ''): string {
  return `${resolveBackendUrl()}/v1/avatar-gallery${path}`
}

// ── Server sync, shared by every hook instance for the session ──────────────
// Avatar Studio and the Character Wizard both use this hook, and the page is
// created fresh on every visit. Without this, each visit downloaded the whole
// gallery (once per instance) and then uploaded it back unchanged. Now one
// download is shared, a recent one is reused, and only real changes are saved.
type ServerSync = {
  key: string
  fetchedAt: number
  /** JSON of the gallery as the server last had it (skip identical saves). */
  synced: string
  inflight: Promise<GalleryItem[] | null> | null
}
let serverSync: ServerSync | null = null
/** Last JSON written to localStorage (skip identical writes). */
let lastStoredJson: string | null = null
const SERVER_FRESH_MS = 30_000

function syncKey(): string {
  return `${resolveBackendUrl()}|${getCurrentUserId()}`
}

function syncFor(key: string): ServerSync {
  if (!serverSync || serverSync.key !== key) {
    serverSync = { key, fetchedAt: 0, synced: '', inflight: null }
  }
  return serverSync
}

/** The account's saved gallery; concurrent callers share one request. */
function fetchServerGallery(key: string): Promise<GalleryItem[] | null> {
  const sync = syncFor(key)
  if (sync.inflight) return sync.inflight
  sync.inflight = authFetch(galleryEndpoint())
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      const remote: GalleryItem[] | null = Array.isArray(data?.items) ? data.items : null
      sync.fetchedAt = Date.now()
      sync.synced = remote ? JSON.stringify(remote) : ''
      return remote
    })
    .catch(() => null)
    .finally(() => { sync.inflight = null })
  return sync.inflight
}

/** Forget the shared server state (tests, sign-out). */
export function resetAvatarGallerySync(): void {
  serverSync = null
  lastStoredJson = null
}

/**
 * Migration: re-parent orphaned outfit items.
 *
 * Before this fix, outfits generated from the Character Sheet were saved
 * without parentId, so they appeared as separate avatars on the landing page.
 * This migration finds items that have a referenceUrl but no parentId,
 * and links them to the root character whose url matches their referenceUrl.
 */
function migrateOrphanOutfits(items: GalleryItem[]): GalleryItem[] {
  // Build a map: url → id for root characters (items without parentId)
  const rootUrlToId = new Map<string, string>()
  for (const item of items) {
    if (!item.parentId && item.url) {
      rootUrlToId.set(item.url, item.id)
    }
  }

  let changed = false
  const migrated = items.map((item) => {
    // Skip items that already have a parentId or have no referenceUrl
    if (item.parentId || !item.referenceUrl) return item
    // If this item's referenceUrl matches a root character's url, re-parent it
    const rootId = rootUrlToId.get(item.referenceUrl)
    if (rootId && rootId !== item.id) {
      changed = true
      return { ...item, parentId: rootId }
    }
    return item
  })

  return changed ? migrated : items
}

function galleryId(): string {
  return `gal_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAvatarGallery() {
  const [items, setItems] = useState<GalleryItem[]>(loadFromStorage)
  const key = syncKey()
  // Already fetched this session: no loading screen on the next visit.
  const fetchedBefore = !!serverSync && serverSync.key === key && serverSync.fetchedAt > 0
  /** True once the account's saved gallery has been fetched (or found unavailable). */
  const [serverLoaded, setServerLoaded] = useState(fetchedBefore)
  const serverLoadedRef = useRef(fetchedBefore)
  const itemsRef = useRef(items)
  itemsRef.current = items

  // Merge the account's saved gallery with this browser's. A download from the
  // last SERVER_FRESH_MS is reused; otherwise refresh quietly in the background.
  useEffect(() => {
    let cancelled = false
    const sync = syncFor(key)
    const markLoaded = () => {
      if (cancelled) return
      serverLoadedRef.current = true
      setServerLoaded(true)
    }
    if (sync.fetchedAt && Date.now() - sync.fetchedAt < SERVER_FRESH_MS && !sync.inflight) {
      markLoaded()
      return () => { cancelled = true }
    }
    fetchServerGallery(key)
      .then((remote) => {
        if (cancelled || !remote || !remote.length) return
        setItems((local) => migrateOrphanOutfits(mergeGalleries(local, remote)))
      })
      .finally(markLoaded)
    return () => { cancelled = true }
  }, [key])

  // Auto-persist on change: localStorage at once, the account shortly after.
  useEffect(() => {
    const json = JSON.stringify(items)
    if (!(storageUnreadable && items.length === 0) && json !== lastStoredJson) {
      try {
        localStorage.setItem(GALLERY_STORAGE_KEY, json)
        lastStoredJson = json
        storageUnreadable = false
      } catch {
        // Storage full — the server copy below still saves it
      }
    }
    // Never push before the server copy was read, or an empty first render
    // would overwrite the account's gallery. Skip when nothing changed.
    if (!serverLoadedRef.current) return
    const sync = syncFor(key)
    if (json === sync.synced) return
    const timer = setTimeout(() => {
      authFetch(galleryEndpoint(), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      })
        .then((r) => { if (r.ok) sync.synced = json })
        .catch(() => { /* retried on the next change */ })
    }, 800)
    return () => clearTimeout(timer)
  }, [items, serverLoaded, key])

  /** Rebuild gallery entries from the avatar images on this computer
   *  (ComfyUI's output folder). Returns how many new avatars were added. */
  const restoreFromComputer = useCallback(async (limit = GALLERY_MAX_ITEMS): Promise<number> => {
    const r = await authFetch(galleryEndpoint(`/recover?limit=${limit}`))
    if (!r.ok) throw new Error(`Restore failed (${r.status})`)
    const data = await r.json()
    const found: GalleryItem[] = Array.isArray(data?.items) ? data.items : []
    const known = new Set(itemsRef.current.map((i) => i.url))
    const fresh = found.filter((i) => !known.has(i.url))
    if (fresh.length) setItems((prev) => mergeGalleries(prev, fresh))
    return fresh.length
  }, [])

  /** Add a single gallery item */
  const addItem = useCallback(
    (item: Omit<GalleryItem, 'id' | 'createdAt'>) => {
      setItems((prev) => {
        const newItem: GalleryItem = {
          ...item,
          id: galleryId(),
          createdAt: Date.now(),
        }
        const updated = [newItem, ...prev]
        // Enforce max items limit
        return updated.slice(0, GALLERY_MAX_ITEMS)
      })
    },
    [],
  )

  /** Add a batch of AvatarResults from a generation run */
  const addBatch = useCallback(
    (
      results: AvatarResult[],
      mode: AvatarMode,
      prompt?: string,
      referenceUrl?: string,
      scenarioTag?: OutfitScenarioTag,
      extra?: { vibeTag?: string; nsfw?: boolean; parentId?: string; role?: GalleryItemRole },
    ) => {
      setItems((prev) => {
        const batchId = `batch_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
        const newItems: GalleryItem[] = results.map((r) => ({
          id: galleryId(),
          url: r.url,
          seed: r.seed,
          prompt: (typeof r.metadata?.prompt === 'string' ? r.metadata.prompt : undefined) ?? prompt,
          mode,
          referenceUrl,
          createdAt: Date.now(),
          scenarioTag,
          vibeTag: extra?.vibeTag,
          nsfw: extra?.nsfw,
          parentId: extra?.parentId,
          batchId,
          role: extra?.role,
        }))
        const updated = [...newItems, ...prev]
        return updated.slice(0, GALLERY_MAX_ITEMS)
      })
    },
    [],
  )

  /** Add an anchor avatar + its alternative portraits in one atomic operation.
   *  Portraits get parentId pointing to the anchor so they're grouped together. */
  const addAnchorWithPortraits = useCallback(
    (
      anchor: AvatarResult,
      portraits: AvatarResult[],
      mode: AvatarMode,
      prompt?: string,
      referenceUrl?: string,
      extra?: { vibeTag?: string; nsfw?: boolean; wizardMeta?: WizardMeta; framingType?: FramingType },
    ) => {
      setItems((prev) => {
        const batchId = `batch_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
        const anchorId = galleryId()
        const anchorItem: GalleryItem = {
          id: anchorId,
          url: anchor.url,
          seed: anchor.seed,
          prompt,
          mode,
          referenceUrl,
          createdAt: Date.now(),
          vibeTag: extra?.vibeTag,
          nsfw: extra?.nsfw,
          batchId,
          role: 'anchor',
          wizardMeta: extra?.wizardMeta,
          framingType: extra?.framingType,
        }
        const portraitItems: GalleryItem[] = portraits.map((r) => ({
          id: galleryId(),
          url: r.url,
          seed: r.seed,
          prompt,
          mode,
          referenceUrl,
          createdAt: Date.now(),
          vibeTag: extra?.vibeTag,
          nsfw: extra?.nsfw,
          parentId: anchorId,
          batchId,
          role: 'portrait',
          framingType: extra?.framingType,
        }))
        const updated = [anchorItem, ...portraitItems, ...prev]
        return updated.slice(0, GALLERY_MAX_ITEMS)
      })
    },
    [],
  )

  /** Swap an anchor with one of its portraits.
   *  The portrait becomes the new anchor; the old anchor becomes a portrait. */
  const swapAnchor = useCallback((anchorId: string, portraitId: string) => {
    setItems((prev) => {
      const anchor = prev.find((i) => i.id === anchorId)
      const portrait = prev.find((i) => i.id === portraitId)
      if (!anchor || !portrait) return prev
      return prev.map((item) => {
        if (item.id === anchorId) {
          // Old anchor → becomes portrait, linked to the new anchor
          return { ...item, role: 'portrait' as GalleryItemRole, parentId: portraitId }
        }
        if (item.id === portraitId) {
          // Portrait → becomes anchor, no parentId
          return { ...item, role: 'anchor' as GalleryItemRole, parentId: undefined }
        }
        if (item.parentId === anchorId) {
          // Other portraits/outfits linked to old anchor → re-link to new anchor
          return { ...item, parentId: portraitId }
        }
        return item
      })
    })
  }, [])

  /** Remove a single item by ID */
  const removeItem = useCallback((id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id))
  }, [])

  /** Clear the entire gallery */
  const clearAll = useCallback(() => {
    setItems([])
  }, [])

  /** Tag an item (merge with existing tags) */
  const tagItem = useCallback((id: string, tags: string[]) => {
    setItems((prev) =>
      prev.map((i) =>
        i.id === id ? { ...i, tags: [...new Set([...(i.tags || []), ...tags])] } : i,
      ),
    )
  }, [])

  /** Mark a gallery item as linked to a persona project */
  const linkToPersona = useCallback((id: string, personaProjectId: string) => {
    setItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, personaProjectId } : i)),
    )
  }, [])

  /** Update arbitrary fields on a gallery item */
  const updateItem = useCallback((id: string, patch: Partial<GalleryItem>) => {
    setItems((prev) =>
      prev.map((i) => (i.id === id ? { ...i, ...patch } : i)),
    )
  }, [])

  return {
    items,
    serverLoaded,
    restoreFromComputer,
    addItem,
    addBatch,
    addAnchorWithPortraits,
    swapAnchor,
    removeItem,
    clearAll,
    tagItem,
    linkToPersona,
    updateItem,
  }
}
