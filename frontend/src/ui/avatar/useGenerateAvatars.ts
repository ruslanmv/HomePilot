/**
 * Hook: manage avatar generation state (loading, results, errors).
 */

import { useState, useCallback } from 'react'
import { generateAvatars } from './avatarApi'
import type { AvatarGenerateRequest, AvatarGenerateResponse } from './types'

export function useGenerateAvatars(backendUrl: string, apiKey?: string) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AvatarGenerateResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(
    async (req: AvatarGenerateRequest) => {
      setLoading(true)
      setError(null)
      try {
        const r = await generateAvatars(backendUrl, req, apiKey)
        setResult(r)
        return r
      } catch (e: any) {
        setError(e?.message || String(e))
        throw e
      } finally {
        setLoading(false)
      }
    },
    [backendUrl, apiKey],
  )

  const reset = useCallback(() => {
    setResult(null)
    setError(null)
  }, [])

  return { loading, result, error, run, reset }
}
