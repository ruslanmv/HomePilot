import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AvatarResult } from './types'
import type { ViewAngle, ViewResultMap, ViewTimestampMap } from './viewPack'
import { getViewAngleOption, VIEW_ANGLE_OPTIONS } from './viewPack'

export interface GenerateViewParams {
  referenceImageUrl: string
  angle: ViewAngle
  characterPrompt?: string
  basePrompt?: string
  checkpointOverride?: string
  seed?: number
}

interface OutfitGenerateResult {
  results: AvatarResult[]
  warnings: string[]
}

// ---------------------------------------------------------------------------
// localStorage cache helpers
// ---------------------------------------------------------------------------
const CACHE_PREFIX = 'hp_viewpack_'

interface CachedViewPack {
  results: ViewResultMap
  timestamps: ViewTimestampMap
}

function cacheKeyFor(key: string): string {
  return `${CACHE_PREFIX}${key}`
}

function loadCached(key: string | undefined): CachedViewPack {
  if (!key) return { results: {}, timestamps: {} }
  try {
    const raw = localStorage.getItem(cacheKeyFor(key))
    if (raw) {
      const parsed = JSON.parse(raw)
      // Support old format (plain ViewResultMap) and new format (CachedViewPack)
      if (parsed && typeof parsed === 'object' && 'results' in parsed) {
        return parsed as CachedViewPack
      }
      // Legacy: plain ViewResultMap without timestamps
      return { results: parsed as ViewResultMap, timestamps: {} }
    }
  } catch { /* corrupt entry — ignore */ }
  return { results: {}, timestamps: {} }
}

function saveCached(key: string | undefined, results: ViewResultMap, timestamps: ViewTimestampMap): void {
  if (!key) return
  try {
    const hasEntries = Object.keys(results).length > 0
    if (hasEntries) {
      const data: CachedViewPack = { results, timestamps }
      localStorage.setItem(cacheKeyFor(key), JSON.stringify(data))
    } else {
      localStorage.removeItem(cacheKeyFor(key))
    }
  } catch { /* storage full — silently fail */ }
}

