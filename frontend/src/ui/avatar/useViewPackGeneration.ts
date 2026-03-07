import { useCallback, useMemo, useState } from 'react'
import type { AvatarResult } from './types'
import type { ViewAngle, ViewResultMap } from './viewPack'
import { getViewAngleOption, VIEW_ANGLE_OPTIONS } from './viewPack'

export interface GenerateViewParams {
  referenceImageUrl: string
  angle: ViewAngle
  characterPrompt?: string
  basePrompt?: string
  checkpointOverride?: string
  seed?: number
}

interface OutfitGenerateResult {
  results: AvatarResult[]
  warnings: string[]
}

export function useViewPackGeneration(backendUrl: string, apiKey?: string) {
  const [resultsByAngle, setResultsByAngle] = useState<ViewResultMap>({})
  const [loadingAngles, setLoadingAngles] = useState<Partial<Record<ViewAngle, boolean>>>({})
  const [warnings, setWarnings] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const anyLoading = useMemo(() => Object.values(loadingAngles).some(Boolean), [loadingAngles])

  const generateAngle = useCallback(async (params: GenerateViewParams) => {
    const base = (backendUrl || '').replace(/\/+$/, '')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiKey) headers['x-api-key'] = apiKey

    const angleMeta = getViewAngleOption(params.angle)
    const basePrompt = params.basePrompt?.trim() || 'portrait photograph'

    // Build the positive prompt: base description + angle-specific direction + consistency phrases
    const viewPrompt = [
      basePrompt,
      angleMeta.prompt,
      'turntable style pose, consistent studio lighting, preserve identity, preserve outfit colors, preserve silhouette, clean full subject visibility',
    ].filter(Boolean).join(', ')

    // Build the negative prompt: prevent front-facing bias from the reference latent
    const negParts = [
      'lowres, blurry, bad anatomy, deformed, extra fingers, missing fingers, bad hands, disfigured face, watermark, text, multiple people, duplicate',
    ]
    if (angleMeta.negativePrompt) {
      negParts.push(angleMeta.negativePrompt)
    }
    const negativePrompt = negParts.join(', ')

    setLoadingAngles((current) => ({ ...current, [params.angle]: true }))
    setError(null)

    try {
      const res = await fetch(`${base}/v1/avatars/outfits`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          reference_image_url: params.referenceImageUrl,
          outfit_prompt: viewPrompt,
          character_prompt: params.characterPrompt,
          negative_prompt: negativePrompt,
          count: 1,
          generation_mode: 'identity',
          checkpoint_override: params.checkpointOverride,
          seed: params.seed,
          // Non-front angles use denoise 1.0 so the text prompt fully controls
          // the pose/angle instead of the reference image's spatial layout.
          denoise_override: angleMeta.denoise,
        }),
      })

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`View generation failed: ${res.status} ${text}`)
      }

      const data: OutfitGenerateResult = await res.json()
      const first = data.results?.[0]
      if (!first) throw new Error('View generation returned no images')

      const tagged: AvatarResult = {
        ...first,
        metadata: {
          ...(first.metadata || {}),
          view_angle: params.angle,
        },
      }

      setResultsByAngle((current) => ({ ...current, [params.angle]: tagged }))
      if (data.warnings?.length) {
        setWarnings((current) => [...current, ...data.warnings])
      }
      return tagged
    } catch (err) {
      const message = err instanceof Error ? err.message : 'View generation failed'
      setError(message)
      throw err
    } finally {
      setLoadingAngles((current) => ({ ...current, [params.angle]: false }))
    }
  }, [backendUrl, apiKey])

  const reset = useCallback(() => {
    setResultsByAngle({})
    setLoadingAngles({})
    setWarnings([])
    setError(null)
  }, [])

  const missingAngles = useCallback((existing?: ViewResultMap) => {
    const source = existing || resultsByAngle
    return VIEW_ANGLE_OPTIONS.filter((item) => !source[item.id]).map((item) => item.id)
  }, [resultsByAngle])

  return {
    resultsByAngle,
    loadingAngles,
    anyLoading,
    warnings,
    error,
    generateAngle,
    reset,
    missingAngles,
  }
}
