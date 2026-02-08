/**
 * TypeScript types for the enriched agentic catalog.
 *
 * These mirror the backend AgenticCatalog (catalog_types.py) and provide
 * strong typing for the wizard UI components.
 */

export type ForgeStatus = {
  base_url: string
  healthy: boolean
  error?: string | null
}

export type CatalogTool = {
  id: string
  name: string
  description?: string
  enabled?: boolean | null
}

export type CatalogA2AAgent = {
  id: string
  name: string
  description?: string
  enabled?: boolean | null
  endpoint_url?: string | null
}

export type CatalogServer = {
  id: string
  name: string
  description?: string
  enabled?: boolean | null
  tool_ids: string[]
  sse_url?: string | null
}

export type CatalogGateway = {
  id: string
  name: string
  enabled?: boolean | null
  url?: string | null
  transport?: string | null
}

export type AgenticCatalog = {
  source: string
  last_updated: string
  forge: ForgeStatus
  servers: CatalogServer[]
  tools: CatalogTool[]
  a2a_agents: CatalogA2AAgent[]
  gateways: CatalogGateway[]
  capability_sources: Record<string, string[]>
}
