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
  url?: string | null
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

/**
 * Unified capability item shown in the Tools / Capabilities tab.
 * Wraps both CatalogTool and CatalogA2AAgent with a discriminator.
 */
export type CapabilityItem =
  | { kind: 'tool';      data: CatalogTool }
  | { kind: 'a2a_agent'; data: CatalogA2AAgent }

// ── Forge MCP Registry types (Phase 9) ─────────────────────────────────

/** A single entry from the Forge MCP catalog YAML. */
export type RegistryServer = {
  id: string
  name: string
  category: string
  url: string
  auth_type: string
  provider: string
  description: string
  requires_api_key: boolean
  secure: boolean
  tags: string[]
  transport?: string | null
  logo_url?: string | null
  documentation_url?: string | null
  is_registered: boolean
  is_available: boolean
  requires_oauth_config: boolean
}

/** Response from GET /v1/agentic/registry/servers */
export type RegistryListResponse = {
  servers: RegistryServer[]
  total: number
  categories: string[]
  auth_types: string[]
  providers: string[]
  all_tags: string[]
}
