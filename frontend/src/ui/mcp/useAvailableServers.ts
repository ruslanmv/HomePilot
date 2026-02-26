/**
 * Hook for fetching MCP server availability and managing install/uninstall.
 *
 * Calls GET /v1/agentic/servers/available for the full server list,
 * POST /v1/agentic/servers/{id}/install and /uninstall for lifecycle.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

export type McpServerEntry = {
  id: string
  port: number
  module: string
  label: string
  description: string
  category: string
  icon: string
  requires_config: string | null
  is_core: boolean
  installed: boolean
  healthy: boolean
  status: 'running' | 'installed' | 'available'
}

type Args = {
  backendUrl: string
  apiKey?: string
}

export function useAvailableServers({ backendUrl, apiKey }: Args) {
  const [servers, setServers] = useState<McpServerEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})

  const headers = useMemo(() => {
    const h: Record<string, string> = {}
    if (apiKey) h['x-api-key'] = apiKey
    return h
  }, [apiKey])

  const fetchServers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${backendUrl}/v1/agentic/servers/available`, { headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as McpServerEntry[]
      setServers(data)
    } catch (e: any) {
      setServers([])
      setError(e?.message || 'Failed to load servers')
    } finally {
      setLoading(false)
    }
  }, [backendUrl, headers])

  useEffect(() => {
    void fetchServers()
  }, [fetchServers])

  const install = useCallback(async (serverId: string): Promise<{ ok: boolean; error?: string; tools_discovered?: number }> => {
    setActionLoading((p) => ({ ...p, [serverId]: true }))
    try {
      const res = await fetch(`${backendUrl}/v1/agentic/servers/${serverId}/install`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
      })
      const data = await res.json()
      if (!res.ok) return { ok: false, error: data?.detail || `HTTP ${res.status}` }
      // Refresh the server list after install
      await fetchServers()
      return { ok: true, tools_discovered: data?.tools_discovered ?? 0 }
    } catch (e: any) {
      return { ok: false, error: e?.message || 'Install failed' }
    } finally {
      setActionLoading((p) => ({ ...p, [serverId]: false }))
    }
  }, [backendUrl, headers, fetchServers])

  const uninstall = useCallback(async (serverId: string): Promise<{ ok: boolean; error?: string }> => {
    setActionLoading((p) => ({ ...p, [serverId]: true }))
    try {
      const res = await fetch(`${backendUrl}/v1/agentic/servers/${serverId}/uninstall`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
      })
      const data = await res.json()
      if (!res.ok) return { ok: false, error: data?.detail || `HTTP ${res.status}` }
      await fetchServers()
      return { ok: true }
    } catch (e: any) {
      return { ok: false, error: e?.message || 'Uninstall failed' }
    } finally {
      setActionLoading((p) => ({ ...p, [serverId]: false }))
    }
  }, [backendUrl, headers, fetchServers])

  const counts = useMemo(() => {
    const core = servers.filter((s) => s.is_core)
    const optional = servers.filter((s) => !s.is_core)
    const running = servers.filter((s) => s.healthy)
    const installed = optional.filter((s) => s.installed)
    return {
      total: servers.length,
      core: core.length,
      optional: optional.length,
      running: running.length,
      installed: installed.length,
    }
  }, [servers])

  return {
    servers,
    counts,
    loading,
    error,
    refresh: fetchServers,
    install,
    uninstall,
    actionLoading,
  }
}
