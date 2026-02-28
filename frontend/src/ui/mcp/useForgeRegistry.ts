/**
 * Hook for browsing the Forge MCP Registry (public catalog of 81+ servers).
 *
 * Calls GET /v1/agentic/registry/servers with optional filters,
 * POST /v1/agentic/registry/{id}/register to install a server,
 * and POST /v1/agentic/registry/{id}/unregister to remove one.
 *
 * Phase 9+10 — additive, does not modify any existing hook.
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
  const [statusFilter, setStatusFilter] = useState<'' | 'available' | 'installed' | 'needs_setup'>('')

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

  // Optimistically update local state for a server's registration status.
  // This avoids stale data from Forge-side caching after install/uninstall.
  const patchServerLocally = useCallback((serverId: string, registered: boolean) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        servers: prev.servers.map((s) =>
          s.id === serverId
            ? { ...s, is_registered: registered, requires_oauth_config: false }
            : s,
        ),
      }
    })
  }, [])

  // Install a server from the registry (optionally with API key)
  const install = useCallback(
    async (serverId: string, serverApiKey?: string): Promise<{ ok: boolean; message: string }> => {
      try {
        const body: Record<string, string> = {}
        if (serverApiKey) body.api_key = serverApiKey

        const res = await fetch(
          `${backendUrl}/v1/agentic/registry/${encodeURIComponent(serverId)}/register`,
          {
            method: 'POST',
            headers: { ...headers(), 'Content-Type': 'application/json' },
            body: Object.keys(body).length > 0 ? JSON.stringify(body) : undefined,
          },
        )
        const json = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, message: json.detail || json.message || `HTTP ${res.status}` }
        }
        // Optimistically mark as registered, then refresh in background
        patchServerLocally(serverId, true)
        setTimeout(() => void fetchRegistry(), 3000)
        return { ok: true, message: json.message || 'Server registered' }
      } catch (e: any) {
        return { ok: false, message: e?.message || 'Install failed' }
      }
    },
    [backendUrl, headers, fetchRegistry, patchServerLocally],
  )

  // Unregister (uninstall) a server
  const uninstall = useCallback(
    async (serverId: string): Promise<{ ok: boolean; message: string }> => {
      try {
        const res = await fetch(
          `${backendUrl}/v1/agentic/registry/${encodeURIComponent(serverId)}/unregister`,
          {
            method: 'POST',
            headers: { ...headers(), 'Content-Type': 'application/json' },
          },
        )
        const json = await res.json().catch(() => ({}))
        if (!res.ok) {
          return { ok: false, message: json.detail || json.message || `HTTP ${res.status}` }
        }
        // Optimistically mark as unregistered, then refresh in background
        patchServerLocally(serverId, false)
        setTimeout(() => void fetchRegistry(), 3000)
        return { ok: true, message: json.message || 'Server unregistered' }
      } catch (e: any) {
        return { ok: false, message: e?.message || 'Uninstall failed' }
      }
    },
    [backendUrl, headers, fetchRegistry, patchServerLocally],
  )

  const allServers: RegistryServer[] = useMemo(() => data?.servers || [], [data])

  // Apply client-side status filter
  const servers: RegistryServer[] = useMemo(() => {
    if (!statusFilter) return allServers
    switch (statusFilter) {
      case 'available':
        return allServers.filter((s) => !s.is_registered)
      case 'installed':
        return allServers.filter((s) => s.is_registered)
      case 'needs_setup':
        return allServers.filter((s) => s.is_registered && s.requires_oauth_config)
      default:
        return allServers
    }
  }, [allServers, statusFilter])

  // Derived counts
  const needsSetupCount = useMemo(
    () => allServers.filter((s) => s.is_registered && s.requires_oauth_config).length,
    [allServers],
  )

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
    uninstall,
    needsSetupCount,
    // Filter state
    search,
    setSearch,
    category,
    setCategory,
    authType,
    setAuthType,
    provider,
    setProvider,
    statusFilter,
    setStatusFilter,
  }
}
