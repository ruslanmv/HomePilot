/**
 * Hook: loads avatar pack availability from the backend.
 */

import { useEffect, useState, useCallback } from 'react'
import { fetchAvatarPacks } from './avatarApi'
import type { AvatarPacksResponse } from './types'

export function useAvatarPacks(backendUrl: string, apiKey?: string) {
  const [data, setData] = useState<AvatarPacksResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    if (!backendUrl) return
    setLoading(true)
    setError(null)
    try {
      const result = await fetchAvatarPacks(backendUrl, apiKey)
      setData(result)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [backendUrl, apiKey])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { data, error, loading, refresh }
}
