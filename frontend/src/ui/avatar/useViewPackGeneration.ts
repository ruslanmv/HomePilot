import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AvatarResult } from './types'
import type { FramingType } from './galleryTypes'
import type { ViewAngle, ViewResultMap, ViewTimestampMap } from './viewPack'
import type { AvatarSettings } from './types'
import { buildAnglePrompt, buildIdentityLockSuffix, getViewAngleOption, resolveAngleTuning, sanitiseBasePromptForAngle, VIEW_ANGLE_OPTIONS } from './viewPack'

export interface GenerateViewParams {
  referenceImageUrl: string
  angle: ViewAngle
  characterPrompt?: string
  basePrompt?: string
  checkpointOverride?: string
  seed?: number
  /** Framing type from the front view — angles will match this composition. */
  framingType?: FramingType
  /** Avatar settings — used to read per-angle tuning overrides (denoise, promptWeight). */
  avatarSettings?: AvatarSettings
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
// Backend helpers — commit & delete durable view-pack images
// ---------------------------------------------------------------------------

/** Commit a /comfy/view/ image to durable /files/ storage, optionally deleting the old one. */
async function commitViewImage(
  base: string,
  headers: Record<string, string>,
  comfyUrl: string,
  oldUrl?: string,
): Promise<string> {
  try {
    const res = await fetch(`${base}/v1/viewpack/commit`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ comfy_url: comfyUrl, old_url: oldUrl }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.ok && data.url) return data.url
    }
  } catch { /* commit failed — fall back to ephemeral URL */ }
  return comfyUrl
}

