/** API types and fetch helper for the System Status dashboard. */

export type ServiceHealth = {
  ok: boolean
  latency_ms?: number | null
  status_code?: number | null
  error?: string
  url?: string
  service?: string
  status?: string
  base_url?: string
}

export type SystemOverviewResponse = {
  ok: boolean
  overview: {
    uptime_seconds: number
    version: string
    healthy_services: number
    total_services: number
    degraded_services: number
    avg_latency_ms: number
    active_entities: number
  }
  architecture: {
    inputs: { virtual_servers_total: number; virtual_servers_active: number }
    gateway: { contextforge_ok: boolean }
    infrastructure: { sqlite: boolean; database: string; memory_mode: string }
    outputs: {
      mcp_servers_total: number
      mcp_servers_active: number
      a2a_agents_total: number
      a2a_agents_active: number
      tools_total: number
      tools_active: number
      prompts_total: number
      prompts_active: number
      resources_total: number
      resources_active: number
    }
  }
  services: Record<string, ServiceHealth>
}

export async function fetchSystemOverview(
  backendUrl: string,
  apiKey?: string,
): Promise<SystemOverviewResponse> {
  const headers: Record<string, string> = {}
  if (apiKey) headers['x-api-key'] = apiKey
  const res = await fetch(`${backendUrl}/v1/system/overview`, { headers })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
