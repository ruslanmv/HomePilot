/**
 * useOutfitGeneration — hook for generating outfit variations via the
 * /v1/avatars/outfits endpoint.
 *
 * Additive — no existing hooks or API clients are modified.
 */

import { useState, useCallback } from 'react'
import type { AvatarResult } from './types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OutfitGenerateParams {
  referenceImageUrl: string
  outfitPrompt: string
  characterPrompt?: string
  negativePrompt?: string
  count?: number
  seed?: number
  generationMode?: 'identity' | 'standard'
  checkpointOverride?: string
}

export interface OutfitGenerateResult {
  results: AvatarResult[]
  warnings: string[]
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * A sentence the Character Sheet can show when outfit generation fails,
 * built from the backend's reply instead of a generic "Oops".
 */
export function describeOutfitError(status: number, bodyText: string): string {
  let detail = ''
  try {
    const parsed = JSON.parse(bodyText)
    detail = typeof parsed?.detail === 'string' ? parsed.detail : ''
  } catch {
    detail = (bodyText || '').trim().slice(0, 200)
  }
  if (status === 503) {
    if (/disabled/i.test(detail)) {
      return 'Avatar generation is turned off on this HomePilot (AVATAR_ENABLED=false).'
    }
    // The backend says which case it is: not running, running but not
    // responding, or models missing. Show that rather than guessing.
    if (detail) return detail
    return "Image generation isn't available right now: ComfyUI isn't reachable. "
      + 'Start it with `make start-comfyui` (or `make start`), then try again.'
  }
  if (status === 0) return 'Could not reach the HomePilot backend.'
  return detail ? `Outfit generation failed: ${detail}` : `Outfit generation failed (HTTP ${status}).`
}

export function useOutfitGeneration(backendUrl: string, apiKey?: string) {
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<AvatarResult[]>([])
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const generate = useCallback(
    async (params: OutfitGenerateParams) => {
      setLoading(true)
      setError(null)
      setWarnings([])

      const base = (backendUrl || '').replace(/\/+$/, '')
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }
      if (apiKey) headers['x-api-key'] = apiKey

      try {
        const res = await fetch(`${base}/v1/avatars/outfits`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            reference_image_url: params.referenceImageUrl,
            outfit_prompt: params.outfitPrompt,
            character_prompt: params.characterPrompt,
            negative_prompt: params.negativePrompt,
            count: params.count ?? 4,
            seed: params.seed,
            generation_mode: params.generationMode ?? 'identity',
            checkpoint_override: params.checkpointOverride,
          }),
        })

        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(describeOutfitError(res.status, text))
        }

        const data: OutfitGenerateResult = await res.json()
        setResults(data.results)
        setWarnings(data.warnings || [])
        return data
      } catch (e) {
        const msg = e instanceof TypeError
          ? describeOutfitError(0, '')
          : e instanceof Error ? e.message : 'Outfit generation failed'
        setError(msg)
        throw e
      } finally {
        setLoading(false)
      }
    },
    [backendUrl, apiKey],
  )

  const reset = useCallback(() => {
    setResults([])
    setWarnings([])
    setError(null)
  }, [])

  return { loading, results, warnings, error, generate, reset }
}
