/**
 * Upscale API client for image enhancement.
 *
 * Provides a simple interface to call the backend /v1/upscale endpoint
 * for upscaling images using AI upscaler models.
 */

export interface UpscaleParams {
  backendUrl: string
  apiKey?: string
  imageUrl: string
  scale: 2 | 4
  model?: string
}

export interface UpscaleResponse {
  media?: {
    images?: string[]
    videos?: string[]
  }
  error?: string
}

/**
 * Upscale an image using the backend upscale endpoint.
 *
 * @param params - Upscale parameters
 * @returns Promise with the upscale response containing the upscaled image URL
 * @throws Error if the request fails
 *
 * @example
 * ```ts
 * const result = await upscaleImage({
 *   backendUrl: 'http://localhost:8000',
 *   imageUrl: 'http://localhost:8000/files/image.png',
 *   scale: 2,
 *   model: '4x-UltraSharp.pth'
 * })
 * const upscaledUrl = result.media?.images?.[0]
 * ```
 */
export async function upscaleImage(params: UpscaleParams): Promise<UpscaleResponse> {
  const base = params.backendUrl.replace(/\/+$/, '')

  const response = await fetch(`${base}/v1/upscale`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(params.apiKey ? { 'X-API-Key': params.apiKey } : {}),
    },
    body: JSON.stringify({
      image_url: params.imageUrl,
      scale: params.scale,
      model: params.model ?? '4x-UltraSharp.pth',
    }),
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => `HTTP ${response.status}`)
    throw new Error(errorText)
  }

  return response.json()
}

/**
 * Available upscale models.
 * These should match the models in the enhance category of model_catalog_data.json
 */
export const UPSCALE_MODELS = [
  { id: '4x-UltraSharp.pth', label: '4x UltraSharp', description: 'Sharp, clean upscaler for general photos' },
  { id: 'RealESRGAN_x4plus.pth', label: 'RealESRGAN x4+', description: 'Excellent photo upscaling with natural textures' },
  { id: 'realesr-general-x4v3.pth', label: 'Real-ESRGAN General', description: 'General-purpose upscaler for mixed content' },
  { id: 'SwinIR_4x.pth', label: 'SwinIR 4x', description: 'Restoration upscaler for compression artifacts' },
] as const

export type UpscaleModelId = typeof UPSCALE_MODELS[number]['id']
