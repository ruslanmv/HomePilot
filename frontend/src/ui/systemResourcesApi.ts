/** API types and fetch helper for Machine Capacity metrics. */

export type GpuInfo = {
  available: boolean
  name?: string | null
  vram_total_mb?: number | null
  vram_used_mb?: number | null
  vram_free_mb?: number | null
  used_percent?: number | null
  utilization_percent?: number | null
  temperature_c?: number | null
  status: string
}

export type RamInfo = {
  total_mb: number
  used_mb: number
  available_mb: number
  percent: number
  status: string
}

export type CpuInfo = {
  name: string
  physical_cores: number
  logical_cores: number
  percent: number
  status: string
}

export type DiskInfo = {
  path: string
  total_gb: number
  used_gb: number
  free_gb: number
  percent: number
  status: string
}

export type SystemResourcesResponse = {
  gpu: GpuInfo
  ram: RamInfo
  cpu: CpuInfo
  disk: DiskInfo
}

export async function fetchSystemResources(
  backendUrl: string,
  apiKey?: string,
): Promise<SystemResourcesResponse> {
  const headers: Record<string, string> = {}
  if (apiKey) headers['x-api-key'] = apiKey
  const res = await fetch(`${backendUrl}/v1/system/resources`, { headers })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
