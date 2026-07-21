/**
 * Shared types for the Account & Computers spine (Batch 2).
 *
 * These mirror the OllaBridge Cloud mirror contract as surfaced by the
 * HomePilot Web BFF at ``/v1/account/mirror/*`` (Batch 1). The node list is
 * intentionally lean; richer detail (GPU/VRAM/models/projects/capabilities)
 * comes from a node's manifest, fetched lazily.
 */

/** One computer linked to the account, from ``GET /v1/account/mirror/nodes``. */
export interface MirrorNode {
  node_id: string
  node_name: string
  platform?: string | null
  online: boolean
}

/**
 * A node's manifest, relayed from the owning machine. Loosely typed because the
 * schema is owned by HomePilot Local; a few commonly-present fields are called
 * out for convenience, everything else is passed through.
 */
export interface NodeManifest {
  gpu?: { name?: string; vram_mb?: number } | null
  os?: string | null
  models?: unknown[]
  projects?: unknown[]
  capabilities?: string[]
  revision?: string | number
  [key: string]: unknown
}

/** Readiness probe from ``GET /v1/account/mirror/status``. */
export interface MirrorStatus {
  ok: boolean
  enabled: boolean
  linked: boolean
  cloud?: string
}

/** Where the user wants AI work to run. */
export type SelectionMode = 'automatic' | 'fixed' | 'ask'

/** Coarse presence state used by status indicators (design §8). */
export type PresenceState = 'online' | 'offline' | 'attention' | 'unknown'
