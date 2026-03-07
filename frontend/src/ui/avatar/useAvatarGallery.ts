/**
 * useAvatarGallery — hook for persistent avatar gallery (localStorage).
 *
 * Additive — no existing hooks or state are modified.
 */

import { useState, useEffect, useCallback } from 'react'
import type { AvatarResult, AvatarMode } from './types'
import type { GalleryItem, GalleryItemRole, OutfitScenarioTag, WizardMeta, FramingType } from './galleryTypes'
import { GALLERY_STORAGE_KEY, GALLERY_MAX_ITEMS } from './galleryTypes'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadFromStorage(): GalleryItem[] {
  try {
    const stored = localStorage.getItem(GALLERY_STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (!Array.isArray(parsed)) return []
      return migrateOrphanOutfits(parsed)
    }
  } catch {
    // Corrupt or missing — start fresh
  }
  return []
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

  // Auto-persist on change
  useEffect(() => {
    try {
      localStorage.setItem(GALLERY_STORAGE_KEY, JSON.stringify(items))
    } catch {
      // Storage full — silently fail
    }
  }, [items])

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
          prompt,
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
