/**
 * useAvatarCapabilities — Additive, non-destructive capability hook.
 *
 * Fetches /v1/avatar-models and derives boolean flags for each optional feature.
 * Components use these flags to show/hide *new* optional buttons without
 * affecting any existing behaviour.
 *
 * Usage:
 *   const { capabilities, loading } = useAvatarCapabilities(backendUrl, apiKey)
 *   // capabilities.canIdentityPortrait → true/false
 *   // capabilities.canOutfits          → true/false
 *   // etc.
 */

import { useEffect, useMemo, useState, useCallback } from 'react'

// ── Types (mirror backend /v1/avatar-models response) ──────────────────────

type AvatarFeatureStatus = {
  label: string
  description: string
  ready: boolean
  required_missing: string[]
  recommended_installed: boolean
  recommended_note: string | null
}

type AvatarModelInfo = {
  id: string
  name: string
  installed: boolean
  commercial_use_ok: boolean | null
}

type AvatarModelsResponse = {
  category: string
  installed: string[]
  available: AvatarModelInfo[]
  defaults: string[]
  features: Record<string, AvatarFeatureStatus>
}

// ── Public capability shape ────────────────────────────────────────────────

export type AvatarCapabilities = {
  /** Generate new portrait preserving identity (AntelopeV2 + InstantID IP-Adapter) */
  canIdentityPortrait: boolean
  /** Generate outfit / wardrobe variations (above + ControlNet + PhotoMaker/PuLID) */
  canOutfits: boolean
  /** Face swap tool (AntelopeV2 + InSwapper) */
  canFaceSwap: boolean
  /** Random face generator (StyleGAN2) */
  canRandomFaces: boolean
  /** Any non-commercial model is installed — show license warning */
  hasNonCommercialInstalled: boolean
  /** IDs of models not yet installed */
  missingIds: string[]
  /** Feature-level readiness from backend */
  features: Record<string, AvatarFeatureStatus>
}

const EMPTY_CAPABILITIES: AvatarCapabilities = {
  canIdentityPortrait: false,
  canOutfits: false,
  canFaceSwap: false,
  canRandomFaces: false,
  hasNonCommercialInstalled: false,
  missingIds: [],
  features: {},
}

// ── Hook ───────────────────────────────────────────────────────────────────

export function useAvatarCapabilities(backendUrl: string, apiKey?: string) {
  const [data, setData] = useState<AvatarModelsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const base = (backendUrl || '').replace(/\/+$/, '')
  const authKey = (apiKey || '').trim()

  const refresh = useCallback(async () => {
    if (!base) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${base}/v1/avatar-models`, {
        method: 'GET',
        headers: authKey ? { 'x-api-key': authKey } : {},
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json: AvatarModelsResponse = await res.json()
      setData(json)
    } catch (e: any) {
      setError(e?.message || String(e))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [base, authKey])

  // Fetch once on mount
  useEffect(() => {
    refresh()
  }, [refresh])

  const capabilities: AvatarCapabilities = useMemo(() => {
    if (!data) return EMPTY_CAPABILITIES

    const feats = data.features || {}

    const hasNonCommercialInstalled = (data.available || []).some(
      (m) => m.installed && m.commercial_use_ok === false
    )

    const missingIds = (data.available || [])
      .filter((m) => !m.installed)
      .map((m) => m.id)

    return {
      canIdentityPortrait: feats.photo_variations?.ready ?? false,
      canOutfits: feats.outfit_generation?.ready ?? false,
      canFaceSwap: feats.face_swap?.ready ?? false,
      canRandomFaces: feats.random_faces?.ready ?? false,
      hasNonCommercialInstalled,
      missingIds,
      features: feats,
    }
  }, [data])

  return { capabilities, loading, error, refresh }
}
