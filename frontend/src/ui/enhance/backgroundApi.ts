/**
 * Background API client for image background operations.
 *
 * Provides a simple interface to call the backend /v1/background endpoint
 * for manipulating image backgrounds:
 * - remove: Make background transparent (PNG with alpha)
 * - replace: Generate new background from prompt
 * - blur: Apply gaussian blur to background (portrait mode)
 */

export type BackgroundAction = 'remove' | 'replace' | 'blur'

export interface BackgroundParams {
  backendUrl: string
  apiKey?: string
  imageUrl: string
  action: BackgroundAction
  /** Required for 'replace' action */
  prompt?: string
  /** Optional negative prompt for 'replace' action */
  negativePrompt?: string
  /** Blur strength for 'blur' action (5-50, default 15) */
  blurStrength?: number
}

export interface BackgroundResponse {
  media?: {
    images?: string[]
    videos?: string[]
  }
  action_used?: string
  has_alpha?: boolean
  original_size?: [number, number]
  error?: string
}

/**
 * Process image background using the backend endpoint.
 *
 * @param params - Background operation parameters
 * @returns Promise with the response containing the processed image URL
 * @throws Error if the request fails
 *
 * @example
 * ```ts
 * // Remove background
 * const result = await processBackground({
 *   backendUrl: 'http://localhost:8000',
 *   imageUrl: 'http://localhost:8000/files/image.png',
 *   action: 'remove'
 * })
 *
 * // Replace background
 * const result = await processBackground({
 *   backendUrl: 'http://localhost:8000',
 *   imageUrl: 'http://localhost:8000/files/image.png',
 *   action: 'replace',
 *   prompt: 'a beautiful sunset beach'
 * })
 *
 * // Blur background
 * const result = await processBackground({
 *   backendUrl: 'http://localhost:8000',
 *   imageUrl: 'http://localhost:8000/files/image.png',
 *   action: 'blur',
 *   blurStrength: 20
 * })
 * ```
 */
export async function processBackground(params: BackgroundParams): Promise<BackgroundResponse> {
  const base = params.backendUrl.replace(/\/+$/, '')

  const body: Record<string, unknown> = {
    image_url: params.imageUrl,
    action: params.action,
  }

  if (params.action === 'replace') {
    if (!params.prompt) {
      throw new Error('prompt is required for replace action')
    }
    body.prompt = params.prompt
    if (params.negativePrompt) {
      body.negative_prompt = params.negativePrompt
    }
  }

  if (params.action === 'blur' && params.blurStrength !== undefined) {
    body.blur_strength = params.blurStrength
  }

  const response = await fetch(`${base}/v1/background`, {
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
 * Available background actions with descriptions.
 */
export const BACKGROUND_ACTIONS = [
  {
    id: 'remove' as const,
    label: 'Remove BG',
    description: 'Make background transparent (PNG)',
    icon: '✂️',
    requiresPrompt: false,
  },
  {
    id: 'replace' as const,
    label: 'Change BG',
    description: 'Replace with AI-generated background',
    icon: '🎨',
    requiresPrompt: true,
  },
  {
    id: 'blur' as const,
    label: 'Blur BG',
    description: 'Portrait mode / bokeh effect',
    icon: '🔵',
    requiresPrompt: false,
  },
] as const
