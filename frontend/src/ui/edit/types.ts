/**
 * Type definitions for the Edit session feature.
 */

/**
 * Represents a single version entry in the edit history.
 */
export type VersionEntry = {
  url: string
  instruction: string
  created_at: number
  parent_url?: string | null
  settings?: Record<string, unknown>
}

/**
 * Represents the current state of an edit session.
 */
export type EditSessionState = {
  conversation_id: string
  active_image_url?: string | null
  original_image_url?: string | null
  versions?: VersionEntry[]
  history?: string[] // Legacy compatibility
}

/**
 * Result from an edit operation containing generated images.
 */
export type EditResult = {
  images: string[]
  raw?: Record<string, unknown>
}

/**
 * Props for the main EditTab component.
 */
export type EditTabProps = {
  backendUrl: string
  apiKey?: string
  conversationId: string
  onOpenLightbox: (url: string) => void
  provider?: string
  providerBaseUrl?: string
  providerModel?: string
  /** Navigate to Avatar Studio to create a new avatar */
  onNavigateToAvatar?: () => void
}

/**
 * Props for the EditDropzone component.
 */
export type EditDropzoneProps = {
  onPickFile: (file: File) => void
  disabled?: boolean
}

/**
 * Props for the EditHistoryStrip component.
 */
export type EditHistoryStripProps = {
  history: string[]
  active?: string | null
  onSelect: (url: string) => void
  disabled?: boolean
}

/**
 * Props for the EditResultGrid component.
 */
export type EditResultGridProps = {
  images: string[]
  onUse: (url: string) => void
  onTryAgain: () => void
  onOpen: (url: string) => void
  disabled?: boolean
}
