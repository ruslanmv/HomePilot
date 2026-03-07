/**
 * Avatar Studio — API client functions.
 */

import type {
  AvatarGenerateRequest,
  AvatarGenerateResponse,
  AvatarPacksResponse,
  AvatarCapabilitiesResponse,
  HybridFullBodyRequest,
  HybridFullBodyResponse,
} from './types'

export async function fetchAvatarPacks(
  backendUrl: string,
  apiKey?: string,
): Promise<AvatarPacksResponse> {
  const base = (backendUrl || '').replace(/\/+$/, '')
  const headers: Record<string, string> = {}
  if (apiKey) headers['x-api-key'] = apiKey

  const res = await fetch(`${base}/v1/avatars/packs`, { headers })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function installAvatarPack(
  backendUrl: string,
  packId: 'avatar-basic' | 'avatar-full' | 'avatar-stylegan2',
  apiKey?: string,
): Promise<{ ok: boolean; pack_id: string; was_already_installed: boolean; error?: string }> {
  const base = (backendUrl || '').replace(/\/+$/, '')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (apiKey) headers['x-api-key'] = apiKey

  const res = await fetch(`${base}/v1/avatars/packs/install`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ pack_id: packId }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * Fetch engine capabilities (ComfyUI, StyleGAN availability).
 * Additive — does not affect existing API functions.
 */
export async function fetchAvatarCapabilities(
  backendUrl: string,
  apiKey?: string,
): Promise<AvatarCapabilitiesResponse> {
  const base = (backendUrl || '').replace(/\/+$/, '')
  const headers: Record<string, string> = {}
  if (apiKey) headers['x-api-key'] = apiKey

  const res = await fetch(`${base}/v1/avatars/capabilities`, { headers })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function generateAvatars(
  backendUrl: string,
  body: AvatarGenerateRequest,
  apiKey?: string,
  signal?: AbortSignal,
): Promise<AvatarGenerateResponse> {
  const base = (backendUrl || '').replace(/\/+$/, '')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (apiKey) headers['x-api-key'] = apiKey

  const res = await fetch(`${base}/v1/avatars/generate`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * Generate full-body images from a face reference via the hybrid pipeline.
 * Uses ComfyUI with identity preservation (InstantID/PhotoMaker).
 */
export async function generateHybridFullBody(
  backendUrl: string,
  body: HybridFullBodyRequest,
  apiKey?: string,
  signal?: AbortSignal,
): Promise<HybridFullBodyResponse> {
  const base = (backendUrl || '').replace(/\/+$/, '')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (apiKey) headers['x-api-key'] = apiKey

  const res = await fetch(`${base}/v1/avatars/hybrid/fullbody`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
