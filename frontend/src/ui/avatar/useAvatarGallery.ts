/**
 * useAvatarGallery — hook for persistent avatar gallery (localStorage).
 *
 * Additive — no existing hooks or state are modified.
 */

import { useState, useEffect, useCallback } from 'react'
import type { AvatarResult, AvatarMode } from './types'
import type { GalleryItem, OutfitScenarioTag } from './galleryTypes'
import { GALLERY_STORAGE_KEY, GALLERY_MAX_ITEMS } from './galleryTypes'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadFromStorage(): GalleryItem[] {
  try {
    const stored = localStorage.getItem(GALLERY_STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      return Array.isArray(parsed) ? parsed : []
    }
  } catch {
    // Corrupt or missing — start fresh
  }
  return []
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
      extra?: { vibeTag?: string; nsfw?: boolean; parentId?: string },
    ) => {
      setItems((prev) => {
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
        }))
        const updated = [...newItems, ...prev]
        return updated.slice(0, GALLERY_MAX_ITEMS)
      })
    },
    [],
  )

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

  return {
    items,
    addItem,
    addBatch,
    removeItem,
    clearAll,
    tagItem,
    linkToPersona,
  }
}
