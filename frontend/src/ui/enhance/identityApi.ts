/**
 * identityApi - API client for identity-aware edit operations.
 *
 * These operations use Avatar & Identity models (InsightFace + InstantID)
 * to perform edits that preserve facial identity.
 *
 * This is additive — existing enhance/edit endpoints are unchanged.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type IdentityToolType =
  | 'fix_faces_identity'
  | 'inpaint_identity'
  | 'change_bg_identity'
  | 'face_swap'

export interface IdentityToolParams {
  backendUrl: string
  apiKey?: string
  imageUrl: string
  toolType: IdentityToolType
  /** Optional reference face image URL (for face swap) */
  referenceImageUrl?: string
  /** Optional mask data URL (for inpaint_identity) */
  maskDataUrl?: string
  /** Optional prompt (for change_bg_identity or inpaint_identity) */
  prompt?: string
}

export interface IdentityToolResponse {
  media?: { images?: string[] }
  text?: string
  error?: string
}

// ---------------------------------------------------------------------------
// Tool definitions (for UI rendering)
// ---------------------------------------------------------------------------

export const IDENTITY_TOOLS = [
  {
    id: 'fix_faces_identity' as const,
    label: 'Fix Faces+',
    description: 'Fix faces while preserving identity',
    pack: 'basic' as const,
  },
  {
    id: 'inpaint_identity' as const,
    label: 'Inpaint (Preserve Person)',
    description: 'Edit regions while keeping the face consistent',
    pack: 'basic' as const,
  },
  {
    id: 'change_bg_identity' as const,
    label: 'Change BG (Preserve Person)',
    description: 'Replace background while keeping the same person',
    pack: 'basic' as const,
  },
  {
    id: 'face_swap' as const,
    label: 'Face Swap',
    description: 'Transfer identity onto generated or existing images',
    pack: 'full' as const,
  },
] as const

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

export async function applyIdentityTool(
  params: IdentityToolParams,
): Promise<IdentityToolResponse> {
  const base = params.backendUrl.replace(/\/+$/, '')

  const body: Record<string, unknown> = {
    image_url: params.imageUrl,
    tool_type: params.toolType,
  }
  if (params.referenceImageUrl) body.reference_image_url = params.referenceImageUrl
  if (params.maskDataUrl) body.mask_data_url = params.maskDataUrl
  if (params.prompt) body.prompt = params.prompt

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (params.apiKey) headers['X-API-Key'] = params.apiKey

  const response = await fetch(`${base}/v1/edit/identity`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    throw new Error(`Identity tool failed: ${response.status} ${text}`)
  }

  return response.json()
}
