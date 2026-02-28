/**
 * useMatrixHub — hook for searching and browsing the MatrixHub MCP server catalog.
 *
 * MatrixHub (https://github.com/agent-matrix/matrix-hub) is an optional
 * secondary catalog source for MCP servers, agents, and tools.
 *
 * Public endpoints used (no auth required):
 *   GET /catalog/search?q=...&type=mcp_server&limit=...
 *   GET /catalog?type=mcp_server&limit=...&offset=...
 *
 * Phase 11 — fully additive, optional feature.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

export type MatrixHubItem = {
  id: string
  type: string
  name: string
  version: string
  summary: string
  capabilities: string[]
  frameworks: string[]
  providers: string[]
  score_final: number
  homepage?: string | null
  source_url?: string | null
  manifest_url?: string | null
  install_url?: string | null
  snippet?: string | null
}

export type MatrixHubSearchResult = {
  items: MatrixHubItem[]
  total: number
}

type Args = {
  /** MatrixHub API base URL (e.g. http://localhost:8080 or https://hub.agent-matrix.dev) */
  hubUrl: string
  enabled?: boolean
}

export function useMatrixHub({ hubUrl, enabled = true }: Args) {
  const [items, setItems] = useState<MatrixHubItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [healthy, setHealthy] = useState<boolean | null>(null)

  const baseUrl = hubUrl.replace(/\/+$/, '')

  // Health check
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(5000) })
        if (!cancelled) setHealthy(res.ok)
      } catch {
        if (!cancelled) setHealthy(false)
      }
    })()
    return () => { cancelled = true }
  }, [baseUrl, enabled])

  // Search / list
  const fetchCatalog = useCallback(async () => {
    if (!enabled || healthy === false) return
    setLoading(true)
    setError(null)
    try {
      let url: string
      if (search.trim()) {
        const q = encodeURIComponent(search.trim())
        url = `${baseUrl}/catalog/search?q=${q}&type=mcp_server&limit=50`
      } else {
        url = `${baseUrl}/catalog?type=mcp_server&limit=100&offset=0`
      }

      const res = await fetch(url, { signal: AbortSignal.timeout(10000) })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()

      // Search returns { items, total }, list returns { items/entities, total }
      const serverItems: MatrixHubItem[] = data.items || data.entities || []
      setItems(serverItems)
      setTotal(data.total ?? serverItems.length)
    } catch (e: any) {
      setError(e?.message || 'Failed to reach MatrixHub')
      setItems([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [baseUrl, enabled, search, healthy])

  useEffect(() => {
    void fetchCatalog()
  }, [fetchCatalog])

  // Derived
  const capabilities = useMemo(() => {
    const set = new Set<string>()
    items.forEach((i) => i.capabilities?.forEach((c) => set.add(c)))
    return Array.from(set).sort()
  }, [items])

  return {
    items,
    total,
    loading,
    error,
    healthy,
    search,
    setSearch,
    capabilities,
    refresh: fetchCatalog,
  }
}
