/**
 * Capabilities API client.
 *
 * Provides a simple interface to check which features are available
 * at runtime (e.g., PIL installed, GPU available, etc.)
 */

export interface CapabilityStatus {
  available: boolean
  reason?: string | null
  endpoint: string
  model?: string | null
}

export interface CapabilitiesResponse {
  capabilities: Record<string, CapabilityStatus>
}

/**
 * Known capability keys.
 */
export type CapabilityKey =
  | 'enhance_photo'
  | 'enhance_restore'
  | 'enhance_faces'
  | 'upscale'
  | 'background_remove'
  | 'background_replace'
  | 'background_blur'
  | 'outpaint'
  | 'inpaint'

/**
 * Fetch all capability statuses from the backend.
 *
 * @param backendUrl - Backend URL
 * @param apiKey - Optional API key
 * @returns Promise with all capability statuses
 *
 * @example
 * ```ts
 * const caps = await getCapabilities('http://localhost:8000')
 * if (!caps.capabilities.background_blur.available) {
 *   console.log('Blur unavailable:', caps.capabilities.background_blur.reason)
 * }
 * ```
 */
export async function getCapabilities(
  backendUrl: string,
  apiKey?: string
): Promise<CapabilitiesResponse> {
  const base = backendUrl.replace(/\/+$/, '')

  const response = await fetch(`${base}/v1/capabilities`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'X-API-Key': apiKey } : {}),
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to fetch capabilities: HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * Check if a specific capability is available.
 *
 * @param backendUrl - Backend URL
 * @param feature - Feature to check
 * @param apiKey - Optional API key
 * @returns Promise with capability status
 *
 * @example
 * ```ts
 * const blur = await checkCapability('http://localhost:8000', 'background_blur')
 * if (!blur.available) {
 *   showTooltip(`Blur unavailable: ${blur.reason}`)
 * }
 * ```
 */
export async function checkCapability(
  backendUrl: string,
  feature: CapabilityKey,
  apiKey?: string
): Promise<CapabilityStatus> {
  const base = backendUrl.replace(/\/+$/, '')

  const response = await fetch(`${base}/v1/capabilities/${feature}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'X-API-Key': apiKey } : {}),
    },
  })

  if (!response.ok) {
    throw new Error(`Failed to check capability: HTTP ${response.status}`)
  }

  return response.json()
}

/**
 * React hook for capability checking (can be used with useEffect/useState).
 * Returns a simple helper to check capabilities.
 */
export function createCapabilityChecker(backendUrl: string, apiKey?: string) {
  let cachedCaps: CapabilitiesResponse | null = null

  return {
    /**
     * Get all capabilities (cached after first call).
     */
    async getAll(): Promise<CapabilitiesResponse> {
      if (!cachedCaps) {
        cachedCaps = await getCapabilities(backendUrl, apiKey)
      }
      return cachedCaps
    },

    /**
     * Check if a specific feature is available.
     */
    async isAvailable(feature: CapabilityKey): Promise<boolean> {
      const caps = await this.getAll()
      return caps.capabilities[feature]?.available ?? false
    },

    /**
     * Get the reason if a feature is unavailable.
     */
    async getUnavailableReason(feature: CapabilityKey): Promise<string | null> {
      const caps = await this.getAll()
      const cap = caps.capabilities[feature]
      if (!cap?.available && cap?.reason) {
        return cap.reason
      }
      return null
    },

    /**
     * Clear the cache (e.g., after installing a dependency).
     */
    clearCache() {
      cachedCaps = null
    },
  }
}
