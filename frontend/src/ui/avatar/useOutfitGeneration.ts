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
  count?: number
  seed?: number
  generationMode?: 'identity' | 'standard'
}

export interface OutfitGenerateResult {
  results: AvatarResult[]
  warnings: string[]
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

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
            count: params.count ?? 4,
            seed: params.seed,
            generation_mode: params.generationMode ?? 'identity',
          }),
        })

        if (!res.ok) {
          const text = await res.text().catch(() => '')
          throw new Error(`Outfit generation failed: ${res.status} ${text}`)
        }

        const data: OutfitGenerateResult = await res.json()
        setResults(data.results)
        setWarnings(data.warnings || [])
        return data
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Outfit generation failed'
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
