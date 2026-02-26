/**
 * Hook that wraps useAgenticCatalog to provide MCP gateway/server views.
 *
 * Reuses the existing catalog fetch — no duplicate HTTP calls.
 * Also exposes catalogTools so drawers can resolve tool IDs to names.
 */

import { useMemo, useState } from 'react'
import { useAgenticCatalog } from '../../agentic/useAgenticCatalog'
import type { CatalogGateway, CatalogServer, CatalogTool } from '../../agentic/types'

type Args = {
  backendUrl: string
  apiKey?: string
}

export type InstalledServer = {
  kind: 'gateway' | 'server'
  id: string
  name: string
  description: string
  enabled: boolean | null
  url: string | null
  transport: string | null
  toolCount: number
  toolIds: string[]
}

function gatewayToInstalled(g: CatalogGateway, toolMap: Map<string, string[]>): InstalledServer {
  const matchedTools = toolMap.get(g.id) || []
  return {
    kind: 'gateway',
    id: g.id,
    name: g.name,
    description: `${g.transport || 'SSE'} gateway`,
    enabled: g.enabled ?? null,
    url: g.url || null,
    transport: g.transport || 'SSE',
    toolCount: matchedTools.length,
    toolIds: matchedTools,
  }
}

function serverToInstalled(s: CatalogServer): InstalledServer {
  return {
    kind: 'server',
    id: s.id,
    name: s.name,
    description: s.description || 'Virtual server',
    enabled: s.enabled ?? null,
    url: s.sse_url || null,
    transport: 'SSE',
    toolCount: (s.tool_ids || []).length,
    toolIds: s.tool_ids || [],
  }
}

export function useInstalledServers({ backendUrl, apiKey }: Args) {
  const { catalog, loading, error, refresh } = useAgenticCatalog({
    backendUrl,
    apiKey,
    enabled: true,
  })

  const [search, setSearch] = useState('')

  const catalogTools: CatalogTool[] = useMemo(() => catalog?.tools || [], [catalog])

  const servers = useMemo((): InstalledServer[] => {
    if (!catalog) return []

    const toolMap = new Map<string, string[]>()

    const gateways = (catalog.gateways || []).map((g) => gatewayToInstalled(g, toolMap))
    const virtualServers = (catalog.servers || []).map(serverToInstalled)

    // Only show servers that have tools (i.e. actually installed).
    // Servers with 0 tools are available in Forge but not set up locally —
    // the user can install them from the Manage tab.
    let combined = [...gateways, ...virtualServers].filter(
      (s) => s.kind === 'gateway' || s.toolCount > 0,
    )

    if (search.trim()) {
      const q = search.toLowerCase()
      combined = combined.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q) ||
          s.id.toLowerCase().includes(q),
      )
    }

    return combined
  }, [catalog, search])

  const counts = useMemo(() => {
    const gateways = catalog?.gateways?.length || 0
    const allVirtualServers = catalog?.servers?.length || 0
    // Only count virtual servers that have tools (installed)
    const installedVirtualServers = (catalog?.servers || []).filter(
      (s) => (s.tool_ids || []).length > 0,
    ).length
    return {
      gateways,
      virtualServers: installedVirtualServers,
      totalVirtualServers: allVirtualServers,
      total: gateways + installedVirtualServers,
    }
  }, [catalog])

  return {
    servers,
    counts,
    loading,
    error,
    refresh,
    search,
    setSearch,
    forgeHealthy: catalog?.forge?.healthy ?? null,
    catalogTools,
  }
}
