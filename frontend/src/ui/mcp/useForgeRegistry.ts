/**
 * Hook for browsing the Forge MCP Registry (public catalog of 81+ servers).
 *
 * Calls GET /v1/agentic/registry/servers with optional filters,
 * and POST /v1/agentic/registry/{id}/register to install a server.
 *
 * Phase 9 — additive, does not modify any existing hook.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { RegistryListResponse, RegistryServer } from '../../agentic/types'

type Args = {
  backendUrl: string
  apiKey?: string
  enabled?: boolean
}

export function useForgeRegistry({ backendUrl, apiKey, enabled = true }: Args) {
  const [data, setData] = useState<RegistryListResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [authType, setAuthType] = useState('')
  const [provider, setProvider] = useState('')

  const headers = useCallback((): Record<string, string> => {
    const h: Record<string, string> = {}
    if (apiKey) h['x-api-key'] = apiKey
    return h
  }, [apiKey])

  const fetchRegistry = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (search) params.set('search', search)
      if (category) params.set('category', category)
      if (authType) params.set('auth_type', authType)
      if (provider) params.set('provider', provider)
      params.set('limit', '200')

      const res = await fetch(
        `${backendUrl}/v1/agentic/registry/servers?${params.toString()}`,
        { headers: headers() },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = (await res.json()) as RegistryListResponse
      setData(json)
    } catch (e: any) {
      setError(e?.message || 'Failed to load registry')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [backendUrl, apiKey, enabled, search, category, authType, provider, headers])

  useEffect(() => {
    void fetchRegistry()
  }, [fetchRegistry])

  // Install a server from the registry
  const install = useCallback(
    async (serverId: string): Promise<{ ok: boolean; message: string }> => {
      try {
        const res = await fetch(
          `${backendUrl}/v1/agentic/registry/${encodeURIComponent(serverId)}/register`,
          {
            method: 'POST',
            headers: { ...headers(), 'Content-Type': 'application/json' },
          },
        )
        const json = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, message: json.detail || json.message || `HTTP ${res.status}` }
        }
        // Refresh the list to update is_registered flags
        void fetchRegistry()
        return { ok: true, message: json.message || 'Server registered' }
      } catch (e: any) {
        return { ok: false, message: e?.message || 'Install failed' }
      }
    },
    [backendUrl, headers, fetchRegistry],
  )

  const servers: RegistryServer[] = useMemo(() => data?.servers || [], [data])

  return {
    servers,
    total: data?.total ?? 0,
    categories: data?.categories ?? [],
    authTypes: data?.auth_types ?? [],
    providers: data?.providers ?? [],
    allTags: data?.all_tags ?? [],
    loading,
    error,
    refresh: fetchRegistry,
    install,
    // Filter state
    search,
    setSearch,
    category,
    setCategory,
    authType,
    setAuthType,
    provider,
    setProvider,
  }
}