/** Ask backend to delete one or more durable view-pack images. Fire-and-forget. */
function deleteViewImages(
  base: string,
  headers: Record<string, string>,
  urls: string[],
): void {
  // Only send /files/ URLs — /comfy/view/ URLs are ephemeral and managed by ComfyUI
  const durable = urls.filter((u) => u.startsWith('/files/'))
  if (durable.length === 0) return
  fetch(`${base}/v1/viewpack/delete`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ urls: durable }),
  }).catch(() => { /* best-effort cleanup */ })
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

  // Stable reference to current results for use inside callbacks
  const resultsRef = useRef(resultsByAngle)
  resultsRef.current = resultsByAngle

  // Track previous cacheKey so we can save before switching.
  // Uses React's "adjusting state from props" pattern: when cacheKey changes
  // we synchronously swap the cached data during render so there is never a
  // stale-data frame where angle thumbnails from the OLD source are shown
  // alongside the NEW source's front image.
  const [prevKey, setPrevKey] = useState(cacheKey)
  const timestampsRef = useRef(timestampsByAngle)
  timestampsRef.current = timestampsByAngle

  if (prevKey !== cacheKey) {
    // Save current in-memory results under the *previous* key
    saveCached(prevKey, resultsByAngle, timestampsRef.current)

    // Load the new key's cached data synchronously
    const loaded = loadCached(cacheKey)
    setPrevKey(cacheKey)
    setResultsByAngle(loaded.results)
    setTimestampsByAngle(loaded.timestamps)
    setLoadingAngles({})
    setWarnings([])
    setError(null)
  }

  // Auto-persist whenever results change
  useEffect(() => {
    saveCached(cacheKey, resultsByAngle, timestampsByAngle)
  }, [cacheKey, resultsByAngle, timestampsByAngle])

  const anyLoading = useMemo(() => Object.values(loadingAngles).some(Boolean), [loadingAngles])

  /** Build common fetch headers. */
  const makeHeaders = useCallback((): Record<string, string> => {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiKey) h['x-api-key'] = apiKey
    return h
  }, [apiKey])

  const generateAngle = useCallback(async (params: GenerateViewParams) => {
    const base = (backendUrl || '').replace(/\/+$/, '')
    const headers = makeHeaders()

    const angleMeta = getViewAngleOption(params.angle)
    const rawBase = params.basePrompt?.trim() || 'portrait photograph'

    // Strip pose / camera / framing tokens that would contradict the angle
    // directive.  For 'front' this is a no-op (returns rawBase unchanged).
    // Keeps only outfit, appearance, and quality tokens so the clothing is
    // faithfully reproduced at every angle without front-bias contamination.
    const basePrompt = sanitiseBasePromptForAngle(rawBase, params.angle)

    // Build the positive prompt: angle-specific direction FIRST (highest weight),
    // then outfit description, then consistency suffix.
    // Angle directive is placed first so CLIP gives it the most attention weight.
    // The outfit description comes second — it's NOT duplicated via character_prompt
    // (we send character_prompt=undefined) to avoid tripling outfit tokens which
    // drowns out the angle instruction.
    //
    // The angle prompt and identity-lock suffix adapt to the front view's
    // framing type (half_body / mid_body / headshot) so the body range
    // matches across all angles — e.g. "head to waist" instead of
    // hardcoded "head to thighs".
    // Resolve per-angle tuning (denoise, promptWeight) from user settings or defaults
    const tunableAngle = params.angle !== 'front' ? params.angle as 'left' | 'right' | 'back' : null
    const angleTuning = tunableAngle ? resolveAngleTuning(tunableAngle, params.avatarSettings) : null

    const viewPrompt = [
      buildAnglePrompt(params.angle, params.framingType, params.avatarSettings),
      basePrompt,
      buildIdentityLockSuffix(params.framingType),
    ].filter(Boolean).join(', ')

    // Build the negative prompt: prevent front-facing bias from the reference latent
    const negParts = [
      'lowres, blurry, bad anatomy, deformed, extra fingers, missing fingers, bad hands, disfigured face, watermark, text, multiple people, duplicate',
    ]
    if (angleMeta.negativePrompt) {
      negParts.push(angleMeta.negativePrompt)
    }
    const negativePrompt = negParts.join(', ')

    setLoadingAngles((current) => ({ ...current, [params.angle]: true }))
    setError(null)

    try {
      const res = await fetch(`${base}/v1/avatars/outfits`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          reference_image_url: params.referenceImageUrl,
          outfit_prompt: viewPrompt,
          // character_prompt intentionally omitted for view pack generation.
          // The outfit description is already in viewPrompt (via basePrompt).
          // Sending it again as character_prompt causes the backend to include
          // it a second time after _strip_outfit_tokens, tripling outfit token
          // weight and drowning out the angle directive.
          // Identity is preserved via the reference image + InstantID, not text.
          negative_prompt: negativePrompt,
          count: 1,
          generation_mode: angleMeta.generationMode || 'identity',
          checkpoint_override: params.checkpointOverride,
          seed: params.seed,
          // Denoise: user-tuned value (from settings) or built-in default.
          denoise_override: angleTuning?.denoise ?? angleMeta.denoise,
        }),
      })

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`View generation failed: ${res.status} ${text}`)
      }

      const data: OutfitGenerateResult = await res.json()
      const first = data.results?.[0]
      if (!first) throw new Error('View generation returned no images')

      // Commit to durable storage, deleting old image if regenerating
      const oldUrl = resultsRef.current[params.angle]?.url
      const durableUrl = await commitViewImage(base, headers, first.url, oldUrl)

      const tagged: AvatarResult = {
        ...first,
        url: durableUrl,
        metadata: {
          ...(first.metadata || {}),
          view_angle: params.angle,
          view_prompt: viewPrompt,
          view_negative: negativePrompt,
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
  }, [backendUrl, apiKey, makeHeaders])

  /** Delete a single angle result (in-memory + cache + backend file). */
  const deleteAngle = useCallback((angle: ViewAngle) => {
    // Delete the durable file on the backend
    const existing = resultsRef.current[angle]
    if (existing?.url) {
      const base = (backendUrl || '').replace(/\/+$/, '')
      deleteViewImages(base, makeHeaders(), [existing.url])
    }

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
  }, [backendUrl, makeHeaders])

  /** Clear all results for the current key (in-memory + cache + backend files). */
  const reset = useCallback(() => {
    // Collect all durable URLs and delete them on the backend
    const allUrls = Object.values(resultsRef.current)
      .map((r) => r?.url)
      .filter((u): u is string => Boolean(u))
    if (allUrls.length > 0) {
      const base = (backendUrl || '').replace(/\/+$/, '')
      deleteViewImages(base, makeHeaders(), allUrls)
    }

    setResultsByAngle({})
    setTimestampsByAngle({})
    setLoadingAngles({})
    setWarnings([])
    setError(null)
    removeCached(cacheKey)
  }, [cacheKey, backendUrl, makeHeaders])

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
