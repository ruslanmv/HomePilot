/**
 * Outpaint API client for canvas extension.
 *
 * Provides a simple interface to call the backend /v1/outpaint endpoint
 * for extending images beyond their original boundaries:
 * - left/right/up/down: Extend in a single direction
 * - horizontal: Extend left and right
 * - vertical: Extend up and down
 * - all: Extend all four sides equally
 */

export type ExtendDirection = 'left' | 'right' | 'up' | 'down' | 'all' | 'horizontal' | 'vertical'

export interface OutpaintParams {
  backendUrl: string
  apiKey?: string
  imageUrl: string
  direction: ExtendDirection
  extendPixels?: number
  prompt?: string
  negativePrompt?: string
}

export interface OutpaintResponse {
  media?: {
    images?: string[]
    videos?: string[]
  }
  direction_used?: string
  original_size?: [number, number]
  new_size?: [number, number]
  extend_pixels?: number
  error?: string
}

/**
 * Extend image canvas using the backend outpaint endpoint.
 *
 * @param params - Outpaint parameters
 * @returns Promise with the response containing the extended image URL
 * @throws Error if the request fails
 *
 * @example
 * ```ts
 * // Extend to the right
 * const result = await outpaintImage({
 *   backendUrl: 'http://localhost:8000',
 *   imageUrl: 'http://localhost:8000/files/image.png',
 *   direction: 'right',
 *   extendPixels: 256
 * })
 *
 * // Extend all sides with prompt
 * const result = await outpaintImage({
 *   backendUrl: 'http://localhost:8000',
 *   imageUrl: 'http://localhost:8000/files/image.png',
 *   direction: 'all',
 *   extendPixels: 128,
 *   prompt: 'beautiful landscape continuation'
 * })
 * ```
 */
export async function outpaintImage(params: OutpaintParams): Promise<OutpaintResponse> {
  const base = params.backendUrl.replace(/\/+$/, '')

  const body: Record<string, unknown> = {
    image_url: params.imageUrl,
    direction: params.direction,
    extend_pixels: params.extendPixels ?? 256,
  }

  if (params.prompt) {
    body.prompt = params.prompt
  }

  if (params.negativePrompt) {
    body.negative_prompt = params.negativePrompt
  }

  const response = await fetch(`${base}/v1/outpaint`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(params.apiKey ? { 'X-API-Key': params.apiKey } : {}),
    },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => `HTTP ${response.status}`)
    throw new Error(errorText)
  }

  return response.json()
}

/**
 * Available extend directions with descriptions.
 */
export const EXTEND_DIRECTIONS = [
  {
    id: 'right' as const,
    label: 'Right',
    description: 'Extend canvas to the right',
    icon: '→',
  },
  {
    id: 'left' as const,
    label: 'Left',
    description: 'Extend canvas to the left',
    icon: '←',
  },
  {
    id: 'down' as const,
    label: 'Down',
    description: 'Extend canvas downward',
    icon: '↓',
  },
  {
    id: 'up' as const,
    label: 'Up',
    description: 'Extend canvas upward',
    icon: '↑',
  },
  {
    id: 'horizontal' as const,
    label: 'Horizontal',
    description: 'Extend left and right',
    icon: '↔',
  },
  {
    id: 'vertical' as const,
    label: 'Vertical',
    description: 'Extend up and down',
    icon: '↕',
  },
  {
    id: 'all' as const,
    label: 'All Sides',
    description: 'Extend all four sides equally',
    icon: '⊕',
  },
] as const
