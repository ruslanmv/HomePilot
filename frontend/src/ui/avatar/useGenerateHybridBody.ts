/**
 * Hook: manage hybrid full-body generation state.
 *
 * Calls the hybrid pipeline endpoint POST /v1/avatars/hybrid/fullbody
 * which takes a face reference and generates full-body images via ComfyUI
 * with identity preservation (InstantID/PhotoMaker).
 */

import { useState, useCallback, useRef } from 'react'
import { generateHybridFullBody } from './avatarApi'
import type { HybridFullBodyRequest, HybridFullBodyResponse } from './types'

const GENERATE_TIMEOUT_MS = 5 * 60 * 1000

export function useGenerateHybridBody(backendUrl: string, apiKey?: string) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<HybridFullBodyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const run = useCallback(
    async (req: HybridFullBodyRequest) => {
      abortRef.current?.abort()

      const controller = new AbortController()
      abortRef.current = controller

      const timer = setTimeout(() => controller.abort(), GENERATE_TIMEOUT_MS)

      setLoading(true)
      setError(null)
      try {
        const r = await generateHybridFullBody(backendUrl, req, apiKey, controller.signal)
        setResult(r)
        return r
      } catch (e: any) {
        if (e?.name === 'AbortError') {
          const msg = 'Body generation timed out. Try reducing the count.'
          setError(msg)
          throw new Error(msg)
        }
        setError(e?.message || String(e))
        throw e
      } finally {
        clearTimeout(timer)
        setLoading(false)
        if (abortRef.current === controller) {
          abortRef.current = null
        }
      }
    },
    [backendUrl, apiKey],
  )

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setLoading(false)
  }, [])

  const reset = useCallback(() => {
    setResult(null)
    setError(null)
  }, [])

  const removeResult = useCallback((index: number) => {
    setResult((prev) => {
      if (!prev?.results) return prev
      const next = prev.results.filter((_, i) => i !== index)
      if (next.length === 0) return null
      return { ...prev, results: next }
    })
  }, [])

  return { loading, result, error, run, reset, cancel, removeResult }
}
