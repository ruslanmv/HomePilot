/**
 * React hook for fetching and refreshing the agentic catalog.
 *
 * Returns { catalog, loading, error, refresh } so the wizard
 * can render tools, servers, agents and trigger manual refreshes.
 */

import { useCallback, useEffect, useState } from 'react'
import type { AgenticCatalog } from './types'

type UseAgenticCatalogArgs = {
  backendUrl: string
  apiKey?: string
  enabled?: boolean
}

export function useAgenticCatalog({ backendUrl, apiKey, enabled = true }: UseAgenticCatalogArgs) {
  const [catalog, setCatalog] = useState<AgenticCatalog | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchCatalog = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError(null)
    try {
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey

      const res = await fetch(`${backendUrl}/v1/agentic/catalog`, { headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as AgenticCatalog
      setCatalog(data)
    } catch (e: any) {
      setCatalog(null)
      setError(e?.message || 'Failed to load catalog')
    } finally {
      setLoading(false)
    }
  }, [backendUrl, apiKey, enabled])

  useEffect(() => {
    void fetchCatalog()
  }, [fetchCatalog])

  return { catalog, loading, error, refresh: fetchCatalog }
}
