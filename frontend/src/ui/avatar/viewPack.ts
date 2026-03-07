import type { AvatarResult } from './types'

export type ViewAngle = 'front' | 'left_45' | 'left' | 'right_45' | 'right' | 'back'
export type ViewSource = 'anchor' | 'latest' | 'equipped'

export interface ViewAngleOption {
  id: ViewAngle
  label: string
  shortLabel: string
  prompt: string
  /** Negative prompt tokens to prevent the reference pose from dominating. */
  negativePrompt: string
  icon: string
  /** Denoise override — higher values let the text prompt control pose.
   *  Front uses default (0.85), non-front uses 1.0 for full prompt control. */
  denoise: number
  /** When true, use 'standard' generation mode instead of 'identity' to avoid
   *  face preservation fighting the desired pose (e.g. back view). */
  skipIdentity?: boolean
}

export const VIEW_ANGLE_OPTIONS: ViewAngleOption[] = [
  {
    id: 'front',
    label: 'Front',
    shortLabel: 'F',
    prompt: 'front view, facing the camera directly, centered composition, standing naturally, same person, same outfit, same hairstyle, same body proportions',
    negativePrompt: '',
    icon: '\u25C9',
    denoise: 0.85,
  },
  {
    id: 'left_45',
    label: '45\u00B0 Left',
    shortLabel: 'L45',
    prompt: 'three-quarter view from the left side, head and body turned 45 degrees to the left, looking slightly away from camera, same person, same outfit, same hairstyle, same body proportions',
    negativePrompt: 'front view, facing camera directly, looking straight at camera',
    icon: '\u25D6',
    denoise: 1.0,
  },
  {
    id: 'left',
    label: 'Left',
    shortLabel: 'L',
    prompt: 'full left side profile view, head and body turned 90 degrees to the left, side of face visible, same person, same outfit, same hairstyle, same body proportions',
    negativePrompt: 'front view, facing camera directly, looking straight at camera, three-quarter view',
    icon: '\u25D0',
    denoise: 1.0,
  },
  {
    id: 'right_45',
    label: '45\u00B0 Right',
    shortLabel: 'R45',
    prompt: 'three-quarter view from the right side, head and body turned 45 degrees to the right, looking slightly away from camera, same person, same outfit, same hairstyle, same body proportions',
    negativePrompt: 'front view, facing camera directly, looking straight at camera',
    icon: '\u25D7',
    denoise: 1.0,
  },
  {
    id: 'right',
    label: 'Right',
    shortLabel: 'R',
    prompt: 'full right side profile view, head and body turned 90 degrees to the right, side of face visible, same person, same outfit, same hairstyle, same body proportions',
    negativePrompt: 'front view, facing camera directly, looking straight at camera, three-quarter view',
    icon: '\u25D1',
    denoise: 1.0,
  },
  {
    id: 'back',
    label: 'Back',
    shortLabel: 'B',
    prompt: 'rear view from behind, person turned completely away from camera, back of head and back of body visible, showing buttocks and back, no face visible, same outfit colors and silhouette, same hairstyle length and color from behind, same body proportions',
    negativePrompt: 'front view, facing camera, looking at camera, face visible, eyes visible, front of body, frontal pose, turning head, looking over shoulder',
    icon: '\u25CE',
    denoise: 1.0,
    skipIdentity: true,
  },
]

export type ViewResultMap = Partial<Record<ViewAngle, AvatarResult>>
export type ViewPreviewMap = Partial<Record<ViewAngle, string>>

export function getViewAngleOption(angle: ViewAngle): ViewAngleOption {
  return VIEW_ANGLE_OPTIONS.find((item) => item.id === angle) ?? VIEW_ANGLE_OPTIONS[0]
}

export function extractViewAngle(metadata?: Record<string, unknown> | null): ViewAngle | null {
  const value = metadata?.view_angle
  if (typeof value !== 'string') return null
  return VIEW_ANGLE_OPTIONS.some((item) => item.id === value) ? (value as ViewAngle) : null
}
