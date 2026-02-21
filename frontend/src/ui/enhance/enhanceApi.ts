/**
 * Enhance API client for image quality improvement.
 *
 * Provides a simple interface to call the backend /v1/enhance endpoint
 * for enhancing images using AI models:
 * - photo: RealESRGAN for natural photo enhancement
 * - restore: SwinIR for artifact/compression removal
 * - faces: GFPGAN for face restoration
 */

export type EnhanceMode = 'photo' | 'restore' | 'faces'

export interface EnhanceParams {
  backendUrl: string
  apiKey?: string
  imageUrl: string
  mode: EnhanceMode
  scale?: 1 | 2 | 4
  faceEnhance?: boolean
}

export interface EnhanceResponse {
  media?: {
    images?: string[]
    videos?: string[]
  }
  mode_used?: string
  model_used?: string
  original_size?: [number, number]
  enhanced_size?: [number, number]
  error?: string
}

/**
 * Enhance an image using the backend enhance endpoint.
 *
 * @param params - Enhance parameters
 * @returns Promise with the enhance response containing the enhanced image URL
 * @throws Error if the request fails
 *
 * @example
 * ```ts
 * const result = await enhanceImage({
 *   backendUrl: 'http://localhost:8000',
 *   imageUrl: 'http://localhost:8000/files/image.png',
 *   mode: 'photo',
 *   scale: 2
 * })
 * const enhancedUrl = result.media?.images?.[0]
 * ```
 */
export async function enhanceImage(params: EnhanceParams): Promise<EnhanceResponse> {
  const base = params.backendUrl.replace(/\/+$/, '')

  const response = await fetch(`${base}/v1/enhance`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(params.apiKey ? { 'X-API-Key': params.apiKey } : {}),
    },
    body: JSON.stringify({
      image_url: params.imageUrl,
      mode: params.mode,
      scale: params.scale ?? 4,
      face_enhance: params.faceEnhance ?? false,
    }),
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => `HTTP ${response.status}`)
    throw new Error(errorText)
  }

  return response.json()
}

/**
 * Available enhancement modes with descriptions.
 */
export const ENHANCE_MODES = [
  {
    id: 'photo' as const,
    label: 'Enhance',
    description: 'Improve photo quality with natural texture recovery',
    icon: '🔼',
    model: 'RealESRGAN_x4plus.pth',
  },
  {
    id: 'restore' as const,
    label: 'Restore',
    description: 'Remove JPEG artifacts and compression blur',
    icon: '🔧',
    model: 'SwinIR_4x.pth',
  },
  {
    id: 'faces' as const,
    label: 'Fix Faces',
    description: 'Restore and enhance faces via ComfyUI',
    icon: '👤',
    model: 'GFPGANv1.4.pth',
  },
] as const