function removeCached(key: string | undefined): void {
  if (!key) return
  try { localStorage.removeItem(cacheKeyFor(key)) } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * @param backendUrl  Backend base URL
 * @param apiKey      Optional API key
 * @param cacheKey    Unique key for localStorage persistence (e.g. characterId
 *                    or characterId+outfitId). When this changes the hook
 *                    loads the cached results for the new key.
 */
export function useViewPackGeneration(backendUrl: string, apiKey?: string, cacheKey?: string) {
  const [resultsByAngle, setResultsByAngle] = useState<ViewResultMap>(() => loadCached(cacheKey).results)
  const [timestampsByAngle, setTimestampsByAngle] = useState<ViewTimestampMap>(() => loadCached(cacheKey).timestamps)
  const [loadingAngles, setLoadingAngles] = useState<Partial<Record<ViewAngle, boolean>>>({})
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  // Track previous cacheKey so we can save before switching
  const prevKeyRef = useRef(cacheKey)
  const timestampsRef = useRef(timestampsByAngle)
  timestampsRef.current = timestampsByAngle

  // When cacheKey changes, persist current results under old key and load new
  useEffect(() => {
    if (prevKeyRef.current === cacheKey) return

    // Save current in-memory results under the *previous* key
    setResultsByAngle((current) => {
      saveCached(prevKeyRef.current, current, timestampsRef.current)
      prevKeyRef.current = cacheKey
      const loaded = loadCached(cacheKey)
      setTimestampsByAngle(loaded.timestamps)
      return loaded.results
    })

    setLoadingAngles({})
    setWarnings([])
    setError(null)
  }, [cacheKey])

  // Auto-persist whenever results change
  useEffect(() => {
    saveCached(cacheKey, resultsByAngle, timestampsByAngle)
  }, [cacheKey, resultsByAngle, timestampsByAngle])

  const anyLoading = useMemo(() => Object.values(loadingAngles).some(Boolean), [loadingAngles])

  const generateAngle = useCallback(async (params: GenerateViewParams) => {
    const base = (backendUrl || '').replace(/\/+$/, '')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiKey) headers['x-api-key'] = apiKey

    const angleMeta = getViewAngleOption(params.angle)
    const outfitDesc = params.basePrompt?.trim() || 'portrait photograph'

    // ── Prompt architecture ─────────────────────────────────────────────
    // The backend concatenates:  outfit_prompt + character_prompt(stripped) + quality suffix
    //
    // CLIP gives highest attention weight to the FIRST tokens in the prompt.
    // For angle generation, the pose directive must lead — otherwise outfit
    // tokens drown out the rotation instruction and the model defaults to
    // a front-facing composition.
    //
    // We put everything into outfit_prompt (angle first, then outfit desc)
    // and OMIT character_prompt entirely.  Reasons:
    //   1. Angle directive leads → maximum CLIP attention on pose
    //   2. Outfit desc follows → still gets strong weight, never stripped
    //   3. No character_prompt → no risk of outfit tokens being doubled
    //      (the backend's _strip_outfit_tokens would remove clothing words
    //       like "lingerie", "dress", etc. if they appeared there)
    //   4. Identity is preserved via the reference image + InstantID ControlNet,
    //      not via text tokens — so we don't need text-based identity cues
    // ────────────────────────────────────────────────────────────────────

    // outfit_prompt: angle directive FIRST (for CLIP priority), then outfit description.
    // The backend places this first and never strips it.
    const outfitPrompt = [
      angleMeta.prompt,
      outfitDesc,
      'full body visible head to knees',
    ].join(', ')

    // Negative prompt: only angle-specific negatives.
    // The backend already prepends its own baseline negatives (lowres, blurry, bad anatomy, etc.)
    // so we do NOT duplicate them here.
    const negativePrompt = angleMeta.negativePrompt || ''

    setLoadingAngles((current) => ({ ...current, [params.angle]: true }))
    setError(null)

    try {
      const res = await fetch(`${base}/v1/avatars/outfits`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          reference_image_url: params.referenceImageUrl,
          outfit_prompt: outfitPrompt,
          negative_prompt: negativePrompt || undefined,
          count: 1,
          generation_mode: angleMeta.skipIdentity ? 'standard' : 'identity',
          checkpoint_override: params.checkpointOverride,
          seed: params.seed,
          // Non-front angles use denoise 1.0 so the text prompt fully controls
          // the pose/angle instead of the reference image's spatial layout.
          denoise_override: angleMeta.denoise,
        }),
      })

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`View generation failed: ${res.status} ${text}`)
      }

      const data: OutfitGenerateResult = await res.json()
      const first = data.results?.[0]
      if (!first) throw new Error('View generation returned no images')

      const tagged: AvatarResult = {
        ...first,
        metadata: {
          ...(first.metadata || {}),
          view_angle: params.angle,
        },
      }

      setResultsByAngle((current) => ({ ...current, [params.angle]: tagged }))
      setTimestampsByAngle((current) => ({ ...current, [params.angle]: Date.now() }))
      if (data.warnings?.length) {
        setWarnings((current) => [...current, ...data.warnings])
      }
      return tagged
    } catch (err) {
      const message = err instanceof Error ? err.message : 'View generation failed'
      setError(message)
      throw err
    } finally {
      setLoadingAngles((current) => ({ ...current, [params.angle]: false }))
    }
  }, [backendUrl, apiKey])

  /** Delete a single angle result (in-memory + cache). */
  const deleteAngle = useCallback((angle: ViewAngle) => {
    setResultsByAngle((current) => {
      const next = { ...current }
      delete next[angle]
      return next
    })
    setTimestampsByAngle((current) => {
      const next = { ...current }
      delete next[angle]
      return next
    })
  }, [])

  /** Clear all results for the current key (in-memory + cache). */
  const reset = useCallback(() => {
    setResultsByAngle({})
    setTimestampsByAngle({})
    setLoadingAngles({})
    setWarnings([])
    setError(null)
    removeCached(cacheKey)
  }, [cacheKey])

  const missingAngles = useCallback((existing?: ViewResultMap) => {
    const source = existing || resultsByAngle
    return VIEW_ANGLE_OPTIONS.filter((item) => !source[item.id]).map((item) => item.id)
  }, [resultsByAngle])

  return {
    resultsByAngle,
    timestampsByAngle,
    loadingAngles,
    anyLoading,
    warnings,
    error,
    generateAngle,
    deleteAngle,
    reset,
    missingAngles,
  }
}
